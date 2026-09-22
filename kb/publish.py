#!/usr/bin/env python3
"""Sync a tenant's kb.json into the DynamoDB table the brain reads at runtime.

    python3 kb/publish.py                                   # tenants/dev-platform -> wakb-kb-dev-platform
    KB_TENANT=office-it python3 kb/publish.py --dry-run     # show the diff only
    python3 kb/publish.py --table my-table                  # override the table name

The table name is `<prefix><tenant id>` (prefix from --table-prefix / KB_TABLE_PREFIX,
default `wakb-kb-`), or `kb_table` in tenant.json if set. The brain resolves it the same way.

The brain caches the table for 60 seconds, so an edit is live in the chat within a minute,
with no Lambda redeploy. Entries removed from the file are deleted from the table so the two
never drift apart, EXCEPT drafts (status=draft) that exist only in the table: those are the
curator's proposals waiting for a human, and are reported rather than deleted.
"""
import argparse
import json
import os
import pathlib
import sys

import boto3

ROOT = pathlib.Path(__file__).resolve().parent.parent
TENANT = os.environ.get("KB_TENANT", "dev-platform")


def table_name(tenant_id, prefix, override=None):
    if override:
        return override
    cfg = json.loads((ROOT / "tenants" / tenant_id / "tenant.json").read_text(encoding="utf-8"))
    return cfg.get("kb_table") or f"{prefix}{tenant_id}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=TENANT)
    ap.add_argument("--table", default=None)
    ap.add_argument("--table-prefix", default=os.environ.get("KB_TABLE_PREFIX", "wakb-kb-"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "eu-west-1"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    kb_path = ROOT / "tenants" / a.tenant / "kb.json"
    entries = {e["id"]: e for e in json.loads(kb_path.read_text(encoding="utf-8"))["entries"]}
    name = table_name(a.tenant, a.table_prefix, a.table)
    table = boto3.resource("dynamodb", region_name=a.region).Table(name)
    live, scan = {}, table.scan()
    while True:
        for item in scan["Items"]:
            live[item["id"]] = item
        if "LastEvaluatedKey" not in scan:
            break
        scan = table.scan(ExclusiveStartKey=scan["LastEvaluatedKey"])

    to_put = [e for i, e in entries.items() if live.get(i) != e]
    to_del = [i for i in live if i not in entries and live[i].get("status") != "draft"]
    drafts = [i for i in live if i not in entries and live[i].get("status") == "draft"]
    verb = "would " if a.dry_run else ""
    for e in to_put:
        print(f"{verb}put  {e['id']}")
    for i in to_del:
        print(f"{verb}del  {i}")
    for i in drafts:
        print(f"draft in table, not in file (left alone): {i}")
    if not to_put and not to_del:
        print(f"{name}: all unchanged")
        return
    if a.dry_run:
        return
    with table.batch_writer() as bw:
        for e in to_put:
            bw.put_item(Item=e)
        for i in to_del:
            bw.delete_item(Key={"id": i})
    print(f"{name}: {len(to_put)} written, {len(to_del)} deleted")


if __name__ == "__main__":
    sys.exit(main())
