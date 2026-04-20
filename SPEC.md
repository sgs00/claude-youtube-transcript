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
            ├─ Auth: OAuth2 Authorization Code + PKCE S256
            │    └─ signing secret in AWS Secrets Manager
            ├─ YouTube oEmbed API      → metadata (title, channel, thumbnail)
            └─ youtube-transcript-api  → transcript (all languages, via Webshare proxy)
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
│   └── lambda_function.py       # MCP handler + YouTube extraction + OAuth2
├── scripts/
│   ├── _lib.sh                  # Shared helpers (build_zip, S3_KEY)
│   ├── bootstrap.sh             # One-time: creates all AWS resources
│   ├── deploy.sh                # Updates Lambda code and env vars
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

# S3 bucket for deployment zips (auto-computed if empty: <FUNCTION_NAME>-deploy-<account-id>)
DEPLOY_BUCKET=

# Lambda memory in MB (default: 256)
LAMBDA_MEMORY=256

# Webshare residential proxy for youtube-transcript-api (leave empty to disable)
WEBSHARE_USERNAME=
WEBSHARE_PASSWORD=
```

`OAUTH_SECRET_NAME` is derived automatically as `${FUNCTION_NAME}-oauth-secret` and is never set in `.env`.

---

## 5. Infrastructure scripts (AWS CLI, eu-south-1)

All three scripts must be **idempotent**: re-running them on an already-provisioned environment must succeed without error and without duplicating resources.

### bootstrap.sh
Creates all AWS resources from scratch. Safe to re-run.

Steps (in order):
1. Create IAM role `$LAMBDA_ROLE_NAME` with Lambda trust policy (skip if exists)
2. Attach `AWSLambdaBasicExecutionRole` managed policy (skip if already attached)
3. Create S3 deploy bucket `$DEPLOY_BUCKET` with public access blocked (skip if exists)
4. Create Secrets Manager secret `${FUNCTION_NAME}-oauth-secret` with a random 32-byte hex value (skip if exists); attach inline policy to Lambda role granting `secretsmanager:GetSecretValue` on that ARN
5. Build the Lambda deployment package (`dist/lambda.zip`), upload to S3
6. Create Lambda function (Python 3.13, arm64, timeout 60s, reserved concurrency 2, env vars `WEBSHARE_USERNAME`, `WEBSHARE_PASSWORD`, `OAUTH_SECRET_NAME`) — skip if exists
7. Create Function URL (auth NONE, buffered) — skip if exists
8. Add `lambda:InvokeFunctionUrl` + `lambda:InvokeFunction` resource-based policy for principal `*` (skip if exists)
9. Print the Function URL

### deploy.sh
Updates Lambda code and environment variables. Does not touch IAM or Function URL.

Steps:
1. Source `.env`
2. Build `dist/lambda.zip`
3. Upload zip to S3 (`aws s3 cp`)
4. `aws lambda update-function-code --s3-bucket --s3-key` (arm64)
5. `aws lambda update-function-configuration` — sync `WEBSHARE_USERNAME`, `WEBSHARE_PASSWORD`, `OAUTH_SECRET_NAME`, `LAMBDA_MEMORY`

### destroy.sh
Tears down all resources created by `bootstrap.sh`. Safe to re-run (skips missing resources without error).

Steps (reverse order of bootstrap):
1. Remove resource-based policies (`FunctionURLAllowPublicAccess`, `FunctionURLAllowPublicInvokeFunction`)
2. Delete Function URL
3. Delete Lambda function
4. Delete Secrets Manager secret (`--force-delete-without-recovery`)
5. Remove inline IAM policy `SecretsManagerOAuthSecret`
6. Detach managed policy `AWSLambdaBasicExecutionRole` from IAM role
7. Delete IAM role
8. Delete S3 deploy bucket (empty first, then delete)

---

## 6. AWS resources managed

| Resource | Name | Notes |
|---|---|---|
| IAM role | `$LAMBDA_ROLE_NAME` | Lambda execution role |
| S3 bucket | `$DEPLOY_BUCKET` | Deployment zip storage, public access blocked |
| Secrets Manager secret | `${FUNCTION_NAME}-oauth-secret` | OAuth HMAC signing key (32 random bytes, hex) |
| Lambda function | `$FUNCTION_NAME` | Python 3.13, arm64 |
| Lambda Function URL | — | Auth NONE (OAuth enforced in application code) |

---

## 7. OAuth2

The server implements **Authorization Code + PKCE S256** as required by Claude.ai for remote MCP connectors.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/.well-known/oauth-protected-resource` | Resource metadata (RFC 9728) |
| `GET` | `/.well-known/oauth-authorization-server` | Authorization server metadata (RFC 8414) |
| `POST` | `/register` | Dynamic client registration |
| `GET` | `/authorize` | Authorization endpoint (auto-approves, redirects to callback) |
| `POST` | `/token` | Token endpoint (exchanges code for Bearer token) |

### Token design (stateless)

Auth codes and access tokens are HMAC-SHA256 signed blobs — no database required.

- **Auth code**: `base64url(JSON({c, r, k, e}) + "." + HMAC(JSON))` — 5-minute TTL
  - `c` = client_id, `r` = redirect_uri, `k` = PKCE code_challenge, `e` = expiry timestamp
- **Access token**: same structure with `{c, e}` — 1-hour TTL

The signing key is a 32-byte random hex string stored in Secrets Manager, lazy-loaded and cached per Lambda container.

### Single-user consent
`GET /authorize` auto-redirects to the `redirect_uri` with the auth code — no consent UI. This is intentional for a single-operator personal server.

---

## 8. MCP protocol

The Lambda handles MCP lifecycle methods (`initialize`, `tools/list`) and tool calls (`tools/call`).

**Request** (Claude Web → Lambda):
```json
POST <function-url>
Content-Type: application/json
Authorization: Bearer <access-token>

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

## 9. Code style

- Python 3.13, managed with `uv` (no virtualenv, no pip directly)
- Single-file Lambda handler (`src/lambda_function.py`)
- All config via environment variables; secrets only via Secrets Manager
- No secrets in code, commits, or logs
- Shell scripts: `bash`, `set -euo pipefail`, sourcing `.env` at the top

---

## 10. Testing strategy

- `uv run pytest` for all tests
- Unit tests mock `boto3`, `urllib.request` (oEmbed), and `youtube-transcript-api`
- Test MCP protocol conformance: `initialize`, `tools/list`, `tools/call`
- Test OAuth endpoints: discovery metadata, register, authorize redirect, token exchange
- Test auth rejection (missing/expired/tampered token)
- Test URL validation: reject non-YouTube URLs before passing to yt-dlp

---

## 11. Boundaries

| Always do | Ask first | Never do |
|---|---|---|
| Serverless / Lambda for compute | Adding new AWS services beyond spec | Commit secrets or tokens |
| AWS CLI scripts for infra changes | Calling Claude API from Lambda | Use Terraform / CloudFormation / SAM |
| `uv` for Python deps | Supporting playlists | Use API Gateway |
| eu-south-1 region | Changing MCP transport | Hard-code region, ARNs, or credentials |
| Validate `url` is a YouTube URL before processing | | Store transcript data persistently |
| IAM policy scoped to specific secret ARN | | Include `boto3` in deployment package |
| `.env` for local config, `.env.example` for template | | Use SSE/HTTP+SSE MCP transport |
| Upload Lambda zip via S3 | | Upload zip directly via `--zip-file` |
