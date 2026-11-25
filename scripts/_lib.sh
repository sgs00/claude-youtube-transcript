#!/usr/bin/env bash
# Shared helpers sourced by bootstrap.sh and deploy.sh.
# Not meant to be executed directly.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ZIP_FILE="$DIST_DIR/lambda.zip"
S3_KEY="lambda.zip"
SRC_DIR="$REPO_ROOT/src"
VENV_DIR="$REPO_ROOT/.venv"

build_zip() {
  echo "==> Building Lambda deployment package"
  mkdir -p "$DIST_DIR"

  STAGING=$(mktemp -d)
  trap 'rm -rf "$STAGING"' EXIT

  cp "$SRC_DIR/lambda_function.py" "$STAGING/"

  SITE_PACKAGES=$("$VENV_DIR/bin/python" -c "import sysconfig; print(sysconfig.get_path('purelib'))" 2>/dev/null \
    || find "$VENV_DIR" -type d -name "site-packages" | head -1)

  if [ -z "$SITE_PACKAGES" ] || [ ! -d "$SITE_PACKAGES" ]; then
    echo "ERROR: Could not locate site-packages in $VENV_DIR. Run 'uv sync' first." >&2
    exit 1
  fi

  # Exclude packages provided by the Lambda runtime or only needed for dev
  EXCLUDE_PKGS="boto3 botocore s3transfer jmespath pytest pytest_mock pluggy iniconfig packaging"

  for pkg_dir in "$SITE_PACKAGES"/*/; do
    pkg_name=$(basename "$pkg_dir" | sed 's/-.*//' | tr '[:upper:]' '[:lower:]' | tr '-' '_')
    skip=false
    for excl in $EXCLUDE_PKGS; do
      [ "$pkg_name" = "$excl" ] && skip=true && break
    done
    $skip || cp -r "$pkg_dir" "$STAGING/"
  done

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

# Create or update the Webshare proxy secret from WEBSHARE_USERNAME / WEBSHARE_PASSWORD (.env).
# The secret is a JSON object {"username": ..., "password": ...}.
# The credentials are meant to stay in .env; they are read only by bootstrap.sh / deploy.sh
# and never passed to the Lambda. If both are empty, an existing secret is left untouched.
# Requires: REGION, WEBSHARE_SECRET_NAME. Sets: WEBSHARE_SECRET_ARN (empty if no secret).
sync_webshare_secret() {
  local user="${WEBSHARE_USERNAME:-}" pass="${WEBSHARE_PASSWORD:-}"
  WEBSHARE_SECRET_ARN=""

  echo "==> Webshare proxy secret: $WEBSHARE_SECRET_NAME"
  if { [ -n "$user" ] && [ -z "$pass" ]; } || { [ -z "$user" ] && [ -n "$pass" ]; }; then
    echo "ERROR: set both WEBSHARE_USERNAME and WEBSHARE_PASSWORD in .env, or neither." >&2
    exit 1
  fi

  local exists=false
  if aws secretsmanager describe-secret --secret-id "$WEBSHARE_SECRET_NAME" --region "$REGION" &>/dev/null; then
    exists=true
  fi

  if [ -n "$user" ]; then
    local desired current tmp
    desired=$(WS_USER="$user" WS_PASS="$pass" "$VENV_DIR/bin/python" -c \
      'import json, os; print(json.dumps({"username": os.environ["WS_USER"], "password": os.environ["WS_PASS"]}))')
    # Pass the value via a 0600 temp file so it never appears in the process list
    tmp=$(mktemp)
    printf '%s' "$desired" > "$tmp"
    if $exists; then
      current=$(aws secretsmanager get-secret-value --secret-id "$WEBSHARE_SECRET_NAME" \
        --region "$REGION" --query SecretString --output text 2>/dev/null || true)
      if [ "$current" = "$desired" ]; then
        echo "    up to date"
      else
        aws secretsmanager put-secret-value --secret-id "$WEBSHARE_SECRET_NAME" \
          --secret-string "file://$tmp" --region "$REGION" --output text --query VersionId >/dev/null
        echo "    updated from .env"
      fi
    else
      aws secretsmanager create-secret --name "$WEBSHARE_SECRET_NAME" \
        --secret-string "file://$tmp" --region "$REGION" --output text --query ARN >/dev/null
      echo "    created from .env"
      exists=true
    fi
    rm -f "$tmp"
  elif $exists; then
    echo "    WARNING: WEBSHARE_* not set in .env, keeping existing secret unchanged" >&2
  else
    echo "    WARNING: no secret and no WEBSHARE_* credentials in .env: proxy disabled," >&2
    echo "    transcript fetches from AWS will likely be blocked by YouTube." >&2
  fi

  if $exists; then
    WEBSHARE_SECRET_ARN=$(aws secretsmanager describe-secret \
      --secret-id "$WEBSHARE_SECRET_NAME" --region "$REGION" --query ARN --output text)
  fi
}

# Grant the Lambda role read access to one secret via an inline policy.
# Usage: grant_secret_read_access <role-name> <policy-name> <secret-arn>
grant_secret_read_access() {
  aws iam put-role-policy \
    --role-name "$1" \
    --policy-name "$2" \
    --policy-document "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Effect\": \"Allow\",
        \"Action\": \"secretsmanager:GetSecretValue\",
        \"Resource\": \"$3\"
      }]
    }"
  echo "    policy attached"
}

