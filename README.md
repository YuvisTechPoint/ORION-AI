# Binary-v2 (ORION)

**ORION — AI-Native Software Delivery & Reliability Control Plane**
run - python scripts\sync_github_oauth.py
.\run_all_stacks.ps1 -SkipInstall

Multi-stack DevOps automation workspace: autonomous pipeline agents, gate fusion, change risk intelligence, multimodal analysis, cross-stack Command Hub, and production-oriented security controls.

**ORION phased roadmap (Phases 0–30):** fully implemented in `ai-cicd-pipeline/` — see [`agents.md`](agents.md), [`docs/AGENTS_QUICKREF.md`](docs/AGENTS_QUICKREF.md), and [`docs/audit/IMPLEMENTATION_BACKLOG.md`](docs/audit/IMPLEMENTATION_BACKLOG.md). Configure via `ai-cicd-pipeline/.env.example`.

| Stack | Path | API | UI | Role |
|-------|------|-----|-----|------|
| **Command Hub** | `hub/` | — | `:5180` | Unified launcher with live health |
| **Canonical DevOps** | `backend/` + `frontend/` | `:8000` | `:5173` | Submit-code / archive / GitHub zip pipelines |
| **ORION CI/CD** | `ai-cicd-pipeline/` | `:8001` | `http://127.0.0.1:8001/ui/` | GitHub webhook → 9-stage pipeline + multimodal APIs |
| **DevOps Platform** | `devops-platform/` | `:8002`* | `:3000`* | Celery + Postgres agents (QA, stress, deploy) |

