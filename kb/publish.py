#!/usr/bin/env python3
"""Sync kb/kb.json into the DynamoDB table the brain reads at runtime.

    python3 kb/publish.py --table wakb-kb-entries            # write
    python3 kb/publish.py --table wakb-kb-entries --dry-run  # show the diff only

The brain caches the table for 60 seconds, so an edit is live in the chat within a
minute, with no Lambda redeploy. Entries removed from the file are deleted from the
table so the two never drift apart.
"""
import argparse
import json
import os
import pathlib

import boto3

KB = pathlib.Path(__file__).parent / "kb.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=os.environ.get("KB_TABLE", "wakb-kb-entries"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "eu-west-1"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    entries = {e["id"]: e for e in json.loads(KB.read_text(encoding="utf-8"))["entries"]}
    table = boto3.resource("dynamodb", region_name=a.region).Table(a.table)
    live = {}
    scan = table.scan()
    while True:
        for item in scan["Items"]:
            live[item["id"]] = item
        if "LastEvaluatedKey" not in scan:
            break
        scan = table.scan(ExclusiveStartKey=scan["LastEvaluatedKey"])

    to_put = [e for i, e in entries.items() if live.get(i) != e]
    to_del = [i for i in live if i not in entries]
    for e in to_put:
        print(("would put " if a.dry_run else "put       ") + e["id"])
    for i in to_del:
        print(("would del " if a.dry_run else "del       ") + i)
    if not to_put and not to_del:
        print("all unchanged")
        return
    if a.dry_run:
        return
    with table.batch_writer() as bw:
        for e in to_put:
            bw.put_item(Item=e)
        for i in to_del:
            bw.delete_item(Key={"id": i})
    print(f"done: {len(to_put)} written, {len(to_del)} deleted")


if __name__ == "__main__":
    main()
