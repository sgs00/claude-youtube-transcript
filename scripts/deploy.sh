#!/usr/bin/env bash
# Deploy claude-yt-companion to AWS Lambda via Terraform.
#
# Usage:
#   bash scripts/deploy.sh                  # full terraform init + plan + apply
#   bash scripts/deploy.sh --update-code-only  # re-zip src/ and update Lambda code only
#
# Required env vars for full deploy:
#   TFSTATE_BUCKET   — S3 bucket for Terraform state
#   TFSTATE_TABLE    — DynamoDB table for state locking (default: terraform-state-lock)
#   AWS_DEFAULT_REGION (or set in ~/.aws/config)
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-eu-south-1}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ZIP_FILE="$DIST_DIR/lambda.zip"
SRC_DIR="$REPO_ROOT/src"
VENV_DIR="$REPO_ROOT/.venv"
INFRA_DIR="$REPO_ROOT/infra"

UPDATE_CODE_ONLY=false
for arg in "$@"; do
  [ "$arg" = "--update-code-only" ] && UPDATE_CODE_ONLY=true
done

# ---------------------------------------------------------------------------
# Build deployment package
# ---------------------------------------------------------------------------

build_zip() {
  echo "==> Building Lambda deployment package"
  mkdir -p "$DIST_DIR"

  STAGING=$(mktemp -d)
  trap 'rm -rf "$STAGING"' EXIT

  # Copy application source (no boto3 — provided by Lambda runtime)
  cp "$SRC_DIR/lambda_function.py" "$STAGING/"

  # Copy runtime deps from the uv venv (exclude boto3, botocore, dev tools)
  SITE_PACKAGES=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib', vars={'base': '$VENV_DIR', 'platbase': '$VENV_DIR'}))" 2>/dev/null \
    || find "$VENV_DIR" -type d -name "site-packages" | head -1)

  if [ -z "$SITE_PACKAGES" ] || [ ! -d "$SITE_PACKAGES" ]; then
    echo "ERROR: Could not locate site-packages in $VENV_DIR. Run 'uv sync' first."
    exit 1
  fi

  EXCLUDE_PKGS="boto3 botocore s3transfer jmespath pytest pytest_mock pluggy iniconfig packaging"
  for pkg_dir in "$SITE_PACKAGES"/*/; do
    pkg_name=$(basename "$pkg_dir" | sed 's/-.*//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    skip=false
    for excl in $EXCLUDE_PKGS; do
      [ "$pkg_name" = "$excl" ] && skip=true && break
    done
    $skip || cp -r "$pkg_dir" "$STAGING/"
  done
  # Also copy .dist-info / top-level .py files for deps
  for f in "$SITE_PACKAGES"/*.py "$SITE_PACKAGES"/*.dist-info "$SITE_PACKAGES"/*.data; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    pkg_name=$(echo "$base" | sed 's/-.*//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    skip=false
    for excl in $EXCLUDE_PKGS; do
      [ "$pkg_name" = "$excl" ] && skip=true && break
    done
    $skip || cp -r "$f" "$STAGING/" 2>/dev/null || true
  done

  (cd "$STAGING" && zip -r9q "$ZIP_FILE" .)
  echo "==> Package built: $ZIP_FILE ($(du -sh "$ZIP_FILE" | cut -f1))"
}

# ---------------------------------------------------------------------------
# --update-code-only: skip Terraform, just push new code to existing function
# ---------------------------------------------------------------------------

if $UPDATE_CODE_ONLY; then
  FUNCTION_NAME="${FUNCTION_NAME:-claude-yt-companion}"
  build_zip
  echo "==> Updating Lambda function code: $FUNCTION_NAME"
  aws lambda update-function-code \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file "fileb://$ZIP_FILE" \
    --architectures arm64 \
    --output text --query 'CodeSize'
  echo "==> Code updated."
  exit 0
fi

# ---------------------------------------------------------------------------
# Full deploy via Terraform
# ---------------------------------------------------------------------------

TFSTATE_BUCKET="${TFSTATE_BUCKET:?Set TFSTATE_BUCKET}"
TFSTATE_TABLE="${TFSTATE_TABLE:-terraform-state-lock}"

build_zip

echo "==> Initialising Terraform"
terraform -chdir="$INFRA_DIR" init \
  -backend-config="bucket=$TFSTATE_BUCKET" \
  -backend-config="key=claude-yt-companion/terraform.tfstate" \
  -backend-config="region=$REGION" \
  -backend-config="dynamodb_table=$TFSTATE_TABLE" \
  -backend-config="encrypt=true"

echo "==> Planning"
terraform -chdir="$INFRA_DIR" plan \
  -var="aws_region=$REGION" \
  -var="tfstate_bucket=$TFSTATE_BUCKET" \
  -var="tfstate_table=$TFSTATE_TABLE" \
  -out="$DIST_DIR/tfplan"

echo "==> Applying"
terraform -chdir="$INFRA_DIR" apply "$DIST_DIR/tfplan"

echo
echo "==> Deployment complete."
echo "==> Function URL:"
terraform -chdir="$INFRA_DIR" output -raw function_url
echo
echo
echo "==> Set the Bearer token (first deploy only):"
SECRET_ARN=$(terraform -chdir="$INFRA_DIR" output -raw secret_arn)
echo "    aws secretsmanager put-secret-value \\"
echo "      --secret-id $SECRET_ARN \\"
echo "      --secret-string 'YOUR_BEARER_TOKEN'"
