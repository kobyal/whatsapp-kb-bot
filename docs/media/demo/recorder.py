#!/usr/bin/env python3
"""A local voice recorder for the demo narration. Opens in the browser, runs only on this Mac.

One card per beat of NARRATION-he.md, each with record / stop / play. A take is written straight
to demo/voice/beat<N>.wav and a re-take overwrites it, so you can fix one line without reading
the whole script again. Nothing leaves localhost and nothing is uploaded anywhere.

There are two films, one per language, and each is narrated in its own:

    python3 docs/media/demo/recorder.py             # Hebrew: NARRATION-he.md -> voice/
    python3 docs/media/demo/recorder.py --lang en   # English: NARRATION-en.md -> voice-en/

Then build the narrated film:

    python3 docs/media/demo/retime_to_narration.py
    python3 docs/media/demo/retime_to_narration.py --lang en

Two things this checks that an ear cannot, while you still have the microphone open:

  * a take the microphone never heard is digital silence, and it is reported as needing a
    re-take instead of quietly becoming a silent beat in the film;
  * each beat has a time budget from marks.json. Going over is allowed -- the builder slows
    that piece of video to fit -- but past roughly 1.5x the picture visibly drags, so the card
    says how far over you are while re-recording is still cheap.
"""
import html
import http.server
import json
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
LANG = "en" if "--lang=en" in sys.argv or ("--lang" in sys.argv and sys.argv[sys.argv.index("--lang") + 1:sys.argv.index("--lang") + 2] == ["en"]) else "he"
SUF = "" if LANG == "he" else f"-{LANG}"      # the Hebrew film keeps the unsuffixed names
VOICE = HERE / f"voice{SUF}"
SCRIPT = HERE / f"NARRATION-{LANG}.md"
MARKS = HERE / "film" / ("marks.json" if LANG == "he" else f"marks-{LANG}.json")
PORT = 8801 if LANG == "he" else 8802         # so both can be open at once
SILENT_DB = -45.0          # below this the microphone heard nothing worth keeping

# Every string the page shows, in the language being recorded. One page template, two languages,
# exactly like the film itself.
UI = {
 "dir":      ("rtl", "ltr"),
 "font":     ('system-ui, "Arial Hebrew", Arial, sans-serif', "system-ui, -apple-system, Helvetica, Arial, sans-serif"),
 "title":    ("הקלטת קריינות — סרטון הדגמה", "Narration recorder — demo film"),
 "h1":       ("הקלטת קריינות — סרטון ההדגמה", "Narration recorder — the demo film"),
 "intro":    ("לוחצים <b>הקלטה</b>, קוראים את השורה, לוחצים <b>עצירה</b>. כל קטע נשמר מיד בתיקייה <code>voice</code>, "
              "והקלטה חדשה מחליפה את הקודמת — אפשר לתקן קטע בודד בלי לקרוא הכול מחדש.<br>"
              "הזמן שליד כל קטע הוא אורך הקטע בסרטון. מותר לחרוג: הבנייה מאטה את התמונה כדי להתאים לקול. "
              "חריגה גדולה תגרום לתמונה להיגרר, ואז כדאי לקצר את המשפט או לקרוא מהר יותר.",
              "Press <b>Record</b>, read the line, press <b>Stop</b>. Each take is written straight to "
              "<code>voice-en</code>, and recording again replaces just that beat — you never read the whole "
              "script twice.<br>The time beside each beat is how long it lasts on screen. Running over is "
              "allowed: the build slows the picture to match your voice. Run far over and the picture drags, "
              "so shorten the sentence or read a little faster."),
 "mic":      ("מיקרופון:", "Microphone:"),
 "meterhint":("דברו כדי לבדוק — הפס צריך לזוז", "Say something to test — the bar should move"),
 "next":     ("כשכל הקטעים ירוקים, בונים את הסרטון:", "When every beat is green, build the film:"),
 "cmd":      ("python3 docs/media/demo/retime_to_narration.py",
              "python3 docs/media/demo/retime_to_narration.py --lang en"),
 "rec":      ("● הקלטה", "● Record"),
 "stop":     ("■ עצירה", "■ Stop"),
 "play":     ("▶ השמעה", "▶ Play"),
 "secs":     (" שנ׳", "s"),
 "have":     ("יש הקלטה ✓ {s}{u}", "recorded ✓ {s}{u}"),
 "over":     ("יש הקלטה — {o}{u} מעל הקטע", "recorded — {o}{u} over the beat"),
 "silentmsg":("⚠ ההקלטה שמורה אבל שקטה — הקליטו שוב", "⚠ the take is saved but silent — record it again"),
 "saving":   ("שומר…", "saving…"),
 "failed":   ("השמירה נכשלה", "save failed"),
 "nosound":  ("⚠ לא נקלט קול — בדקו את המיקרופון למעלה והקליטו שוב",
              "⚠ no sound captured — check the microphone above and record again"),
 "savedover":("נשמר ✓ ${res.seconds} שנ׳ — ${res.over.toFixed(1)} שנ׳ מעל הקטע",
              "saved ✓ ${res.seconds}s — ${res.over.toFixed(1)}s over the beat"),
 "saved":    ("נשמר ✓ ${res.seconds} שנ׳", "saved ✓ ${res.seconds}s"),
 "recording":("● מקליט ' + s.toFixed(0) + ' שנ׳ / ' + card.dataset.secs + ' שנ׳",
              "● recording ' + s.toFixed(0) + 's / ' + card.dataset.secs + 's"),
 "micerr":   ("אין גישה למיקרופון: ", "No microphone access: "),
 "micfix":   (" — אשרו גישה בדפדפן, ובמק: הגדרות מערכת ← פרטיות ואבטחה ← מיקרופון.",
              " — allow it in the browser, and on a Mac in System Settings > Privacy & Security > Microphone."),
 "micname":  ("מיקרופון", "Microphone"),
 "noserver": ("⚠ ההקלטה לא נשמרה — שרת ההקלטה לא רץ. להריץ שוב  python3 docs/media/demo/recorder.py  ולרענן את הדף",
              "⚠ not saved — the recorder server is not running. Start it again with  python3 docs/media/demo/recorder.py  and reload this page"),
}
def U(k):
    return UI[k][0 if LANG == "he" else 1]


