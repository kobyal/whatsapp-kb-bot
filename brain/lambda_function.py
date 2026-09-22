"""The brain: given a message (and optionally a screenshot), decide which knowledge-base
entry answers it, ask ONE fixed clarifying question, or stay silent.

Channel-agnostic on purpose. Input is a plain dict, output is a plain dict, so the same
function serves WhatsApp today and Teams or Slack tomorrow with no change here.

    in : {"text": "...", "image_b64": "...", "mime": "image/jpeg",
          "jid": "<chat id>", "participant": "<sender id>",      # required for clarify
          "quoted_participant": "<id of the human being replied to>" | null,
          "explicit": bool,                                       # @-mention / call word
          "dm": bool, "candidate_tenants": ["tenant-id", ...],    # 1:1 mode (listener roster)
          "tenant": "tenant-id"}                                  # optional override (tests)
    out: {"outcome": "answer"|"clarify"|"silent"|"nomatch"|"help"|"dm_setup",
          "id": ..., "score": 0.93, "reply": "...", "tenant": "...", "note": "..."}

DESIGN RULES, in order of importance:
1. The model ROUTES, it does not write. An answer is a KB entry's text as a human wrote it
   (ANSWER_MODE=verbatim). A clarifying question is one of a fixed per-tenant dict; the model
   only picks a key. The no-match text is fixed. Nothing the model produced reaches the chat.
2. Silence is designed. Below the floor the bot says nothing; in a group a wrong answer costs
   more than no answer. A non-request (announcement, "same here", two people talking) never
   gets a reply at all.
3. Identity and structure beat judgement. Who is talking (supporters), what they are replying
   to (quoted_participant) and whether a human is already on it (supporter window) are facts
   the listener knows; the model is never asked to guess them.

THE PIPELINE:
  screen (is this a request? on-domain? too vague?)  ->  classify against the catalogue
  -> >= MIN_CONFIDENCE: answer | CLARIFY_MIN_CANDIDATE..floor: one fixed question | else silent

MULTI-TENANT: one Lambda, several groups, several knowledge bases. tenants.json (assembled by
brain/build.sh or by Terraform from tenants/<id>/) carries per tenant the group jids, the KB
table, header, prompts' audience text, clarifying questions, supporters and fixed texts. The
tenant is picked from the group jid of each message; an unknown jid falls back to `default`.
"""
import base64
import contextvars
import json
import os
import pathlib
import re
import time
from decimal import Decimal

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "eu-west-1"))
KB_REGION = os.environ.get("KB_REGION", REGION)
# Table per tenant: `<KB_TABLE_PREFIX><tenant id>` unless tenant.json names `kb_table`.
# Empty prefix and no kb_table = bundled snapshot only (offline runs, tests, first deploy).
KB_TABLE_PREFIX = os.environ.get("KB_TABLE_PREFIX", "")
KB_CACHE_TTL = float(os.environ.get("KB_CACHE_TTL", "60"))
CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
VISION_MODEL = os.environ.get("VISION_MODEL", "eu.anthropic.claude-sonnet-4-6")
# Tried when VISION_MODEL fails; a transient error on the big model must not turn a readable
# screenshot into silence. Haiku reads screenshots well enough to classify on.
VISION_FALLBACK_MODEL = os.environ.get("VISION_FALLBACK_MODEL", CLASSIFY_MODEL)
# The most important number in this file. The production bot measured 0.85 as the bucket
# where the classifier is right 3 times in 39 and moved its floor to 0.90; the template
# ships at 0.85 as a starting point. Measure your own (see docs/TESTING.md).
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.85"))
# The clarify band: a named candidate the classifier cannot be trusted on gets ONE fixed
# question instead of a probably-wrong answer. Below this the pick is noise, not a candidate.
CLARIFY_MIN_CANDIDATE = float(os.environ.get("CLARIFY_MIN_CANDIDATE", "0.70"))
ANSWER_MODE = os.environ.get("ANSWER_MODE", "verbatim")   # verbatim | compose
CACHE_PROMPT = os.environ.get("CACHE_PROMPT", "1") != "0"

# Per-conversation state (DynamoDB, TTL attribute `expires_at`). Empty = no clarify, no 1:1
# preference memory: without a rate limit, clarifying is not safe in a big group, so it
# fails closed to silence.
CONVO_TABLE = os.environ.get("CONVO_TABLE", "")
CONVO_REGION = os.environ.get("CONVO_REGION", KB_REGION)
CLARIFY_ENABLED = os.environ.get("CLARIFY_ENABLED", "1") != "0"
CLARIFY_TTL = int(os.environ.get("CLARIFY_TTL", "1800"))          # how long a question is remembered
CLARIFY_COOLDOWN = int(os.environ.get("CLARIFY_COOLDOWN", "1800"))  # once per person per window
# How long after one of the tenant's supporters speaks in a group the bot keeps its clarifying
# question to itself. Measured in production as the typical gap between a question and a
# human answerer picking it up (1-4 minutes). Inside it a bot question is a second voice
# talking over a diagnosis already under way.
SUPPORTER_WINDOW = int(os.environ.get("SUPPORTER_WINDOW", "180"))
# Shortest error_string that may identify an entry on its own. Short strings appear inside
# unrelated text too often to count as the exact words of one screen.
ERROR_STRING_MIN_LEN = int(os.environ.get("ERROR_STRING_MIN_LEN", "20"))
# A message longer than this (and than 3x the matched error string) is not a bare paste; the
# screen still decides whether it is a request.
VERBATIM_PASTE_MAX_LEN = int(os.environ.get("VERBATIM_PASTE_MAX_LEN", "240"))

