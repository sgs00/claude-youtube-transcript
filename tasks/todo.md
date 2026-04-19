# TODO

- [ ] T1: Scaffolding — delete infra/, delete bootstrap-tfstate.sh, create .env.example, update .gitignore
- [ ] T2: scripts/_lib.sh — shared build_zip function
- [ ] T3: scripts/bootstrap.sh — idempotent AWS resource creation (IAM, secret, Lambda, Function URL)
- [ ] T4: scripts/deploy.sh — rewrite: source .env, build zip, update-function-code + update-function-configuration
- [ ] T5: scripts/destroy.sh — idempotent teardown in reverse order
- [ ] CHECKPOINT: bash -n scripts/*.sh; run bootstrap.sh, verify URL, deploy.sh, destroy.sh x2
