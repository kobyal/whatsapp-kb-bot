/**
 * WhatsApp listener. The only channel-aware part of the bot.
 *
 * Runs as a *linked device* of the bot's WhatsApp account (Baileys, protocol-level,
 * no Chromium). Holds the session, forwards each allowed message to the brain Lambda,
 * and sends back whatever `reply` the brain returns. Nothing here decides what to say.
 *
 * Safety controls, in order of importance:
 *  1. Allowlist. Replies ONLY in groups whose jid or subject is listed in ALLOWED_GROUPS
 *     (comma-separated). Empty allowlist = reply to nobody (fails closed).
 *     A 1:1 message is answered ONLY when DM_ENABLED=1 AND the sender is on the live roster
 *     of a group in DM_ROSTER_GROUPS; anyone else is dropped in silence, never told why.
 *  2. Never answers itself (key.fromMe), never answers messages that predate startup, and
 *     never handles the same message id twice (WhatsApp does deliver duplicates).
 *  3. Jittered 1.5-4 s delay before replying. Fixed machine cadence is a signal
 *     WhatsApp's anti-automation classifiers look at.
 *
 * What is passed to the brain, beyond the text and image: who is asking (`participant`),
 * in which chat (`jid`), whom they are replying to when that is a human (`quoted_participant`),
 * whether the bot was called by name (`explicit`), and for a DM the tenants the sender may ask
 * about (`candidate_tenants`). The brain keys its conversation state and its rate limits on
 * those; without them it fails closed to silence.
 *
 * Files shared with qrserve.js: qr.txt, READY, bot.log under DATA_DIR. The log format is a
 * contract with curator/events.py: `IN  <group jid|DM> <sender>: <text>`, `BRAIN tenant=… outcome=… …`,
 * `OUT sent …`, `BRAIN ERROR …`. Change one, change both.
 */
const fs = require('fs');
const path = require('path');
const pino = require('pino');
const {
  default: makeWASocket, useMultiFileAuthState, downloadMediaMessage, DisconnectReason,
} = require('@whiskeysockets/baileys');
const { LambdaClient, InvokeCommand } = require('@aws-sdk/client-lambda');

const DIR = process.env.DATA_DIR || '/opt/wakb/data';
const AUTH = path.join(DIR, 'auth');
const BRAIN = process.env.BRAIN_FUNCTION || 'wakb-brain';
const REGION = process.env.AWS_REGION || 'eu-west-1';
const csv = (s) => (s || '').split(',').map(x => x.trim()).filter(Boolean);
const ALLOWED = csv(process.env.ALLOWED_GROUPS);
// Explicit call: an @-mention of the bot, or a message starting with one of CALL_WORDS
// ("bot", and "בוט" for Hebrew groups). The brain always replies to an explicit call, if only
// to say it has no answer. No \b in the regex: JS word boundaries are ASCII-only.
const CALL_WORDS = csv(process.env.CALL_WORDS || 'bot,בוט').map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
const CALL_WORD = new RegExp(`^\\s*@?(${CALL_WORDS.join('|')})(?=$|[\\s,:.!?\\-])[\\s,:.!?\\-]*`, 'i');
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;   // Lambda sync payload is 6 MB; base64 adds a third
const STARTED_AT = Math.floor(Date.now() / 1000);

// ---------------------------------------------------------------- 1:1 mode
// OFF by default, on purpose: the service can ship and restart without opening the DM
// channel to anyone. DM_ROSTER_GROUPS maps group jid -> tenant id ("<jid>=<tenant>,..."):
// members of those groups may DM the bot, and get that tenant's knowledge base.
const DM_ENABLED = process.env.DM_ENABLED === '1';
const DM_ROSTER_GROUPS = csv(process.env.DM_ROSTER_GROUPS)
  .map(pair => pair.split('=')).filter(p => p.length === 2)
  .reduce((m, [jid, tenant]) => (m[jid.trim()] = tenant.trim(), m), {});
const DM_ROSTER_REFRESH_MS = Number(process.env.DM_ROSTER_REFRESH_MIN || 15) * 60 * 1000;

fs.mkdirSync(DIR, { recursive: true });
const lambda = new LambdaClient({ region: REGION });
const logger = pino({ level: 'silent' });
const log = (...a) => {
  const line = `[${new Date().toISOString()}] ${a.join(' ')}`;
  console.log(line);
  try { fs.appendFileSync(path.join(DIR, 'bot.log'), line + '\n'); } catch (e) { /* best effort */ }
};

const subjects = new Map();   // jid -> group subject, so ALLOWED_GROUPS can hold names
async function groupSubject(sock, jid) {
  if (!subjects.has(jid)) {
    try { subjects.set(jid, (await sock.groupMetadata(jid)).subject || ''); }
    catch (e) { subjects.set(jid, ''); }
  }
  return subjects.get(jid);
}

async function isAllowed(sock, jid) {
  if (!jid.endsWith('@g.us')) return false;   // groups only; DMs go through dmTenants()
  return ALLOWED.includes(jid) || ALLOWED.includes(await groupSubject(sock, jid));
}

