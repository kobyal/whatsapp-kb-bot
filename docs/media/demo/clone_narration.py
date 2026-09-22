#!/usr/bin/env python3
"""Clone the narrator's voice and read NARRATION-he.md, one file per beat, for mix_narration.sh --beats.

    python3 -m venv .venv && .venv/bin/pip install chatterbox-tts soundfile
    .venv/bin/python clone_narration.py my_voice.wav [outdir]

my_voice.wav: 15-30 s of the narrator speaking Hebrew, quiet room, no music (m4a/mp3 fine: ffmpeg converts).
Chatterbox Multilingual (Resemble AI, MIT) lists Hebrew; on an M1 Pro a 6 s line takes ~15 s on MPS.
Then: ./mix_narration.sh --beats [outdir]
"""
import json, re, subprocess, sys, pathlib

HERE = pathlib.Path(__file__).resolve().parent
ref = pathlib.Path(sys.argv[1]); out = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else HERE); out.mkdir(exist_ok=True)

# reference -> 24 kHz mono wav (the model resamples anyway; this just avoids codec surprises)
ref_wav = out / "_ref.wav"
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ref), "-ar", "24000", "-ac", "1", str(ref_wav)], check=True)

# lines from the "text only" section of NARRATION-he.md: "1. (0.0s) text"
lines = re.findall(r"^\d+\.\s+\([\d.]+s\)\s+(.+)$", (HERE / "NARRATION-he.md").read_text(encoding="utf-8"), re.M)
marks = json.load(open(HERE / "marks.json"))
assert len(lines) == len(marks), f"{len(lines)} lines vs {len(marks)} beats"

import torch, soundfile as sf, perth
if getattr(perth, "PerthImplicitWatermarker", None) is None:  # missing on some Python builds
    class _NoWM:
        def apply_watermark(self, wav, sample_rate=None, **k): return wav
    perth.PerthImplicitWatermarker = _NoWM
from chatterbox.mtl_tts import ChatterboxMultilingualTTS
device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
model = ChatterboxMultilingualTTS.from_pretrained(device=device)

for i, (text, m) in enumerate(zip(lines, marks), 1):
    budget = m["end"] - m["start"] - 0.3
    wav = model.generate(text, language_id="he", audio_prompt_path=str(ref_wav))
    dur = wav.shape[-1] / model.sr
    f = out / f"beat{i}.wav"
    sf.write(f, wav.squeeze().cpu().numpy(), model.sr)
    flag = "" if dur <= budget else f"  <-- {dur-budget:.1f}s over the beat; shorten the line or re-run"
    print(f"beat{i}: {dur:4.1f}s / {budget:4.1f}s  {text[:40]}{flag}")
print(f"-> {out}/beat1..{len(lines)}.wav ; now: ./mix_narration.sh --beats {out}")
