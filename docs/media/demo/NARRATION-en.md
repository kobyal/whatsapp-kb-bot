# Narration script — demo film (English)

One line per beat. The times come from `film/marks-en.json` for the current build; "max words"
is (beat length minus half a second to breathe) × ~2.6 words/second, which is an unhurried
English reading pace. There is no need to fill the time — finishing early is better than
running over, because the builder slows the *picture* to fit the voice.

Record with `python3 docs/media/demo/recorder.py --lang en`, which opens a page with one card
per line and writes `voice-en/beat<N>.wav`. Then build:

    python3 docs/media/demo/retime_to_narration.py --lang en

| # | beat | start | end | length | max words | text | words |
|---|---|---|---|---|---|---|---|
| 1 | `title` — Title | 0.00 | 3.00 | 3.0 s | 6 | A support bot for WhatsApp groups and private chats. | 8 |
| 2 | `group_answer` — Group, verified match | 3.00 | 8.37 | 5.4 s | 12 | Yoav asks about the VPN. The bot finds a verified answer and sends it, marked automatic. | 15 |
| 3 | `group_silence` — Group, no match, silence | 8.37 | 14.67 | 6.3 s | 15 | Dana asks something no one has verified. The bot says nothing. No guessing, no noise. | 14 |
| 4 | `group_screenshot` — Group, screenshot (vision) | 14.67 | 20.23 | 5.6 s | 13 | Yoav sends a screenshot. The bot reads the image and answers from the same knowledge base. | 15 |
| 5 | `dm_answer` — Direct chat, team question then answer | 20.23 | 28.70 | 8.5 s | 20 | In a private chat too. Once, it asks which team you are on, then answers exactly the same way. | 18 |
| 6 | `dm_nomatch` — Direct chat, no match | 28.70 | 33.77 | 5.1 s | 11 | With no verified answer in a private chat, it says so plainly, and invents nothing. | 14 |
| 7 | `end_card` — End card | 33.77 | 37.70 | 3.9 s | 8 | Answers a person verified, or silence. In your own AWS account. | 11 |

## The text alone (for reading)

1. (0.0s) A support bot for WhatsApp groups and private chats.
2. (3.0s) Yoav asks about the VPN. The bot finds a verified answer and sends it, marked automatic.
3. (8.4s) Dana asks something no one has verified. The bot says nothing. No guessing, no noise.
4. (14.7s) Yoav sends a screenshot. The bot reads the image and answers from the same knowledge base.
5. (20.2s) In a private chat too. Once, it asks which team you are on, then answers exactly the same way.
6. (28.7s) With no verified answer in a private chat, it says so plainly, and invents nothing.
7. (33.8s) Answers a person verified, or silence. In your own AWS account.

Notes: several lines run a little over the word budget on purpose — the picture stretches to fit,
and these beats have room. Read at a normal pace rather than rushing. "VPN" and "AWS" are said as
letters. The whole film is 37.7 seconds silent, and lands around 45 with narration.
