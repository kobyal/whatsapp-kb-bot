# WhatsApp KB bot

A WhatsApp bot that answers repeat questions in a support group from a **curated knowledge
base**, running entirely in your own AWS account. The model picks *which* answer applies;
it never writes one. What the group receives is text a human wrote, verbatim. When nothing
matches well enough, the bot asks **one fixed clarifying question**, or stays silent.

Built from a bot that has been answering two company support groups (about 120 and 90
people) since mid-2026. This repo is the generic, brand-neutral template of that system, kept
in step with it: multi-tenant, conversation-aware, with an optional 1:1 mode and a separate
"curator" layer that learns from the bot's own log.

![architecture](docs/diagrams/architecture.png)

**Watch the 44-second demo:** https://youtu.be/XYJXuLu0HpE — a group answer, a deliberate
silence, a screenshot being read, and a direct chat. The silent cuts are in the repo
(`docs/media/demo/demo.mp4` Hebrew, `demo-en.mp4` English); `film/` rebuilds either from one
scene, and `recorder.py` + `retime_to_narration.py` add narration.

**Read the article on Medium:** *coming soon* — the write-up of how this was built.

## What you get

| Folder | What |
|---|---|
| `tenants/<id>/` | One folder per group family ("tenant"): `tenant.json` (groups, header, prompts' audience text, clarifying questions, supporters, fixed texts) and `kb.json` (the knowledge base). Two examples ship: `dev-platform` (17 entries, an internal developer-platform support group, Hebrew + English triggers) and `office-it` (4 entries, a Hebrew office-IT group). Delete the second for a single-tenant deploy, or keep it: an unknown group falls back to the default tenant |
| `kb/` | `kbcheck.py` validates a KB (rules R0-R15, including the WhatsApp formatting traps), `publish.py` syncs it to that tenant's DynamoDB table |
| `brain/` | One Python Lambda for all tenants. Screens the message (is it a request? on-domain? too vague?), asks Bedrock (Claude Haiku 4.5) which entry answers it, applies a confidence floor, and returns `answer`, `clarify` or `silent`. Optional screenshot reading with Claude Sonnet. `build.sh` assembles `tenants.json`; `tests/` run offline |
| `listener/` | Node.js service for an always-on EC2 box. Holds the WhatsApp session with [Baileys](https://github.com/WhiskeySockets/Baileys), forwards allowlisted group messages (and, if enabled, 1:1 messages from group members) to the brain, sends the reply. Plus a self-refreshing QR page for linking |
| `curator/` | Optional, workstation-run. Reads the listener's log over SSM and turns it into KB maintenance at three confidence tiers: verified trigger fixes (applied), draft entries (for a human), and a digest. Never touches the operational path |
| `tools/probe.py` | Runs real questions through the real brain offline (Bedrock only), so you can tune triggers before you publish |
| `infra/terraform/` | Everything above as Terraform: VPC, EC2, Lambda, one KB table per tenant, the conversation-state table, IAM |
| `infra/cloudformation/` | The same stack as one CloudFormation template (up to two tenants) plus a `deploy.sh` |
| `scripts/` | `ask.sh` (test the deployed brain), `qr.sh` (link the phone), `logs.sh`, `shell.sh`, all over SSM, no SSH |
| `docs/` | The article, diagrams, design notes, testing notes, the validation record, and a survey of open-source alternatives |

**Cost.** About $18/month for the EC2 (t3.small, 24/7). Bedrock: **$0.0013 per message that
the screen stops** (most messages in a group are not questions) and **$0.0024 per message that
is fully classified**, measured on the production bot with Haiku 4.5 and a cached catalogue
prefix. With a small KB the classify prefix is below Haiku's prompt-cache minimum and the
classify call costs about $0.004 uncached; it still rounds to nothing at support-group volumes.
Everything else is on-demand and rounds to zero.

## Before you start: read this

- **This uses an unofficial WhatsApp client.** Baileys speaks the WhatsApp Web protocol as a
  linked device. That is against WhatsApp's terms of service, and numbers do get banned.
  The official Business Cloud API is the compliant route, but its Groups API caps groups at
  **8 participants** and cannot join a group a person created, so it cannot serve an
  existing community group. Use a **dedicated prepaid number**, never your own. Keep the bot
  reply-only, low volume, and in groups of people who know it is there.
  See `docs/DESIGN.md` and `docs/research/open-source-landscape.md`.
- **The bot never writes an answer.** People do. An answer is a KB entry verbatim; a
  clarifying question is one of a fixed per-tenant list; the no-match text is fixed. Nothing
  the model produced reaches the chat. (`ANSWER_MODE=compose` relaxes this to "rephrase the
  one matched entry" if you want it.)
- **Silence is designed.** In a group, a wrong answer costs more than no answer. The floor
  defaults to 0.85; the production bot measured that its 0.85 bucket was 92% wrong or partial
  and runs at 0.90. Below the floor but above 0.70 the bot asks one question instead; below
  that, nothing. Non-requests (announcements, "same here", two people talking to each other)
  get nothing at all.
- **The KB is the product.** The code is a few hundred lines. Stale entries are the failure
  mode you will actually hit; every entry has a `last_verified` date and a `verified_against`
  line for that reason.
- **Start small, and leave most of this switched off.** One group, one knowledge base, twenty
  entries. 1:1 mode and the curator are both **off by default** and should stay off for the
  first couple of weeks: they exist because the bot outgrew a single group, and neither helps
  on day one. Run it, read every answer it gives, and fix the KB. Turn on 1:1 when people start
  asking you privately what the group already answered. Turn on the curator when adding entries
  by hand starts to annoy you. A bot that answers twenty questions well beats one with every
  feature enabled and a knowledge base nobody trusts.

## Quick start (Terraform)

Prerequisites: an AWS account with Bedrock model access enabled for Claude Haiku 4.5 (and
Sonnet 4.6 if you want screenshots) in your region, Terraform >= 1.5, Python 3, the AWS CLI
with the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html).

```bash
git clone https://github.com/kobyal/whatsapp-kb-bot.git && cd whatsapp-kb-bot

# 1. Make the KB yours. Edit tenants/dev-platform/{tenant.json,kb.json} (or rename the folder),
#    delete tenants/office-it if you have one group family, then check:
KB_TENANT=dev-platform python3 kb/kbcheck.py --warnings

# 2. Fork first, then point the instance at your fork (it clones the listener code at boot)
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars      # set allowed_groups, repo_url, default_tenant
terraform init && terraform apply                  # one KB table per tenant folder

# 3. Publish the knowledge base(s)
cd ../.. && KB_TENANT=dev-platform python3 kb/publish.py --table-prefix wakb-kb-

# 4. Test the brain with no WhatsApp involved
scripts/ask.sh wakb-brain "my vpn keeps disconnecting"

# 5. Link the bot phone: open http://localhost:8090 and scan from WhatsApp > Linked devices
scripts/qr.sh <instance-id>

# 6. Watch it work
scripts/logs.sh <instance-id>
```

`allowed_groups` takes group **subjects** (the name you see in WhatsApp) or jids. Everything
not on the list is logged with its jid and dropped, so if you are unsure of a name, send one
message and read it off `scripts/logs.sh`. Then put the jid into that tenant's `groups` in
`tenant.json`, so the brain knows which KB the group gets, and `terraform apply` again.

## Quick start (CloudFormation)

```bash
aws s3 mb s3://<your-deploy-bucket>
infra/cloudformation/deploy.sh wakb <your-deploy-bucket> \
  AllowedGroups="Dev Platform Support" RepoUrl=https://github.com/<you>/whatsapp-kb-bot.git
# a second tenant: add SecondTenant=office-it
```
Then steps 3-6 above.

## How the brain decides

```
message ──► supporter talking? (identity) ──► silent, no model call
        ──► (image? read it into text with Sonnet)
        ──► SCREEN (Haiku, no KB in the prompt): request? on-domain? outage / too vague / specific?
              not a request or off-domain ──► silent, no classify call
        ──► CLASSIFY (Haiku, the catalogue: ids, six triggers, exact error strings, 130-char gloss)
              ≥ floor ──► ANSWER: the entry verbatim, under a per-tenant header, quoted reply, 1.5-4 s jitter
              0.70-floor ──► CLARIFY: ONE fixed question, once per person per 30 min, unless a human is already on it
              else ──► SILENT (an @-mention gets a fixed "no answer" text instead)
```

Three things the model is never asked to judge, because the listener knows them as facts:

- **Supporters** (`tenant.json`): the group's own answerers. Their messages cost nothing and
  never trigger a question; a supporter who @-mentions the bot still gets an answer.
- **Who is being replied to** (`quoted_participant`): a reply inside a two-person exchange
  suppresses the clarifying question, never an answer above the floor.
- **Is a human already on it** (the supporter window, 180 s per group): while one of the
  answerers is active in the room, the bot keeps its questions to itself.

`clarify_route2` per tenant turns off the "your message is too vague" question. It is only
worth asking when the KB is dense enough for the sharpened question to have an answer; the
production bot measured 11 questions and 0 answers against an 8-entry KB and turned it off there.

## Multi-tenant

One Lambda, one EC2, several groups, several knowledge bases. Each `tenants/<id>/tenant.json`
names its groups; the brain picks the tenant from the group jid and uses that tenant's KB
table, header, screen-prompt audience, clarifying questions, supporters and fixed texts. A jid
no tenant claims falls back to `default_tenant`. Terraform creates `<prefix>-kb-<id>` for every
tenant folder; `kb/publish.py` and the brain derive the same name, so nothing has to agree by hand.

## 1:1 mode (off by default)

People will message the bot directly. With `dm_enabled = true` and `dm_roster_groups = { "<group jid>" = "<tenant>" }`,
the listener rebuilds a roster from live group metadata every 15 minutes and answers a DM only
from someone who is currently in one of those groups. Strangers are dropped **in silence**: a
refusal would confirm what the number is. A DM is treated as an explicit call (no screen, and a
no-match says so). Someone in the groups of two tenants is asked once which one they mean; the
answer is stored (`dmpref#<user>`, 90 days) and changed with the word "switch". Two fail-closed
rules: a failed `groupMetadata` keeps the previous roster, and a roster that builds empty is refused.

## The curator (optional)

```bash
export AWS_PROFILE=... AWS_REGION=eu-west-1 KB_TABLE_PREFIX=wakb-kb-
python3 curator/fetch_log.py --instance <instance-id> --out /tmp/bot.log
python3 curator/curate.py --log /tmp/bot.log --days 1 --out digest.md                       # report only
python3 curator/curate.py --log /tmp/bot.log --days 1 --apply-triggers --write-drafts       # the daily run
```

| Tier | Change | Gate | Who clicks |
|---|---|---|---|
| **A, applied** | a phrasing added to an **existing** entry's triggers, inside the visible top six | a human in the thread gave *that entry's* answer and the asker accepted it; re-classifying the missed message against the modified entry clears the floor; kbcheck adds no error or warning | nobody: the answer text never changes |
| **B, draft** | a **new** entry, `status=draft` | human answered and the asker confirmed **after** the answer; a referral ("open a ticket") is not an answer; kbcheck; never overwrites an id | the tenant's KB owner |
| **C, reported** | nothing | | the digest reader |

**Tier A changes how an answer is found, never what it says.** See `curator/README.md`.

## Day two

- **Edit a KB**: change `tenants/<id>/kb.json`, run `kbcheck.py --warnings`, run `publish.py`.
  Live within a minute; no redeploy. The zip also carries a snapshot as a fallback.
- **Tune**: `min_confidence`, `clarify_min_candidate`, `clarify_enabled`, `answer_mode`, the
  models, `supporter_window_seconds`. All are variables in both infra flavours and env vars on
  the Lambda. Per-tenant texts and questions live in `tenant.json` (a redeploy).
- **Try before you publish**: `python3 tools/probe.py "a question"` scores it against the
  snapshot with the real prompts; `--suite tools/probe-suite.json` runs a labelled set.
- **Re-link**: if the phone unlinks the device (WhatsApp does this after 14 days without the
  phone online), the listener clears its auth and shows a new QR. Run `scripts/qr.sh` again.
- **Update the listener code**: `terraform apply` after changing `git_ref`, or on the box
  `sudo bash /opt/wakb/src/listener/install.sh`.

## If your account has an instance scheduler

Many company accounts run automation that tags new instances (for example `schedule = stop_dont_start`)
and stops them on a timer. That kills the WhatsApp session. Two Terraform variables handle it:
`disable_api_stop = true` makes every `StopInstances` call fail, and `ignore_tag_keys = ["schedule"]`
stops Terraform from fighting the tagger. The trade-off: you cannot stop the instance yourself,
and **`terraform destroy` is blocked**, until you set it back to `false` and apply. This bit me in
the test account on the first night.

Two more Amazon Linux 2023 traps `listener/install.sh` already handles: first boot holds the
rpm lock for a minute, so package installs are retried rather than failed; and `/usr/bin/node`
is an alternatives link that must not be overwritten by hand.

## License

MIT. Use it, fork it, tell me what broke.
