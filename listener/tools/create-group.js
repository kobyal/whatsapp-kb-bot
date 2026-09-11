// Create a WhatsApp group from the bot account and add one or more phone numbers.
// Handy for a private "just me and the bot" test group.
//
//   sudo systemctl stop wakb                       # the auth dir must not be in use
//   cd /opt/wakb/src/listener
//   sudo -u wakb DATA_DIR=/opt/wakb/data node tools/create-group.js "KB Bot Test" 9725XXXXXXXX
//   sudo systemctl start wakb
//
// Prints the new group's jid and subject; add either to ALLOWED_GROUPS.
const path = require('path');
const pino = require('pino');
const { default: makeWASocket, useMultiFileAuthState } = require('@whiskeysockets/baileys');

const [subject, ...numbers] = process.argv.slice(2);
if (!subject || numbers.length === 0) {
  console.error('usage: node tools/create-group.js "<group name>" <phone number without +> [more numbers]');
  process.exit(2);
}
const AUTH = path.join(process.env.DATA_DIR || '/opt/wakb/data', 'auth');

(async () => {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH);
  const sock = makeWASocket({ auth: state, logger: pino({ level: 'silent' }), browser: ['Ubuntu', 'Chrome', '22.04.4'] });
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect }) => {
    if (connection === 'close') { console.error('connection closed', lastDisconnect && lastDisconnect.error && lastDisconnect.error.message); process.exit(1); }
    if (connection !== 'open') return;
    try {
      const g = await sock.groupCreate(subject, numbers.map(n => `${n.replace(/\D/g, '')}@s.whatsapp.net`));
      console.log(JSON.stringify({ jid: g.id, subject: g.subject, participants: g.participants.map(p => p.id) }, null, 2));
    } catch (e) { console.error('groupCreate failed:', e.message); process.exit(1); }
    setTimeout(() => process.exit(0), 1500);
  });
})();
