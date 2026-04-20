# claude-youtube-transcript

A remote MCP server that adds YouTube video comprehension to [Claude](https://claude.ai) — something Gemini has natively but Claude doesn't. Paste a YouTube URL in a Claude chat, and Claude fetches the transcript + metadata to reason about the video.

Runs as a single AWS Lambda function exposed via a Function URL, protected by OAuth2 (Authorization Code + PKCE S256).

See [SPEC.md](SPEC.md) for the full contract and [CLAUDE.md](CLAUDE.md) for implementation notes.

## Architecture

```
Claude Web
  └─ MCP (Streamable HTTP over HTTPS)
       └─ Lambda Function URL (eu-south-1)
            ├─ OAuth2 Authorization Code + PKCE S256
            │    └─ signing secret in AWS Secrets Manager
            ├─ YouTube oEmbed API       → metadata (title, channel, thumbnail)
            └─ youtube-transcript-api  → timestamped transcript (via Webshare proxy)
```

The handler is a single file: [`src/lambda_function.py`](src/lambda_function.py).

## MCP tool

| Tool | Input | Output |
|---|---|---|
| `get_youtube_transcript` | `url: string` | `{ url, metadata, transcript[] }` |

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (Python package manager)
- `aws` CLI (authenticated)
- `zip`, `openssl`

## Local development

```bash
uv sync           # install deps
uv run pytest     # run the test suite
```

## First-time deploy

```bash
bash scripts/bootstrap.sh
```

Creates in order: IAM role, S3 deploy bucket, OAuth signing secret (Secrets Manager), Lambda function, Function URL, resource-based policies.

## Update code

```bash
bash scripts/deploy.sh
```

Rebuilds the zip, uploads to S3, updates Lambda code and environment variables.

## Tear down

```bash
bash scripts/destroy.sh
```

## Connect to Claude

1. In Claude → **Settings → Connectors → Add custom connector**.
2. URL: the Function URL printed by `bootstrap.sh`.
3. Click **Connect** — Claude opens an OAuth consent flow, which auto-approves (single-user server).
4. In a chat: _"summarize https://www.youtube.com/watch?v=..."_.

## Configuration

All values live in `.env` (gitignored). Copy `.env.example` and fill in:

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_DEFAULT_REGION` | no | `eu-south-1` | AWS region |
| `FUNCTION_NAME` | yes | — | Lambda function name |
| `LAMBDA_ROLE_NAME` | yes | — | IAM execution role name |
| `DEPLOY_BUCKET` | no | `<FUNCTION_NAME>-deploy-<account-id>` | S3 bucket for deployment zips |
| `LAMBDA_MEMORY` | no | `256` | Lambda memory in MB |
| `WEBSHARE_USERNAME` | no | `` | Webshare residential proxy username |
| `WEBSHARE_PASSWORD` | no | `` | Webshare residential proxy password |

## Gotchas

- **Public Function URL requires two resource-policy statements**: both `lambda:InvokeFunction` and `lambda:InvokeFunctionUrl` must be granted to principal `*`. Missing the first yields a generic 403 with no CloudWatch trace.
- **`boto3` is not a deployment dependency**: it ships with the Lambda runtime. It's dev-only so tests can mock it.
- **Lambda base64-encodes `application/x-www-form-urlencoded` bodies**: the OAuth `/token` endpoint decodes them automatically via `isBase64Encoded`.
- **OAuth tokens are stateless**: signed with HMAC-SHA256 using a secret in Secrets Manager. No database required.

## License

MIT.
