# Demo movie: knowledge-base support bot in a chat app

`demo.mp4` — 1920x1080, 30 fps, H.264, **34.2 s**, no audio track needed (captions only, works muted).
`demo.gif` — 720px wide, 10 fps, 2.4 MB, same content.
`frames/*.png` — 1080p stills of the six key moments (title, group_answer, group_silence, dm_answer, dm_nomatch, end_card).

## What is shown

| t (s) | Beat | On screen |
|---|---|---|
| 0–3 | Title | "A knowledge-base bot for support groups. It answers only what a person has verified. Otherwise it stays quiet." |
| 3–9 | 1 · GROUP | In the fictional group "Dev Platform Support", Yoav asks in Hebrew that the VPN will not connect. The bot replies as a quoted reply with a small "automatic answer" header line (highlighted) and the VPN checklist from the example KB. |
| 9–16 | 2 · GROUP | Dana asks something the KB does not cover (IDE theme resets). A typing indicator appears and fades; an amber caption reads "no verified answer → silence". The bot posts nothing. |
| 16–25 | 3 · DIRECT | A 1:1 chat with "Support bot". The member says hi; the bot asks once "Which team are you on? Reply 1 or 2"; the member answers "2", then asks (Hebrew) that git push wants a password. The bot answers with the personal-access-token entry, quoted, marked automatic. |
| 25–31 | 4 · DIRECT | The member asks about proxy settings inside Docker (not in the KB). The bot replies in plain text: "I don't have a verified answer for this. Please ask in the group so a person can help." (highlighted). |
| 31–34 | End card | "Curated answers, or silence. / Your AWS account. / github.com/kobyal/whatsapp-kb-bot" |

All names (Dana, Yoav), the group name and the chat UI are fictional/generic; no product logos or trademarks. The two bot answers are shortened from the brand-neutral example KB entries `vpn_not_connecting` and `git_pat_auth_failed` in `whatsapp-kb-bot/kb/kb.json`.

## How it was built

Same toolkit as `code-explainer-film` (Manim Community 0.20.1 + ffmpeg, in the `my-lab` venv), without narration.

```bash
~/vscode/projects/my-lab/.venv/bin/python build.py            # full 1080p build: demo.mp4, demo.gif, frames/
FILM_QUALITY=-ql ~/vscode/projects/my-lab/.venv/bin/python build.py   # 480p15 draft, mp4 only
```

- `scenes.py` — one Manim scene (`Demo`). A small `Chat` class draws a generic chat panel (header with initials avatar, wallpaper, bubbles with name / quote strip / header line / timestamp) and scrolls the column when it overflows. Captions live in a left column. `self.mark(name)` records the time of each key moment to `marks.json`.
- `build.py` — renders the scene at 1920x1080/30 fps, re-encodes to `demo.mp4` (libx264 crf 20, faststart), makes the palette-optimised gif, and extracts one PNG per mark into `frames/`.

### Hebrew / RTL notes (the part that took the iterations)

- Manim's plain `Text` drops glyphs on RTL strings (the "ה-" prefix vanished) and the 4x-render trick made `MarkupText` wrap, because `MarkupText` hardcodes a 600x400 cairo surface and `pango_width=500`. RTL lines are right-aligned to `pango_width`, so anything past the surface edge is silently clipped. `scenes.py` monkeypatches `MarkupUtils.text2svg` to widen the surface and the layout together (12800 px surface, 12000 px layout) — no wrapping, nothing clipped.
- Hebrew lines that start with Latin ("git push …") get a leading U+200F (RLM) so Pango keeps an RTL base direction.
- Manim caches text SVGs under `media/texts/` and the cache key ignores `pango_width`; `build.py` deletes that folder before every render.
- Hebrew font: `Arial Hebrew`; Latin: `Helvetica Neue` (both macOS system fonts).

Intermediates live under `media/`; `marks.json` is regenerated each build.