\*When using `run_all_stacks.ps1`, devops-platform runs on **8002** to avoid conflicting with the canonical backend on 8000. DevOps UI defaults to **3000** but auto-falls back to **3001**/**3002** if another app owns that port (check the launcher banner). Set `DEVOPS_UI_PORT` to pin. Docker Compose defaults remain documented in `devops-platform/README.md`.

## Prerequisites

- Python 3.11+ with workspace venv at `.venv/`
- Node 20+ (for frontends)
- Optional: Docker (real deploy mode), PostgreSQL + Redis (devops-platform production path)

## Quick start

```powershell
# Create venv once (if needed)
python -m venv .venv

# Full test verification (all stacks + Playwright hub smoke)
.\run_e2e_all.ps1 -Offline

# Unified command hub + all three stacks
.\run_all_stacks.ps1
# Open http://127.0.0.1:5180 for the Command Hub (stack URLs: config/stacks.json)

# Start canonical stack only
.\run_local_all.ps1
```

### Individual stacks

**Canonical**

```powershell
cd backend
..\.venv\Scripts\uvicorn.exe main:app --port 8000
# separate terminal
cd frontend && npm run dev
```

**ORION CI/CD**

```powershell
cd ai-cicd-pipeline
.\scripts\run_local.ps1 -Background   # SQLite + staging + API on :8001
# Dashboard: http://127.0.0.1:8001/ui/
# Stop: .\scripts\stop_local.ps1
```

**DevOps Platform**

```powershell
cd devops-platform\backend
..\.venv\Scripts\uvicorn.exe app.main:app --port 8002
# separate terminal — set VITE_API_URL=http://127.0.0.1:8002
cd devops-platform\frontend && npm run dev
```

## Deployment modes (`DEPLOY_MODE`)

All pipeline stacks support:

| Mode | Behavior |
|------|----------|
| `auto` | Docker when daemon available; otherwise **simulate** deploy |
| `docker` | Require Docker build + run |
| `simulate` | Record successful deploy without Docker |
| `skip` | Skip deployment stage (ai-cicd ends at `approved`; devops marks deploy skipped) |

Set in `.env` or environment before starting the API. Restart the API after changes.

**Phase 2 progressive delivery (optional):**

```env
PROGRESSIVE_DELIVERY_ENABLED=true
CANARY_STAGES=5,25,50,100
CANARY_MAX_P95_MS=2000
PREVIEW_BASE_URL=http://{pr}.preview.orion.internal
```

**Phase 3 SRE intelligence (optional):**

```env
SLO_TARGET_AVAILABILITY=0.999
SYNTHETIC_MONITORING_LIVE=false
```

When `SYNTHETIC_MONITORING_LIVE=true`, post-deploy synthetic checks hit `STAGING_URL` journeys instead of simulated pass.

**Phase 4 enterprise & Phase 5 AI platform (optional):**

```env
POLICY_ENFORCEMENT_ENABLED=true
POLICY_STRICT_REQUIREMENTS=false
COMPLIANCE_PACKS=soc2,iso27001,owasp,cis
PROMPT_INJECTION_GATE_ENABLED=true
MODEL_ROUTER_ENABLED=true
AGENT_EVAL_MIN_SCORE=0.6
PATCH_AUTO_PR_ENFORCEMENT=true
AGENT_EVAL_GATE_ENABLED=false
REQUIRE_SIGNED_BUILDS=false
TENANT_ISOLATION_MODE=org
FINOPS_LLM_COST_PER_1K_TOKENS=0.003
FINOPS_COMPUTE_COST_PER_MINUTE=0.008
SSO_SAML_ENTITY_ID=
SSO_OIDC_ISSUER=
DEVOPS_RAG_MAX_CHUNKS=8
SLO_ALERT_SLACK_ENABLED=true
SLO_ALERT_COOLDOWN_SECONDS=3600
```

Intelligence APIs: `/intelligence/dashboard`, `/intelligence/fleet`, `/intelligence/audit-explorer`, `/intelligence/agents`, `/intelligence/rag?q=`.

## Text analysis APIs

Shared utilities in `backend/core/text_analysis.py` and `ai-cicd-pipeline/app/utils/text_analysis.py`.

```bash
# Canonical backend
curl -s -X POST http://127.0.0.1:8000/api/v1/tools/text-analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"ERROR connection timed out","operations":["classify_log","metrics"]}'

# ORION CI/CD
curl -s -X POST http://127.0.0.1:8001/api/v1/tools/text-analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"ModuleNotFoundError: flask","operations":["classify_log"]}'
```

The ORION dashboard auto-detects log type via this endpoint before multimodal log analysis.

## Documentation

- [`agents.md`](agents.md) — **master reference** (Part I: implemented baseline · Part II: control-plane expansion · 71 sections)
- [`ai-cicd-pipeline/README.md`](ai-cicd-pipeline/README.md) — ORION setup, security, E2E
- [`backend/README.md`](backend/README.md) — canonical API reference
- [`devops-platform/README.md`](devops-platform/README.md) — Docker Compose, Celery workers

## Verification

```powershell
.\run_e2e_all.ps1 -Offline          # all stacks
.\run_e2e_all.ps1 -SkipDevops       # canonical + ai-cicd only
.\run_e2e_all.ps1 -SkipCanonical    # ai-cicd + devops only
```

## URL policy

Use **`127.0.0.1`** consistently for OAuth callbacks, dashboard links, and API bases (see `config/stacks.json`). Register both OAuth callbacks on your GitHub app when running multiple stacks:

- `http://127.0.0.1:8000/api/v1/auth/github/callback` — DevOps Console
- `http://127.0.0.1:8001/api/v1/auth/github/callback` — ORION CI/CD

## Security notes

- Production: set real secrets (`SESSION_SECRET`, `GITHUB_WEBHOOK_SECRET`, `ANTHROPIC_API_KEY`, API keys)
- ai-cicd: `API_REQUIRE_AUTH=true` in production
- Webhook HMAC verification uses dedicated webhook secrets (not GitHub tokens)

## Production deployment

1. Copy `.env.production.example` → `.env.production` for each stack (`ai-cicd-pipeline/`, `backend/`, `devops-platform/`)
2. Start infra: `docker compose -f docker-compose.prod.yml up -d`
3. Preflight: `.\.venv\Scripts\python scripts\production_preflight.py`
4. Launch: `.\run_production.ps1`
5. Verify: `orion production checklist` or `GET /api/v1/production/ready`

Full guide: [docs/PRODUCTION_RUNBOOK.md](docs/PRODUCTION_RUNBOOK.md)
