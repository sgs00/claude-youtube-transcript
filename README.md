# claude-yt-companion

A remote MCP server that adds YouTube video comprehension to [Claude](https://claude.ai) — something Gemini has natively but Claude doesn't. Paste a YouTube URL in a Claude chat, and Claude fetches the transcript + metadata to reason about the video.

Runs as a single AWS Lambda function exposed via a Function URL. Auth is a bearer token stored in AWS Secrets Manager.

See [SPEC.md](SPEC.md) for the full contract and [CLAUDE.md](CLAUDE.md) for implementation notes.

## Architecture

```
Claude Web
  └─ MCP (Streamable HTTP over HTTPS, spec 2025-03-26)
       └─ Lambda Function URL
            ├─ Auth: Bearer token from Secrets Manager
            ├─ yt-dlp                  → metadata (title, channel, duration, views, ...)
            └─ youtube-transcript-api  → timestamped transcript
```

The handler is a single file: [`src/lambda_function.py`](src/lambda_function.py).

## MCP tool

| Tool | Input | Output |
|---|---|---|
| `get_youtube_transcript` | `url: string` | `{ url, metadata, transcript[] }` |

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (Python package manager)
- `terraform` ≥ 1.5
- `aws` CLI (authenticated)
- `zip`, `unzip`

## Local development

```bash
uv sync               # install deps (uses uv — NOT pip)
uv run pytest         # run the full test suite (26 tests)
```

## Deploy

First-time setup creates the S3 bucket + DynamoDB table for Terraform state:

```bash
TFSTATE_BUCKET=<your-unique-bucket-name> bash scripts/bootstrap-tfstate.sh
```

Then deploy (provisions IAM role, secret, Lambda, Function URL):

```bash
TFSTATE_BUCKET=<your-unique-bucket-name> bash scripts/deploy.sh
```

Set the bearer token (only on first deploy):

```bash
aws secretsmanager put-secret-value \
  --secret-id youtube-transcript/bearer-token \
  --secret-string 'YOUR_BEARER_TOKEN'
```

For subsequent code-only changes (no infra update):

```bash
bash scripts/deploy.sh --update-code-only
```

## Smoke test

```bash
FUNCTION_URL=https://<your-url>.lambda-url.<region>.on.aws/ \
BEARER_TOKEN=<your-token> \
bash scripts/smoke-test.sh
```

Exercises `initialize`, `tools/list`, `tools/call`, and verifies a wrong token is rejected with 401.

## Connect to Claude

1. In Claude → **Settings → Connectors → Add custom connector**.
2. URL: the Function URL from `terraform output function_url`.
3. Authentication: **Bearer token** — paste the value you stored in Secrets Manager.
4. In a chat, try: _"summarize https://www.youtube.com/watch?v=..."_.

## Gotchas

- **Public Function URL requires two resource-policy statements**: both `lambda:InvokeFunction` and `lambda:InvokeFunctionUrl` must be granted to principal `*`. Missing the first yields a generic 403 with no CloudWatch trace. The Terraform config sets both.
- **`boto3` is not a runtime dependency**: it's provided by the Lambda runtime. It's declared as a dev dep only so tests can mock it.
- **Region**: defaults to `eu-south-1`. Override with `AWS_DEFAULT_REGION`.

## License

MIT.
