# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commit style

Do NOT include `Co-Authored-By: Claude` or any reference to AI tools in commit messages.

# claude-yt-companion

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
1. Authenticates the request by comparing the `Authorization: Bearer <token>` header against a secret fetched from AWS Secrets Manager (`SECRET_NAME` env var, default: `youtube-transcript/bearer-token`)
2. Extracts the `url` field from the JSON body
3. Fetches video metadata via `yt-dlp`
4. Fetches transcript via `youtube-transcript-api`
5. Returns combined JSON response

Deployed as a Lambda Function URL (no API Gateway). The deploy script in `scripts/deploy.sh` provisions the IAM role, Secrets Manager secret, Lambda function, and Function URL in one pass.

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `SECRET_NAME` | Secrets Manager secret name | `youtube-transcript/bearer-token` |

## Request / Response

```
POST /
Authorization: Bearer <token>
Content-Type: application/json

{ "url": "https://www.youtube.com/watch?v=VIDEO_ID" }
```

Response includes `video_id`, `url`, `metadata` (title, channel, duration, views, description, thumbnail), and `transcript` (array of `{timestamp, start_seconds, duration_seconds, text}` objects).
