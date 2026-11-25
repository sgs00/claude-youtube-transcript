# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit style

Do NOT include `Co-Authored-By: Claude` or any reference to AI tools in commit messages.

# claude-youtube-transcript

AWS Lambda function that extends Claude with YouTube video summarization — a capability natively available in Gemini but missing from Claude. It extracts transcripts and metadata from YouTube videos, exposed via Function URL with Bearer token authentication stored in AWS Secrets Manager.

## Commands

```bash
# Install dependencies (uses uv — do NOT use pip or virtualenv)
uv sync

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_lambda_function.py::test_name -v

# First-time setup: creates IAM role, S3 bucket, OAuth secret, Lambda, Function URL
bash scripts/bootstrap.sh

# Update Lambda code and env vars
bash scripts/deploy.sh

# Tear down all AWS resources (asks for confirmation; --yes skips it).
# Afterwards the Claude connector must be removed and re-added with the new Function URL.
bash scripts/destroy.sh
```

## Architecture

Single-file Lambda handler at `src/lambda_function.py`. The handler:
1. Decodes base64 body if `isBase64Encoded` (Lambda encodes `application/x-www-form-urlencoded` this way)
2. Routes OAuth2 endpoints: `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token`
3. For `POST /`: validates the Bearer token (HMAC-SHA256, signed with secret from Secrets Manager)
4. Dispatches JSON-RPC 2.0 MCP methods: `initialize`, `tools/list`, `tools/call`
5. For `tools/call get_youtube_transcript`: validates the URL, fetches metadata via YouTube oEmbed API and transcript via `youtube-transcript-api` (Webshare residential proxy, credentials from Secrets Manager)
6. For `tools/call get_youtube_playlist`: extracts the `list=` id, lists videos via YouTube Data API v3 (`playlists` + paged `playlistItems`, key from Secrets Manager sent as `X-goog-api-key`). Returns only the video list; Claude then calls `get_youtube_transcript` per video
7. Returns MCP-formatted JSON response

Deployed as a Lambda Function URL (no API Gateway). Auth is OAuth2 Authorization Code + PKCE S256 with refresh tokens; tokens are stateless HMAC blobs (`t` field distinguishes access/refresh) — no database required. `/token` bodies are never logged.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `WEBSHARE_SECRET_NAME` | Secrets Manager secret with Webshare **Residential** proxy credentials, JSON `{"username","password"}`. Effectively required on AWS: YouTube blocks cloud IPs | auto-set by scripts (`<FUNCTION_NAME>-webshare`); empty = proxy disabled |
| `YOUTUBE_API_KEY_SECRET_NAME` | Secrets Manager secret with the YouTube Data API v3 key (plain string), used by `get_youtube_playlist` | auto-set by scripts (`<FUNCTION_NAME>-youtube-api-key`); empty = playlist tool disabled |
| `OAUTH_SECRET_NAME` | Secrets Manager secret name for OAuth signing key | auto-set by scripts |
| `LAMBDA_MEMORY` | Lambda memory in MB | `256` |
| `ACCESS_TOKEN_TTL_HOURS` | Access token TTL in hours (also returned as `expires_in`) | `4` |
| `REFRESH_TOKEN_TTL_DAYS` | Refresh token TTL in days; rotated on every `refresh_token` grant | `30` |

`WEBSHARE_USERNAME` / `WEBSHARE_PASSWORD` and `YOUTUBE_API_KEY` live in `.env` (keep them there) and are read only by `bootstrap.sh` / `deploy.sh`, which use them to create or update the `<FUNCTION_NAME>-webshare` and `<FUNCTION_NAME>-youtube-api-key` secrets (`sync_webshare_secret` / `sync_youtube_api_key_secret` in `scripts/_lib.sh`). They are never passed to Lambda.
