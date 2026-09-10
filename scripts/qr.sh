#!/bin/bash
# Port-forward the QR page from the instance to http://localhost:8090 through SSM.
# Nothing is exposed on the internet; the page is bound to 127.0.0.1 on the box.
#   scripts/qr.sh i-0123456789abcdef0
set -euo pipefail
IID="${1:?instance id}"
echo "open http://localhost:8090 and scan with the bot phone (WhatsApp > Linked devices)"
aws ssm start-session --target "$IID" --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["8090"]}'
