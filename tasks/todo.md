# TODO

- [ ] T1: Project scaffolding — pyproject.toml, src/__init__.py, uv sync, uv run pytest
- [ ] T2: YouTube extraction — _validate_youtube_url, _get_metadata, _get_transcript + tests
- [ ] T3: MCP protocol handler — _handle_mcp, initialize, tools/list, tools/call + tests
- [ ] T4: Auth + Lambda entry point — _get_bearer_token, handler, error paths + tests
- [ ] CHECKPOINT 1: uv run pytest -v → all green
- [ ] T5: Terraform infra — main.tf, variables.tf, outputs.tf, backend.tf + terraform validate
- [ ] T6: Bootstrap + deploy scripts — bootstrap-tfstate.sh, deploy.sh + bash -n check
- [ ] CHECKPOINT 2: scripts/smoke-test.sh with curl commands
