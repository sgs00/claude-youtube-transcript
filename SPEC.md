# SPEC.md — claude-yt-companion

## 1. Objective

Extend Claude Web with the ability to read YouTube videos (transcript + metadata) via a remote MCP server hosted on AWS Lambda. The user pastes a YouTube URL in Claude Web; Claude calls the `get_youtube_transcript` MCP tool and uses the result as context for Q&A and brainstorming.

**Target user**: single operator (personal use). Code will be open-sourced so others can replicate the setup.

---

## 2. Architecture

```
Claude Web
  └─ MCP (Streamable HTTP over HTTPS)
       └─ Lambda Function URL   (eu-south-1, streaming enabled)
            ├─ Auth: Bearer token from Secrets Manager
            ├─ yt-dlp           → video metadata
            └─ youtube-transcript-api → transcript (all languages)
```

### MCP transport
Claude Web remote MCP uses the **Streamable HTTP** transport (JSON-RPC 2.0 over HTTPS POST, spec 2025-03-26). For `tools/call`, the response is a single JSON object — Lambda buffered response mode is sufficient, no SSE streaming required for Phase 1. The old HTTP+SSE transport is deprecated since April 2026 and must not be used.

### MCP tools exposed (Phase 1)
| Tool | Input | Output |
|---|---|---|
| `get_youtube_transcript` | `url: string` | metadata + full transcript |

Phase 2 (out of scope now): optional pre-summarization via Claude API for very long videos.

---

## 3. Project structure

```
claude-yt-companion/
├── src/
│   └── lambda_function.py     # MCP handler + YouTube extraction
├── infra/
│   ├── main.tf                # Lambda, IAM role, Secrets Manager, Function URL
│   ├── variables.tf
│   ├── outputs.tf
│   └── backend.tf             # S3 + DynamoDB state backend
├── scripts/
│   ├── bootstrap-tfstate.sh   # One-time: creates S3 bucket + DynamoDB table for TF state
│   └── deploy.sh              # Plain AWS CLI deploy (readable fallback)
├── tests/
│   └── test_lambda_function.py
├── pyproject.toml             # uv-managed dependencies
├── SPEC.md                    # This file
└── CLAUDE.md                  # Claude Code guidance
```

---

## 4. Infrastructure (Terraform, eu-south-1)

Resources managed by Terraform:
- `aws_iam_role` + `aws_iam_role_policy` — Lambda execution role; `secretsmanager:GetSecretValue` scoped to the specific secret ARN only (least privilege)
- `aws_secretsmanager_secret` — stores the Bearer token (value injected outside Terraform, never in state or code)
- `aws_lambda_function` — Python 3.13, arm64, `timeout = 60` (yt-dlp requires up to 15s for metadata extraction), `reserved_concurrency = 2` (cost protection in case of token leak)
- `aws_lambda_function_url` — auth type NONE (auth handled at application level via Bearer token); buffered response mode (no streaming required for MCP Phase 1)

Terraform files split into `main.tf`, `variables.tf`, `outputs.tf`, `backend.tf` for replicability.

Terraform state: S3 backend with DynamoDB locking. The bootstrap resources (S3 bucket + DynamoDB table) are created by a one-time script (`scripts/bootstrap-tfstate.sh`) before the first `terraform init`. Backend config in `backend.tf`; bucket name and table name are variables so each operator can use their own.

The secret *value* is set via AWS CLI or console after `terraform apply`, never via Terraform.

`boto3` is excluded from the deployment package — it is already available in the Lambda managed runtime.

---

## 5. MCP protocol

The Lambda handles MCP lifecycle methods (`initialize`, `tools/list`) and tool calls (`tools/call`).

**Request** (Claude Web → Lambda):
```json
POST <function-url>
Authorization: Bearer <token>
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

## 6. Code style

- Python 3.13, managed with `uv` (no virtualenv, no pip directly)
- Single-file Lambda handler (`src/lambda_function.py`)
- All config via environment variables; secrets only via Secrets Manager
- No secrets in code, commits, or logs

---

## 7. Testing strategy

- `uv run pytest` for all tests
- Unit tests mock `boto3`, `yt-dlp`, and `youtube-transcript-api`
- Test MCP protocol conformance: `initialize`, `tools/list`, `tools/call`
- Test auth rejection (missing/wrong token)
- Test URL validation: reject non-YouTube URLs before passing to yt-dlp

---

## 8. Boundaries

| Always do | Ask first | Never do |
|---|---|---|
| Serverless / Lambda for compute | Adding new AWS services beyond spec | Commit secrets or tokens |
| Terraform for infra changes | Calling Claude API from Lambda | Use API Gateway |
| `uv` for Python deps | Supporting playlists | Hard-code region or ARNs |
| eu-south-1 region | Changing MCP transport | Store transcript data persistently |
| Validate `url` is a YouTube URL before processing | | Include `boto3` in deployment package |
| IAM policy scoped to specific secret ARN | | Use SSE/HTTP+SSE MCP transport |
