#!/usr/bin/env bash
# Tear down all AWS resources created by bootstrap.sh.
# Idempotent — safe to re-run even if resources are already gone.
#
# Usage: bash scripts/destroy.sh
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

# Helper: run a command and ignore "not found" / "does not exist" errors
ok_if_gone() {
  "$@" 2>&1 | grep -v -E \
    "NoSuchEntity|ResourceNotFoundException|ResourceConflictException|Function not found|does not exist" \
    || true
}

echo "==> Removing resource-based policies"
for sid in FunctionURLAllowPublicAccess FunctionURLAllowPublicInvokeFunction; do
  if aws lambda get-policy --function-name "$FUNCTION_NAME" --region "$REGION" \
      --output text --query Policy 2>/dev/null | grep -q "\"$sid\""; then
    aws lambda remove-permission \
      --function-name "$FUNCTION_NAME" \
      --statement-id "$sid" \
      --region "$REGION"
    echo "    removed: $sid"
  else
    echo "    $sid not found, skipping"
  fi
done

echo "==> Deleting Function URL"
if aws lambda get-function-url-config \
    --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  aws lambda delete-function-url-config \
    --function-name "$FUNCTION_NAME" --region "$REGION"
  echo "    deleted"
else
  echo "    not found, skipping"
fi

echo "==> Deleting Lambda function: $FUNCTION_NAME"
if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" &>/dev/null; then
  aws lambda delete-function \
    --function-name "$FUNCTION_NAME" --region "$REGION"
  echo "    deleted"
else
  echo "    not found, skipping"
fi

BASIC_EXEC="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
echo "==> Detaching AWSLambdaBasicExecutionRole"
if aws iam list-attached-role-policies --role-name "$LAMBDA_ROLE_NAME" \
    --query 'AttachedPolicies[].PolicyArn' --output text 2>/dev/null \
    | grep -q "$BASIC_EXEC"; then
  aws iam detach-role-policy \
    --role-name "$LAMBDA_ROLE_NAME" --policy-arn "$BASIC_EXEC"
  echo "    detached"
else
  echo "    not attached or role gone, skipping"
fi

echo "==> Deleting IAM role: $LAMBDA_ROLE_NAME"
if aws iam get-role --role-name "$LAMBDA_ROLE_NAME" &>/dev/null; then
  aws iam delete-role --role-name "$LAMBDA_ROLE_NAME"
  echo "    deleted"
else
  echo "    not found, skipping"
fi

echo
echo "==> Destroy complete."