# 1:1 mode. Someone who is in the groups of two tenants is asked once which one they mean;
# the choice is stored under `dmpref#<user>` and changed with one word.
DM_PREF_TTL = int(os.environ.get("DM_PREF_TTL", str(90 * 24 * 3600)))
DM_SWITCH_WORDS = tuple(w.strip().lower() for w in os.environ.get("DM_SWITCH_WORDS", "switch,החלף").split(",") if w.strip())
DM_ASK_TEXT = os.environ.get("DM_ASK_TEXT",
    "Before I answer: which group is this about?\n{choices}\n\nReply with the number. "
    "I will remember it; send \"switch\" any time to change.")
DM_SAVED_TEXT = os.environ.get("DM_SAVED_TEXT", "Noted. From now on I answer you about {name}.\nTo change: \"switch\".")

# ----------------------------------------------------------------------------- tenants

_TENANTS = json.loads((pathlib.Path(__file__).parent / "tenants.json").read_text(encoding="utf-8"))
DEFAULT_TENANT = os.environ.get("DEFAULT_TENANT", _TENANTS.get("default") or sorted(_TENANTS["tenants"])[0])
_current_tenant = contextvars.ContextVar("tenant", default=None)


def resolve_tenant(event):
    """The tenant config for this message: an explicit `tenant` in the event (harness, 1:1
    routing, tests), else the group jid, else the default."""
    tid = (event or {}).get("tenant")
    if not tid:
        jid = (event or {}).get("jid") or ""
        for t in _TENANTS["tenants"].values():
            if jid and jid in (t.get("groups") or []):
                tid = t["id"]
                break
    if not tid or tid not in _TENANTS["tenants"]:
        tid = DEFAULT_TENANT
    return _TENANTS["tenants"][tid]


def T(key, default=None):
    """A field of the tenant handling the current invocation."""
    t = _current_tenant.get() or _TENANTS["tenants"][DEFAULT_TENANT]
    v = t.get(key)
    return default if v is None else v


# ----------------------------------------------------------------------------- AWS clients

# Bound every Bedrock call. botocore's default read timeout is 60 s, the same as a typical
# Lambda timeout, so one stalled HTTP call used to consume the whole budget and the listener
# received an error envelope it logged as silence. 25 s per call leaves room for screen +
# classify + vision, and a stall now fails FAST into the fail-silent paths below.
_brt = boto3.client("bedrock-runtime", region_name=REGION, config=BotoConfig(
    connect_timeout=int(os.environ.get("BEDROCK_CONNECT_TIMEOUT", "5")),
    read_timeout=int(os.environ.get("BEDROCK_READ_TIMEOUT", "25")),
    retries={"max_attempts": 2, "mode": "standard"}))
_ddb = None
_convo_ddb = None
_tables = {}
_CACHES = {}   # tenant id -> {"entries", "expires", "source"}


def _kb_table_name():
    return T("kb_table") or (f"{KB_TABLE_PREFIX}{T('id')}" if KB_TABLE_PREFIX else "")


def _table():
    global _ddb
    name = _kb_table_name()
    if not name:
        return None
    if _ddb is None:
        _ddb = boto3.resource("dynamodb", region_name=KB_REGION)
    if name not in _tables:
        _tables[name] = _ddb.Table(name)
    return _tables[name]


def _convo_table():
    """Lazy, so the module imports offline (tests, the curator, the probe tool)."""
    global _convo_ddb
    if not CONVO_TABLE:
        raise RuntimeError("CONVO_TABLE not set")
    if _convo_ddb is None:
        _convo_ddb = boto3.resource("dynamodb", region_name=CONVO_REGION)
    return _convo_ddb.Table(CONVO_TABLE)


def _plain(value):
    """DynamoDB returns Decimal for every number; json.dumps and "%.2f" both choke on it."""
    if isinstance(value, Decimal):
        i = int(value)
        return i if value == i else float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


# ----------------------------------------------------------------------------- KB

def _published(entries):
    return [e for e in entries if e.get("status", "published") == "published" and e.get("id")]


def _snapshot_entries():
    return _published(T("snapshot", []))


def load_entries():
    """(entries, note). Published entries from the tenant's DynamoDB table (cached
    KB_CACHE_TTL seconds), else the snapshot baked into the zip. Fail safe, not open:
    anything that would leave the bot with no KB falls back to the snapshot and says so."""
    cache = _CACHES.setdefault(T("id"), {"entries": None, "expires": 0.0, "source": None})
    now = time.time()
    if cache["entries"] and now < cache["expires"]:
        return cache["entries"], f"kb {cache['source']} ({len(cache['entries'])})"
    table = _table()
    if table is None:
        return _snapshot_entries(), f"kb snapshot ({len(_snapshot_entries())})"
    try:
        items, kwargs = [], {}
        while True:
            page = table.scan(**kwargs)
            items.extend(page.get("Items", []))
            if not page.get("LastEvaluatedKey"):
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        entries = _published([_plain(i) for i in items])
        # Scan order is not stable and entry order is part of the prompt.
        entries.sort(key=lambda e: e["id"])
    except Exception as e:  # noqa: BLE001 - any table problem falls back
        if cache["entries"]:
            cache["expires"] = now + KB_CACHE_TTL
            return cache["entries"], f"kb dynamodb failed ({type(e).__name__}) -> serving last good read"
        return _snapshot_entries(), f"kb dynamodb failed ({type(e).__name__}) -> snapshot ({len(_snapshot_entries())})"
    if not entries:
        # Not cached: an empty table is usually transient or mid-migration.
        return _snapshot_entries(), f"kb table empty -> snapshot ({len(_snapshot_entries())})"
    cache.update(entries=entries, expires=now + KB_CACHE_TTL, source=f"dynamodb:{table.name}")
    return entries, f"kb dynamodb ({len(entries)})"


