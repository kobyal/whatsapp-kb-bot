// Serves the CURRENT WhatsApp linking QR as a page that re-renders every 4 seconds.
// The QR rotates every 20-60 s, so "save it to a PNG and send it to someone" always
// loses the race; a self-refreshing page does not.
//
// Bound to 127.0.0.1 only. Reach it through an SSM port-forward (scripts/qr.sh). A
// publicly reachable linking QR would let anyone link the bot account to THEIR phone.
const http = require('http');
const fs = require('fs');
const path = require('path');
const QRCode = require('qrcode');

const DIR = process.env.DATA_DIR || '/opt/wakb/data';
const PORT = Number(process.env.QR_PORT || 8080);
const page = (body, refresh) => `<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="${refresh}">
<title>WhatsApp KB bot - link device</title>
<body style="font-family:system-ui;text-align:center;padding:32px;background:#0b141a;color:#e9edef">${body}</body>`;

http.createServer(async (req, res) => {
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
  const ready = path.join(DIR, 'READY');
  if (fs.existsSync(ready)) {
    return res.end(page(`<h1 style="color:#25d366">Linked</h1><p>The bot is connected as +${fs.readFileSync(ready)}.</p>
      <p style="color:#8696a0">You can close this page. To re-link, delete the auth folder and restart the service.</p>`, 10));
  }
  let qr = '';
  try { qr = fs.readFileSync(path.join(DIR, 'qr.txt'), 'utf8').trim(); } catch (e) { /* not yet */ }
  if (!qr) return res.end(page('<h2>Waiting for the listener to produce a QR code...</h2>', 3));
  const img = await QRCode.toDataURL(qr, { width: 400, margin: 2 });
  const age = Math.round((Date.now() - fs.statSync(path.join(DIR, 'qr.txt')).mtimeMs) / 1000);
  res.end(page(`<h2 style="margin:0 0 6px">Scan with the bot's phone</h2>
    <div style="color:#8696a0;font-size:14px;margin-bottom:16px">WhatsApp &rarr; Linked devices &rarr; Link a device<br>
    this code is ${age}s old &middot; page refreshes every 4s</div>
    <img src="${img}" style="border-radius:12px">`, 4));
}).listen(PORT, '127.0.0.1', () => console.log(`qrserve on 127.0.0.1:${PORT}`));
