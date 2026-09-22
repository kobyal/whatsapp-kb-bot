#!/usr/bin/env python3
"""The KB curator: a separate, optional layer that learns from what the bot already logged.

It touches NOTHING on the operational path. The listener and the brain are unchanged; the
curator pulls bot.log over SSM (fetch_log.py), turns it into events (events.py), and produces
what a KB owner otherwise digs out of a chat export by hand:

  1. USAGE       what fired, how often, and what never fires
  2. REPEATED    the same question asked again and again with no entry to answer it
  3. TRIGGER FIX a miss the classifier nearly got (the clarify band) -> the person's own
                 phrasing as a trigger on that entry, inside the visible top six
  4. DRAFTS      a miss that a human then answered, and the asker confirmed -> a draft entry,
                 written to the KB table as status=draft for the owner to approve
  5. REVIEW      a confident answer followed within minutes by a supporter speaking up
  6. OPEN GAPS   misses nobody answered: the questions the group itself has no answer to

THREE CONFIDENCE TIERS, i.e. what the curator may do on its own and what needs a click:

  Tier A  APPLIED   a trigger fix on an EXISTING entry, only when (1) a human in the thread
                    gave THAT entry's answer and the asker accepted it, (2) re-classifying the
                    missed message against the modified entry clears the floor, (3) kbcheck adds
                    no error and no warning. The answer text is untouched, so nothing new is ever
                    said; the entry just gets found. Written to tenants/<id>/kb.json + published.
  Tier B  DRAFT     a NEW entry from a confirmed thread lands as status=draft in the KB table.
                    The brain reads only `published`; the tenant's KB owner publishes it.
  Tier C  REPORTED  everything else: repeated topics, review flags, open gaps, in the digest.

The line between A and B is the design rule of the whole bot: the bot never writes an answer.
People do. Tier A changes how an answer is FOUND, never what it SAYS.

    python3 curator/curate.py --log /tmp/bot.log --days 1 --no-model --out digest.md   # numbers only
    python3 curator/curate.py --log /tmp/bot.log --days 1 --out digest.md              # + model judgements
    python3 curator/curate.py --log /tmp/bot.log --days 1 --apply-triggers --write-drafts  # the daily run

Test rooms (tenant.json `test_groups`) are EXCLUDED by default: they are one person talking to
the bot, not the group. `--include-test-groups` includes them and lets that one person play
asker, answerer and confirmer, which is how the pipeline is proven end to end before it is
trusted on a real group. It is never right for a real group.
"""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import events as ev_mod  # noqa: E402

REGION = os.environ.get("BEDROCK_REGION", os.environ.get("AWS_REGION", "eu-west-1"))
JUDGE_MODEL = os.environ.get("CURATOR_MODEL", "eu.anthropic.claude-sonnet-4-6")   # drafts, confirmations, clustering
FLOOR = float(os.environ.get("MIN_CONFIDENCE", "0.85"))                            # must match the brain's
NEAR_LO = float(os.environ.get("CLARIFY_MIN_CANDIDATE", "0.70"))                    # the clarify band
THREAD_WINDOW = timedelta(hours=6)     # how long after a miss a human answer still counts
REVIEW_WINDOW = timedelta(minutes=30)  # a supporter speaking this soon after a bot answer

# ------------------------------------------------------------------ helpers


def tenant_cfg(tid):
    return json.loads((REPO / "tenants" / tid / "tenant.json").read_text(encoding="utf-8"))


def tenant_kb(tid):
    return json.loads((REPO / "tenants" / tid / "kb.json").read_text(encoding="utf-8"))["entries"]


def _brt():
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=REGION,
                        config=Config(connect_timeout=5, read_timeout=60, retries={"max_attempts": 2}))


def judge_json(system, user, max_tokens=2500):
    """One converse call, JSON out. The model is asked for JSON only; prose around it is
    tolerated (outermost object), anything else is a failure we report rather than parse around."""
    from botocore.exceptions import ClientError
    r = None
    for attempt in (1, 2):
        try:
            r = _brt().converse(modelId=JUDGE_MODEL, system=[{"text": system}],
                                messages=[{"role": "user", "content": [{"text": user}]}],
                                inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
            break
        except ClientError:
            if attempt == 2:
                raise
            time.sleep(4)
    txt = r["output"]["message"]["content"][0]["text"].strip()
    txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt)
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        i, j = txt.find("{"), txt.rfind("}")
        if i >= 0 and j > i:
            return json.loads(txt[i:j + 1])
        raise