def _catalogue(entries):
    """What the classifier sees: ids, the first six phrasings, exact error strings, and a
    130-char gloss of the answer. Never the full answers: small, cheap, cacheable."""
    out = []
    for e in entries:
        gloss = (e.get("answer") or "")[:130].replace("\n", " ")
        block = [f"- id: {e['id']}", f"  category: {e.get('category', '')}",
                 f"  typical phrasings: {', '.join((e.get('triggers') or [])[:6])}"]
        for err in e.get("error_strings") or []:
            block.append(f"  EXACT ERROR SEEN ON SCREEN: {err}")
        block.append(f"  answers: {gloss}")
        out.append("\n".join(block))
    return "\n".join(out)


def kb_categories(entries):
    cats = sorted({str(e.get("category") or "").strip() for e in entries} - {""})
    return ", ".join(cats) if cats else "(none)"


def verbatim_error_hit(text, entries):
    """The error_strings value that appears verbatim (case-insensitive) in the text, or None."""
    low = (text or "").lower()
    for e in entries:
        for err in e.get("error_strings") or []:
            if len(str(err)) >= ERROR_STRING_MIN_LEN and str(err).lower() in low:
                return str(err)
    return None


# ----------------------------------------------------------------------------- prompts

# Every prompt keeps its fixed text FIRST and the per-request part LAST, so Bedrock prompt
# caching can reuse the prefix across messages.
SCREEN_SYSTEM = """__DOMAIN__

Many messages in a support group are NOT requests for help. Your only job is to decide
whether the assistant should consider replying at all. Answer these about the message.

1. is_request: should the assistant consider helping?
   TRUE for: anyone describing a problem they are having or asking a question they want
   answered; a pasted error message, log line or command output ON ITS OWN with no words
   around it (the most common way to ask for help; a program wrote those words, so someone
   pasted them because they are stuck, even when the line sounds informational); a
   description transcribed from a screenshot; a bare fragment of an error.
   FALSE only when the sender clearly does not want help: they are ANSWERING or ADVISING
   others ("try this", "run X", "the solution is"); an ANNOUNCEMENT or status update ("it
   works now", "a new version is out", "we are looking into it"); AGREEMENT or me-too chatter
   with no detail ("same here", "thanks", "+1"); one person addressing ANOTHER PERSON in the
   second person ("are you on VPN?", "did you update?", "can you show me what you did?");
   a flat statement of fact in the sender's own words with no problem and no question;
   social talk, jokes, greetings, a bare link.
   A message that opens with a statement and then ASKS something is a request. WHEN IN
   DOUBT, ANSWER TRUE: a later confidence floor stops a weak answer cheaply, but wrongly
   dropping a real cry for help costs a lot.

2. domain: "on" if the message is about the tools, systems or activities described above, or
   about any of the knowledge-base categories listed with the message; "off" only for
   something clearly unrelated (weather, lunch, sport, small talk, a different system). A bare
   technical error string is "on" unless it clearly belongs elsewhere. WHEN IN DOUBT, "on".

3. kind: one of
   - "outage": the question is about THE STATE OF THE WORLD right now: is the service down, is
     anyone else affected, is it only me. A knowledge base cannot answer that and no follow-up
     helps. Only when there is NOTHING ELSE in the message to look up; a message that also
     names a concrete error or symptom is "specific".
   - "underspecified": about the sender's OWN broken thing, but they have not said WHAT broke,
     WHERE, or with WHICH error ("I need help with the tool", "something is not working for
     me", "stuck on the install"). One follow-up question would make it answerable. A message
     that names a concrete error or symptom, quoted or described, is NOT underspecified.
   - "specific": definite enough to look up, including questions about HOW or WHY something
     works or whether a permission or feature exists.
   - "other": anything else, including everything that is not a request.

4. ask: which single follow-up would unlock it, EXACTLY one of:
__ASK_KEYS__
   - "none"

Reply with JSON only:
{"is_request": true|false, "domain": "on"|"off", "kind": "underspecified|outage|specific|other", "ask": "<key or none>"}"""

SCREEN_USER = '''Message:
"""{text}"""

The knowledge base behind this assistant currently has entries in these categories:
{categories}
A message about any of these categories is ON-DOMAIN ("on").

Reply with JSON only.'''

CLASSIFY_SYSTEM = """You route messages from {audience} onto a fixed knowledge base.
People write informally, in any language, with typos and inconsistent spelling.

Pick the ONE entry that genuinely answers the user's question. Rules:
- Return "none" unless the entry addresses the user's actual problem. Most messages have no
  match, and answering the wrong thing is worse than staying silent.
- Match on meaning, not shared words. A message that merely mentions a topic is not a match;
  it must be the same problem. Prefixes, inflections and misspellings must not stop a match.
- An EXACT ERROR string quoted by the user is the strongest possible signal.

Reply with JSON only: {{"id": "<id or none>", "confidence": <0-1>, "why": "<max 12 words>"}}

Knowledge base:
{catalogue}"""