# Grant the Lambda role read access to the Webshare secret (no-op if there is no secret).
# Usage: grant_webshare_secret_access <role-name>
grant_webshare_secret_access() {
  [ -n "${WEBSHARE_SECRET_ARN:-}" ] || return 0
  echo "==> IAM: grant Lambda read access to Webshare secret"
  grant_secret_read_access "$1" "SecretsManagerWebshareSecret" "$WEBSHARE_SECRET_ARN"
}

# Create or update the YouTube Data API key secret from YOUTUBE_API_KEY (.env).
# The secret holds the key as a plain string. Like the Webshare credentials, the key stays
# in .env and is never passed to the Lambda. If it is empty, an existing secret is left untouched.
# Requires: REGION, YOUTUBE_API_KEY_SECRET_NAME. Sets: YOUTUBE_API_KEY_SECRET_ARN (empty if no secret).
sync_youtube_api_key_secret() {
  local key="${YOUTUBE_API_KEY:-}"
  YOUTUBE_API_KEY_SECRET_ARN=""

  echo "==> YouTube Data API key secret: $YOUTUBE_API_KEY_SECRET_NAME"
  local exists=false
  if aws secretsmanager describe-secret --secret-id "$YOUTUBE_API_KEY_SECRET_NAME" --region "$REGION" &>/dev/null; then
    exists=true
  fi

  if [ -n "$key" ]; then
    local current tmp
    # Pass the value via a 0600 temp file so it never appears in the process list
    tmp=$(mktemp)
    printf '%s' "$key" > "$tmp"
    if $exists; then
      current=$(aws secretsmanager get-secret-value --secret-id "$YOUTUBE_API_KEY_SECRET_NAME" \
        --region "$REGION" --query SecretString --output text 2>/dev/null || true)
      if [ "$current" = "$key" ]; then
        echo "    up to date"
      else
        aws secretsmanager put-secret-value --secret-id "$YOUTUBE_API_KEY_SECRET_NAME" \
          --secret-string "file://$tmp" --region "$REGION" --output text --query VersionId >/dev/null
        echo "    updated from .env"
      fi
    else
      aws secretsmanager create-secret --name "$YOUTUBE_API_KEY_SECRET_NAME" \
        --secret-string "file://$tmp" --region "$REGION" --output text --query ARN >/dev/null
      echo "    created from .env"
      exists=true
    fi
    rm -f "$tmp"
  elif $exists; then
    echo "    WARNING: YOUTUBE_API_KEY not set in .env, keeping existing secret unchanged" >&2
  else
    echo "    WARNING: no secret and no YOUTUBE_API_KEY in .env: the playlist tool is disabled." >&2
  fi

  if $exists; then
    YOUTUBE_API_KEY_SECRET_ARN=$(aws secretsmanager describe-secret \
      --secret-id "$YOUTUBE_API_KEY_SECRET_NAME" --region "$REGION" --query ARN --output text)
  fi
}

# Grant the Lambda role read access to the YouTube API key secret (no-op if there is no secret).
# Usage: grant_youtube_api_key_secret_access <role-name>
grant_youtube_api_key_secret_access() {
  [ -n "${YOUTUBE_API_KEY_SECRET_ARN:-}" ] || return 0
  echo "==> IAM: grant Lambda read access to YouTube API key secret"
  grant_secret_read_access "$1" "SecretsManagerYouTubeApiKeySecret" "$YOUTUBE_API_KEY_SECRET_ARN"
}
