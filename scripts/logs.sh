#!/bin/bash
# Tail the listener log on the instance through SSM Run Command (no SSH).
#   scripts/logs.sh i-0123456789abcdef0 [lines]
set -euo pipefail
IID="${1:?instance id}"; N="${2:-40}"
CMD=$(aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
  --parameters "commands=[\"systemctl is-active wakb wakb-qr; tail -n $N /opt/wakb/data/bot.log\"]" \
  --query Command.CommandId --output text)
sleep 3
aws ssm get-command-invocation --command-id "$CMD" --instance-id "$IID" \
  --query '[StandardOutputContent,StandardErrorContent]' --output text
