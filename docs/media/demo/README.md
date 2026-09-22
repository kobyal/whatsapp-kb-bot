# Demo movie v2: knowledge-base support bot, Hebrew UI, groups + direct chat

`demo.mp4` — 1920x1080, 30 fps, H.264, **37.7 s**, no audio track (captioned; narration is mixed in separately, see below).
`demo.gif` — 720px wide, 10 fps, 2.7 MB, same content.
`frames/*.png` — 1080p stills of the seven beats.
`marks.json` — per beat: `start`, `end` (seconds) and `t` (the still-frame moment). Regenerated on every build.
`NARRATION-he.md` — Hebrew narration script, one line per beat, with the beat's start/end and its word budget.
`mix_narration.sh` — mixes Koby's recording onto `demo.mp4` → `demo-narrated.mp4`.

Changes from v1: everything on screen is Hebrew (UI, questions, bot answers, captions; small English sublines under the captions), the chat UI is mirrored for RTL (incoming on the right, own messages on the left, timestamp bottom-left, quote bar on the right), the title says groups **and** direct chat, and a screenshot beat was added.

## What is shown

| # | t (s) | Beat (`marks.json` name) | On screen |
|---|---|---|---|
| 1 | 0.0–3.0 | `title` | "בוט תמיכה לקבוצות וואטסאפ ולצ'אט פרטי" / "עונה רק ממה שבן אדם אימת. אחרת שותק." + English subline. |
| 2 | 3.0–8.4 | `group_answer` | Group "תמיכה בפלטפורמת הפיתוח": יואב asks the VPN will not connect. The bot replies quoted, header "● תשובה אוטומטית" (highlighted), with the VPN checklist in Hebrew. |
| 3 | 8.4–14.7 | `group_silence` | דנה asks about the IDE theme resetting (not in the KB). Typing dots appear and fade; amber "אין תשובה מאומתת ← שתיקה". The bot posts nothing. |
| 4 | 14.7–20.2 | `group_screenshot` | יואב sends a *picture*: a generic error dialog mock ("Connection error" title bar, "The connection was refused (ECONNREFUSED 127.0.0.1:3128)", OK button) with the caption "זה מה שאני מקבל ב-IDE". The bot quotes the image and answers in Hebrew from the proxy-agent entry. Caption: the bot reads screenshots too (vision). |
| 5 | 20.2–28.7 | `dm_answer` | 1:1 chat with "בוט תמיכה". Member says hi; bot asks once "לאיזה צוות את/ה שייך/ת? השב/י 1 או 2"; member answers 2; asks (Hebrew) that `git push` wants a password. Bot answers with the PAT entry, quoted, marked automatic. |
| 6 | 28.7–33.8 | `dm_nomatch` | Member asks about proxy settings inside Docker (not in the KB). Bot, plain text, highlighted: "אין לי תשובה מאומתת לזה. כדאי לשאול בקבוצה, כדי שבן אדם יעזור." |
| 7 | 33.8–37.7 | `end_card` | "תשובות שבן אדם אימת — או שתיקה." / "בחשבון ה-AWS שלכם." / github.com/kobyal/whatsapp-kb-bot |

Names (דנה, יואב), the group and the chat UI are fictional/generic; no product logos or trademarks; the screenshot is a drawn mock, not real product UI. The three bot answers are shortened Hebrew translations of the example KB entries `vpn_not_connecting`, `proxy_auth_dialog_407` and `git_pat_auth_failed` in `whatsapp-kb-bot/tenants/dev-platform/kb.json` — same steps, nothing invented. The screenshot's error string uses port 3128 (the KB's platform proxy agent, `http://127.0.0.1:3128`) so that the answer really is the KB entry.

## Narration (recorded by Koby, not synthesized)

1. Read `NARRATION-he.md`. Each beat has a start/end time and a word budget (~2.3 words/s minus a breath). Play `demo.mp4` alongside and start each line at its start time.
2. Record on macOS:
   - **QuickTime Player** → File → New Audio Recording → record → File → Export As → Audio Only (`.m4a`), or
   - **Voice Memos** → record → right-click the memo → Save to Files / drag it to the Finder (`.m4a`).
   - Either one pass as `narration.m4a` (aligned from t=0), or one file per beat: `beat1.m4a` … `beat7.m4a` (each just its sentence; timing is done by the script).
3. Mix:
   ```bash
   ./mix_narration.sh                    # finds narration.m4a/.wav next to the script, or beat1.* if no single file
   ./mix_narration.sh ~/Desktop/koby.m4a # explicit single file
   ./mix_narration.sh --beats ~/Desktop/beats   # beat1.m4a..beat7.m4a placed at each beat's start (adelay), mixed
   ```
   Output: `demo-narrated.mp4` (video copied, AAC 160k, `loudnorm` to -16 LUFS, audio padded/trimmed to the video). Tested with placeholder tones in both modes.

## How it was built

Manim Community 0.20.1 + ffmpeg, in the `my-lab` venv.

```bash
~/vscode/projects/my-lab/.venv/bin/python build.py                     # full 1080p build: demo.mp4, demo.gif, frames/, marks.json
FILM_QUALITY=-ql ~/vscode/projects/my-lab/.venv/bin/python build.py   # 480p15 draft, mp4 only
```

- `scenes.py` — one Manim scene (`Demo`). `Chat` draws a generic RTL chat panel; `Chat.image_bubble` + `screenshot_mock()` draw the picture message. `self.beat(name)` opens a narration beat (closing the previous one) and `self.mark()` records the still-frame moment; both go to `marks.json`.
- `build.py` — unchanged from v1: renders at 1920x1080/30, re-encodes to `demo.mp4` (libx264 crf 20, faststart), palette-optimised gif, one PNG per mark in `frames/`.

### Hebrew / RTL notes — keep these

- Manim's plain `Text` drops glyphs on RTL strings, and `MarkupText` hardcodes a 600x400 cairo surface with `pango_width=500`: at 4x render size long lines wrap and RTL lines (right-aligned to `pango_width`) are silently clipped off the surface. `scenes.py` monkeypatches `MarkupUtils.text2svg` to widen the surface and the layout together (12800 px surface, 12000 px layout). **Do not remove it.**
- Hebrew lines get a leading U+200F (RLM) so Pango keeps an RTL base direction even when the line starts with Latin (`git push …`). Lines that start with a long Latin phrase are still safest when re-worded to start with a Hebrew word (the PAT answer's first line was).
- Manim caches text SVGs under `media/texts/` and the cache key ignores `pango_width`; `build.py` deletes that folder before every render. **Keep the wipe.**
- No emoji in `Text`: colour emoji do not survive the cairo→SVG path (they render blank). The image quote says `[תמונה]` for that reason.
- Fonts: `Arial Hebrew` for Hebrew lines, `Helvetica Neue` for Latin (macOS system fonts).

Intermediates live under `media/`.