CLASSIFY_USER = 'Message:\n"""{question}"""\n\nReply with JSON only.'

COMPOSE_SYSTEM = """You answer a support question using ONLY the reference answer below.
Rephrase it to fit the question, keep every command and step, add nothing that is not in
the reference, and keep it short. Answer in the language of the question. Plain text with
WhatsApp formatting (*bold*, `code`), no headings.

Reference answer:
{answer}"""

VISION_PROMPT = """This is a screenshot sent to __AUDIENCE__, usually a terminal, a dialog or an
error page. Transcribe the user's actual problem as one or two first-person sentences, the way
they would type them to ask for help. Quote any error code, heading, button label or command
VERBATIM: the knowledge base matches on the exact words a screen shows.
If there is no error, decide which of two things the screen is: a screen WAITING for the
person (a login chooser, a dialog with buttons, a wizard step) - write "I am stuck at the
<kind of screen> "<heading verbatim>" with the options "<button 1>", "<button 2>"; or a HEALTHY
idle or finished screen - write "the screen shows <what>, nothing wrong visible" and do not
invent a question for the user.
Reply NO_PROBLEM_VISIBLE only when the image is genuinely unrelated to __SCOPE__ at all."""


def ask_lines():
    hints = T("clarify_hints") or {k: f"the {k}" for k in T("clarify_questions", {})}
    return "\n".join(f'   - "{k}": {v}' for k, v in hints.items())


# ----------------------------------------------------------------------------- bedrock

def _converse(model, system, user_content, max_tokens=200, cache=False):
    sys_blocks = [{"text": system}] + ([{"cachePoint": {"type": "default"}}] if cache else [])
    kwargs = dict(modelId=model, system=sys_blocks,
                  messages=[{"role": "user", "content": user_content}],
                  inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
    try:
        r = _brt.converse(**kwargs)
    except Exception:
        if not cache:
            raise
        kwargs["system"] = [{"text": system}]   # model/region without caching: retry plain
        r = _brt.converse(**kwargs)
    return r["output"]["message"]["content"][0]["text"].strip(), r.get("usage") or {}


def _converse_json(system, user_text, max_tokens=200, cache=False):
    raw, usage = _converse(CLASSIFY_MODEL, system, [{"text": user_text}], max_tokens, cache)
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw), usage


def screen(text, categories="(none)"):
    """(is_request, domain, kind, ask_key, usage). Runs BEFORE classification on a short
    prompt with no catalogue in it, so a non-request never pays for the classify call.
    `ask_key` is validated against the tenant's questions: a hallucinated key never becomes
    message text; "none" is honoured; anything else falls back to the tenant default."""
    system = SCREEN_SYSTEM.replace("__DOMAIN__", T("screen_domain", "")).replace("__ASK_KEYS__", ask_lines())
    data, usage = _converse_json(system, SCREEN_USER.format(text=text, categories=categories),
                                 max_tokens=120, cache=CACHE_PROMPT)
    raw = data.get("ask")
    questions = T("clarify_questions", {})
    ask = raw if raw in questions else (None if raw == "none" else T("clarify_default"))
    if ask not in questions:
        ask = None
    return (bool(data.get("is_request")), str(data.get("domain") or "off"),
            str(data.get("kind") or "other"), ask, usage)


def bedrock_classify(text, entries):
    """(entry|None, confidence, why, usage). Raises on Bedrock failure."""
    data, usage = _converse_json(
        CLASSIFY_SYSTEM.format(audience=T("audience", "a support chat group"), catalogue=_catalogue(entries)),
        CLASSIFY_USER.format(question=text), cache=CACHE_PROMPT)
    conf = float(data.get("confidence") or 0)
    if data.get("id") in (None, "", "none"):
        return None, conf, data.get("why", ""), usage
    entry = next((e for e in entries if e["id"] == data["id"]), None)
    return entry, conf, data.get("why", ""), usage


def read_image(image_b64, mime="image/jpeg", model=None):
    fmt = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "jpeg")
    prompt = VISION_PROMPT.replace("__AUDIENCE__", T("vision_audience", T("audience", "a support chat"))) \
                          .replace("__SCOPE__", T("vision_scope", "software or devices"))
    content = [{"image": {"format": fmt, "source": {"bytes": base64.b64decode(image_b64)}}},
               {"text": prompt}]
    r = _brt.converse(modelId=model or VISION_MODEL, messages=[{"role": "user", "content": content}],
                      inferenceConfig={"maxTokens": 300, "temperature": 0})
    return r["output"]["message"]["content"][0]["text"].strip()


# ----------------------------------------------------------------------------- conversation state

def convo_key(event):
    """`jid#participant`, or None. Both parts are required: without a stable per-person key
    there is no rate limit, and without the rate limit clarifying is not safe."""
    jid = str(event.get("jid") or "").strip()
    part = str(event.get("participant") or "").strip()
    return f"{jid}#{part}" if jid and part else None


