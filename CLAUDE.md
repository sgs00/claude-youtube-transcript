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

# Deploy (first-time: creates IAM role, secret, function, function URL)
bash scripts/deploy.sh

# Update Lambda code only
bash scripts/deploy.sh --update-code-only
```

## Architecture

Single-file Lambda handler at `src/lambda_function.py`. The handler:
1. Validates the request method (POST to `/` only)
2. Dispatches JSON-RPC 2.0 MCP methods: `initialize`, `tools/list`, `tools/call`
3. For `tools/call get_youtube_transcript`: validates the URL, fetches metadata via `yt-dlp` and transcript via `youtube-transcript-api`
4. Returns MCP-formatted JSON response

Deployed as a Lambda Function URL (no API Gateway). Auth is currently absent (testing phase) — OAuth2 is planned.

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
