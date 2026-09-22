#!/usr/bin/env python3
"""Pull the listener's bot.log off the EC2 instance over SSM, without touching the bot.

SSM caps a command's captured output at 24,000 characters, so the file comes down in
gzip+base64 slices addressed by line range. No agent, no shipper, no new process on the box:
this is a read, and the bot cannot tell it happened.

    python3 curator/fetch_log.py --instance i-0123456789abcdef0 --out /tmp/bot.log
    LISTENER_INSTANCE=i-... python3 curator/fetch_log.py --out /tmp/bot.log
"""
from __future__ import annotations
import argparse
import base64
import gzip
import os
import subprocess
import sys
import time

LOG = os.environ.get("LISTENER_LOG", "/opt/wakb/data/bot.log")
SLICE = 600           # lines per slice; ~24k of base64 gzip is comfortably above this


def _ssm(instance: str, cmd: str) -> str:
    cid = subprocess.check_output([
        "aws", "ssm", "send-command", "--instance-ids", instance, "--document-name", "AWS-RunShellScript",
        "--parameters", f'commands=["{cmd}"]', "--query", "Command.CommandId", "--output", "text"], text=True).strip()
    st = "Pending"
    for _ in range(40):
        time.sleep(1.5)
        st = subprocess.check_output([
            "aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", instance,
            "--query", "Status", "--output", "text"], text=True).strip()
        if st in ("Success", "Failed", "Cancelled", "TimedOut"):
            break
    if st != "Success":
        raise SystemExit(f"ssm {st}: {cmd[:80]}")
    return subprocess.check_output([
        "aws", "ssm", "get-command-invocation", "--command-id", cid, "--instance-id", instance,
        "--query", "StandardOutputContent", "--output", "text"], text=True)


def fetch(instance: str) -> str:
    total = int(_ssm(instance, f"wc -l < {LOG}").strip())
    parts = []
    for start in range(1, total + 1, SLICE):
        end = min(start + SLICE - 1, total)
        b64 = _ssm(instance, f"sed -n {start},{end}p {LOG} | gzip -c | base64 -w0").replace("\n", "")
        parts.append(gzip.decompress(base64.b64decode(b64)).decode("utf-8", "replace"))
        print(f"  {end}/{total} lines", file=sys.stderr)
    return "".join(parts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default=os.environ.get("LISTENER_INSTANCE"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if not a.instance:
        raise SystemExit("--instance or LISTENER_INSTANCE is required")
    text = fetch(a.instance)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {a.out}: {text.count(chr(10))} lines")