def _user_part(jid):
    """`123@lid`, `123:12@lid` and `123` all compare equal (same as the listener's userPart)."""
    return str(jid or "").split("@")[0].split(":")[0].strip()


def is_supporter(participant):
    """One of the tenant's own answerers. They are in the group to ANSWER, not to ask, and
    the difference is identity, not something a model should judge from a bare string."""
    me = _user_part(participant)
    return bool(me) and any(_user_part(s) == me for s in (T("supporters") or []))


def supporter_key(jid):
    """One row per GROUP: "is a human already on this?" is a property of the room."""
    return f"{jid}#__supporter__"


def supporter_touch(jid, now):
    """Best-effort: a failure costs one clarify suppression, never an answer."""
    try:
        _convo_table().put_item(Item={"convo": supporter_key(jid), "last_at": int(now),
                                      "expires_at": int(now) + max(SUPPORTER_WINDOW * 4, CLARIFY_TTL)})
    except Exception:  # noqa: BLE001
        pass


def supporter_recent_secs(jid, now):
    """Seconds since a supporter last spoke in this group, or None. Read lazily, only on the
    path that is about to clarify."""
    try:
        row = _plain(_convo_table().get_item(Key={"convo": supporter_key(jid)}).get("Item") or {})
    except Exception:  # noqa: BLE001
        return None
    last = float(row.get("last_at") or 0)
    if not last:
        return None
    age = int(now - last)
    return age if 0 <= age < SUPPORTER_WINDOW else None


def state_get(key):
    """The stored row, or {}. Raises on a DynamoDB error so the caller fails closed."""
    return _plain(_convo_table().get_item(Key={"convo": key}).get("Item") or {})


def state_try_claim(key, original_text, ask_key, now):
    """ATOMICALLY win the right to clarify. The rate limit is a conditional write, not a
    timestamp comparison: under a burst several invocations for the same person run in
    parallel, every read happens before any write, and only DynamoDB can pick one winner."""
    cutoff = int(now) - CLARIFY_COOLDOWN
    try:
        _convo_table().put_item(
            Item={"convo": key, "pending_text": original_text[:2000], "asked_key": ask_key,
                  "asked_at": int(now), "last_clarify_at": int(now), "expires_at": int(now) + CLARIFY_TTL},
            ConditionExpression=("attribute_not_exists(convo) OR attribute_not_exists(last_clarify_at) "
                                 "OR last_clarify_at < :cutoff"),
            ExpressionAttributeValues={":cutoff": cutoff})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def state_clear_pending(key, asked_at):
    """Consume the remembered question, but only the one we actually read. `last_clarify_at`
    stays: deleting the row would hand the person a fresh clarify budget on reply."""
    try:
        _convo_table().update_item(Key={"convo": key}, UpdateExpression="REMOVE pending_text, asked_key",
                                   ConditionExpression="asked_at = :a",
                                   ExpressionAttributeValues={":a": int(asked_at)})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


# ----------------------------------------------------------------------------- compose

HEBREW = re.compile(r"[֐-׿]")
CODE_SPAN = re.compile(r"`[^`\n]+`")
RLM, LRI, PDI = "‏", "⁦", "⁩"


def rtl(text):
    """WhatsApp renders a mixed Hebrew/English message LTR unless every line starts with an
    RTL mark, and the LAST line needs a lone mark of its own or it flips back. Code spans
    are isolated so `commands` keep reading left-to-right."""
    text = CODE_SPAN.sub(lambda m: LRI + m.group(0) + PDI, text)
    body = "\n".join(RLM + ln if ln.strip() else ln for ln in text.split("\n"))
    return body + "\n" + RLM


def _finish(parts):
    msg = "\n".join(parts)
    return rtl(msg) if HEBREW.search(msg) else msg


def _header():
    return f"{T('icon', '🤖')} _{T('header', 'Automated answer from the support bot')}_"


def compose(entry, question="", kb_size=None):
    """The KB text, under the disclosure header. The one substitution: {KB_COUNT} -> number of
    published entries, so the bot's self-description never goes stale."""
    body = entry.get("answer") or ""
    if kb_size is not None:
        body = body.replace("{KB_COUNT}", str(kb_size))
    if ANSWER_MODE == "compose" and question:
        body, _ = _converse(CLASSIFY_MODEL, COMPOSE_SYSTEM.format(answer=body), [{"text": question}], max_tokens=600)
    parts = [_header(), "", body]
    if entry.get("owner") and T("contact_text"):
        parts += ["", T("contact_text").replace("{owner}", str(entry["owner"]))]
    return _finish(parts)


def compose_fixed(body):
    return _finish([_header(), "", body])


def compose_clarify(ask_key):
    """`ask_key` has been validated against the tenant's questions: nothing the model produced
    reaches the chat as text."""
    parts = [_header(), ""]
    if T("clarify_lead"):
        parts.append(T("clarify_lead"))
    parts.append(T("clarify_questions")[ask_key])
    return _finish(parts)


# ----------------------------------------------------------------------------- classify + floor

