#!/bin/bash
# Ask the brain directly, no WhatsApp involved. Prints the full decision including the note.
#   scripts/ask.sh wakb-brain "my vpn keeps disconnecting"
#   KB_TENANT=office-it scripts/ask.sh wakb-brain "..."   # pick a tenant explicitly (default: the default tenant)
set -euo pipefail
FN="${1:?function name}"; shift
Q="$*"
aws lambda invoke --function-name "$FN" --cli-binary-format raw-in-base64-out \
  --payload "$(python3 -c 'import json,sys; print(json.dumps({"text": sys.argv[1], "jid": "cli@g.us", "participant": "cli@lid", "tenant": sys.argv[2] or None}))' "$Q" "${KB_TENANT:-}")" \
  /dev/stdout --query 'FunctionError' --output text 2>/dev/null | python3 -c '
import json,sys
raw=sys.stdin.read().strip()
body=raw[:raw.rfind("}")+1]
d=json.loads(body)
print(json.dumps(d, indent=2, ensure_ascii=False))'
