# Plan: Remove Terraform, add idempotent AWS CLI scripts

## Context

Terraform and its S3/DynamoDB state backend have been destroyed and deleted.
All AWS resources are gone. Replace `infra/` with three shell scripts driven by `.env`.

## Dependency graph

```
T1: Scaffolding (.env.example, .gitignore, delete infra/ + old scripts)
 └─ T2: scripts/_lib.sh  (shared build_zip helper)
      ├─ T3: scripts/bootstrap.sh  (idempotent — create all AWS resources)
      ├─ T4: scripts/deploy.sh     (rewrite — update code + env vars only)
      └─ T5: scripts/destroy.sh    (idempotent — tear down all AWS resources)
```

## Critical files

| Path | Role |
|---|---|
| `.env` | Local config (gitignored) |
| `.env.example` | Versioned template |
| `scripts/_lib.sh` | Shared build_zip function |
| `scripts/bootstrap.sh` | One-time infra provisioning |
| `scripts/deploy.sh` | Code-only update |
| `scripts/destroy.sh` | Full teardown |

## Verification

1. `bash -n scripts/*.sh` → no syntax errors
2. `bootstrap.sh` → exits 0, prints Function URL
3. `bootstrap.sh` (again) → exits 0, no errors (idempotency)
4. `deploy.sh` → exits 0, Lambda updated
5. `destroy.sh` → exits 0, resources gone
6. `destroy.sh` (again) → exits 0 (idempotency)
