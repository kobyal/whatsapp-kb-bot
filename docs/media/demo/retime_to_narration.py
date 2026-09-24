#!/usr/bin/env python3
"""Fit the video to the narration instead of the narration to the video.

    python3 retime_to_narration.py [BEATDIR] [--gap 0.5]

For each beat k in marks.json: trim silence off beatK.wav, and if the speech is longer than the
beat, slow that video segment (setpts) so the beat lasts speech+gap. Segments that already fit
are left alone. Voice is never time-stretched. Output: demo-narrated.mp4 (+ marks-narrated.json).
"""
import json, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
args = [a for a in sys.argv[1:] if not a.startswith("--")]
# Absolute: ffmpeg resolves the paths inside a concat list relative to the list file itself,
# so a relative BEATDIR silently becomes voice/_retime/voice/_retime/seg1.mp4 and fails.
beatdir = (pathlib.Path(args[0]).resolve() if args else HERE)
gap = float(sys.argv[sys.argv.index("--gap") + 1]) if "--gap" in sys.argv else 0.5
video, marks = HERE / "demo.mp4", json.load(open(HERE / "marks.json"))
work = beatdir / "_retime"; work.mkdir(exist_ok=True)

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
out = HERE / "demo-narrated.mp4"
run("-i", str(work / "video.mp4"), *inputs, "-filter_complex", fc, "-map", "0:v", "-map", "[a]",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out))
json.dump(segs, open(HERE / "marks-narrated.json", "w"), ensure_ascii=False, indent=1)
print(f"-> {out}  {dur(out):.1f}s  (was {dur(video):.1f}s)")
