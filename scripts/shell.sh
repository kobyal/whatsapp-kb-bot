#!/bin/bash
# Interactive shell on the instance through SSM Session Manager.
set -euo pipefail
aws ssm start-session --target "${1:?instance id}"
