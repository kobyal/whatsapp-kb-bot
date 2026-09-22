# Design notes

Short answers to the questions people ask first. Longer reasoning is in the article.

## The three rules

1. **The bot never writes an answer.** The model routes: it picks a KB id, or a key from a fixed
   dict of clarifying questions. What reaches the chat is text a human wrote. This bounds the
   damage of a wrong decision to "wrong entry", which the confidence floor addresses, and
   removes "plausible invented steps" entirely.
2. **Silence is designed.** In a group, a confident wrong answer is read by everyone and trusted
   because it looks authoritative. Below the floor the bot says nothing, or asks one question.
   A non-request never gets a reply.
3. **Identity and structure beat judgement.** Who is talking, whom they reply to, and whether a
   human is already on it are facts the listener knows. They are passed as fields and acted on
   in code; the model is never asked to guess them from a bare string.

## Why an EC2 and a Lambda, not one or the other

A WhatsApp linked device is a persistent authenticated WebSocket. Lambda is stateless with a
15-minute ceiling and cannot hold it. So the channel lives on a small always-on box. The
decision logic does not need to be always-on and benefits from being stateless, versioned
and cheap to redeploy, so it lives in a Lambda. The interface between them is one JSON in,
one JSON out, which is also what lets you swap WhatsApp for Slack or Teams by replacing
`listener/` only.

## Why Baileys and not whatsapp-web.js

whatsapp-web.js drives a real Chromium through Puppeteer. That presents as a browser (lower
ban risk) but weighs hundreds of MB, and at the time of building, media download was broken
against the live WhatsApp Web build. Screenshots are most of a support group's traffic.
Baileys speaks the protocol directly, needs no browser, and handled images out of the box.

## Why not the official WhatsApp Business Cloud API

Two hard limits, verified on Meta's docs: the Groups API allows **8 participants** per group
and the business must create the group itself. A community group of 100+ people created by a
person is out of reach. Also, registering a number on the Cloud API deletes its consumer
WhatsApp account. If your use case is 1:1 customer service, the Cloud API is the right and
compliant choice, and the brain here works unchanged behind it.

## Why a confidence floor, and why so high

The production bot started at 0.80. Replaying 326 real messages and grading every confident
answer with an independent model showed the 0.85 bucket was 92% wrong or partial. Raising
the floor to 0.90 and staying silent below it cut the judged wrong-answer rate from 42% to
6%. The template ships at 0.85 as a starting point; measure your own with `tools/probe.py`.

## Why a screen before the classifier

Half of the false positives were never questions: someone posting a solution, a staff
announcement, "same here", one person asking another. The screen runs first on a short prompt
with no KB in it, so a non-request never pays for the classify call. It also decides whether
the message is on-domain, whether it is an *outage* question ("is it down for everyone?",
which no KB can answer) and whether it is *underspecified* (one detail away from answerable).
The screen is skipped for an explicit call, for a reply to the bot's own question, and for a
message that IS a verbatim KB error string, which is a request by definition.

## The third outcome: one fixed question

Between 0.70 and the floor the classifier has named an entry it cannot be trusted on. Sending
that entry is a probably-wrong answer; sending nothing wastes a real question. The bot asks
ONE clarifying question from the tenant's fixed dict (the screen picks the key: environment,
exact error, what they ran). The reply is combined with the remembered question and
re-classified through exactly the same path, floor included. A thread is clarified at most
once, so nobody gets interrogated.

**The rate limit is the safety property, not a nicety.** Once per person per 30 minutes, and
it is enforced by a DynamoDB *conditional write*, not by comparing timestamps: under a burst
(the normal state of a group during an incident) several invocations for the same person run
in parallel, every read happens before any write, and only the database can pick one winner.
No conversation table, no `jid`/`participant`, or a failed write all fail closed to silence.

Route 2 (no candidate at all, message too vague) is a bet that the KB can answer once the
message is sharpened. With a small KB the bet always loses; production measured 11 questions
and 0 answers against 8 entries. So it is a per-tenant flag, `clarify_route2`.

## Conversation awareness

Two live cases on one morning: a supporter asked a colleague "is there a sign-in bar at the
top of Outlook?" and the bot asked *the supporter* a clarifying question. The screen's "one
person addressing another" rule was right and could not fire, because the screen sees a bare
string. Three signals fixed it, each a fact rather than a judgement:

- `supporters` per tenant: their messages return silent before vision or the screen, at zero
  model cost. An explicit call is exempt.
- `quoted_participant` from the listener (set only when the quoted author is a human): a reply
  inside a two-person exchange withholds the question, never an answer above the floor.
- The supporter window: one row per group, "a human spoke here N seconds ago", read lazily only
  on the path that is about to clarify.

## Multi-tenant

One brain, several knowledge bases. `tenants/<id>/tenant.json` carries everything that differs
between groups: group jids, the KB table, the disclosure header, the audience text inside the
prompts, the domain description for the screen, the clarifying questions and their hints, the
supporters, the fixed no-match and vision-failed texts, and the route-2 flag. `build.sh` (or
Terraform, in HCL) assembles them with each KB snapshot into `tenants.json` inside the zip. The
tenant is resolved from the group jid per message and held in a `contextvars` variable, so
every helper reads the right config without threading a parameter through.

## 1:1 mode

The same engine reached directly, behind a flag that defaults to off. Three deltas: the
authorisation is live group membership (a roster rebuilt from `groupMetadata` every 15 minutes,
fail-closed twice: keep the previous roster on error, refuse an empty one); the tenant comes
from the roster, and is asked once when the person is in two; and the message is treated as
explicit, because silence is a readable answer in a group and just a bot ignoring you in a DM.
A stranger's DM is dropped without a reply: a refusal would confirm what the number is.

## Reliability: bounded model calls

botocore's default read timeout is 60 s, the same as the Lambda timeout, so one stalled Bedrock
call consumed the whole budget and the listener received an error envelope that it logged as
silence. The Bedrock client is bounded (5 s connect, 25 s read, 2 attempts) so a stall fails
fast into the existing fail-silent paths, and the listener prints `BRAIN ERROR` on a function
error or a non-JSON payload so a human and the curator both see it.

## The curator

A separate layer that reads the listener's log (over SSM, a read the bot cannot tell happened)
and proposes KB changes at three tiers. Tier A adds a phrasing to an existing entry's triggers
and is applied without a click, but only after a model judgement over the thread confirms a
human gave *that entry's* answer and the asker accepted it, the fix is proven to lift the
score over the floor, and kbcheck adds no warning. Tier B drafts a new entry from a confirmed
thread for a human to publish; the confirmation must come *after* the answer (a code gate, not
a judgement), and a referral is not an answer. Tier C is the digest. A bug in the curator cannot
reach a group, by construction.

## Security posture

- No inbound ports. No SSH keys. Access is SSM Session Manager only.
- The QR page binds to 127.0.0.1 and is reached over an SSM port-forward. A public linking
  QR would let anyone link the bot account to their own phone.
- EC2 role: SSM core plus `lambda:InvokeFunction` on one ARN. Lambda role: logs, Bedrock
  invoke, `dynamodb:Scan` on the KB tables, Get/Put/Update on the conversation table.
- WhatsApp session credentials live in `/opt/wakb/data/auth` on the instance and nowhere else.
  Back them up only if you understand they are equivalent to the phone's login.
- Allowlist fails closed: an empty list answers nobody. 1:1 fails closed the same way.