def short(s, n=90):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def load_offline_brain():
    """brain/lambda_function.py imported unchanged, so the curator re-classifies with the real
    prompt, the real catalogue and the real floor. KB_TABLE_PREFIX decides whether it reads
    the live tables or the snapshot; the operational Lambda is never invoked."""
    brain_dir = REPO / "brain"
    if not (brain_dir / "tenants.json").exists():
        subprocess.run(["bash", str(brain_dir / "build.sh")], check=True, stdout=subprocess.DEVNULL)
    spec = importlib.util.spec_from_file_location("brain_offline", brain_dir / "lambda_function.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def with_tenant(brain, tid, fn):
    tok = brain._current_tenant.set(brain._TENANTS["tenants"][tid])
    try:
        return fn()
    finally:
        brain._current_tenant.reset(tok)


# ------------------------------------------------------------------ 1. usage

def usage(evs, tid):
    mine = [e for e in evs if e.tenant == tid and not e.supporter]
    out = Counter(e.outcome for e in mine)
    requests = [e for e in mine if e.is_request or e.explicit or e.dm or e.outcome in ("answer", "clarify", "nomatch")]
    fired = Counter(e.entry for e in mine if e.outcome == "answer" and e.entry)
    published = [e for e in tenant_kb(tid) if e.get("status", "published") == "published"]
    never = [e for e in published if e["id"] not in fired]
    return {"messages": len(mine), "requests": len(requests), "outcomes": dict(out),
            "answers": out.get("answer", 0), "misses": sum(e.is_miss for e in mine),
            "errors": out.get("error", 0),
            "people": len({e.user for e in mine}), "dms": sum(e.dm for e in mine),
            "dm_people": len({e.user for e in mine if e.dm}),
            "dm_answered": sum(1 for e in mine if e.dm and e.outcome == "answer"),
            "dm_nomatch": sum(1 for e in mine if e.dm and e.outcome == "nomatch"),
            "fired": fired.most_common(),
            "never_fired": [(e["id"], e.get("last_verified", "")) for e in never],
            "kb_size": len(published)}


# ------------------------------------------------------- 2. repeated questions

CLUSTER_SYS = """You group support questions from a chat group into topics.
Return JSON only: {"topics":[{"label":"<short label, in the language of the questions>","ids":[<int>,...],"answered_by":"<entry id or null>"}]}
Rules: a topic is the SAME underlying problem, not the same words. Put every id in exactly one topic.
`answered_by` is the KB entry id that answered most of the topic's questions, or null if most were missed.
Singletons are fine. Do not invent ids."""


def cluster_requests(evs, tid, use_model):
    reqs = [e for e in evs if e.tenant == tid and not e.supporter and len(e.text) >= 12 and
            (e.is_request or e.explicit or e.dm or e.outcome in ("answer", "clarify", "nomatch"))]
    if not reqs:
        return []
    if not use_model or len(reqs) < 2:
        return [{"label": short(e.text, 60), "ids": [i], "answered_by": e.entry, "count": 1,
                 "missed": int(e.is_miss), "people": 1, "examples": [e]} for i, e in enumerate(reqs)]
    lines = "\n".join(f'{i}\t{("answer:" + e.entry) if e.outcome == "answer" else e.outcome}\t{short(e.text, 140)}'
                      for i, e in enumerate(reqs))
    try:
        data = judge_json(CLUSTER_SYS, f"Questions (id<TAB>outcome<TAB>text):\n{lines}")
    except Exception as ex:  # noqa: BLE001
        return [{"label": f"(clustering failed: {type(ex).__name__})", "ids": [], "answered_by": None,
                 "count": 0, "missed": 0, "people": 0, "examples": []}]
    topics = []
    for t in data.get("topics", []):
        ids = [i for i in t.get("ids", []) if isinstance(i, int) and 0 <= i < len(reqs)]
        if not ids:
            continue
        exs = [reqs[i] for i in ids]
        topics.append({"label": t.get("label", "?"), "ids": ids, "answered_by": t.get("answered_by"),
                       "count": len(ids), "missed": sum(e.is_miss for e in exs),
                       "people": len({e.user for e in exs}), "examples": exs})
    topics.sort(key=lambda t: (-t["missed"], -t["count"]))
    return topics


# ---------------------------------------------------------- 3. trigger fixes

DISTIL_SYS = """Turn a chat support message into ONE knowledge-base trigger phrase, in the message's own language:
the core symptom or question only, 4-12 words, no greeting, no names, no user ids, no dates, no
"please help". Keep the user's own key nouns. Return JSON only: {"trigger":"..."}"""

CONFIRM_SYS = """You judge whether a KB entry is the RIGHT answer for a support thread.
Given the thread (ASKER / SUPPORTER / PEER, with times) and one KB entry's answer text, return JSON only:
{"confirmed": true|false, "why": "<one line>"}
confirmed=true ONLY if a human in the thread gave substantively the SAME answer as the entry AND the asker
accepted it or reported it worked. A human giving a DIFFERENT answer, no answer, or an unconfirmed one -> false.
A referral ("contact X", "open a ticket", "we'll look into it") is NOT an answer."""

TEST_HINT = ("\nNOTE: this is a TEST group with a single human who plays asker, answerer and confirmer in turn. "
             "Judge the SUBSTANCE of the messages by their order (question, then answer, then acceptance) "
             "and do not reject the thread merely because the same person wrote them.")


def distil_trigger(text):
    try:
        return judge_json(DISTIL_SYS, text, max_tokens=80).get("trigger") or short(text, 60)
    except Exception:  # noqa: BLE001
        return short(text, 60)


def _role(e, miss):
    return "ASKER" if e.user == miss.user else ("SUPPORTER" if e.supporter else "PEER")


def thread_lines(miss, later):
    return [f"{miss.ts[11:16]} ASKER: {miss.text}"] + [f"{e.ts[11:16]} {_role(e, miss)}: {e.text}" for e in later]


def thread_confirms_entry(miss, later, entry_answer, self_ok=False):
    try:
        d = judge_json(CONFIRM_SYS + (TEST_HINT if self_ok else ""),
                       "THREAD:\n" + "\n".join(thread_lines(miss, later)) + "\n\nKB ENTRY ANSWER:\n" + entry_answer,
                       max_tokens=200)
        return bool(d.get("confirmed")), d.get("why", "")
    except Exception as ex:  # noqa: BLE001
        return False, f"model error {type(ex).__name__}"


def thread_after(evs, miss, self_ok=False):
    """(everything that belongs to THIS question, the replies by other people). Same group,
    inside the window, stopping at the next question anyone asks: without the stop a 6-hour
    window swallows a later, unrelated thread and a draft gets anchored to the wrong miss."""
    same = sorted((e for e in evs if e.tenant == miss.tenant and e.jid == miss.jid
                   and miss.when < e.when <= miss.when + THREAD_WINDOW), key=lambda e: e.when)
    cut = []
    for e in same:
        if e.is_miss and len(e.text) >= 8:
            break
        cut.append(e)
    others = [e for e in cut if e.user != miss.user]
    return cut, (others or (cut if self_ok else []))


def near_misses(evs, tid, brain, test_groups=()):
    """Re-run every miss through the real classifier to learn WHICH entry it nearly picked.
    The log does not carry that, and it is the single most useful fact for fixing a KB: a
    near miss on entry X for a question a human then answered with X's content means X is
    missing that phrasing in its top six."""
    misses = [e for e in evs if e.tenant == tid and e.is_miss and e.text]
    if not misses:
        return []

    def run():
        entries, _ = brain.load_entries()
        out = []
        for e in misses:
            try:
                ent, conf, why, _u = brain.bedrock_classify(e.text, entries)
            except Exception:  # noqa: BLE001
                continue
            if ent is not None and NEAR_LO <= conf < FLOOR:
                later, answerers = thread_after(evs, e, self_ok=e.jid in test_groups)
                confirmed, cwhy = (False, "no human reply in the thread")
                if answerers:
                    confirmed, cwhy = thread_confirms_entry(e, later, ent.get("answer", ""), self_ok=e.jid in test_groups)
                out.append({"event": e, "entry": ent["id"], "conf": round(conf, 2), "why": why,
                            "top6": (ent.get("triggers") or [])[:6], "proposal": distil_trigger(e.text),
                            "confirmed": confirmed, "confirm_why": cwhy})
        return out
    return with_tenant(brain, tid, run)


def apply_trigger_fix(near, tid, brain):
    """Tier A, the one change the curator may make WITHOUT a human click. Returns (applied, message)."""
    if not near.get("confirmed"):
        return False, f"not confirmed by a human answer in the thread ({short(near.get('confirm_why', ''), 90)}); proposal only"
    kb_path = REPO / "tenants" / tid / "kb.json"
    kb = json.loads(kb_path.read_text(encoding="utf-8"))
    entry = next((e for e in kb["entries"] if e["id"] == near["entry"]), None)
    if entry is None:
        return False, "entry not in kb.json"
    phrase = near["proposal"].rstrip("…").strip()
    trig = list(entry.get("triggers") or [])
    if any(phrase.lower() == x.lower() for x in trig[:6]):
        return False, "already in the top six"
    trig.insert(min(5, len(trig)), phrase)   # sixth position: visible, least disturbance to the author's order
    if len(trig) > 6:
        trig = trig[:6]                       # never leave a phrasing the classifier cannot see (kbcheck R15)
    modified = dict(entry, triggers=trig)
    ok, out = kbcheck_ok(modified, tid, replacing=True)
    if not ok:
        return False, f"kbcheck refused: {short(out, 120)}"

    def reclassify():
        entries, _ = brain.load_entries()
        trial = [modified if e["id"] == entry["id"] else e for e in entries]
        return brain.bedrock_classify(near["event"].text, trial)
    ent, conf, _why, _u = with_tenant(brain, tid, reclassify)
    if ent is None or ent["id"] != entry["id"] or conf < FLOOR:
        return False, f"re-classified at {conf:.2f} on {ent['id'] if ent else 'none'}; not enough, left as a proposal"
    entry["triggers"] = trig
    kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not os.environ.get("KB_TABLE_PREFIX"):
        # Snapshot mode (no tables): the repo file is the only KB there is. Commit it.
        return True, f"{near['conf']} -> {conf:.2f}; trigger #{trig.index(phrase) + 1} on `{entry['id']}`, written to kb.json (no table to publish to)"
    r = subprocess.run([sys.executable, str(REPO / "kb" / "publish.py"), "--tenant", tid],
                       capture_output=True, text=True, env={**os.environ, "KB_TENANT": tid})
    if r.returncode != 0:
        return False, f"kb.json updated but publish failed: {short(r.stderr or r.stdout, 120)}"
    return True, f"{near['conf']} -> {conf:.2f}; trigger #{trig.index(phrase) + 1} on `{entry['id']}`, published"


# ----------------------------------------------------------------- 4. drafts

DRAFT_SYS = """You draft knowledge-base entries for a chat support bot. You are given a THREAD: a question
the bot could not answer, then what other people in the group said within six hours, labelled
ASKER / SUPPORTER / PEER with timestamps.

THE ONE RULE: write a draft ONLY if a human gave an answer AND the asker (or another person)
confirmed it worked or accepted it. A supporter saying "we'll look into it", an outage notice, a
workaround nobody confirmed, or a question nobody answered -> {"verdict":"decline","why":"..."}.
A referral ("contact X", "open a ticket", "talk to Y") is NOT an answer: decline. A KB entry must
tell the reader what to DO.

If the rule is met, return JSON only:
{"verdict":"draft","why":"<one line>","entry":{
 "id":"<snake_case, 3-64 chars, a-z0-9_>","category":"<category>",
 "triggers":["<up to 6 phrasings in the group's language, MOST REPRESENTATIVE FIRST; only the first six are ever read>"],
 "error_strings":["<exact on-screen strings only, else empty>"],
 "answer":"<the answer in the SUPPORTER's/PEER's own substance; first line names the subject; short lines <=160 chars;
   identifiers in `backticks`; *bold* only at a word boundary, never glued to a letter>",
 "owner":"<role of who answered, e.g. platform-team>",
 "source":"chat group '<group>', <date> <time range>",
 "verified_against":"<quote WHO (by role) said WHAT, WHEN: the question, the answer, the confirmation>",
 "last_verified":"<YYYY-MM-DD>","status":"draft",
 "notes":"Drafted by the curator from bot.log; message text in the log is cut at 160 chars; verify against the chat before publishing."}}
Never put a person's name in the answer. Never invent commands, paths or policies that are not in
the thread. Do not duplicate an existing entry: if the answer is already covered by one of the
EXISTING entry ids given, decline and name it."""


def threads_for_drafts(evs, tid, test_groups=(), unconfirmed=None):
    """A miss, then someone ELSE spoke, then the asker spoke again AFTER that: the shape of a
    question answered and confirmed. The order gate is code, not judgement: a model once read
    an asker's screenshot sent BEFORE the peer's answer as acknowledgement and drafted."""
    mine = [e for e in evs if e.tenant == tid and not e.dm]
    out = []
    unconfirmed = [] if unconfirmed is None else unconfirmed
    for m in mine:
        if not m.is_miss or len(m.text) < 8:
            continue
        later, answerers = thread_after(mine, m, self_ok=m.jid in test_groups)
        if not answerers:
            continue
        first_answer = min(e.when for e in answerers)
        if not any(e.user == m.user and e.when > first_answer for e in later):
            unconfirmed.append({"miss": m, "why": "someone answered, but the asker never replied after the answer; no confirmation to harvest"})
            continue
        out.append((m, later))
    return out


def draft_from_thread(miss, later, cfg, existing_ids, self_ok=False):
    user = (f"Group: {cfg['name']}\nDate: {miss.ts[:10]}\nEXISTING entry ids: {', '.join(existing_ids)}\n\n"
            "THREAD:\n" + "\n".join(thread_lines(miss, later)))
    return judge_json(DRAFT_SYS + (TEST_HINT if self_ok else ""), user)


def _kbcheck(entries, tid):
    """(errors, warnings, output) from the real kbcheck on an in-memory KB."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False)
        path = f.name
    r = subprocess.run([sys.executable, str(REPO / "kb" / "kbcheck.py"), "--kb", path],
                       capture_output=True, text=True, env={**os.environ, "KB_TENANT": tid})
    os.unlink(path)
    out = (r.stdout + r.stderr).strip()
    m = re.search(r"(\d+) errors, (\d+) warnings", out)
    return (int(m.group(1)) if m else 99, int(m.group(2)) if m else 99, out)


def kbcheck_ok(draft, tid, replacing=False):
    """A change may not add an error, and may not ADD a warning. Pre-existing warnings on other
    entries are not this change's fault and must not block it."""
    base = tenant_kb(tid)
    trial = [draft if e["id"] == draft["id"] else e for e in base] if replacing else base + [draft]
    e0, w0, _ = _kbcheck(base, tid)
    e1, w1, out = _kbcheck(trial, tid)
    return (e1 == 0 and w1 <= w0), out


def write_draft(draft, tid):
    """Land the draft in the tenant's KB table as status=draft. Refuses to overwrite an existing
    id: a draft may never clobber an entry a human wrote."""
    import boto3
    from botocore.exceptions import ClientError
    spec = importlib.util.spec_from_file_location("kb_publish", REPO / "kb" / "publish.py")
    pub = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pub)
    name = pub.table_name(tid, os.environ.get("KB_TABLE_PREFIX", "wakb-kb-"))
    table = boto3.resource("dynamodb", region_name=REGION).Table(name)
    try:
        table.put_item(Item=dict(draft, status="draft"), ConditionExpression="attribute_not_exists(id)")
        return True, f"created in {name}"
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False, "id already exists; left alone"
        raise


