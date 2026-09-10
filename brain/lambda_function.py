"""The brain: given a message (and optionally a screenshot), decide which knowledge-base
entry answers it, or stay silent.

Channel-agnostic on purpose. Input is a plain dict, output is a plain dict, so the same
function serves WhatsApp today and Teams or Slack tomorrow with no change here.

    in : {"text": "...", "image_b64": "...", "mime": "image/jpeg", "sender": "..."}
    out: {"outcome": "answer"|"silent", "id": ..., "score": 0.93, "reply": "...", "note": "..."}

Design rule: the model ROUTES, it does not write. `ANSWER_MODE=verbatim` (default) sends
the entry's answer text exactly as a human wrote it. `ANSWER_MODE=compose` lets the model
rephrase that one entry for the question, still with nothing outside the entry as a source.
Below MIN_CONFIDENCE the bot says nothing: in a group, silence beats a wrong answer.
"""
import base64
import json
import os
import pathlib
import re
import time

import boto3

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "eu-west-1"))
KB_TABLE = os.environ.get("KB_TABLE", "")                 # empty = use bundled kb.json only
KB_CACHE_TTL = float(os.environ.get("KB_CACHE_TTL", "60"))
CLASSIFY_MODEL = os.environ.get("CLASSIFY_MODEL", "eu.anthropic.claude-haiku-4-5-20251001-v1:0")
VISION_MODEL = os.environ.get("VISION_MODEL", "eu.anthropic.claude-sonnet-4-6")
MIN_CONFIDENCE = float(os.environ.get("MIN_CONFIDENCE", "0.85"))
ANSWER_MODE = os.environ.get("ANSWER_MODE", "verbatim")   # verbatim | compose
BOT_HEADER = os.environ.get("BOT_HEADER", "🤖 _Automated answer from the support bot_")
CACHE_PROMPT = os.environ.get("CACHE_PROMPT", "1") != "0"

_brt = boto3.client("bedrock-runtime", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION) if KB_TABLE else None
_SNAPSHOT = json.loads((pathlib.Path(__file__).parent / "kb.json").read_text(encoding="utf-8"))
_CACHE = {"entries": None, "expires": 0.0, "source": None}

HEBREW = re.compile(r"[֐-׿]")
CODE_SPAN = re.compile(r"`[^`\n]+`")
RLM, LRI, PDI = "‏", "⁦", "⁩"


# ----------------------------------------------------------------------------- KB

def _published(entries):
    return [e for e in entries if e.get("status", "published") == "published"]


def load_entries():
    """Published entries from DynamoDB (60 s cache), else the kb.json baked into the zip."""
    now = time.time()
    if _CACHE["entries"] is not None and now < _CACHE["expires"]:
        return _CACHE["entries"], _CACHE["source"]
    entries, source = None, None
    if _ddb is not None:
        try:
            table = _ddb.Table(KB_TABLE)
            items, scan = [], table.scan()
            while True:
                items += scan["Items"]
                if "LastEvaluatedKey" not in scan:
                    break
                scan = table.scan(ExclusiveStartKey=scan["LastEvaluatedKey"])
            entries, source = _published(items), f"dynamodb:{len(items)}"
        except Exception as e:  # noqa: BLE001 - any table problem falls back to the snapshot
            source = f"dynamodb failed ({type(e).__name__}); snapshot"
    if entries is None:
        entries = _published(_SNAPSHOT["entries"])
        source = source or "snapshot"
    _CACHE.update(entries=entries, expires=now + KB_CACHE_TTL, source=source)
    return entries, source


def _catalogue(entries):
    """What the classifier sees: ids, phrasings, exact error strings, and a short gloss.
    Never the full answers. That keeps the prompt small, cheap and cacheable."""
    out = []
    for e in entries:
        gloss = e["answer"][:140].replace("\n", " ")
        block = [f"- id: {e['id']}", f"  category: {e.get('category', '')}",
                 f"  typical phrasings: {', '.join(e.get('triggers', [])[:6])}"]
        for err in e.get("error_strings") or []:
            block.append(f"  EXACT ERROR SEEN ON SCREEN: {err}")
        block.append(f"  answers: {gloss}")
        out.append("\n".join(block))
    return "\n".join(out)


# ----------------------------------------------------------------------------- prompts