def beats():
    """The script lines, paired with each beat's length from marks.json."""
    marks = json.loads(MARKS.read_text(encoding="utf-8"))
    text = SCRIPT.read_text(encoding="utf-8")
    lines = re.findall(r"^\d+\.\s+\([\d.]+s\)\s+(.+)$", text, re.M)
    if len(lines) != len(marks):
        raise SystemExit(f"{SCRIPT.name} has {len(lines)} lines but {MARKS.name} has {len(marks)} beats")
    return [{"n": i, "name": m["name"], "secs": round(m["end"] - m["start"], 1), "text": t}
            for i, (m, t) in enumerate(zip(marks, lines), 1)]


def measure(path):
    """(peak dB, seconds) via ffmpeg, so 'saved' never means 'saved silence'."""
    log = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    mx = re.search(r"max_volume: (-?[\d.]+) dB", log)
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip()
    return (float(mx.group(1)) if mx else -91.0), (round(float(dur), 1) if dur else 0.0)


PAGE = """<!doctype html><html lang="__LANG__" dir="__DIR__"><head><meta charset="utf-8">
<title>__TITLE__</title><style>
body { font-family: __FONT__; background: #f3f5f9; color: #111827; margin: 0; }
main { max-width: 860px; margin: 0 auto; padding: 24px 20px 60px; }
h1 { margin: 0 0 4px; color: #0b3fb0; } .sub { color: #4b5563; margin: 0 0 18px; line-height: 1.6; }
.card { background: #fff; border: 1px solid #e5e7eb; border-inline-start: 5px solid #0b5fff; border-radius: 12px;
  padding: 14px 16px; margin-bottom: 12px; }
.card.done { border-inline-start-color: #15803d; }
.card.over { border-inline-start-color: #b45309; }
.card.rec { border-inline-start-color: #dc2626; box-shadow: 0 0 0 3px #fee2e2; }
.head { display: flex; gap: 10px; align-items: center; color: #6b7280; font-size: 14px; margin-bottom: 6px; }
.n { width: 28px; height: 28px; border-radius: 50%; background: #0b5fff; color: #fff; display: grid; place-items: center; font-weight: 700; }
.done .n { background: #15803d; } .over .n { background: #b45309; }
.scene { font-weight: 700; color: #111827; }
p { font-size: 21px; line-height: 1.7; margin: 4px 0 12px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
button { font: inherit; font-weight: 600; border: 0; border-radius: 8px; padding: 9px 18px; cursor: pointer; }
.go { background: #dc2626; color: #fff; } .stop { background: #111827; color: #fff; }
.play { background: #e5e7eb; } button:disabled { opacity: .4; cursor: default; }
.state { font-size: 14px; color: #6b7280; margin-inline-start: 8px; }
.warn { color: #b45309 !important; font-weight: 700; } .silent { color: #b91c1c !important; font-weight: 700; }
.mic { display: flex; align-items: center; gap: 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px 16px; margin-bottom: 16px; }
.mic select { font: inherit; padding: 6px 8px; border-radius: 8px; border: 1px solid #d1d5db; max-width: 360px; }
.meter { flex: 1; height: 12px; background: #e5e7eb; border-radius: 99px; overflow: hidden; min-width: 120px; }
#lvl { display: block; height: 100%; width: 0; background: #15803d; transition: width .08s; }
.err { background: #fee2e2; color: #991b1b; padding: 10px 14px; border-radius: 8px; display: none; }
.next { background: #eef2ff; border: 1px solid #c7d2fe; border-radius: 10px; padding: 12px 16px; margin-top: 18px; font-size: 15px; }
code { background: #eef2ff; padding: 2px 6px; border-radius: 5px; }
</style></head><body><main>
<h1>__H1__</h1>
<p class="sub">__INTRO__</p>
<div id="err" class="err"></div>
<div class="mic"><label>__MIC__ <select id="dev"></select></label>
<span class="meter"><span id="lvl"></span></span><span id="lvltxt" class="state">__METERHINT__</span></div>
__CARDS__
<div class="next">__NEXT__<br>
<code>__CMD__</code></div>
</main><script>
let rec = null, chunks = [], started = 0, tick = null, live = null;
const $ = (s, e = document) => e.querySelector(s);
const showErr = (t) => { const b = $('#err'); b.textContent = t; b.style.display = 'block'; };
function constraints() {
  const id = $('#dev').value;
  return { audio: Object.assign({ echoCancellation: true, noiseSuppression: true }, id ? { deviceId: { exact: id } } : {}) };
}
// A live level meter on the chosen microphone: the only way to know it hears you before a take.
async function monitor() {
  if (live) live.getTracks().forEach((t) => t.stop());
  try { live = await navigator.mediaDevices.getUserMedia(constraints()); }
  catch (e) { showErr('__MICERR__' + e.message + '__MICFIX__'); return; }
  const ctx = new AudioContext(), an = ctx.createAnalyser(); an.fftSize = 1024;
  ctx.createMediaStreamSource(live).connect(an);
  const buf = new Float32Array(an.fftSize);
  const draw = () => {
    an.getFloatTimeDomainData(buf);
    let m = 0; for (const v of buf) m = Math.max(m, Math.abs(v));
    $('#lvl').style.width = Math.min(100, m * 250) + '%';
    requestAnimationFrame(draw);
  };
  draw();
  const devs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput');
  const sel = $('#dev'), cur = sel.value || live.getAudioTracks()[0].getSettings().deviceId;
  sel.innerHTML = devs.map((d) => `<option value="${d.deviceId}">${d.label || '__MICNAME__'}</option>`).join('');
  sel.value = cur;
}
$('#dev').onchange = monitor;
monitor();
async function start(card) {
  if (rec) return;
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia(constraints()); }
  catch (e) { showErr('__MICERR__' + e.message); return; }
  chunks = []; rec = new MediaRecorder(stream, { mimeType: 'audio/webm' });
  rec.ondataavailable = (e) => chunks.push(e.data);
  rec.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    const blob = new Blob(chunks, { type: 'audio/webm' });
    const st = $('.state', card);
    st.textContent = '__SAVING__'; st.className = 'state';
    // The recorder is a local server, and it can be gone (window closed, Ctrl-C, a machine
    // asleep). Without this the fetch rejects, the handler dies half way, and the card sits on
    // "recording" for ever -- which looks exactly like a Stop button that does nothing.
    let r, res = {};
    try {
      r = await fetch('/save?n=' + card.dataset.n, { method: 'POST', body: blob });
      res = await r.json().catch(() => ({}));
    } catch (e) {
      card.classList.remove('rec');
      st.textContent = '__NOSERVER__'; st.className = 'state silent';
      $('.go', card).disabled = false; $('.stop', card).disabled = true;
      document.querySelectorAll('.go').forEach((b) => b.disabled = false);
      rec = null; clearInterval(tick);
      return;
    }
    card.classList.remove('rec', 'done', 'over');
    if (!r.ok) { st.textContent = '__FAILED__'; }
    else if (res.silent) { st.textContent = '__NOSOUND__'; st.className = 'state silent'; }
    else if (res.over > 0.4) { st.textContent = `__SAVEDOVER__`; st.className = 'state warn'; card.classList.add('over'); }
    else { st.textContent = `__SAVED__`; card.classList.add('done'); }
    const a = $('audio', card); a.src = '/audio/beat' + card.dataset.n + '.wav?' + Date.now();
    $('.play', card).disabled = false; $('.go', card).disabled = false; $('.stop', card).disabled = true;
    document.querySelectorAll('.go').forEach((b) => b.disabled = false);
    rec = null; clearInterval(tick);
  };
  rec.start(); started = Date.now();
  card.classList.add('rec'); $('.stop', card).disabled = false;
  document.querySelectorAll('.go').forEach((b) => b.disabled = true);
  tick = setInterval(() => {
    const s = (Date.now() - started) / 1000;
    $('.state', card).textContent = '__RECORDING__';
  }, 250);
}
document.querySelectorAll('.card').forEach((card) => {
  $('.go', card).onclick = () => start(card);
  $('.stop', card).onclick = () => rec && rec.stop();
  $('.play', card).onclick = () => $('audio', card).play();
});
</script></body></html>"""