# ----------------------------------------------------------------- 5. review

def review_flags(evs, tid):
    mine = [e for e in evs if e.tenant == tid and not e.dm]
    flags = []
    for a in mine:
        if a.outcome != "answer" or a.score < FLOOR:
            continue
        soon = [s for s in mine if s.supporter and s.jid == a.jid and a.when < s.when <= a.when + REVIEW_WINDOW]
        if soon:
            flags.append({"answer": a, "supporter": soon[0]})
    return flags


# ------------------------------------------------------------- 6. open gaps

def open_gaps(evs, tid, test_groups=()):
    mine = [e for e in evs if e.tenant == tid and not e.dm]
    return [m for m in mine if m.is_miss and len(m.text) >= 8
            and not thread_after(mine, m, self_ok=m.jid in test_groups)[1]]


# ----------------------------------------------------------------- digest

def render(window, results, window_days=1):
    L = [f"# KB curator digest: {window}", ""]
    for tid, r in results.items():
        u = r["usage"]
        L += [f"## {tid}", "",
              f"**{u['messages']}** messages from **{u['people']}** people · **{u['requests']}** requests · "
              f"**{u['answers']}** answered · **{u['misses']}** missed · **{u['errors']}** brain errors · KB {u['kb_size']} entries", "",
              f"**1:1:** {u['dm_people']} people, {u['dms']} messages: {u['dm_answered']} answered, {u['dm_nomatch']} no-match", ""]
        if u["fired"]:
            L += ["### Frequent: entries that fired", ""] + [f"- `{eid}` × {n}" for eid, n in u["fired"][:10]] + [""]
        if u["never_fired"] and window_days >= 7:
            L += [f"### Seldom: {len(u['never_fired'])} published entries never fired in {window_days:g} days", "",
                  "- " + ", ".join(f"`{e}`" for e, _ in u["never_fired"][:25]), ""]
        rep = [t for t in r["topics"] if t["missed"] >= 2]
        if rep:
            L += ["### Repeated questions without an answer", ""]
            for t in rep[:8]:
                L += [f"- **{t['label']}**: asked {t['count']}× by {t.get('people', '?')} people, {t['missed']} missed"
                      + (f", partly answered by `{t['answered_by']}`" if t.get("answered_by") else "")]
                L += [f"  - {e.ts[:10]} “{short(e.text, 100)}”" for e in t["examples"][:2]]
            L += [""]
        if r["applied"]:
            L += ["### KB UPDATED: trigger fixes applied and published (verified: score now at or above the floor)", ""]
            for n in r["applied"]:
                L += [f"- `{n['entry']}`: {n['apply_msg']}", f"  - from “{short(n['event'].text, 90)}” ({n['event'].ts[:10]})"]
            L += [""]
        pending_near = [n for n in r["near"] if not n.get("applied")]
        if pending_near:
            L += ["### Trigger fixes proposed (the classifier nearly got it), not applied", ""]
            for n in pending_near:
                L += [f"- `{n['entry']}` scored **{n['conf']}** on “{short(n['event'].text, 90)}” ({n['event'].ts[:10]})",
                      f"  - propose trigger: **{n['proposal']}** into the top six (currently: {', '.join(n['top6'][:3])}…)",
                      f"  - {'CONFIRMED by a human answer' if n.get('confirmed') else 'unconfirmed'}: {short(n.get('confirm_why', ''), 110)}"]
                if n.get("apply_msg"):
                    L += [f"  - {n['apply_msg']}"]
            L += [""]
        if r["drafts"]:
            L += ["### Drafts", ""]
            for d in r["drafts"]:
                L += [f"- `{d['entry']['id']}`: {d['status']}. {d['why']}", f"  - from {d['miss'].ts[:16]} “{short(d['miss'].text, 80)}”"]
                if d.get("kbcheck"):
                    L += [f"  - kbcheck: {short(d['kbcheck'], 160)}"]
            L += [""]
        if r["declined"]:
            L += [f"### Threads with a human reply but no confirmed answer ({len(r['declined'])})", ""]
            L += [f"- {d['miss'].ts[:10]} “{short(d['miss'].text, 80)}”: {short(d['why'], 120)}" for d in r["declined"][:8]] + [""]
        if r["review"]:
            L += ["### Review: a confident answer, then a supporter spoke up within 30 min", ""]
            L += [f"- `{f['answer'].entry}` ({f['answer'].score}) on “{short(f['answer'].text, 70)}” -> "
                  f"{f['supporter'].ts[11:16]} supporter: “{short(f['supporter'].text, 90)}”" for f in r["review"]] + [""]
        if r["gaps"]:
            L += [f"### Open gaps: nobody answered ({len(r['gaps'])})", ""]
            L += [f"- {g.ts[:10]} “{short(g.text, 110)}”" for g in r["gaps"][:12]] + [""]
    return "\n".join(L)