// Same WhatsApp user regardless of device suffix (":12") or lid/phone addressing.
const userPart = (j) => (j || '').split('@')[0].split(':')[0];
function isMe(sock, j) {
  if (!j) return false;
  const u = sock.user || {};
  return userPart(j) === userPart(u.id) || (u.lid && userPart(j) === userPart(u.lid));
}

// ---- the 1:1 roster: who may DM the bot, and about which tenant. Rebuilt from live group
// metadata, because "is this person still in the group?" has exactly one honest source.
let dmRoster = null;          // Map: userPart -> Set(tenant id)
let dmRosterAt = 0;

async function refreshDmRoster(sock) {
  const next = new Map();
  for (const [jid, tenant] of Object.entries(DM_ROSTER_GROUPS)) {
    let meta;
    try { meta = await sock.groupMetadata(jid); }
    catch (e) { log(`dm roster: ${jid} FAILED (${e && e.message}) - keeping the previous roster`); return; }
    for (const p of (meta.participants || [])) {
      const u = userPart(p.id || p.jid || p);
      if (!u) continue;
      if (!next.has(u)) next.set(u, new Set());
      next.get(u).add(tenant);
    }
  }
  // Never install an empty roster over a working one: an empty map silently denies
  // everybody, which looks exactly like the feature being broken.
  if (next.size === 0) { log('dm roster: built empty - keeping the previous roster'); return; }
  dmRoster = next;
  dmRosterAt = Date.now();
  const both = [...next.values()].filter(s => s.size > 1).length;
  log(`dm roster: ${next.size} people across ${Object.keys(DM_ROSTER_GROUPS).length} groups, ${both} in more than one tenant`);
}

// The tenants this DM sender may ask about. Empty = not authorised, and the caller stays
// SILENT: a refusal would confirm to a stranger what this number is.
async function dmTenants(sock, jid) {
  if (!DM_ENABLED) return [];
  if (!dmRoster || Date.now() - dmRosterAt > DM_ROSTER_REFRESH_MS) await refreshDmRoster(sock);
  if (!dmRoster) return [];                            // never built: fail closed
  return [...(dmRoster.get(userPart(jid)) || [])];
}

// WhatsApp can deliver the SAME message more than once (seen live: a screenshot arrived
// bundled with a key-distribution message and again on its own 2.5 s later, same key.id).
const seenIds = new Map();
const SEEN_TTL_MS = 10 * 60 * 1000;
function alreadyHandled(id) {
  if (!id) return false;
  const now = Date.now();
  if (seenIds.size > 500) for (const [k, t] of seenIds) if (now - t > SEEN_TTL_MS) seenIds.delete(k);
  const at = seenIds.get(id);
  if (at !== undefined && now - at < SEEN_TTL_MS) return true;
  seenIds.set(id, now);
  return false;
}

function contextInfo(m) {
  const msg = m.message || {};
  return (msg.extendedTextMessage || msg.imageMessage || msg.videoMessage || {}).contextInfo || {};
}
function explicitCall(sock, m, text) {
  // Quoting one of the bot's messages is NOT a call: people quote the bot to talk about it,
  // and answering that with a no-match text is the bot arguing with the humans.
  const mentioned = (contextInfo(m).mentionedJid || []).some(j => isMe(sock, j));
  const callWord = CALL_WORD.test(text);
  return { explicit: mentioned || callWord, how: mentioned ? 'mention' : callWord ? 'word' : null };
}
const stripAddress = (text) => text.replace(/@\d{6,}/g, ' ').replace(CALL_WORD, '').replace(/\s+/g, ' ').trim();

// Who this message replies to, when that is a HUMAN. Null for a message that quotes nothing
// and for one that quotes the bot. The brain reads this as "two people are talking".
function quotedParticipant(sock, m) {
  const ctx = contextInfo(m);
  const author = ctx.participant || (ctx.quotedMessage ? ctx.remoteJid : null);
  if (!author || isMe(sock, author)) return null;
  return author;
}