def _classify_with_floor(text, entries, note, usage_acc):
    """(entry|None, conf, why, suppressed_id, suppressed_score): the answering path, floor
    included, so a follow-up turn runs through exactly the same rules as a first question."""
    try:
        entry, conf, why, usage = bedrock_classify(text, entries)
        usage_acc.append(usage)
        note.append(f"classify {entry['id'] if entry else 'none'} {conf:.2f} ({why})")
    except Exception as e:  # noqa: BLE001 - a broken model must never produce a guess
        note.append(f"classify failed ({type(e).__name__}) -> silent")
        entry, conf, why = None, 0.0, "classify failed"

    low = text.lower()

    def owners_of(exclude=None):
        return [e for e in entries if e.get("id") != exclude and any(
            len(x) >= ERROR_STRING_MIN_LEN and x.lower() in low for x in (e.get("error_strings") or []))]

    # CORROBORATION. A pick in the clarify band whose own error string is in the text is not
    # a guess: the exact words the entry documents are on the user's screen. And when a
    # DIFFERENT single entry owns the string in the text, that entry wins over the pick.
    if entry is not None and CLARIFY_MIN_CANDIDATE <= conf < MIN_CONFIDENCE:
        if owners_of() and entry in owners_of():
            note.append(f"corroborated by an exact on-screen string: {conf:.2f} -> answer")
            conf = MIN_CONFIDENCE
        else:
            others = owners_of(exclude=entry["id"])
            if len(others) == 1:
                note.append(f"exact on-screen string belongs to {others[0]['id']}, not {entry['id']} -> switched")
                entry, conf, why = others[0], MIN_CONFIDENCE, "exact error string override"
    # VERBATIM PICK. The classifier found nothing usable while exactly ONE entry documents,
    # word for word, an error string that is in the text.
    if entry is None or conf < CLARIFY_MIN_CANDIDATE:
        others = owners_of()
        if len(others) == 1:
            note.append(f"classifier had nothing ({conf:.2f}) but the text carries {others[0]['id']}'s exact error string -> answer")
            entry, conf, why = others[0], MIN_CONFIDENCE, "verbatim error string"

    suppressed_id, suppressed_score = None, None
    if entry is not None and conf < MIN_CONFIDENCE:
        note.append(f"below floor {MIN_CONFIDENCE}: suppressed {entry['id']}")
        suppressed_id, suppressed_score = entry["id"], round(conf, 2)
        entry = None
    return entry, conf, why, suppressed_id, suppressed_score


def _usage_note(usage_acc):
    tot = {"in": 0, "out": 0, "cache_read": 0}
    for u in usage_acc:
        tot["in"] += u.get("inputTokens") or 0
        tot["out"] += u.get("outputTokens") or 0
        tot["cache_read"] += u.get("cacheReadInputTokens") or 0
    return "usage in={in} out={out} cache_read={cache_read} calls={n}".format(n=len(usage_acc), **tot)


# ----------------------------------------------------------------------------- 1:1 mode

def dm_pref_key(user):
    return f"dmpref#{_user_part(user)}"


def dm_pref_get(user):
    """The remembered tenant for this person, or None. If the table is unreachable we ask
    again rather than guess a tenant."""
    try:
        row = _plain(_convo_table().get_item(Key={"convo": dm_pref_key(user)}).get("Item") or {})
    except Exception:  # noqa: BLE001
        return None
    return row.get("dm_tenant") or None


def dm_pref_set(user, tenant_id, now):
    _convo_table().put_item(Item={"convo": dm_pref_key(user), "dm_tenant": tenant_id,
                                  "expires_at": int(now) + DM_PREF_TTL})


def _dm_fixed(reply, note, tenant_id=None):
    return {"matched": False, "outcome": "dm_setup", "id": None, "score": 0, "reply": reply,
            "resolved_text": "", "tenant": tenant_id, "note": note}


def _dm_route(event):
    """Decide which tenant a direct message belongs to. Returns None to carry on (with
    `event["tenant"]` set), or a complete response when the turn IS the routing.

    `candidate_tenants` comes from the listener's live group roster and IS the authorisation:
    an empty list never reaches here, because the listener drops a stranger's DM without
    replying. A refusal would confirm to a stranger what this number is."""
    user = event.get("participant") or event.get("jid") or ""
    cands = [t for t in (event.get("candidate_tenants") or []) if t in _TENANTS["tenants"]]
    text = (event.get("text") or "").strip()
    now = time.time()
    if len(cands) == 1:                       # almost everyone lands here, silently
        event["tenant"] = cands[0]
        return None
    if not cands:                             # belt and braces; the listener already gated
        event["tenant"] = DEFAULT_TENANT
        return None
    cands = sorted(cands)
    choices = {str(i + 1): t for i, t in enumerate(cands)}
    ask = DM_ASK_TEXT.format(choices="\n".join(f"{n}  {_TENANTS['tenants'][t]['name']}" for n, t in choices.items()))
    chosen = choices.get(text)
    if chosen:
        try:
            dm_pref_set(user, chosen, now)
        except Exception as e:  # noqa: BLE001
            return _dm_fixed(ask, f"dm: could not store the choice ({type(e).__name__}) -> asking again")
        return _dm_fixed(DM_SAVED_TEXT.format(name=_TENANTS["tenants"][chosen]["name"]), f"dm: tenant set to {chosen}", chosen)
    if any(w in text.lower() for w in DM_SWITCH_WORDS):
        return _dm_fixed(ask, "dm: switch requested -> asking again")
    pref = dm_pref_get(user)
    if pref in cands:
        event["tenant"] = pref
        return None
    return _dm_fixed(ask, "dm: in more than one tenant and no choice stored -> asking")


# ----------------------------------------------------------------------------- handler