# -------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--days", type=float, default=1)
    ap.add_argument("--tenant", action="append")
    ap.add_argument("--out")
    ap.add_argument("--no-model", action="store_true", help="numbers only; no Bedrock calls")
    ap.add_argument("--write-drafts", action="store_true", help="Tier B: land drafts in the KB table as status=draft")
    ap.add_argument("--apply-triggers", action="store_true", help="Tier A: apply VERIFIED trigger fixes to existing entries and publish")
    ap.add_argument("--include-test-groups", action="store_true",
                    help="include each tenant's test_groups AND let one person play asker/answerer/confirmer there")
    a = ap.parse_args()

    allev = ev_mod.load(a.log)
    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    evs = [e for e in allev if e.when >= cutoff and e.tenant in ev_mod.TENANT_IDS]
    tenants = a.tenant or sorted({e.tenant for e in evs})
    all_test = tuple(g for tid in ev_mod.TENANT_IDS for g in ev_mod.TEST_GROUPS.get(tid, []))
    test_groups = all_test if a.include_test_groups else ()
    if not a.include_test_groups:
        evs = [e for e in evs if e.jid not in all_test]
    window = f"last {a.days:g} day(s) · {len(evs)} events · {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}"
    use_model = not a.no_model
    brain = load_offline_brain() if use_model else None

    results = {}
    for tid in tenants:
        cfg = tenant_cfg(tid)
        r = {"usage": usage(evs, tid), "topics": cluster_requests(evs, tid, use_model),
             "near": near_misses(evs, tid, brain, test_groups) if use_model else [],
             "applied": [], "drafts": [], "declined": [],
             "review": review_flags(evs, tid), "gaps": open_gaps(evs, tid, test_groups)}
        if use_model and a.apply_triggers:
            for n in list(r["near"]):
                ok, msg = apply_trigger_fix(n, tid, brain)
                n["applied"], n["apply_msg"] = ok, msg
                if ok:
                    r["applied"].append(n)
        if use_model:
            existing = [e["id"] for e in tenant_kb(tid)]
            fixed = {id(n["event"]) for n in r["applied"]}   # a thread that just taught an entry needs no new one
            for miss, later in threads_for_drafts(evs, tid, test_groups, unconfirmed=r["declined"]):
                if id(miss) in fixed:
                    r["declined"].append({"miss": miss, "why": "covered by the trigger fix applied above; no new entry needed"})
                    continue
                try:
                    d = draft_from_thread(miss, later, cfg, existing, self_ok=miss.jid in test_groups)
                except Exception as ex:  # noqa: BLE001
                    r["declined"].append({"miss": miss, "why": f"model error {type(ex).__name__}"})
                    continue
                if d.get("verdict") != "draft" or not d.get("entry"):
                    r["declined"].append({"miss": miss, "why": d.get("why", "?")})
                    continue
                entry = d["entry"]
                entry["status"] = "draft"
                own = str(entry.get("owner") or "").strip()
                if not own or re.search(r"\b(ASKER|PEER|SUPPORTER|self)\b", own, re.I):
                    entry["owner"] = cfg.get("kb_owner") or "KB owner"   # a role label must never reach a group
                ok, out = kbcheck_ok(entry, tid)
                rec = {"entry": entry, "why": d.get("why", ""), "miss": miss,
                       "status": "passes kbcheck" if ok else "FAILS kbcheck; not written", "kbcheck": "" if ok else out}
                if ok and a.write_drafts:
                    wrote, msg = write_draft(entry, tid)
                    rec["status"] = f"written as draft ({msg})" if wrote else f"not written: {msg}"
                r["drafts"].append(rec)
        results[tid] = r

    text = render(window, results, a.days)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        drafts = {t: [d["entry"] for d in r["drafts"]] for t, r in results.items() if r["drafts"]}
        if drafts:
            pathlib.Path(a.out).with_suffix(".drafts.json").write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
