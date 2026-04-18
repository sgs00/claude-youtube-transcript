#!/usr/bin/env bash
# One-time setup: creates the S3 bucket and DynamoDB table used for
# Terraform remote state. Safe to re-run (idempotent).
set -euo pipefail

REGION="${AWS_DEFAULT_REGION:-eu-south-1}"
BUCKET="${TFSTATE_BUCKET:?Set TFSTATE_BUCKET to your desired state bucket name}"
TABLE="${TFSTATE_TABLE:-terraform-state-lock}"

echo "==> Bootstrap Terraform state backend"
echo "    Region : $REGION"
echo "    Bucket : $BUCKET"
echo "    Table  : $TABLE"

# --- S3 bucket ---
if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
  echo "==> Bucket $BUCKET already exists, skipping creation"
else
  echo "==> Creating bucket $BUCKET"
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket \
      --bucket "$BUCKET" \
      --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION"
  fi
fi

echo "==> Enabling versioning on $BUCKET"
aws s3api put-bucket-versioning \
  --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled

echo "==> Enabling SSE on $BUCKET"
aws s3api put-bucket-encryption \
  --bucket "$BUCKET" \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
      "BucketKeyEnabled": true
    }]
  }'

echo "==> Blocking public access on $BUCKET"
aws s3api put-public-access-block \
  --bucket "$BUCKET" \
  --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# --- DynamoDB table for state locking ---
if aws dynamodb describe-table --table-name "$TABLE" --region "$REGION" 2>/dev/null; then
  echo "==> DynamoDB table $TABLE already exists, skipping creation"
else
  echo "==> Creating DynamoDB table $TABLE"
  aws dynamodb create-table \
    --table-name "$TABLE" \
    --region "$REGION" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
  echo "==> Waiting for table to become active..."
  aws dynamodb wait table-exists --table-name "$TABLE" --region "$REGION"
fi

echo "==> Bootstrap complete."
echo
echo "Run terraform init with:"
echo "  terraform init \\"
echo "    -backend-config=\"bucket=$BUCKET\" \\"
echo "    -backend-config=\"key=claude-yt-companion/terraform.tfstate\" \\"
echo "    -backend-config=\"region=$REGION\" \\"
echo "    -backend-config=\"dynamodb_table=$TABLE\" \\"
echo "    -backend-config=\"encrypt=true\""
