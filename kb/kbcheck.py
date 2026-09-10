#!/usr/bin/env python3
"""Validate kb/kb.json. Exit 1 on any error.

Run it before every publish. The brain trusts this file blindly, so a malformed entry
here becomes a malformed answer in the chat.
"""
import json
import pathlib
import re
import sys

KB = pathlib.Path(__file__).parent / "kb.json"
REQUIRED = {"id", "category", "status", "triggers", "answer"}
ID_RE = re.compile(r"^[a-z0-9_]+$")


def main():
    kb = json.loads(KB.read_text(encoding="utf-8"))
    errors, warnings, seen = [], [], set()
    for i, e in enumerate(kb.get("entries", [])):
        tag = f"entry[{i}] {e.get('id', '?')}"
        missing = REQUIRED - set(e)
        if missing:
            errors.append(f"{tag}: missing {sorted(missing)}")
            continue
        if not ID_RE.match(e["id"]):
            errors.append(f"{tag}: id must be lowercase snake_case")
        if e["id"] in seen:
            errors.append(f"{tag}: duplicate id")
        seen.add(e["id"])
        if e["status"] not in ("published", "draft"):
            errors.append(f"{tag}: status must be published or draft")
        if len(e["triggers"]) < 2:
            warnings.append(f"{tag}: fewer than 2 triggers; the classifier matches on them")
        if len(e["answer"]) > 1500:
            warnings.append(f"{tag}: answer is {len(e['answer'])} chars; WhatsApp readers skim")
        if not e.get("last_verified"):
            warnings.append(f"{tag}: no last_verified date; stale answers are the #1 failure mode")
    for w in warnings:
        print("WARN ", w)
    for err in errors:
        print("ERROR", err)
    print(f"{len(seen)} entries, {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
