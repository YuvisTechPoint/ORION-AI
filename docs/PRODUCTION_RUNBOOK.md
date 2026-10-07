# ORION / Binary-v2 — Production Runbook

This runbook covers deploying all stacks with production hardening enabled.

## Prerequisites

- Docker (for PostgreSQL + Redis via `docker-compose.prod.yml`)
- Python 3.11+ with repo `.venv`
- Node.js 18+ (frontends)
- TLS termination at nginx or cloud load balancer (not included in local launcher)

## 1. Create production env files

**Option A — auto-generate (local production simulation):**

```powershell
.\run_production.ps1 -GenerateSecrets -SkipDocker -SkipPreflight
# or force regenerate:
python scripts\generate_production_env.py --force
```

This writes `.env.production` for all stacks plus `.env.prod.infra` for Docker Postgres/Redis.

**Preflight (all stacks):**

```powershell
python scripts/production_preflight.py
```

Validates placeholder secrets, ORION `validate_startup()`, Canonical `check_required_env_vars()`, and DevOps `validate_startup()`.  
Secrets print once to the console; a non-secret manifest lands in `.local/production_manifest.json`.

**Option B — manual (real cloud deploy):**

```powershell
copy ai-cicd-pipeline\.env.production.example ai-cicd-pipeline\.env.production
copy backend\.env.production.example backend\.env.production
copy devops-platform\.env.production.example devops-platform\.env.production
```

Replace **every** placeholder with real values. Never commit `.env.production` files.

## 2. Start infrastructure

```powershell
docker compose --env-file .env.prod.infra -f docker-compose.prod.yml up -d
```

Postgres creates databases: `orion`, `canonical`, `devops_platform` (see `docker/postgres-init/`).

**ORION schema migrations** (required after upgrade — includes `performance_baselines` table):

```powershell
cd ai-cicd-pipeline
..\.venv\Scripts\alembic upgrade head
```

## 2b. TLS (optional, local nginx)

```powershell
.\scripts\generate_local_tls.ps1 -HostName orion.local
```

Certs land in `observability/tls/local/`. Use `ai-cicd-pipeline/nginx/conf.d/orion.conf` in Docker nginx with volume mounts.

## 3. Run preflight

```powershell
.\.venv\Scripts\python scripts\production_preflight.py
```

Exit code `0` means env files pass placeholder and hardening checks.

## 4. Launch all stacks (production mode)

```powershell
.\run_production.ps1
```

This starts Docker infra (when available), runs preflight, then calls `run_all_stacks.ps1` with per-stack env loading.

**No Docker?** The launcher auto-enables `PRODUCTION_LOCAL_SIM` (SQLite + inline executor, production auth + gates still on):

```powershell
.\run_production.ps1 -GenerateSecrets -LocalSim
```

## 5. Verify readiness

| Check | Endpoint |
|-------|----------|
| ORION liveness | `GET /health` |
| ORION readiness | `GET /ready` |
| Production checklist | `GET /api/v1/production/checklist` |
| Production gate | `GET /api/v1/production/ready` (503 if not ready) |

CLI:

```bash
orion production checklist
orion production ready
```

## Production hardening defaults (ORION)

When `APP_ENV=production`:

- `API_REQUIRE_AUTH` auto-enabled
- `validate_startup()` rejects placeholder secrets, SQLite DB, missing API keys
- Session cookies: `https_only=true`, `same_site=none`
- Recommended gates: `PROMPT_INJECTION_GATE_ENABLED`, `POLICY_ENFORCEMENT_ENABLED`, `UNIFIED_RISK_GATE_ENABLED`

## Minimum secret checklist

- [ ] `SECRET_KEY` — 32+ random bytes
- [ ] `SESSION_SECRET_KEY` — unique per environment
- [ ] `GITHUB_WEBHOOK_SECRET` — dedicated (not `GITHUB_TOKEN`)
- [ ] `AUTH_API_KEYS_JSON` — scoped RBAC keys
- [ ] `DATABASE_URL` — PostgreSQL with TLS in cloud
- [ ] `ANTHROPIC_API_KEY` — scoped LLM key (optional; heuristic fallback)
- [ ] `SLACK_WEBHOOK_URL` — alerting

## Stop

```powershell
.\stop_local_all.ps1
docker compose -f docker-compose.prod.yml down
```

## Troubleshooting

| Symptom | Action |
|---------|--------|
| `validate_startup` SECRET_KEY error | Replace placeholders in `.env.production` |
| SQLite in production | Point `DATABASE_URL` to Postgres |
| 401 on APIs | Set `X-ORION-API-Key` or GitHub OAuth session |
| Preflight missing file | Copy `.env.production.example` → `.env.production` |
| Celery not processing | Confirm Redis up; `GET /ready` executor check |

See `AGENTS.md` §10–§11 for full security and deployment topology guidance.
