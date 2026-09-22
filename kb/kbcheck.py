#!/usr/bin/env python3
"""Validate a tenant's knowledge base. Exit 1 on any error (and on warnings with --warnings).

    python3 kb/kbcheck.py                       # tenants/dev-platform/kb.json (the default tenant)
    KB_TENANT=office-it python3 kb/kbcheck.py   # another tenant
    python3 kb/kbcheck.py --warnings            # fail on advisory warnings too (CI does this)
    python3 kb/kbcheck.py --kb some/file.json   # any file, e.g. a curator draft

Run it before every publish. The brain trusts this file blindly, so a malformed entry here
becomes a malformed answer in the chat. Rule ids (R*) are stable so tooling can grep them.
"""
import argparse
import json
import os
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
TENANT = os.environ.get("KB_TENANT", "dev-platform")
KB = ROOT / "tenants" / TENANT / "kb.json"

REQUIRED = {"id", "category", "status", "triggers", "answer", "last_verified"}
ID_RE = re.compile(r"^[a-z0-9_]{3,64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
BIDI = {0x200E, 0x200F, 0x2066, 0x2067, 0x2068, 0x2069, 0x061C,
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E}
MAX_LINE = 160          # WhatsApp readers skim; the brain adds RTL marks per line
MAX_ANSWER = 1500
GLOSS = 130             # the classifier sees only this many chars of the answer
VISIBLE_TRIGGERS = 6    # and only this many triggers


def check_entry(e, err, warn):
    eid = e.get("id", "<no id>")
    missing = REQUIRED - set(e)
    if missing:
        err(eid, "R0", f"missing {sorted(missing)}")
        return
    if not isinstance(eid, str) or not ID_RE.match(eid):
        err(eid, "R0", "id must match ^[a-z0-9_]{3,64}$")
    if e["status"] not in ("published", "draft"):
        err(eid, "R0", "status must be published or draft")
    if not DATE_RE.match(str(e.get("last_verified") or "")):
        err(eid, "R0", "last_verified must be YYYY-MM-DD; stale answers are the #1 failure mode")
    for field in ("triggers", "error_strings"):
        v = e.get(field, [])
        if not isinstance(v, list) or any(not isinstance(s, str) or not s.strip() for s in v):
            err(eid, "R0", f"{field} must be a list of non-empty strings")
    trig = e.get("triggers") or []
    if len(trig) < 3:
        warn(eid, "R9", f"only {len(trig)} triggers; the classifier matches on them, give it 4-6")
    # R15: the classifier reads only the first six triggers, so the rest are dead weight and,
    # worse, an author who adds the good phrasing at position 9 believes it is live.
    for field in ("triggers", "triggers_he"):
        extra = (e.get(field) or [])[VISIBLE_TRIGGERS:] if isinstance(e.get(field), list) else []
        if extra:
            warn(eid, "R15", f"{field} at position {VISIBLE_TRIGGERS + 1}+ are invisible to the classifier "
                             f"(only the first six are read): {extra}")
    for field in ("source", "verified_against"):
        if not str(e.get(field) or "").strip():
            warn(eid, "R10", f"{field} is empty; an unattributed answer is hard to trust or to fix")

    ans = e["answer"]
    if not isinstance(ans, str) or not ans.strip():
        err(eid, "R0", "answer is empty")
        return
    lines = ans.split("\n")
    gloss = lines[0].strip()
    if len(gloss) < 15:
        warn(eid, "R12", f"first line is {len(gloss)} chars; the classifier reads only the first "
                         f"{GLOSS} chars of the answer, so the first line should name the subject")

    # ---- formatting WhatsApp will get wrong ------------------------------------------
    if "**" in ans:
        err(eid, "R1", "contains '**'; WhatsApp bold is a single '*'")
    if ans.count("*") % 2:
        warn(eid, "R1", "odd number of '*'; one bold marker is unclosed")
    if "```" in ans:
        err(eid, "R5", "triple-backtick block; WhatsApp renders it as a monospace wall, use `spans`")
    found = sorted({hex(ord(c)) for c in ans if ord(c) in BIDI})
    if found:
        err(eid, "R2", f"contains bidi control chars {found}; the brain adds these itself")
    if "\n\n\n" in ans:
        err(eid, "R6", "two or more consecutive blank lines")
    if len(ans) > MAX_ANSWER:
        warn(eid, "R11", f"answer is {len(ans)} chars, over the {MAX_ANSWER} soft cap")
    for n, line in enumerate(lines, 1):
        if len(line) > MAX_LINE:
            err(eid, "R6", f"line {n} is {len(line)} chars, over {MAX_LINE}")
        # R14: WhatsApp honours *bold* only when the opening asterisk starts a word. A letter
        # glued to it (a Hebrew one-letter prefix is the usual case: `ב*שורת המשימות*`) kills
        # the markup and the reader sees the literal asterisks. Asterisks pair per line, so the
        # 1st, 3rd, 5th... are the openers; an unbalanced line is R1's business, not this rule's.
        pos = [i for i, c in enumerate(line) if c == "*"]
        if len(pos) % 2:
            continue
        for k, i in enumerate(pos):
            if k % 2 == 0 and i > 0 and (line[i - 1].isalnum() or line[i - 1] == "-"):
                err(eid, "R14", f"line {n}: bold opener glued to {line[i - 1]!r}; WhatsApp will "
                                f"print the asterisks instead of bolding")


def check_kb(entries):
    """(errors, warnings) as lists of (id, rule, message)."""
    errors, warns = [], []
    err = lambda i, r, m: errors.append((i, r, m))   # noqa: E731
    warn = lambda i, r, m: warns.append((i, r, m))   # noqa: E731
    ids = [e.get("id") for e in entries]
    for i in {i for i in ids if ids.count(i) > 1}:
        err(i, "R0", "duplicate id")
    for e in entries:
        check_entry(e, err, warn)
    # A trigger or error string shared by two entries is a coin flip for the classifier.
    owners = defaultdict(list)
    for e in entries:
        for field in ("triggers", "error_strings"):
            for s in e.get(field) or []:
                if isinstance(s, str):
                    owners[(field, re.sub(r"\s+", " ", s.strip().lower()))].append(e.get("id"))
    for (field, s), ids in sorted(owners.items()):
        if len(ids) > 1:
            err(ids[0], "R8", f"{field} {s!r} is shared with {', '.join(ids[1:])}")
    return errors, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default=str(KB))
    ap.add_argument("--warnings", action="store_true", help="fail on advisory warnings too")
    a = ap.parse_args()
    entries = json.loads(pathlib.Path(a.kb).read_text(encoding="utf-8")).get("entries", [])
    errors, warns = check_kb(entries)
    for eid, rule, msg in errors:
        print(f"ERROR [{rule}] {eid}: {msg}")
    for eid, rule, msg in warns:
        print(f"warn  [{rule}] {eid}: {msg}")
    print(f"{a.kb}: {len(entries)} entries, {len(errors)} errors, {len(warns)} warnings")
    sys.exit(1 if errors or (a.warnings and warns) else 0)


if __name__ == "__main__":
    main()
