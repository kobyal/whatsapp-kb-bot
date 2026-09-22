#!/bin/bash
# Assemble tenants.json, package the brain, upload it, and create/update the CloudFormation stack.
#
#   infra/cloudformation/deploy.sh <stack-name> <code-bucket> [ParameterKey=Value ...]
#   infra/cloudformation/deploy.sh wakb my-deploy-bucket AllowedGroups="Dev Platform Support"
#   infra/cloudformation/deploy.sh wakb my-deploy-bucket SecondTenant=office-it AllowedGroups="A,B"
#
# The bucket must exist and be in the same region (create one: aws s3 mb s3://my-deploy-bucket).
set -euo pipefail
STACK="${1:?stack name}"; BUCKET="${2:?code bucket}"; shift 2
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUILD="$(mktemp -d)"
"$ROOT/brain/build.sh" "$BUILD/brain.zip"
KEY="brain-$(md5 -q "$BUILD/brain.zip" 2>/dev/null || md5sum "$BUILD/brain.zip" | cut -c1-32).zip"
aws s3 cp --quiet "$BUILD/brain.zip" "s3://$BUCKET/$KEY"
rm -rf "$BUILD"

aws cloudformation deploy \
  --stack-name "$STACK" \
  --template-file "$ROOT/infra/cloudformation/template.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides CodeBucket="$BUCKET" CodeKey="$KEY" "$@"
aws cloudformation describe-stacks --stack-name "$STACK" --query 'Stacks[0].Outputs' --output table
