# The KB curator

A **separate, optional layer** that learns from what the bot already logged and lands changes
in the knowledge bases at three confidence tiers. It touches nothing on the operational path:
the listener and the brain are unchanged, and a bug here can never reach a group.

```
bot.log ──fetch_log.py (SSM read)──► events.py ──► curate.py ──► Tier A applied · Tier B drafts · Tier C digest
```

| File | Does |
|---|---|
| `fetch_log.py` | Pulls `/opt/wakb/data/bot.log` over SSM in gzip+base64 slices. A read; no agent or shipper on the box. |
| `events.py` | One event per `IN`+`BRAIN` pair. Both log generations, supporters **by identity** from `tenant.json`, a Lambda timeout envelope or a `BRAIN ERROR` line as `outcome=error`. |
| `curate.py` | Usage, repeated-question clusters, near-miss re-classification, verified trigger fixes, drafts, review flags, open gaps, digest. |
| `tests/` | The deterministic parts against `fixture-bot.log` (fictional ids). `python3 -m pytest curator/tests -q` |

## The daily run

```bash
export AWS_PROFILE=... AWS_REGION=eu-west-1 KB_TABLE_PREFIX=wakb-kb-     # read the live KB tables
python3 curator/fetch_log.py --instance <instance-id> --out /tmp/bot.log
python3 curator/curate.py --log /tmp/bot.log --days 1 --apply-triggers --write-drafts --out /tmp/digest.md
```

Tier A writes `tenants/<id>/kb.json` and publishes through `kb/publish.py`: **commit the result**,
that file is the source of truth. Tier B writes only to the KB table (status `draft`); the repo
is untouched until the owner publishes and the next `publish.py` run reports it as "draft in
table, not in file". With `KB_TABLE_PREFIX` empty (no tables) Tier A edits `kb.json` only.

Models: the brain's classifier (`CLASSIFY_MODEL`, Haiku) for re-classification, and
`CURATOR_MODEL` (default Claude Sonnet 4.6 on Bedrock) for the judgements: thread
confirmation, trigger distillation, drafting, clustering. `--no-model` gives the numbers only.

## Three tiers: what it may do alone

| Tier | Change | Gate | Who clicks |
|---|---|---|---|
| **A, applied** | a phrasing added to an **existing** entry's triggers, at position <= 6 | a human in the thread gave **that entry's** answer and the asker accepted it; re-classifying the missed message against the modified entry clears the floor; kbcheck adds no error or warning (pre-existing warnings on other entries do not block) | nobody: the answer text never changes |
| **B, draft** | a **new** entry | a human answered and the asker confirmed **after** the first answer (a code gate: the model once read a screenshot sent before the answer as acknowledgement); a referral is not an answer; kbcheck; not a duplicate of an existing id; never overwrites an id | the tenant's KB owner |
| **C, reported** | nothing | | the digest reader |

The line between A and B is the design rule: **the bot never writes an answer.** People do.
Tier A changes how an answer is *found*, never what it *says*. A thread that produced an
applied Tier A fix is not also drafted.

## Test rooms

Each tenant's `test_groups` (in `tenant.json`) are **excluded by default**: they are one person
talking to the bot, not the group. `--include-test-groups` includes them and lets that one
person play asker, answerer and confirmer, which is how the pipeline is proven end to end before
it is trusted on a real group. It is never right for a real group.

## What the log cannot tell you

`text` is cut at 160 characters and the note at 200; the near-miss entry is not in the note at
all (the curator recovers it by re-classifying offline). Drafts say so in `notes`; verify against
the chat before publishing. Review flags ("a supporter spoke within 30 minutes of a confident
answer") over-fire; they are a reading list, not a verdict.