# The catalogue sits at the END of the system prompt and nothing per-request appears
# before it, so Bedrock prompt caching can reuse the whole prefix across messages.
CLASSIFY_SYSTEM = """You route messages from a support chat group onto a fixed knowledge base.
People write informally, in any language, with typos.

First decide whether the message is a REQUEST FOR HELP at all. Announcements, someone
posting a solution for others, "same here", jokes, thanks, and people answering each other
are NOT requests. For those, return id "none".

If it is a request, pick the ONE entry that genuinely answers it. Rules:
- Return "none" unless the entry addresses the user's actual problem. Most messages have no
  match, and answering the wrong thing is worse than staying silent.
- Match on meaning, not shared words. A message that merely mentions a topic is not a match.
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

VISION_PROMPT = """This is a screenshot sent to a technical support chat, usually a terminal or
an error dialog. Transcribe the user's problem as one or two first-person sentences, the way
they would type it to ask for help. Quote any error code, heading or command VERBATIM.
If nothing is wrong on screen, describe what it shows in one sentence.
Reply NO_PROBLEM_VISIBLE only if the image is unrelated to software or devices."""


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


def classify(text, entries):
    raw, usage = _converse(CLASSIFY_MODEL, CLASSIFY_SYSTEM.format(catalogue=_catalogue(entries)),
                           [{"text": CLASSIFY_USER.format(question=text)}], cache=CACHE_PROMPT)
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    data = json.loads(raw)
    conf = float(data.get("confidence") or 0)
    entry = next((e for e in entries if e["id"] == data.get("id")), None)
    return entry, conf, data.get("why", ""), usage


def read_image(image_b64, mime):
    fmt = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "jpeg")
    content = [{"image": {"format": fmt, "source": {"bytes": base64.b64decode(image_b64)}}},
               {"text": VISION_PROMPT}]
    r = _brt.converse(modelId=VISION_MODEL, messages=[{"role": "user", "content": content}],
                      inferenceConfig={"maxTokens": 300, "temperature": 0})
    return r["output"]["message"]["content"][0]["text"].strip()


# ----------------------------------------------------------------------------- compose

def rtl(text):
    """WhatsApp renders a mixed Hebrew/English message LTR unless every line starts with an
    RTL mark, and the LAST line needs a lone mark of its own or it flips back. Code spans
    are isolated so `commands` keep reading left-to-right."""
    text = CODE_SPAN.sub(lambda m: LRI + m.group(0) + PDI, text)
    body = "\n".join(RLM + ln if ln.strip() else ln for ln in text.split("\n"))
    return body + "\n" + RLM


def compose(entry, question):
    body = entry["answer"]
    if ANSWER_MODE == "compose":
        body, _ = _converse(CLASSIFY_MODEL, COMPOSE_SYSTEM.format(answer=body),
                            [{"text": question}], max_tokens=600)
    parts = [BOT_HEADER, "", body]
    if entry.get("owner"):
        parts += ["", f"Still stuck? Contact: {entry['owner']}"]
    msg = "\n".join(parts)
    return rtl(msg) if HEBREW.search(msg) else msg


# ----------------------------------------------------------------------------- handler

def lambda_handler(event, context):
    event = event or {}
    text = (event.get("text") or "").strip()
    note = []

    def out(**kw):
        base = {"outcome": "silent", "id": None, "score": 0, "reply": None,
                "resolved_text": text[:300]}
        base.update(kw)
        base["note"] = "; ".join(note)
        return base

    if event.get("image_b64"):
        try:
            seen = read_image(event["image_b64"], event.get("mime", "image/jpeg"))
            note.append(f"vision: {seen[:160]}")
            if seen != "NO_PROBLEM_VISIBLE":
                text = f"{text}\n{seen}".strip()
        except Exception as e:  # noqa: BLE001
            note.append(f"vision failed: {e}")
    if not text:
        note.append("empty")
        return out()

    entries, source = load_entries()
    note.append(f"kb {source} ({len(entries)} published)")
    try:
        entry, conf, why, usage = classify(text, entries)
    except Exception as e:  # noqa: BLE001 - a broken model must never produce a guess
        note.append(f"classify failed: {type(e).__name__}: {e}")
        return out()
    note.append(f"classify {entry['id'] if entry else 'none'} {conf:.2f} ({why}); "
                f"tokens in={usage.get('inputTokens')} cached={usage.get('cacheReadInputTokens', 0)}")

    if entry is None or conf < MIN_CONFIDENCE:
        if entry is not None:
            note.append(f"below floor {MIN_CONFIDENCE}")
        return out(id=entry["id"] if entry else None, score=conf if entry else 0)

    try:
        reply = compose(entry, text)
    except Exception as e:  # noqa: BLE001
        note.append(f"compose failed: {e}; sending verbatim")
        reply = entry["answer"]
    return out(outcome="answer", id=entry["id"], score=conf, reply=reply)


if __name__ == "__main__":   # python3 brain/lambda_function.py "my vpn keeps disconnecting"
    import sys
    print(json.dumps(lambda_handler({"text": " ".join(sys.argv[1:])}, None), indent=2, ensure_ascii=False))
