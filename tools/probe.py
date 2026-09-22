#!/usr/bin/env python3
"""Run REAL questions through the REAL brain, offline, against a tenant's kb.json snapshot.

No Lambda, no DynamoDB, no WhatsApp: the brain module is imported unchanged (same prompts,
same catalogue, same floor) with the snapshot as its KB and no conversation table, and only
Bedrock is called. Use it to see what the classifier scores before you publish, and to tune
triggers and glosses until every intended question clears the floor and controls stay silent.

    export AWS_PROFILE=... AWS_REGION=eu-west-1
    python3 tools/probe.py "my vpn keeps disconnecting" "docker says the daemon is not running"
    python3 tools/probe.py --tenant office-it "אאוטלוק מבקש להתחבר שוב ושוב"
    python3 tools/probe.py --suite tools/probe-suite.json        # [{"text":..., "expect": "<id>|silent|clarify"}]
    python3 tools/probe.py --suite tools/probe-suite.json --md   # a Markdown table for a report

Exit code is 1 when a suite case misses its expectation. Costs a fraction of a cent per case.
"""
import argparse
import importlib.util
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_brain():
    os.environ.setdefault("KB_TABLE_PREFIX", "")   # snapshot only
    os.environ.setdefault("CONVO_TABLE", "")       # no clarify state: the band shows up as `silent` + suppressed_*
    if not (ROOT / "brain" / "tenants.json").exists():
        subprocess.run(["bash", str(ROOT / "brain" / "build.sh")], check=True, stdout=subprocess.DEVNULL)
    spec = importlib.util.spec_from_file_location("brain_probe", ROOT / "brain" / "lambda_function.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verdict(r):
    """answer <id> | clarify-band <id> <score> | silent (<why>)."""
    if r["outcome"] == "answer":
        return f"answer `{r['id']}` {r['score']}"
    if r.get("suppressed_id") and (r.get("suppressed_score") or 0) >= 0.70:
        return f"clarify-band `{r['suppressed_id']}` {r['suppressed_score']}"
    if r.get("suppressed_id"):
        return f"silent (near miss `{r['suppressed_id']}` {r['suppressed_score']})"
    n = r["note"]
    why = ("not a request" if "not a request" in n else "off-domain" if "off-domain" in n
           else "classifier: none" if "classify none" in n else "silent")
    return f"silent ({why})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--tenant", default=os.environ.get("KB_TENANT", "dev-platform"))
    ap.add_argument("--suite", help="JSON list of {text, expect, tenant?}")
    ap.add_argument("--md", action="store_true", help="print a Markdown table")
    a = ap.parse_args()
    brain = load_brain()
    cases = [{"text": q, "expect": None, "tenant": a.tenant} for q in a.questions]
    if a.suite:
        for c in json.loads(pathlib.Path(a.suite).read_text(encoding="utf-8")):
            cases.append({"text": c["text"], "expect": c.get("expect"), "tenant": c.get("tenant", a.tenant)})
    fails = 0
    rows = []
    for c in cases:
        r = brain.lambda_handler({"text": c["text"], "jid": "probe@g.us", "participant": "probe@lid",
                                  "tenant": c["tenant"]}, None)
        v = verdict(r)
        ok = None
        if c["expect"]:
            exp = c["expect"]
            ok = (v.startswith(f"answer `{exp}`") if exp not in ("silent", "clarify")
                  else v.startswith("silent") if exp == "silent" else v.startswith("clarify-band"))
            fails += 0 if ok else 1
        rows.append((c["tenant"], c["text"], v, "" if ok is None else ("pass" if ok else "FAIL"), r["note"]))
    if a.md:
        print("| tenant | message | result | expected | verdict |\n|---|---|---|---|---|")
        for t, q, v, ok, _n in rows:
            exp = next((c["expect"] for c in cases if c["text"] == q), "") or ""
            print(f"| {t} | {q.replace('|', '/')} | {v} | {exp} | {ok} |")
    else:
        for t, q, v, ok, n in rows:
            print(f"[{t}] {q}\n   -> {v} {ok}\n   {n[:220]}\n")
    if a.suite:
        print(f"{len(cases) - fails}/{len(cases)} as expected")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
