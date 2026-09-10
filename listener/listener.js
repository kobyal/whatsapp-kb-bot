/**
 * WhatsApp listener. The only channel-aware part of the bot.
 *
 * Runs as a *linked device* of the bot's WhatsApp account (Baileys, protocol-level,
 * no Chromium). Holds the session, forwards each allowed message to the brain Lambda,
 * and sends back whatever `reply` the brain returns. Nothing here decides what to say.
 *
 * Safety controls, in order of importance:
 *  1. Allowlist. Replies ONLY in groups whose jid or subject is listed in ALLOWED_GROUPS
 *     (comma-separated). Everything else, including DMs unless ALLOW_DMS=1, is logged
 *     and dropped. Empty allowlist = reply to nobody (fails closed).
 *  2. Never answers itself (key.fromMe) and never answers messages that predate startup.
 *  3. Jittered 1.5-4 s delay before replying. Fixed machine cadence is a signal
 *     WhatsApp's anti-automation classifiers look at.
 *
 * Files shared with qrserve.js: qr.txt, READY, bot.log under DATA_DIR.
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
const ALLOWED = (process.env.ALLOWED_GROUPS || '').split(',').map(s => s.trim()).filter(Boolean);
const ALLOW_DMS = process.env.ALLOW_DMS === '1';
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;   // Lambda sync payload is 6 MB; base64 adds a third
const STARTED_AT = Math.floor(Date.now() / 1000);

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
  if (jid.endsWith('@g.us')) {
    return ALLOWED.includes(jid) || ALLOWED.includes(await groupSubject(sock, jid));
  }
  return ALLOW_DMS;   // 1:1 chats
}

function extractText(m) {
  const msg = m.message || {};
  return (msg.conversation
    || (msg.extendedTextMessage && msg.extendedTextMessage.text)
    || (msg.imageMessage && msg.imageMessage.caption)
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
      log(`READY as ${me}; allowlist=${JSON.stringify(ALLOWED)} dms=${ALLOW_DMS}`);
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
        if (!(await isAllowed(sock, jid))) {
          log(`drop: jid=${jid} subject="${jid.endsWith('@g.us') ? await groupSubject(sock, jid) : ''}" (not allowlisted)`);
          continue;
        }

        const text = extractText(m);
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
        if (!text && !image_b64) continue;
        const sender = m.key.participant || jid;
        log(`IN  ${sender}: ${text.slice(0, 160)}${image_b64 ? ' [+image]' : ''}`);

        const res = await lambda.send(new InvokeCommand({
          FunctionName: BRAIN,
          Payload: Buffer.from(JSON.stringify({ text, image_b64, mime, sender, chat: jid })),
        }));
        const brain = JSON.parse(Buffer.from(res.Payload).toString());
        log(`BRAIN ${brain.outcome} id=${brain.id} score=${brain.score} | ${(brain.note || '').slice(0, 200)}`);
        if (!brain.reply) continue;

        await new Promise(r => setTimeout(r, 1500 + Math.floor(Math.random() * 2500)));
        await sock.sendMessage(jid, { text: brain.reply }, { quoted: m });   // quote = the humans' own convention
        log(`OUT ${brain.id} (${brain.reply.length} chars)`);
      } catch (e) {
        log('ERROR:', e && e.message);
      }
    }
  });
}

log('starting listener');
start().catch(e => { log('fatal:', e && e.message); process.exit(1); });