def lambda_handler(event, context):
    event = event or {}
    if event.get("dm"):
        decided = _dm_route(event)
        if decided is not None:
            return decided
        # A DM is addressed to the bot by construction: same weight as an @-mention. The
        # screen is skipped and a no-match says so instead of staying silent. The group-only
        # suppressions (supporters, quoted replies, supporter window) are all guarded on
        # `not explicit`, so they go inert here.
        event["explicit"] = True
    tenant = resolve_tenant(event)
    token = _current_tenant.set(tenant)
    try:
        return _handle(event, tenant)
    finally:
        _current_tenant.reset(token)


def _handle(event, tenant):
    text = (event.get("text") or "").strip()
    explicit = bool(event.get("explicit"))
    note = [f"tenant={tenant['id']}"] + (["explicit call"] if explicit else [])
    usage_acc = []

    def out(**kw):
        note.append(_usage_note(usage_acc))
        base = {"matched": False, "outcome": "silent", "id": None, "score": 0, "reply": None,
                "resolved_text": text[:300], "tenant": tenant["id"]}
        base.update(kw)
        base["note"] = "; ".join(note)
        return base

    # A supporter's own message is never a request for help. First thing, before vision or
    # the screen, so it costs nothing; and record the moment so the rest of the group gets a
    # clarify-free window while the human works. An explicit call still goes through.
    if not explicit and is_supporter(event.get("participant")):
        supporter_touch(event.get("jid"), time.time())
        note.append("supporter: one of the group's own answerers is talking -> silent")
        return out()

    vision_broken, vision_text = False, ""
    if event.get("image_b64"):
        for model in (None, VISION_FALLBACK_MODEL):
            try:
                seen = read_image(event["image_b64"], event.get("mime", "image/jpeg"), model=model)
                note.append(f"vision{' (fallback)' if model else ''}: {seen[:160]}")
                if seen != "NO_PROBLEM_VISIBLE":
                    vision_text = seen
                    text = f"{text}\n{seen}".strip()   # the caption is kept, never thrown away
                break
            except Exception as e:  # noqa: BLE001
                note.append(f"vision failed: {type(e).__name__}")
                vision_broken = model is not None

    entries, kb_note = load_entries()
    note.append(kb_note)

    if not text:
        if explicit:
            help_entry = next((e for e in entries if e["id"] == T("help_entry_id")), None)
            note.append("empty explicit call -> help text")
            reply = compose(help_entry, kb_size=len(entries)) if help_entry else compose_fixed(T("no_match_text", ""))
            return out(outcome="help", reply=reply, id=help_entry["id"] if help_entry else None)
        note.append("empty")
        return out()

    now = time.time()
    # Conversation state FIRST: a reply to our own clarifying question is not a request when
    # read on its own, and the screen would correctly drop it.
    key = convo_key(event)
    state, state_ok = {}, False
    if CLARIFY_ENABLED and CONVO_TABLE and key:
        try:
            state, state_ok = state_get(key), True
        except Exception as e:  # noqa: BLE001
            note.append(f"convo state read failed ({type(e).__name__}) -> clarify off")
    pending = ""
    if state.get("pending_text") and (now - float(state.get("asked_at") or 0)) < CLARIFY_TTL:
        pending = str(state["pending_text"])

    # ---- the request gate
    is_request, domain, kind, ask_from_screen, screened = True, "on", "specific", None, False
    verbatim = verbatim_error_hit(text, entries)
    if pending:
        note.append("screen skipped: reply to our clarifying question")
    elif explicit:
        note.append("screen skipped: explicit call")
    elif verbatim and len(text) <= max(VERBATIM_PASTE_MAX_LEN, 3 * len(verbatim)):
        # The message IS an error string some entry documents: a request by definition.
        note.append(f"screen skipped: verbatim KB error string ({verbatim[:40]})")
    else:
        try:
            is_request, domain, kind, ask_from_screen, u = screen(text, kb_categories(entries))
            usage_acc.append(u)
            screened = True
            note.append(f"screen request={is_request} domain={domain} kind={kind} ask={ask_from_screen}")
            if verbatim and domain == "off":
                domain = "on"
                note.append("domain forced on: text carries a KB error string")
        except Exception as e:  # noqa: BLE001 - fail OPEN; the floor still guards every answer
            note.append(f"screen failed ({type(e).__name__}) -> proceeding unscreened")
    if screened and not is_request:
        note.append("not a request for help -> silent (no classification attempted)")
        return out()
    if screened and domain == "off":
        note.append("off-domain -> silent (no classification attempted)")
        return out()

    entry, conf, why, suppressed_id, suppressed_score = _classify_with_floor(text, entries, note, usage_acc)

    # A caption is the user's theory; the screenshot is the evidence. If the two together
    # failed, try the screen's own words alone.
    if entry is None and vision_text and vision_text != text:
        note.append("caption+screen did not land -> re-classifying the screen alone")
        e2, c2, w2, s2, ss2 = _classify_with_floor(vision_text, entries, note, usage_acc)
        if e2 is not None:
            entry, conf, why, suppressed_id, suppressed_score = e2, c2, w2, s2, ss2
        elif (ss2 or 0) > (suppressed_score or 0):
            suppressed_id, suppressed_score = s2, ss2

    # The follow-up turn: the new message alone first, then combined with the remembered one.
    if entry is None and pending:
        note.append("follow-up: combining with the remembered question")
        e2, c2, w2, s2, ss2 = _classify_with_floor(pending + "\n" + text, entries, note, usage_acc)
        if e2 is not None:
            entry, conf, why, suppressed_id, suppressed_score = e2, c2, w2, s2, ss2
        elif (ss2 or 0) > (suppressed_score or 0):
            suppressed_id, suppressed_score = s2, ss2
    if pending and state_ok:
        try:
            if not state_clear_pending(key, state.get("asked_at") or 0):
                note.append("convo state: pending already consumed or superseded")
        except Exception as e:  # noqa: BLE001
            note.append(f"convo state clear failed ({type(e).__name__})")

    if entry is not None:
        try:
            reply = compose(entry, text, len(entries))
        except Exception as e:  # noqa: BLE001
            note.append(f"compose failed ({type(e).__name__}); sending verbatim")
            reply = compose_fixed(entry.get("answer") or "")
        return out(matched=True, outcome="answer", id=entry["id"], score=round(conf, 2), reply=reply, kb_size=len(entries))

    # ---- no answer. Third outcome: clarify, or stay silent.
    near = suppressed_score or 0.0
    route = None
    if near >= CLARIFY_MIN_CANDIDATE:
        route = "candidate"        # ROUTE 1: a named entry the classifier cannot be trusted on
    elif kind == "underspecified" and ask_from_screen and not T("clarify_route2", True):
        # ROUTE 2 is a bet that the KB can answer once the message is sharpened. With a small
        # KB that bet always loses (production measured 11 questions, 0 answers on an 8-entry
        # KB), so it is a per-tenant flag.
        note.append("clarify: route 2 (underspecified) disabled for this tenant")
    elif kind == "underspecified" and ask_from_screen:
        route = "underspecified"   # ROUTE 2: no candidate, the message itself is too vague

    sup_age = None if (explicit or not CONVO_TABLE) else supporter_recent_secs(event.get("jid"), now)
    ask_key = None
    if not CLARIFY_ENABLED or not CONVO_TABLE:
        note.append("clarify: disabled (CLARIFY_ENABLED=0 or no CONVO_TABLE)")
    elif not key:
        note.append("clarify: no jid/participant -> cannot rate-limit -> silent")
    elif not state_ok:
        note.append("clarify: state unavailable -> silent")
    elif pending and not explicit:
        note.append("clarify: this thread was already clarified -> silent")
    elif event.get("quoted_participant") and not explicit:
        # One half of a two-person exchange. Only the QUESTION is withheld; an answer above
        # the floor was already sent above, whoever the message was aimed at.
        note.append("clarify: this message replies to another person -> silent")
    elif sup_age is not None:
        note.append(f"clarify: a supporter spoke here {sup_age}s ago -> silent")
    elif kind == "outage" and not explicit:
        note.append("clarify: outage question -> silent (only a human knows)")
    elif route is None:
        note.append(f"clarify: no route (near miss {near} < {CLARIFY_MIN_CANDIDATE}, kind={kind}) -> silent")
    elif (now - float(state.get("last_clarify_at") or 0)) < CLARIFY_COOLDOWN and not explicit:
        left = int(CLARIFY_COOLDOWN - (now - float(state.get("last_clarify_at") or 0)))
        note.append(f"clarify: rate-limited, {left}s of the {CLARIFY_COOLDOWN}s window left")
    else:
        ask_key = ask_from_screen or T("clarify_default")
        if ask_key not in T("clarify_questions", {}):
            note.append("clarify: tenant has no question to ask -> silent")
            ask_key = None
        elif ask_key == "error" and vision_text:
            note.append("clarify: suppressed, the screenshot was already read; nothing to ask for")
            ask_key = None
        else:
            note.append(f"clarify: route={route} ask={ask_key}")
    if ask_key:
        try:
            if not state_try_claim(key, text, ask_key, now):
                note.append("clarify: lost the concurrent claim -> silent")
                ask_key = None
        except Exception as e:  # noqa: BLE001
            note.append(f"convo state write failed ({type(e).__name__}) -> silent")
            ask_key = None
    if ask_key:
        return out(outcome="clarify", reply=compose_clarify(ask_key), clarify_key=ask_key, clarify_route=route,
                   kb_size=len(entries), suppressed_id=suppressed_id, suppressed_score=suppressed_score)

    if explicit:
        # Asked directly and nothing fits: say so in fixed text rather than ignore the person.
        if vision_broken:
            note.append("explicit call, image unreadable -> fixed vision-failed text")
            return out(outcome="nomatch", reply=compose_fixed(T("vision_failed_text", "")), kb_size=len(entries))
        note.append("explicit call with no answer -> fixed no-match text")
        return out(outcome="nomatch", reply=compose_fixed(T("no_match_text", "")), kb_size=len(entries),
                   suppressed_id=suppressed_id, suppressed_score=suppressed_score)
    # score is 0 on a genuine no-match; `suppressed_*` carries the near miss, which is the
    # single most useful signal for deciding which entry to write next.
    return out(kb_size=len(entries), suppressed_id=suppressed_id, suppressed_score=suppressed_score)


if __name__ == "__main__":   # python3 brain/lambda_function.py "my vpn keeps disconnecting"
    import sys
    print(json.dumps(lambda_handler({"text": " ".join(sys.argv[1:]), "jid": "cli", "participant": "cli"}, None),
                     indent=2, ensure_ascii=False))
