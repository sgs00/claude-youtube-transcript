# SPEC.md — claude-youtube-transcript

## 1. Objective

Extend Claude Web with the ability to read YouTube videos (transcript + metadata) via a remote MCP server hosted on AWS Lambda. The user pastes a YouTube URL in Claude Web; Claude calls the `get_youtube_transcript` MCP tool and uses the result as context for Q&A and brainstorming.

**Target user**: single operator (personal use). Code will be open-sourced so others can replicate the setup.

---

## 2. Architecture

```
Claude Web
  └─ MCP (Streamable HTTP over HTTPS)
       └─ Lambda Function URL   (eu-south-1, buffered)
            ├─ Auth: OAuth2 (planned; currently unauthenticated for testing)
            ├─ yt-dlp           → video metadata
            └─ youtube-transcript-api → transcript (all languages)
```

### MCP transport
Claude Web remote MCP uses the **Streamable HTTP** transport (JSON-RPC 2.0 over HTTPS POST, spec 2025-03-26). For `tools/call`, the response is a single JSON object — Lambda buffered response mode is sufficient. The old HTTP+SSE transport is deprecated since April 2026 and must not be used.

### MCP tools exposed (Phase 1)
| Tool | Input | Output |
|---|---|---|
| `get_youtube_transcript` | `url: string` | metadata + full transcript |

Phase 2 (out of scope now): optional pre-summarization via Claude API for very long videos.

---

## 3. Project structure

```
claude-youtube-transcript/
├── src/
│   └── lambda_function.py       # MCP handler + YouTube extraction
├── scripts/
│   ├── bootstrap.sh             # One-time: creates IAM role, Lambda, Function URL
│   ├── deploy.sh                # Updates Lambda code (zip + update-function-code)
│   └── destroy.sh               # Tears down all AWS resources
├── tests/
│   └── test_lambda_function.py
├── .env                         # Local config (not versioned)
├── .env.example                 # Template with example values (versioned)
├── pyproject.toml               # uv-managed dependencies
├── SPEC.md                      # This file
└── CLAUDE.md                    # Claude Code guidance
```

No Terraform, no CloudFormation, no S3 state backend. Infrastructure is managed exclusively via AWS CLI in the scripts above.

---

## 4. Configuration — .env

All operator-specific values live in `.env` (gitignored). Scripts source it at startup.

`.env.example` (versioned) documents every variable with placeholder values:

```dotenv
# AWS
AWS_DEFAULT_REGION=eu-south-1

# Lambda
FUNCTION_NAME=claude-youtube-transcript
LAMBDA_ROLE_NAME=claude-youtube-transcript-exec

# Proxy (optional — leave empty to disable)
PROXY_URL=
```

---

## 5. Infrastructure scripts (AWS CLI, eu-south-1)

All three scripts must be **idempotent**: re-running them on an already-provisioned environment must succeed without error and without duplicating resources.

### bootstrap.sh
Creates all AWS resources from scratch. Safe to re-run.

Steps (in order):
1. Create IAM role `$LAMBDA_ROLE_NAME` with Lambda trust policy (skip if exists)
2. Attach `AWSLambdaBasicExecutionRole` managed policy (skip if already attached)
3. Build the Lambda deployment package (`dist/lambda.zip`)
4. Create Lambda function (Python 3.13, arm64, timeout 60s, reserved concurrency 2, env var `PROXY_URL`) — skip if exists
5. Create Function URL (auth NONE, buffered) — skip if exists
6. Add `lambda:InvokeFunctionUrl` + `lambda:InvokeFunction` resource-based policy for principal `*` (skip if exists)
7. Print the Function URL

### deploy.sh
Updates Lambda code only. Does not touch IAM or Function URL.

Steps:
1. Source `.env`
2. Build `dist/lambda.zip`
3. `aws lambda update-function-code` (arm64)
4. Update environment variables on the function (`PROXY_URL`) in case `.env` changed

### destroy.sh
Tears down all resources created by `bootstrap.sh`. Safe to re-run (skips missing resources without error).

Steps (reverse order of bootstrap):
1. Remove resource-based policies (`FunctionURLAllowPublicAccess`, `FunctionURLAllowPublicInvokeFunction`)
2. Delete Function URL
3. Delete Lambda function
4. Detach managed policy from IAM role
5. Delete IAM role

---

## 6. AWS resources managed

| Resource | Name | Notes |
|---|---|---|
| IAM role | `$LAMBDA_ROLE_NAME` | Lambda execution role |
| Lambda function | `$FUNCTION_NAME` | Python 3.13, arm64 |
| Lambda Function URL | — | Auth NONE (OAuth2 planned) |

No S3 buckets, no DynamoDB tables, no API Gateway.

---

## 7. MCP protocol

The Lambda handles MCP lifecycle methods (`initialize`, `tools/list`) and tool calls (`tools/call`).

**Request** (Claude Web → Lambda):
```json
POST <function-url>
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "get_youtube_transcript",
    "arguments": { "url": "https://www.youtube.com/watch?v=VIDEO_ID" }
  },
  "id": 1
}
```

**Response**:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "content": [{ "type": "text", "text": "<metadata + transcript>" }]
  },
  "id": 1
}
```

---

## 8. Code style

- Python 3.13, managed with `uv` (no virtualenv, no pip directly)
- Single-file Lambda handler (`src/lambda_function.py`)
- All config via environment variables; secrets only via Secrets Manager
- No secrets in code, commits, or logs
- Shell scripts: `bash`, `set -euo pipefail`, sourcing `.env` at the top

---

## 9. Testing strategy

- `uv run pytest` for all tests
- Unit tests mock `boto3`, `yt-dlp`, and `youtube-transcript-api`
- Test MCP protocol conformance: `initialize`, `tools/list`, `tools/call`
- Test auth rejection (missing/wrong token)
- Test URL validation: reject non-YouTube URLs before passing to yt-dlp

---

## 10. Boundaries

| Always do | Ask first | Never do |
|---|---|---|
| Serverless / Lambda for compute | Adding new AWS services beyond spec | Commit secrets or tokens |
| AWS CLI scripts for infra changes | Calling Claude API from Lambda | Use Terraform / CloudFormation / SAM |
| `uv` for Python deps | Supporting playlists | Use API Gateway |
| eu-south-1 region | Changing MCP transport | Hard-code region, ARNs, or credentials |
| Validate `url` is a YouTube URL before processing | | Store transcript data persistently |
| IAM policy scoped to specific secret ARN | | Include `boto3` in deployment package |
| `.env` for local config, `.env.example` for template | | Use SSE/HTTP+SSE MCP transport |
