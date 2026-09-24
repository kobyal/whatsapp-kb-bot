"""Build the demo: Manim scene -> 1080p30 mp4, a <=10 MB gif, and still frames of the key beats.

    DEMO_LANG=he python film/build.py          # -> demo.mp4,    demo.gif,    frames/*.png
    DEMO_LANG=en python film/build.py          # -> demo-en.mp4, demo-en.gif, frames-en/*.png
    FILM_QUALITY=-ql DEMO_LANG=en python film/build.py    # quick draft, no gif or frames

Needs manim (`pip install manim`) and ffmpeg. Everything lands one directory up, in docs/media/demo,
because that is where the article and the README reference it from.

No narration here: the film is captioned and works muted. Voice is added afterwards by
recorder.py + retime_to_narration.py, which never touch the picture this produces.
"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); VENV = os.path.dirname(sys.executable)
OUT = os.path.dirname(HERE)                  # docs/media/demo
LANG = os.environ.get("DEMO_LANG", "he").lower()
SUF = "" if LANG == "he" else f"-{LANG}"     # the Hebrew film keeps the unsuffixed names
Q = os.getenv("FILM_QUALITY", "-qh")
RES = {"-ql": ("854,480", "15", "480p15"), "-qh": ("1920,1080", "30", "1080p30")}[Q]

def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                          "-of", "csv=p=0", p]).strip())

import shutil; shutil.rmtree(os.path.join(HERE, "media", "texts"), ignore_errors=True)  # Pango SVG cache survives --disable_caching
subprocess.run([os.path.join(VENV, "manim"), "-r", RES[0], "--fps", RES[1], "--disable_caching",
                "-o", "demo_raw.mp4", os.path.join(HERE, "scenes.py"), "Demo"],
               check=True, cwd=HERE, env={**os.environ, "DEMO_LANG": LANG})
raw = os.path.join(HERE, "media", "videos", "scenes", RES[2], "demo_raw.mp4")
mp4 = os.path.join(OUT, f"demo{SUF}.mp4")
subprocess.run(["ffmpeg", "-y", "-i", raw, "-c:v", "libx264", "-preset", "slow", "-crf", "20",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4], check=True, capture_output=True)
if Q == "-qh":
    gif = os.path.join(OUT, f"demo{SUF}.gif")
    subprocess.run(["ffmpeg", "-y", "-i", mp4, "-vf",
                    "fps=10,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                    "-loop", "0", gif], check=True, capture_output=True)
    fr = os.path.join(HERE, f"frames{SUF}"); os.makedirs(fr, exist_ok=True)
    marks = os.path.join(HERE, "marks.json" if LANG == "he" else f"marks-{LANG}.json")
    for m in json.load(open(marks)):
        subprocess.run(["ffmpeg", "-y", "-ss", str(max(0, m["t"] - 0.05)), "-i", mp4, "-frames:v", "1",
                        os.path.join(fr, f"{m['name']}.png")], check=True, capture_output=True)
    shutil.copy(marks, os.path.join(OUT, os.path.basename(marks)))   # the mixers read it from there
    print("gif MB", round(os.path.getsize(gif) / 1e6, 2))
print(f"[{LANG}] duration", round(dur(mp4), 2), "s ->", mp4)
