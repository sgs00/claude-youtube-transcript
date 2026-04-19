#!/usr/bin/env bash
# Update Lambda code and environment variables.
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
PROXY_URL="${PROXY_URL:-}"

# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/_lib.sh"

# ---------------------------------------------------------------------------
# Build + upload code
# ---------------------------------------------------------------------------
build_zip

echo "==> Updating Lambda function code: $FUNCTION_NAME"
aws lambda update-function-code \
  --function-name "$FUNCTION_NAME" \
  --zip-file "fileb://$ZIP_FILE" \
  --architectures arm64 \
  --region "$REGION" \
  --output text --query 'CodeSize' | xargs -I{} echo "    code size: {} bytes"

aws lambda wait function-updated \
  --function-name "$FUNCTION_NAME" --region "$REGION"

# ---------------------------------------------------------------------------
# Sync environment variables
# ---------------------------------------------------------------------------
echo "==> Updating environment variables"
aws lambda update-function-configuration \
  --function-name "$FUNCTION_NAME" \
  --environment "Variables={PROXY_URL=$PROXY_URL}" \
  --region "$REGION" \
  --output text --query 'LastModified' | xargs echo "    updated:"

echo "==> Deploy complete."
