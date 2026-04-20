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

# Tear down all AWS resources
bash scripts/destroy.sh
```

## Architecture

Single-file Lambda handler at `src/lambda_function.py`. The handler:
1. Decodes base64 body if `isBase64Encoded` (Lambda encodes `application/x-www-form-urlencoded` this way)
2. Routes OAuth2 endpoints: `/.well-known/oauth-protected-resource`, `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token`
3. For `POST /`: validates the Bearer token (HMAC-SHA256, signed with secret from Secrets Manager)
4. Dispatches JSON-RPC 2.0 MCP methods: `initialize`, `tools/list`, `tools/call`
5. For `tools/call get_youtube_transcript`: validates the URL, fetches metadata via `yt-dlp` and transcript via `youtube-transcript-api`
6. Returns MCP-formatted JSON response

Deployed as a Lambda Function URL (no API Gateway). Auth is OAuth2 Authorization Code + PKCE S256; tokens are stateless HMAC blobs — no database required.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `PROXY_URL` | HTTP proxy for YouTube requests | `` (disabled) |

## Commands

```bash
bash scripts/bootstrap.sh       # first-time: creates IAM role, Lambda, Function URL
bash scripts/deploy.sh          # update code only
bash scripts/destroy.sh         # tear down all resources
```
