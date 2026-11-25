#!/usr/bin/env bash
# Update Lambda code, environment variables and the Webshare proxy secret.
# Requires the function to already exist (run bootstrap.sh first).
#
# Prerequisites: aws CLI, zip, uv (run 'uv sync' first)
# Usage: bash scripts/deploy.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load config
if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "ERROR: .env not found. Copy .env.example to .env and fill in values." >&2
  exit 1
fi
# shellcheck source=../.env
set -o allexport; source "$REPO_ROOT/.env"; set +o allexport

REGION="${AWS_DEFAULT_REGION:-eu-south-1}"
FUNCTION_NAME="${FUNCTION_NAME:?FUNCTION_NAME not set in .env}"
LAMBDA_MEMORY="${LAMBDA_MEMORY:-256}"
ACCESS_TOKEN_TTL_HOURS="${ACCESS_TOKEN_TTL_HOURS:-720}"
REFRESH_TOKEN_TTL_DAYS="${REFRESH_TOKEN_TTL_DAYS:-365}"
DEPLOY_BUCKET="${DEPLOY_BUCKET:-${FUNCTION_NAME}-deploy-$(aws sts get-caller-identity --query Account --output text)}"
SECRET_NAME="${FUNCTION_NAME}-oauth-secret"
WEBSHARE_SECRET_NAME="${FUNCTION_NAME}-webshare"

# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/_lib.sh"

# ---------------------------------------------------------------------------
# Webshare proxy secret (from WEBSHARE_* in .env) + IAM policy
# ---------------------------------------------------------------------------
sync_webshare_secret
ROLE_NAME=$(aws lambda get-function-configuration --function-name "$FUNCTION_NAME" \
  --region "$REGION" --query Role --output text | sed 's#.*/##')
grant_webshare_secret_access "$ROLE_NAME"
WEBSHARE_SECRET_ENV=""
[ -n "$WEBSHARE_SECRET_ARN" ] && WEBSHARE_SECRET_ENV="$WEBSHARE_SECRET_NAME"

# ---------------------------------------------------------------------------
# Build + upload code
# ---------------------------------------------------------------------------
build_zip

echo "==> Uploading package to s3://$DEPLOY_BUCKET/$S3_KEY"
aws s3 cp "$ZIP_FILE" "s3://$DEPLOY_BUCKET/$S3_KEY" --region "$REGION"

echo "==> Updating Lambda function code: $FUNCTION_NAME"
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --s3-bucket "$DEPLOY_BUCKET" \
  --s3-key "$S3_KEY" \
  --architectures arm64 \
  --region "$REGION" \
  --output text --query 'CodeSize' | xargs -I{} echo "    code size: {} bytes"

aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" --region "$REGION"

# ---------------------------------------------------------------------------
# Sync environment variables
# ---------------------------------------------------------------------------
echo "==> Updating configuration (memory: ${LAMBDA_MEMORY}MB)"
aws lambda update-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --memory-size "$LAMBDA_MEMORY" \
  --environment "Variables={WEBSHARE_SECRET_NAME=$WEBSHARE_SECRET_ENV,OAUTH_SECRET_NAME=$SECRET_NAME,ACCESS_TOKEN_TTL_HOURS=$ACCESS_TOKEN_TTL_HOURS,REFRESH_TOKEN_TTL_DAYS=$REFRESH_TOKEN_TTL_DAYS}" \
  --region "$REGION" \
  --output text --query 'LastModified' | xargs echo "    updated:"

echo "==> Deploy complete."
