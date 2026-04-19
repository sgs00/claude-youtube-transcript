#!/usr/bin/env bash
# One-time setup: creates all AWS resources for claude-youtube-transcript.
# Idempotent — safe to re-run on an already-provisioned environment.
#
# Prerequisites: aws CLI, zip, uv (run 'uv sync' first)
# Usage: bash scripts/bootstrap.sh
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
LAMBDA_ROLE_NAME="${LAMBDA_ROLE_NAME:?LAMBDA_ROLE_NAME not set in .env}"
PROXY_URL="${PROXY_URL:-}"

# shellcheck source=scripts/_lib.sh
source "$SCRIPT_DIR/_lib.sh"

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
TRUST_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

# ---------------------------------------------------------------------------
# 1. IAM role
# ---------------------------------------------------------------------------
echo "==> IAM role: $LAMBDA_ROLE_NAME"
if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" &>/dev/null; then
  echo "    already exists, skipping"
else
  aws iam create-role \
    --role-name "$LAMBDA_ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --output text --query 'Role.RoleId' | xargs echo "    created:"
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${LAMBDA_ROLE_NAME}"

# ---------------------------------------------------------------------------
# 2. Attach AWSLambdaBasicExecutionRole
# ---------------------------------------------------------------------------
BASIC_EXEC="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
echo "==> Attaching AWSLambdaBasicExecutionRole"
if aws iam list-attached-role-policies --role-name "$LAMBDA_ROLE_NAME" \
    --query 'AttachedPolicies[].PolicyArn' --output text | grep -q "$BASIC_EXEC"; then
  echo "    already attached, skipping"
else
  aws iam attach-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-arn "$BASIC_EXEC"
  echo "    attached"
fi

# ---------------------------------------------------------------------------
# 3. Build zip + create Lambda function
# ---------------------------------------------------------------------------
build_zip

echo "==> Lambda function: $FUNCTION_NAME"
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  echo "    already exists, skipping creation"
else
  # IAM role propagation can take a few seconds
  echo "    waiting for IAM role to propagate..."
  sleep 10
  aws lambda create-function \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.13 \
    --architectures arm64 \
    --handler lambda_function.handler \
    --role "$ROLE_ARN" \
    --zip-file "fileb://$ZIP_FILE" \
    --timeout 60 \
    --reserved-concurrent-executions 2 \
    --environment "Variables={PROXY_URL=$PROXY_URL}" \
    --region "$REGION" \
    --output text --query 'FunctionArn' | xargs echo "    created:"
  echo "    waiting for function to become Active..."
  aws lambda wait function-active \
    --function-name "$FUNCTION_NAME" --region "$REGION"
fi

# ---------------------------------------------------------------------------
# 6. Function URL
# ---------------------------------------------------------------------------
echo "==> Function URL"
if aws lambda get-function-url-config \
    --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  echo "    already exists, skipping"
  FUNCTION_URL=$(aws lambda get-function-url-config \
    --function-name "$FUNCTION_NAME" --region "$REGION" \
    --query FunctionUrl --output text)
else
  FUNCTION_URL=$(aws lambda create-function-url-config \
    --function-name "$FUNCTION_NAME" \
    --auth-type NONE \
    --invoke-mode BUFFERED \
    --region "$REGION" \
    --query FunctionUrl --output text)
  echo "    created: $FUNCTION_URL"
fi

# ---------------------------------------------------------------------------
# 7. Resource-based policies for public invocation
# ---------------------------------------------------------------------------
echo "==> Lambda permissions for public Function URL"

add_permission_if_missing() {
  local sid="$1"; shift
  if aws lambda get-policy --function-name "$FUNCTION_NAME" --region "$REGION" \
      --output text --query Policy 2>/dev/null | grep -q "\"$sid\""; then
    echo "    $sid already exists, skipping"
  else
    aws lambda add-permission "$@"
    echo "    $sid added"
  fi
}

add_permission_if_missing "FunctionURLAllowPublicAccess" \
  --function-name "$FUNCTION_NAME" \
  --statement-id "FunctionURLAllowPublicAccess" \
  --action "lambda:InvokeFunctionUrl" \
  --principal "*" \
  --function-url-auth-type NONE \
  --region "$REGION"

add_permission_if_missing "FunctionURLAllowPublicInvokeFunction" \
  --function-name "$FUNCTION_NAME" \
  --statement-id "FunctionURLAllowPublicInvokeFunction" \
  --action "lambda:InvokeFunction" \
  --principal "*" \
  --region "$REGION"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo
echo "==> Bootstrap complete!"
echo
echo "    Function URL: $FUNCTION_URL"
