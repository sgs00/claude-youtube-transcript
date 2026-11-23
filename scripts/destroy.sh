#!/usr/bin/env bash
# Tear down all AWS resources created by bootstrap.sh.
# Idempotent — safe to re-run even if resources are already gone.
#
# WARNING: this deletes the OAuth signing secret and the Function URL. After a new
# bootstrap.sh, the Claude connector must be removed and re-added with the new URL.
#
# Usage: bash scripts/destroy.sh [--yes]
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
DEPLOY_BUCKET="${DEPLOY_BUCKET:-${FUNCTION_NAME}-deploy-$(aws sts get-caller-identity --query Account --output text)}"
SECRET_NAME="${FUNCTION_NAME}-oauth-secret"
WEBSHARE_SECRET_NAME="${FUNCTION_NAME}-webshare"

cat <<MSG
This permanently deletes, in $REGION:
  - Lambda function $FUNCTION_NAME and its Function URL
  - Secrets: $SECRET_NAME (OAuth signing key), $WEBSHARE_SECRET_NAME
  - IAM role $LAMBDA_ROLE_NAME and S3 bucket $DEPLOY_BUCKET

The Claude connector will STOP working. After running bootstrap.sh again, the
Function URL and the OAuth signing key are new: in Claude, remove the connector
and add it again with the new URL (Settings -> Connectors).
The Webshare credentials are kept in .env and re-synced by bootstrap.sh.

MSG
if [ "${1:-}" != "--yes" ]; then
  read -r -p "Type the function name ($FUNCTION_NAME) to confirm: " answer
  if [ "$answer" != "$FUNCTION_NAME" ]; then
    echo "Aborted." >&2
    exit 1
  fi
fi

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

# Force-delete (no recovery window) so a later bootstrap.sh can recreate the same names
for secret in "$SECRET_NAME" "$WEBSHARE_SECRET_NAME"; do
  echo "==> Deleting secret: $secret"
  if aws secretsmanager describe-secret --secret-id "$secret" --region "$REGION" &>/dev/null; then
    aws secretsmanager delete-secret --secret-id "$secret" \
      --force-delete-without-recovery --region "$REGION" --output text --query Name >/dev/null
    echo "    deleted"
  else
    echo "    not found, skipping"
  fi
done

# Inline policies must be removed before the role can be deleted
echo "==> Removing inline IAM policies"
for policy in SecretsManagerOAuthSecret SecretsManagerWebshareSecret; do
  if aws iam get-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-name "$policy" &>/dev/null; then
    aws iam delete-role-policy --role-name "$LAMBDA_ROLE_NAME" --policy-name "$policy"
    echo "    removed: $policy"
  else
    echo "    $policy not found, skipping"
  fi
done

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

echo "==> Deleting S3 deploy bucket: $DEPLOY_BUCKET"
if aws s3api head-bucket --bucket "$DEPLOY_BUCKET" --region "$REGION" &>/dev/null; then
  aws s3 rb "s3://$DEPLOY_BUCKET" --force --region "$REGION" >/dev/null
  echo "    emptied and deleted"
else
  echo "    not found, skipping"
fi

echo
echo "==> Destroy complete."
echo "    Remember: after bootstrap.sh, remove and re-add the Claude connector with the new Function URL."
