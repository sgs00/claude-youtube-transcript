# Plan: claude-yt-companion — full implementation

## Context

Empty repo with a complete SPEC.md. Need to build a remote MCP server (Streamable HTTP, spec 2025-03-26) on AWS Lambda that exposes `get_youtube_transcript`. Greenfield.

## Dependency graph

```
pyproject.toml (uv)
    └─ youtube extraction (yt-dlp + youtube-transcript-api)
        └─ MCP JSON-RPC handler (initialize / tools/list / tools/call)
            └─ auth middleware (Bearer token ↔ Secrets Manager)
                └─ Lambda handler (lambda_function.handler)
                    └─ tests
                        └─ Terraform infra
                            └─ bootstrap + deploy scripts
```

## Critical files

| Path | Role |
|---|---|
| `src/lambda_function.py` | Entire application logic |
| `pyproject.toml` | uv deps |
| `infra/main.tf` | All AWS resources |
| `infra/variables.tf` | Configurable values |
| `infra/backend.tf` | Remote state config |
| `scripts/bootstrap-tfstate.sh` | One-time state bucket setup |
| `scripts/deploy.sh` | Deployment |
| `tests/test_lambda_function.py` | All unit tests |

## Verification

1. `uv run pytest -v` → all tests green
2. `terraform validate` in `infra/` → no errors
3. `bash -n scripts/*.sh` → no syntax errors
4. (post-deploy) `scripts/smoke-test.sh` → 200 for all three MCP methods