def page():
    cards = []
    for b in beats():
        f = VOICE / f"beat{b['n']}.wav"
        have = f.exists()
        peak, secs = measure(f) if have else (-91.0, 0.0)
        silent = have and peak < SILENT_DB
        over = round(secs - b["secs"], 1) if have else 0.0
        cls, state = "", ""
        if have and not silent:
            cls, state = (("over", U("over").format(o=over, u=U("secs"))) if over > 0.4
                          else ("done", U("have").format(s=secs, u=U("secs"))))
        elif silent:
            state = U("silentmsg")
        cards.append(
            f"""<div class="card {cls}" data-n="{b['n']}" data-secs="{b['secs']}"><div class="head">
<span class="n">{b['n']}</span><span class="scene">{html.escape(b['name'])}</span><span>{b['secs']}{U("secs")}</span></div>
<p>{html.escape(b['text'])}</p><div class="row"><button class="go">{U("rec")}</button>
<button class="stop" disabled>{U("stop")}</button>
<button class="play"{'' if have else ' disabled'}>{U("play")}</button>
<span class="state{' warn' if cls == 'over' else ' silent' if silent else ''}">{state}</span>
<audio{f' src="/audio/beat{b["n"]}.wav"' if have else ''}></audio></div></div>""")
    page = PAGE.replace("__CARDS__", "".join(cards))
    for key, token in (("dir", "__DIR__"), ("font", "__FONT__"), ("title", "__TITLE__"), ("h1", "__H1__"),
                       ("intro", "__INTRO__"), ("mic", "__MIC__"), ("meterhint", "__METERHINT__"),
                       ("next", "__NEXT__"), ("cmd", "__CMD__"), ("saving", "__SAVING__"),
                       ("failed", "__FAILED__"), ("nosound", "__NOSOUND__"), ("savedover", "__SAVEDOVER__"),
                       ("saved", "__SAVED__"), ("recording", "__RECORDING__"), ("micerr", "__MICERR__"),
                       ("micfix", "__MICFIX__"), ("micname", "__MICNAME__"), ("noserver", "__NOSERVER__")):
        page = page.replace(token, U(key))
    return page.replace("__LANG__", LANG).encode()


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self._send(200, page(), "text/html; charset=utf-8")
        m = re.match(r"^/audio/beat(\d+)\.wav", self.path)
        if m and (VOICE / f"beat{m.group(1)}.wav").exists():
            return self._send(200, (VOICE / f"beat{m.group(1)}.wav").read_bytes(), "audio/wav")
        self._send(404, b"not found")

    def do_POST(self):
        m = re.match(r"^/save\?n=(\d+)$", self.path)
        if not m:
            return self._send(400, b"bad request")
        n = int(m.group(1))
        budget = next((b["secs"] for b in beats() if b["n"] == n), 0.0)
        VOICE.mkdir(exist_ok=True)
        raw = VOICE / f"beat{n}.webm"
        raw.write_bytes(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        # One-deep undo. A re-take overwrites the file, and a bad one (a muted microphone, a
        # stray click) would otherwise destroy a good recording with nothing to go back to.
        prev = VOICE / f"beat{n}.wav"
        if prev.exists():
            (VOICE / ".previous").mkdir(exist_ok=True)
            shutil.copy2(prev, VOICE / ".previous" / f"beat{n}.wav")
        # Convert on save: the builders take wav, and a webm that only the browser can read
        # is a trap you discover at build time instead of here.
        wav = VOICE / f"beat{n}.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(wav)],
                       check=True)
        raw.unlink(missing_ok=True)
        peak, secs = measure(wav)
        silent = peak < SILENT_DB
        over = round(secs - budget, 1)
        print(f"  saved voice/{wav.name}  {secs}s (beat {budget}s)  peak {peak} dB"
              + ("  SILENT" if silent else f"  over {over}s" if over > 0.4 else ""))
        self._send(200, json.dumps({"ok": True, "silent": silent, "peak": peak,
                                    "seconds": secs, "over": over}).encode(), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    beats()                      # fail loudly here, not after the browser is open
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"recorder on http://localhost:{PORT}  -> saves to {VOICE}\n(Ctrl-C to stop)")
    threading.Timer(0.6, lambda: webbrowser.open(f"http://localhost:{PORT}")).start()
    srv.serve_forever()
