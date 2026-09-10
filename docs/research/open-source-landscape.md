# Open-source options for a KB-answering WhatsApp bot

Survey done 2026-09-10 while writing this template. Stars and dates are as of that day.
Verify before relying on them.

## 1. Transport layer: unofficial multi-device clients

All of these speak the WhatsApp Web protocol from a normal phone number. All violate
WhatsApp ToS; bans are permanent with no appeal, and reports put detection typically at
2–8 weeks for spammy patterns (low reply ratio, stranger contacts, robotic timing). A
reply-only support bot answering members who message it first is the lowest-risk pattern,
but it is still unsanctioned.

| Project | Lang | Stars | Last push / release | License | Chromium? | Form |
|---|---|---|---|---|---|---|
| [Baileys](https://github.com/WhiskeySockets/Baileys) | TS | 11.0k | 2026-09-06 / v7.0.0-rc14 | MIT | No | Library |
| [whatsapp-web.js](https://github.com/wwebjs/whatsapp-web.js) | JS | 22.5k | 2026-09-06 / v1.34.7 | Apache-2.0 | **Yes** | Library |
| [wppconnect](https://github.com/wppconnect-team/wppconnect) | TS | 3.4k | 2026-09-10 | custom | **Yes** | Library + server |
| [whatsmeow](https://github.com/tulir/whatsmeow) | Go | 7.3k | 2026-09-09 (no tags) | MPL-2.0 | No | Library |
| [WAHA](https://github.com/devlikeapro/waha) | TS | 7.4k | 2026-09-10 / 2026.8.2 | Apache-2.0 | Optional | **HTTP API + webhooks** |
| [Evolution API](https://github.com/evolution-foundation/evolution-api) | TS | 9.6k | 2026-07-14 | Apache-2.0 + brand clause | No (Baileys) | **HTTP API** |
| [open-wa](https://github.com/open-wa/wa-automate-nodejs) | TS | 3.7k | 2026-09-10 | custom, partly paid | **Yes** | Library + API |
| [GOWA](https://github.com/aldinokemal/go-whatsapp-web-multidevice) | Go | 4.7k | 2026-09-09 / v9.3.1 | MIT | No (whatsmeow) | **HTTP API** + MCP, single binary |

Notes:
- WAHA folded its paid Plus tier into the free Core image from 2026.6.1. It ships first-party n8n nodes and Chatwoot and Typebot bridges.
- Evolution API moved to `evolution-foundation`; its last push is about two months old. It is the de-facto Baileys gateway for the Typebot / Chatwoot / Dify / n8n ecosystem.
- Baileys is on a long 7.0 RC series. whatsapp-web.js still needs a headless browser.

## 2. Official route

**Meta WhatsApp Business Cloud API** ([pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing))
- Since 2025-07-01 billing is per delivered template message. Free-form replies inside the 24 h customer-service window are free today.
- **From 2026-10-01**, service messages inside the 24 h window become billable at the utility rate for the country. For an FAQ bot that means roughly $0.003–0.05 per answer depending on country.
- **Groups API** ([docs](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups)): max **8 participants**, only the business may create the group, one Cloud API business per group, Official Business Account required, group-specific templates. A 120-member community group cannot have a compliant in-group bot.
- **AI policy**: since 2026-01-15 general-purpose assistants are banned from the Business API; scoped customer-service and FAQ bots are allowed, provided out-of-scope queries get a standard refusal or handoff.

**Twilio WhatsApp**: $0.005 per message on top of Meta's fees, same rules, simpler onboarding.

## 3. Bot and RAG platforms with WhatsApp connectors

| Project | Stars | License | WhatsApp path | Groups | KB / RAG | Bedrock / Anthropic |
|---|---|---|---|---|---|---|
| [n8n](https://github.com/n8n-io/n8n) | 204k | Sustainable Use | Cloud API node; WAHA community node; Evolution webhooks | via WAHA/Evolution | vector-store nodes, AI Agent node | **built in** |
| [Dify](https://github.com/langgenius/dify) | 155k | Apache-2.0 + conditions | via Evolution API | via Evolution | strong: hybrid retrieval, rerank, Bedrock KB plugin | Bedrock, Anthropic |
| [Chatwoot](https://github.com/chatwoot/chatwoot) + Captain | 36.7k | MIT core | Cloud API, 360dialog, Twilio; Baileys via forks | official: no | document KB, auto-resolve, human handoff | OpenAI-compatible only; Bedrock via proxy |
| [Typebot](https://github.com/baptisteArno/typebot.io) | 10.3k | FSL-1.1 | Cloud API, **paid tier even self-hosted** | No | weak | OpenAI/Anthropic blocks |
| [Botpress](https://github.com/botpress/botpress) | 14.9k | MIT (v12 sunset) | cloud only | No | cloud only | not self-hostable in practice |
| [Rasa](https://github.com/RasaHQ/rasa) | 21.3k | Apache-2.0 (OSS frozen) | Twilio | No | not a RAG tool | Pro only |
| [Flowise](https://github.com/FlowiseAI/Flowise) | 55.5k | Apache-2.0 | none | – | yes | **archived 2026-08-13, do not adopt** |
| [Langflow](https://github.com/langflow-ai/langflow) | 155k | MIT | none native | – | yes | Bedrock, Anthropic |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 65.9k | MIT | none, API only | – | strong workspace RAG | Bedrock, Anthropic |
| [LibreChat](https://github.com/danny-avila/LibreChat) | 43k | MIT | none | – | RAG sidecar | native |
| [OpenClaw](https://github.com/openclaw/openclaw) | 389k | MIT | **Baileys**, production channel | Yes | memory/skills, general-purpose agent | Anthropic, Bedrock |
| [builderbot](https://github.com/codigoencasa/builderbot) | 3.0k | MIT | Baileys, WWebJS, Meta, Twilio | Yes | none | bring your own |
| [askrella/whatsapp-chatgpt](https://github.com/askrella/whatsapp-chatgpt) | 3.8k | none | whatsapp-web.js | Yes | none | OpenAI only |

## Summary

| Need | Best fit |
|---|---|
| Compliant 1:1 bot, no ban risk | Meta Cloud API (direct or Twilio) + this repo's brain or n8n |
| Bot inside a group of more than 8 | Unofficial only: Baileys / whatsmeow / GOWA / WAHA / Evolution |
| Lightest self-hosted gateway | GOWA (single Go binary) or WAHA with the NOWEB/GOWS engine |
| Turn-key KB + WhatsApp, least code | Dify + Evolution API, or n8n + WAHA |
| Support desk with human handoff | Chatwoot + Captain behind an OpenAI-compatible proxy for Bedrock |

**Recommendations for a small team on AWS with Bedrock**

1. **Thin Baileys (or GOWA) gateway + your own Lambda**: what this repo is. Baileys and whatsmeow are the actively maintained cores everything else wraps.
2. **WAHA + n8n**: both free, first-party nodes, native Bedrock and Anthropic nodes, group support, non-developers can edit the flow. One `docker compose` on the same EC2.
3. **Dify + Evolution API**: richest KB features with a documented WhatsApp bridge, at the cost of two heavy services and Evolution's slower 2026 cadence.

Avoid: Flowise (archived), Botpress OSS (sunset), Typebot (WhatsApp paywalled), anything Puppeteer-based on a small instance.

**Worth a deeper code scan before adopting**: WAHA (confirm no telemetry or license callbacks after the Plus merge; session persistence), GOWA (auth on REST/MCP endpoints, webhook signing, whatsmeow pinning), Evolution API (pinned Baileys fork, default secrets, Cloud API migration path).
