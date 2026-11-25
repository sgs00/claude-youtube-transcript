#!/usr/bin/env bash
# Manual smoke test against the deployed Lambda Function URL.
#
# Usage:
#   FUNCTION_URL=https://xxx.lambda-url.eu-south-1.on.aws/ \
#   BEARER_TOKEN=your-token \
#   bash scripts/smoke-test.sh
set -euo pipefail

URL="${FUNCTION_URL:?Set FUNCTION_URL to the Lambda Function URL}"
TOKEN="${BEARER_TOKEN:?Set BEARER_TOKEN to your secret token}"
VIDEO_URL="${TEST_VIDEO_URL:-https://www.youtube.com/watch?v=dQw4w9WgXcQ}"
PLAYLIST_URL="${TEST_PLAYLIST_URL:-https://www.youtube.com/playlist?list=PLjWQg1Pqur_E25ZTyZSK9w0hkQHtW_mSd}"

call() {
  local label="$1"
  local body="$2"
  echo
  echo "==> $label"
  curl -sf \
    -X POST "$URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" | python3 -m json.tool
}

# 1. initialize
call "initialize" '{"jsonrpc":"2.0","method":"initialize","params":{},"id":1}'

# 2. tools/list
call "tools/list" '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}'

# 3. tools/call — get_youtube_transcript
call "tools/call — get_youtube_transcript" \
  "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"get_youtube_transcript\",\"arguments\":{\"url\":\"$VIDEO_URL\"}},\"id\":3}"

# 4. tools/call — get_youtube_playlist
call "tools/call — get_youtube_playlist" \
  "{\"jsonrpc\":\"2.0\",\"method\":\"tools/call\",\"params\":{\"name\":\"get_youtube_playlist\",\"arguments\":{\"url\":\"$PLAYLIST_URL\",\"max_videos\":5}},\"id\":4}"

# 5. auth rejection — wrong token
echo
echo "==> 401 rejection (wrong token)"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$URL" \
  -H "Authorization: Bearer WRONGTOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":5}')
if [ "$HTTP_CODE" = "401" ]; then
  echo "    OK: received 401"
else
  echo "    FAIL: expected 401, got $HTTP_CODE"
  exit 1
fi

echo
echo "==> All smoke tests passed."
