#!/usr/bin/env bash
# Shared helpers sourced by bootstrap.sh and deploy.sh.
# Not meant to be executed directly.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ZIP_FILE="$DIST_DIR/lambda.zip"
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
