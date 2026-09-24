#!/usr/bin/env python3
"""Fit the video to the narration instead of the narration to the video.

    python3 retime_to_narration.py [--lang en] [BEATDIR] [--gap 0.5]

Defaults follow the language: Hebrew reads voice/ + film/marks.json + demo.mp4 and writes
demo-narrated.mp4; English reads voice-en/ + film/marks-en.json + demo-en.mp4 and writes
demo-en-narrated.mp4. The two never share a file.

For each beat k in marks.json: trim silence off beatK.wav, and if the speech is longer than the
beat, slow that video segment (setpts) so the beat lasts speech+gap. Segments that already fit
are left alone. Voice is never time-stretched. Output: demo-narrated.mp4 (+ marks-narrated.json).
"""
import json, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
argv = sys.argv[1:]
LANG = "en" if "--lang=en" in argv or (("--lang" in argv) and argv[argv.index("--lang") + 1:argv.index("--lang") + 2] == ["en"]) else "he"
SUF = "" if LANG == "he" else f"-{LANG}"
skip = set()
if "--lang" in argv:
    skip = {argv.index("--lang"), argv.index("--lang") + 1}
args = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
# Absolute: ffmpeg resolves the paths inside a concat list relative to the list file itself,
# so a relative BEATDIR silently becomes voice/_retime/voice/_retime/seg1.mp4 and fails.
beatdir = (pathlib.Path(args[0]).resolve() if args else HERE / f"voice{SUF}")
gap = float(sys.argv[sys.argv.index("--gap") + 1]) if "--gap" in sys.argv else 0.5
video = HERE / f"demo{SUF}.mp4"
marks = json.load(open(HERE / "film" / ("marks.json" if LANG == "he" else f"marks-{LANG}.json")))
if not video.exists():
    raise SystemExit(f"no film at {video.name} — build it first: DEMO_LANG={LANG} python3 film/build.py")
takes = sorted(beatdir.glob("beat*.wav")) if beatdir.is_dir() else []
if not takes:
    raise SystemExit(f"no takes in {beatdir.name}/ — record them first: "
                     f"python3 docs/media/demo/recorder.py{' --lang ' + LANG if LANG != 'he' else ''}")
if len(takes) < len(marks):
    print(f"note: {len(takes)} of {len(marks)} beats recorded; the rest stay silent")
work = beatdir / "_retime"; work.mkdir(parents=True, exist_ok=True)

def run(*cmd): subprocess.run(["ffmpeg", "-y", "-v", "error", *cmd], check=True)
def dur(p): return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).strip())

segs, t = [], 0.0
for i, m in enumerate(marks, 1):
    orig = m["end"] - m["start"]
    src = next((beatdir / f"beat{i}.{e}" for e in ("wav", "m4a", "mp3") if (beatdir / f"beat{i}.{e}").exists()), None)
    speech = None
    if src:
        trimmed = work / f"beat{i}.wav"
        run("-i", str(src), "-af", "silenceremove=start_periods=1:start_threshold=-40dB,areverse,silenceremove=start_periods=1:start_threshold=-40dB,areverse,apad=pad_dur=0.15", str(trimmed))
        speech = dur(trimmed)
    new = max(orig, (speech or 0) + gap)
    seg = work / f"seg{i}.mp4"
    run("-ss", str(m["start"]), "-to", str(m["end"]), "-i", str(video), "-an",
        "-vf", f"setpts={new/orig:.5f}*PTS", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(seg))
    segs.append({"beat": m.get("beat", i), "start": round(t, 2), "end": round(t + new, 2), "speech": speech, "slow": round(new / orig, 2)})
    print(f"beat{i}: video {orig:4.1f}s  speech {speech or 0:4.1f}s  -> {new:4.1f}s  (x{new/orig:.2f})")
    t += new

(work / "list.txt").write_text("".join(f"file '{work}/seg{i}.mp4'\n" for i in range(1, len(marks) + 1)))
run("-f", "concat", "-safe", "0", "-i", str(work / "list.txt"), "-c", "copy", str(work / "video.mp4"))

inputs, fc, mix, k = [], "", "", 0
for i, s in enumerate(segs, 1):
    if s["speech"] is None: continue
    k += 1; ms = int(round(s["start"] * 1000))
    inputs += ["-i", str(work / f"beat{i}.wav")]
    fc += f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[b{k}];"; mix += f"[b{k}]"
fc += f"{mix}amix=inputs={k}:duration=longest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11,apad[a]"
out = HERE / f"demo{SUF}-narrated.mp4"
run("-i", str(work / "video.mp4"), *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out))
json.dump(segs, open(HERE / f"marks{SUF}-narrated.json", "w"), ensure_ascii=False, indent=1)
print(f"-> {out}  {dur(out):.1f}s  (was {dur(video):.1f}s)")