function extractText(m) {
  const msg = m.message || {};
  return (msg.conversation
    || (msg.extendedTextMessage && msg.extendedTextMessage.text)
    || (msg.imageMessage && msg.imageMessage.caption)
    || (msg.videoMessage && msg.videoMessage.caption)
    || '').trim();
}

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH);
  const sock = makeWASocket({ auth: state, logger, browser: ['Ubuntu', 'Chrome', '22.04.4'] });
  sock.ev.on('creds.update', saveCreds);

  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) { fs.writeFileSync(path.join(DIR, 'qr.txt'), qr); log('QR updated - open the QR page and scan it'); }
    if (connection === 'open') {
      const me = ((sock.user && sock.user.id) || '').split(':')[0];
      fs.writeFileSync(path.join(DIR, 'READY'), me);
      log(`READY as ${me}; allowlist=${JSON.stringify(ALLOWED)} dm=${DM_ENABLED} rosterGroups=${Object.keys(DM_ROSTER_GROUPS).length}`);
      if (DM_ENABLED) refreshDmRoster(sock).catch(e => log(`dm roster: ${e && e.message}`));
    }
    if (connection === 'close') {
      const code = lastDisconnect && lastDisconnect.error && lastDisconnect.error.output
        && lastDisconnect.error.output.statusCode;
      log(`connection closed (code=${code})`);   // 515 right after pairing is normal: restart required
      if (code === DisconnectReason.loggedOut) {
        fs.rmSync(AUTH, { recursive: true, force: true });
        fs.rmSync(path.join(DIR, 'READY'), { force: true });
        log('logged out by the phone - auth cleared, a new QR will be issued');
      }
      setTimeout(start, 5000);
    }
  });

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const m of messages) {
      try {
        if (m.key.fromMe) continue;
        if (Number(m.messageTimestamp) < STARTED_AT) continue;   // history sync, not new traffic
        const jid = m.key.remoteJid || '';
        const isGroup = jid.endsWith('@g.us');
        // A DM is authorised by group membership, never by the group allowlist. `dmCandidates`
        // is empty for every group message, so the group path is unchanged by this branch.
        const dmCandidates = isGroup ? [] : await dmTenants(sock, jid);
        const isDm = !isGroup && dmCandidates.length > 0;
        if (!isDm && !(await isAllowed(sock, jid))) {
          log(`drop: jid=${jid} subject="${isGroup ? await groupSubject(sock, jid) : ''}"${isGroup ? ' (not allowlisted)' : ' (dm: disabled or not a group member)'}`);
          continue;
        }
        if (alreadyHandled(m.key.id)) { log(`skip: duplicate delivery of ${m.key.id} in ${jid}`); continue; }

        const rawText = extractText(m);
        const call = explicitCall(sock, m, rawText);
        const text = call.explicit ? stripAddress(rawText) : rawText;
        let image_b64 = null, mime = null;
        if (m.message && m.message.imageMessage) {
          try {
            const buf = await downloadMediaMessage(m, 'buffer', {}, { logger, reuploadRequest: sock.updateMediaMessage });
            if (buf.length <= MAX_IMAGE_BYTES) {
              image_b64 = buf.toString('base64');
              mime = m.message.imageMessage.mimetype || 'image/jpeg';
            } else log(`image too large (${buf.length} B), ignored`);
          } catch (e) { log('image download failed:', e && e.message); }
        }
        if (!text && !image_b64 && !call.explicit && !isDm) continue;
        const participant = m.key.participant || jid;
        log(`IN  ${isDm ? 'DM' : jid} ${participant}: ${text.slice(0, 160)}${image_b64 ? ' [+image]' : ''}${call.explicit ? ` [explicit:${call.how}]` : ''}${isDm ? ` [tenants:${dmCandidates.join('|')}]` : ''}`);

        const res = await lambda.send(new InvokeCommand({
          FunctionName: BRAIN,
          Payload: Buffer.from(JSON.stringify({
            text, image_b64, mime, jid, participant,
            quoted_participant: quotedParticipant(sock, m),
            explicit: call.explicit,
            dm: isDm,
            candidate_tenants: dmCandidates,
          })),
        }));
        const rawPayload = Buffer.from(res.Payload).toString();
        if (res.FunctionError || !rawPayload.startsWith('{')) {
          // A timed-out or crashed brain returns an error envelope, not a verdict. Name it, so
          // a human grepping the log and the curator both see it instead of reading silence.
          log(`BRAIN ERROR ${res.FunctionError || 'bad payload'}: ${rawPayload.slice(0, 200)}`);
          continue;
        }
        const brain = JSON.parse(rawPayload);
        if (!brain || typeof brain !== 'object' || !brain.outcome) {
          log(`BRAIN ERROR no outcome in payload: ${rawPayload.slice(0, 200)}`);
          continue;
        }
        log(`BRAIN tenant=${brain.tenant || '?'} outcome=${brain.outcome} matched=${!!brain.matched} id=${brain.id} score=${brain.score} | ${(brain.note || '').slice(0, 200)}`);
        // Branch on `reply`, never on `matched`: a clarifying question has matched=false AND a reply.
        if (!brain.reply) { log(`no reply (outcome=${brain.outcome}) - staying silent`); continue; }

        await new Promise(r => setTimeout(r, 1500 + Math.floor(Math.random() * 2500)));
        // Quote the question in a group (the humans' own convention; several people ask at
        // once). In a 1:1 there is one conversation, so quoting adds nothing.
        await sock.sendMessage(jid, { text: brain.reply }, isDm ? {} : { quoted: m });
        log(`OUT sent ${brain.outcome} ${brain.id || ''} (${brain.reply.length} chars)`);
      } catch (e) {
        log('ERROR:', e && e.message);
      }
    }
  });
}

log('starting listener');
start().catch(e => { log('fatal:', e && e.message); process.exit(1); });
