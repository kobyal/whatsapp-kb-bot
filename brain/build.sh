#!/bin/bash
# Assemble brain/tenants.json from tenants/*/tenant.json + tenants/*/kb.json and zip the brain.
# tenants.json is a build artefact (gitignored); the sources of truth are the files under
# tenants/. Terraform does the same assembly in HCL (infra/terraform/lambda.tf); this script
# is for the CloudFormation flavour, for running the brain offline, and for the tests.
#
#   brain/build.sh                 # writes brain/tenants.json only
#   brain/build.sh out/brain.zip   # ...and zips lambda_function.py + tenants.json
#   DEFAULT_TENANT=office-it brain/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
OUT="${1:-}"
python3 - "$REPO" "$HERE/tenants.json" "${DEFAULT_TENANT:-}" <<'PY'
import json, pathlib, sys
repo, out, default = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
tenants, groups = {}, {}
for d in sorted((repo / "tenants").iterdir()):
    cfg_p, kb_p = d / "tenant.json", d / "kb.json"
    if not cfg_p.exists():
        continue
    cfg = json.loads(cfg_p.read_text(encoding="utf-8"))
    assert cfg["id"] == d.name, f"{cfg_p}: id {cfg['id']!r} != folder {d.name!r}"
    kb = json.loads(kb_p.read_text(encoding="utf-8")) if kb_p.exists() else {"entries": []}
    cfg["snapshot"] = kb.get("entries", [])
    for g in cfg.get("groups") or []:
        assert g not in groups, f"group {g} claimed by both {groups[g]} and {cfg['id']}"
        groups[g] = cfg["id"]
    tenants[cfg["id"]] = cfg
assert tenants, "no tenants/<id>/tenant.json found"
default = default or ("dev-platform" if "dev-platform" in tenants else sorted(tenants)[0])
assert default in tenants, f"default tenant {default!r} is not one of {sorted(tenants)}"
out.write_text(json.dumps({"default": default, "tenants": tenants}, ensure_ascii=False, indent=1) + "\n",
               encoding="utf-8")
print("tenants.json: default=%s; %s" % (default, ", ".join(
    f"{k} ({len(v['snapshot'])} entries, {len(v.get('groups') or [])} groups)" for k, v in tenants.items())))
PY
if [ -n "$OUT" ]; then
  mkdir -p "$(dirname "$OUT")"; rm -f "$OUT"
  ( cd "$HERE" && zip -q -j "$OUT" lambda_function.py tenants.json )
  echo "zip: $OUT ($(du -k "$OUT" | cut -f1) KB)"
fi
