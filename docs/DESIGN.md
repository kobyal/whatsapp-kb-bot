# Design notes

Short answers to the questions people ask first. Longer reasoning is in the article.

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

## Why the model routes but does not write (by default)

In a group, a confident wrong answer is read by everyone and trusted because it looks
authoritative. Sending a human-verified entry verbatim bounds the damage to "wrong entry",
which the confidence floor addresses, and removes "plausible invented steps" entirely.
`ANSWER_MODE=compose` exists for teams that prefer natural phrasing; it is constrained to the
one matched entry as its only source.

## Why a confidence floor, and why so high

The production bot started at 0.80. Replaying 326 real messages and grading every confident
answer with an independent model showed the 0.85 bucket was 92% wrong or partial. Raising
the floor to 0.90 and staying silent below it cut the judged wrong-answer rate from 42% to
6%. The template ships at 0.85 as a starting point; measure your own.

## Why the "is this a request" screen matters

Half of the false positives were never questions: someone posting a solution, a staff
announcement, "same here". The classifier prompt asks that first. In the production system
it is a separate call with no KB in the prompt; here it is folded into one call to keep the
template small.

## Security posture

- No inbound ports. No SSH keys. Access is SSM Session Manager only.
- The QR page binds to 127.0.0.1 and is reached over an SSM port-forward. A public linking
  QR would let anyone link the bot account to their own phone.
- EC2 role: SSM core plus `lambda:InvokeFunction` on one ARN. Lambda role: logs, Bedrock
  invoke, `dynamodb:Scan` on one table.
- WhatsApp session credentials live in `/opt/wakb/data/auth` on the instance and nowhere else.
  Back them up only if you understand they are equivalent to the phone's login.
- Allowlist fails closed: an empty list answers nobody.
