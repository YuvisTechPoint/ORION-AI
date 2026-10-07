# ORION — Autonomous AI CI/CD Pipeline

## Overview

ORION turns every `git push` into an autonomous, AI-reviewed release. A signed GitHub webhook (or the dashboard's **Run Pipeline** form) queues a run — on Celery when Redis is available, otherwise inside the API process; the orchestrator clones the commit and runs a **9-stage agent chain** — ingestion, code analysis, security scanning, QA, load testing, approval, deployment and post-deploy monitoring — each backed by Claude with a deterministic fallback when no API key is configured. When a quality gate blocks a release, ORION opens **fix pull requests** grouped by category and deletes the branches automatically once they are merged.

Beyond the core pipeline, ORION ships:

- **Auto-PR remediation** — Claude-generated patches committed to `orion/fix-<category>-<run>` branches with a review-ready PR body and a branch registry.
- **Nginx reverse proxy** — TLS, HTTP/2, rate-limited webhook/API zones, WebSocket upgrade and a basic-auth-protected Flower dashboard.
- **Multimodal agents** — payment reconciliation, log analysis, GitHub Actions failure analysis, Dockerfile hardening (with auto-PR) and production incident triage over images, PDFs, CSVs, logs and ZIPs.
- **Bare-metal operations** — systemd units, a self-healing monitor daemon, journald log aggregation and the `orion` management CLI.

This project is independent of the workspace-root `backend/`, `frontend/` and `devops-platform/` stacks.

**Agent reference:** see [`../agents.md`](../agents.md) for every pipeline/multimodal agent, artifacts, string utilities, and extension guide.

## Architecture

```
GitHub push ──HMAC──▶ Nginx ──▶ FastAPI /api/v1/webhook/github ──▶ PostgreSQL (pipeline_runs: queued)
                                        │
                                        ▼
                              Redis ◀── Celery worker ──▶ PipelineOrchestrator
                                                             │
   1 Ingest (clone, diff, metadata)                          │
   2-4 FullScanOrchestrator ── concurrently ── Code ▸ Security ▸ QA
          │ blocked? ──▶ AutoPRService ──▶ fix PRs on GitHub ──▶ Slack
   5 Stress test (Locust vs staging)
   6 Approval (rule engine + Claude)
   7 Deployment (docker build/run, health check, rollback)
   8 Success ──▶ GitHub commit status + Slack
   9 Monitoring (Celery task: metrics + journald + Claude) ──▶ rollback / alert
                                                             │
                     Redis pub/sub ──▶ WebSocket /ws/pipeline/{id} ──▶ dashboard
```

Every stage persists a `pipeline_artifacts` row (JSONB on PostgreSQL), so each decision is auditable through the API.

The infrastructure is optional — each piece degrades to a local equivalent:

| Component | When available | Without it |
|-----------|----------------|------------|
| Redis + Celery | `PIPELINE_EXECUTOR=auto` queues runs on Celery; WebSocket events relay over Redis pub/sub | Runs execute inside the API process (bounded by `PIPELINE_INLINE_CONCURRENCY`), events go through an in-process bus, interrupted runs are marked `failed` on restart |
| Docker | `DEPLOY_MODE=auto` builds, runs and health-checks the container | **`simulate`**: records a successful deploy and runs a short simulated monitoring window (status **`deployed`**). Use **`DEPLOY_MODE=skip`** to end at **`approved`** instead. |
| PostgreSQL | Production database | SQLite (`sqlite+aiosqlite:///./orion.db`) |
| Anthropic key | Claude reviews every stage | Deterministic heuristics (`analysis_mode: "heuristic"`); a rejected key pauses LLM calls for 5 minutes and shows up in `/health` → `llm.status = auth_failed` |

## Security & production hardening

| Control | Development (default) | Production (`APP_ENV=production`) |
|---------|----------------------|----------------------------------|
| API auth | Open (`API_REQUIRE_AUTH=false`) | Auto-enabled — session **or** `X-ORION-API-Key` header |
| WebSocket | Open | Requires same auth (`?api_key=` query param supported) |
| `/health` | Full runtime diagnostics | Minimal payload (no integration details) |
| Webhook HMAC | Uses `GITHUB_WEBHOOK_SECRET` from `.env` | Placeholder secrets rejected at startup |
| Trigger dedup | Same repo+commit inflight runs return `status: duplicate` | Same |
| Clone URLs | Local git dirs allowed | **https:// only**, blocked private/metadata hosts |
| Secrets | Placeholders tolerated | Startup fails on default `SECRET_KEY`, session key, webhook secret |

Run the full cross-stack verification from the repo root:

```powershell
.\run_e2e_all.ps1 -Offline
```


- Python 3.11+ (3.12 also works) and `git`
- Optional: Docker (deployments), Redis 7 (Celery queue), PostgreSQL 15 (production database)
- GitHub account with webhook access (a token with `repo` scope enables commit statuses and Auto-PR)
- Anthropic API key (optional — without one every agent runs in heuristic mode and reports `analysis_mode: "heuristic"`)
- `pylint`, `bandit`, `pip-audit`, `pytest` and `locust` are installed from `requirements.txt` and always run through ORION's own interpreter (`python -m <tool>`)

## Local Quick Start (no Docker, Redis or PostgreSQL)

```bash
cd ai-cicd-pipeline
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                # SQLite + PIPELINE_EXECUTOR=auto + DEPLOY_MODE=auto
uvicorn app.main:app --port 8000
```

Open `http://localhost:8000/ui/`, enter a git URL (or, with `APP_ENV=development`, a local repository path) and press **Run Pipeline**. The dashboard streams agent logs over the WebSocket, shows the stage timeline, every artifact, and lets you retry or cancel runs. The same thing from a shell:

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/trigger \
     -H "Content-Type: application/json" \
     -d '{"clone_url": "https://github.com/owner/repo.git", "branch": "main"}'
```

To verify the whole pipeline on a machine, `python scripts/e2e_run.py` builds a sample repository, starts a staging service and ORION, and drives three real runs: a clean commit (`approved`, or `deployed` with Docker), a failing test (`blocked_tests`) and a vulnerable dependency (`blocked_security`). Add `--offline` to skip Anthropic calls and `--keep` to keep the temporary workspace.

## Full Quick Start (PostgreSQL, Redis, Celery)

```bash
git clone <your-fork-url> && cd ai-cicd-pipeline
cp .env.example .env              # fill in ANTHROPIC_API_KEY, GITHUB_*, SLACK_WEBHOOK_URL; switch DATABASE_URL to Postgres
docker compose up -d postgres redis
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000                                   # terminal 1
celery -A app.tasks.pipeline_tasks.celery_app worker --loglevel=info        # terminal 2
celery -A app.tasks.pipeline_tasks.celery_app beat --loglevel=info          # terminal 3 (stale-run sweeper)
```

Configure the GitHub webhook (repository → Settings → Webhooks → Add webhook):

| Field | Value |
|-------|-------|
| Payload URL | `http://your-server:8000/api/v1/webhook/github` (or `https://your-domain/api/v1/webhook/github` behind Nginx) |
| Content type | `application/json` |
| Secret | the value of `GITHUB_WEBHOOK_SECRET` |
| Events | Push events and Pull requests (PR events drive Auto-PR branch cleanup) |

API docs: `http://localhost:8000/docs`. The dashboard is served by the API at `http://localhost:8000/ui/` (`/` redirects there). It can also be hosted separately (`npx --yes serve frontend -p 5173`); it then talks to `http://localhost:8001` unless you open it with `?api=http://host:port` (remembered in localStorage, `?api=reset` clears it).

## Full Docker Setup

```bash
python scripts/generate_htpasswd.py      # writes nginx/.htpasswd for Flower (uses FLOWER_BASIC_AUTH_*)
docker compose up --build -d             # postgres, redis, app, worker, beat, flower, nginx
```

The `app` container runs `alembic upgrade head` before starting uvicorn. Nginx serves `nginx/conf.d/orion_dev.conf` (HTTP on :80) by default. For HTTPS:

```bash
bash nginx/generate_dev_ssl.sh           # self-signed cert in nginx/ssl/ (use real certs in production)
make prod-nginx                          # NGINX_SITE_CONF=orion.conf, recreates the nginx container
```

Useful targets: `make nginx-test`, `make nginx-reload`, `make nginx-logs`, `make docker-down`. Nginx access logs (`orion_log` format) land in `nginx/logs/` so they can be fed to the log analysis agent.

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `APP_ENV` | `development`, `test` or `production` | `development` |
| `APP_PORT` | API port (CLI and systemd use it) | `8000` |
| `SECRET_KEY` | Application secret | `orion-secret-key-min-32-chars-here` |
| `DATABASE_URL` | Async SQLAlchemy URL | `sqlite+aiosqlite:///./orion.db` or `postgresql+asyncpg://postgres:postgres@localhost:5432/aicicd` |
| `SYNC_DATABASE_URL` | Sync URL for Alembic, Celery and the monitor daemon | `sqlite:///./orion.db` or `postgresql://postgres:postgres@localhost:5432/aicicd` |
| `REDIS_URL` | Celery broker/result backend and WebSocket pub/sub (optional) | `redis://localhost:6379/0` |
| `PIPELINE_EXECUTOR` | `auto` (Celery if Redis answers, else inline), `celery` or `inline` | `auto` |
| `PIPELINE_INLINE_CONCURRENCY` | Max concurrent runs in the inline executor | `2` |
| `DEPLOY_MODE` | `auto` (Docker if daemon up, else simulate), `docker`, `simulate`, or `skip` | `auto` |
| `SQL_ECHO` | Log SQL statements | `false` |
| `CORS_ORIGINS` | Comma-separated dashboard origins | `http://localhost:5173` |
| `API_REQUIRE_AUTH` | Require GitHub OAuth session for retry/multimodal endpoints | `false` |
| `ANTHROPIC_API_KEY` | Claude API key; placeholder ⇒ heuristic mode | `sk-ant-...` |
| `ANTHROPIC_MODEL` | Default Claude model | `claude-sonnet-4-20250514` |
| `*_MODEL` | Per-agent overrides: `ORCHESTRATOR`, `CODE_ANALYSIS`, `SECURITY`, `QA`, `STRESS`, `APPROVAL`, `DEPLOYMENT`, `MONITORING`, `MULTIMODAL_PAYMENT`, `MULTIMODAL_GIT` | `claude-sonnet-4-20250514` |
| `MODEL_DEVICE_MODE` | Reserved for local model execution | `cpu` |
| `GITHUB_WEBHOOK_SECRET` | HMAC-SHA256 secret shared with GitHub | `a-long-random-string` |
| `GITHUB_TOKEN` | PAT for commit statuses, Auto-PR and run-log downloads | `ghp_...` |
| `GITHUB_OWNER` | Default owner for repository lookups | `your-github-username` |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | OAuth app for dashboard login | `Iv1.abc...` |
| `GITHUB_REDIRECT_URI` | OAuth callback | `http://localhost:8000/api/v1/auth/github/callback` |
| `SESSION_SECRET_KEY` | Signs the session cookie | `random-string` |
| `FRONTEND_URL` | Where OAuth redirects after login | `http://localhost:5173` |
| `OAUTH_TOKEN_EXPIRY_HOURS` | Session lifetime | `24` |
| `SLACK_WEBHOOK_URL` | Incoming webhook for pipeline, PR and triage alerts | `https://hooks.slack.com/services/...` |
| `STAGING_URL` | Base URL load-tested and health-checked after deploy | `http://localhost:8080` |
| `STAGING_HOST_PORT` / `STAGING_CONTAINER_PORT` | Port mapping for the deployed container | `8080` / `8000` |
| `CONTAINER_REGISTRY` | Registry prefix for built images | `registry.example.com` |
| `APP_NAME` | Image/container name of the deployed app | `orion-app` |
| `DEPLOY_ENVIRONMENT` | Label used in notifications | `staging` |
| `PIPELINE_WORKDIR` | Clone directory for pipeline runs (default `<system temp>/orion-pipeline`) | `/tmp/orion-pipeline` |
| `STALE_RUN_TIMEOUT_MINUTES` | Beat task marks stuck runs failed after this | `120` |
| `MAX_SECURITY_SEVERITY` | Highest tolerated security severity | `medium` |
| `STRESS_TEST_USERS` / `STRESS_TEST_SPAWN_RATE` / `STRESS_TEST_DURATION` | Locust parameters | `1000` / `50` / `60` |
| `MONITORING_POLL_INTERVAL_SECONDS` / `MONITORING_WINDOW_MINUTES` | Post-deploy monitoring cadence | `30` / `5` |
| `HEALTH_CHECK_TIMEOUT_SECONDS` | Deployment health-check budget | `180` |
| `JOURNALD_ENABLED` | Include journald error summaries in monitoring | `true` |
| `NGINX_MODE` | `development` or `production` | `development` |
| `NGINX_SITE_CONF` | Site config mounted by compose | `orion_dev.conf` / `orion.conf` |
| `FLOWER_BASIC_AUTH_USER` / `FLOWER_BASIC_AUTH_PASSWORD` | Credentials for `/flower/` | `admin` / `change-me` |

**Phases 1–5** (see root `README.md` and `.env.example`): `PROGRESSIVE_DELIVERY_*`, `SLO_*`, `POLICY_*`, `COMPLIANCE_PACKS`, `FINOPS_*`, `PROMPT_INJECTION_GATE_ENABLED`, `MODEL_ROUTER_ENABLED`, `PATCH_AUTO_PR_ENFORCEMENT`, `AGENT_EVAL_*`, `SMALL_MODEL_SLUG`, `DEVOPS_RAG_MAX_CHUNKS`.

Intelligence dashboard: `GET /api/v1/intelligence/dashboard` (also wired in the ORION UI **Intelligence** view).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirects to the dashboard |
| GET | `/ui/` | Dashboard (static `frontend/`) |
| GET | `/health` | Liveness probe plus runtime: `executor`, `redis`, `deploy_mode`, `llm` (`status` = `ok`, `unverified`, `auth_failed`, `error` or `disabled`), `github`, `slack` |
| POST | `/api/v1/pipeline/trigger` | Start a run without a webhook: `clone_url`, `branch` (default `main`), optional `repo_full_name`; the branch head is resolved with `git ls-remote`; local paths only outside production |
| GET | `/api/v1/pipeline/health` | Pipeline API health (used by Nginx/Docker health checks) |
| POST | `/api/v1/webhook/github` | GitHub webhook (push, ping, pull_request); HMAC-verified |
| POST | `/api/v1/webhook/github/pr` | Dedicated pull_request webhook for Auto-PR branch cleanup |
| GET | `/api/v1/pipeline/runs` | List runs (`status`, `branch`, `repo`, `limit`, `offset`) |
| GET | `/api/v1/pipeline/runs/{id}` | Run details |
| GET | `/api/v1/pipeline/runs/{id}/artifacts` | All artifacts of a run |
| GET | `/api/v1/pipeline/runs/{id}/artifacts/{type}` | Latest artifact of a type, including raw tool output |
| POST | `/api/v1/pipeline/runs/{id}/retry` | Re-queue a blocked/failed/rejected run (409 otherwise) |
| POST | `/api/v1/pipeline/runs/{id}/cancel` | Cancel a non-terminal run |
| POST | `/api/v1/multimodal/analyze` | Multipart upload; `agent_type` = `payment`, `log_analysis`, `github_actions`, `dockerfile`, `production_triage`, `git_logs` |
| POST | `/api/v1/multimodal/triage` | Production incident triage; Slack alert on P1/P2 |
| POST | `/api/v1/multimodal/git-logs` | Git operation log analysis |
| POST | `/api/v1/multimodal/payment` | Payment failure analysis (`reconcile=true` adds a reconciliation report) |
| GET | `/api/v1/auth/github` | Start GitHub OAuth login |
| GET | `/api/v1/auth/github/callback` | OAuth callback |
| GET | `/api/v1/auth/me` | Current session user |
| GET | `/api/v1/auth/status` | Whether OAuth is configured / logged in |
| GET | `/api/v1/auth/logout` | Clear the session |
| WS | `/ws/pipeline/{id}` | Live stage updates for a run |

`/api/v1/multimodal/analyze` accepts `files` (repeatable), `text_input`, optional `pipeline_run_id` (persists the result as an artifact), `log_type` (`server_timeout`, `build_error`, `git_operation`, `deployment_crash`, `memory_leak`), and for GitHub/Dockerfile agents `repo_full_name`, `clone_url`, `branch`, `dockerfile_path`, `github_run_id`. Uploads are limited to 25 MB each.

## Agent Pipeline Stages

1. **Ingestion** — clones the pushed commit, records metadata, diff and changed files; sets a `pending` commit status. Blocks only on clone failure (run → `failed`).
2. **Code analysis** — pylint + AST metrics on changed Python files, reviewed by Claude. Blocks (`blocked_code`) on severity `fail` (heuristic: ≥3 pylint errors).
3. **Security** — bandit plus pip-audit (PyPI/OSV advisories for exact `==` pins in `requirements.txt`) enriched by Claude. Unpinned requirements are listed as `not_audited`, and a scanner that fails to run is reported in the summary instead of passing silently. Blocks (`blocked_security`) when the highest severity exceeds `MAX_SECURITY_SEVERITY`; the LLM can never downgrade scanner severity.
4. **QA** — runs the repository's pytest suite with a JSON report and maps failures to files. Blocks (`blocked_tests`) on real test failures; missing tests or tooling errors are warnings.
   - Stages 2–4 run concurrently. If any blocks, Auto-PR generates fixes and the run becomes `blocked_with_prs_sent` when PRs were opened.
5. **Stress test** — Locust against `STAGING_URL`. Blocks (`blocked_stress`) when error rate > 5% or p95 > 2000 ms; warns above 1% / 1000 ms or if staging is unreachable.
6. **Approval** — hard rule engine (code fail, security above threshold, test or load failure ⇒ reject) followed by a Claude risk review. Blocks with `rejected`.
7. **Deployment** — `docker build`/`run`, health checks against staging and automatic rollback to the previous image. Ends as `rolled_back` or `failed` on error. With `DEPLOY_MODE=auto` and no Docker daemon, deployment is **simulated** (artifact `deployment_info.simulated=true`) and the run continues to monitoring. Set `DEPLOY_MODE=skip` to end at `approved` with GitHub status "All gates passed (deployment skipped)".
8. **Success** — status `deployed`, GitHub `success` status and Slack notification.
9. **Monitoring** — background task polls health, error rates and journald summaries; Claude recommends `monitor`, `alert` or `rollback`.

## Running Tests

```bash
pytest tests/ -v                  # 124 tests, fully offline (SQLite, mocked Claude/GitHub/Slack)
python scripts/verify_imports.py  # imports every app module
python scripts/smoke_test.py      # boots the API, sends a signed webhook, verifies the run is recorded
```

`smoke_test.py --with-queue` enqueues to the real Celery broker, and `--url http://host:8000 --secret <webhook-secret>` checks an existing deployment.

## Monitoring

- **Flower**: `http://localhost:5555` (direct) or `https://your-domain/flower/` behind Nginx (basic auth).
- **Logs**: `orion logs api -f`, `orion logs worker --json`, or `journalctl -u orion-api`.
- **Monitor daemon** (`orion-monitor.service`): every 60 s it restarts inactive ORION services (with a 120 s cooldown), vacuums the journal when `/var/log/orion` has < 500 MB free, restarts the API above 2 GB RSS and alerts Slack when PostgreSQL is unreachable.

## Operations CLI

Installed as `/usr/local/bin/orion` by the systemd installer. Every command accepts `--json`.

| Command | Description |
|---------|-------------|
| `orion status` | Active state, PID, memory and uptime of all units (exit 3 if any is down) |
| `orion restart [api\|worker\|beat\|monitor\|all]` | Restart services |
| `orion logs [service] [-n 100] [-f]` | journald logs |
| `orion deploy [repo_path]` | Trigger a pipeline for a local git checkout via a signed webhook |
| `orion health` | Call the pipeline health endpoint |
| `orion db-migrate` | `alembic upgrade head` |
| `orion workers` | Celery workers via Flower (falls back to `celery inspect ping`) |
| `orion backup-db [--output-dir DIR]` | `pg_dump` to `/var/lib/orion/backups/orion_<timestamp>.sql` |

## Production Deployment

Tested target: Ubuntu 22.04/24.04 or Debian 12 with PostgreSQL 15 and Redis 7 reachable from the host.

```bash
# 1. Prerequisites
sudo apt-get update
sudo apt-get install -y git python3.11 python3.11-venv rsync postgresql-client redis-tools docker.io
sudo -u postgres createdb aicicd            # or point DATABASE_URL at a managed database

# 2. Get the code
git clone <your-fork-url> ~/orion-src && cd ~/orion-src/ai-cicd-pipeline
cp .env.example .env
nano .env                                    # APP_ENV=production, real DATABASE_URL/SYNC_DATABASE_URL, REDIS_URL,
                                             # ANTHROPIC_API_KEY, GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET,
                                             # SLACK_WEBHOOK_URL, FLOWER_BASIC_AUTH_PASSWORD

# 3. Install: creates the orion user, /opt/orion venv, /etc/orion/orion.env (600), runs migrations,
#    installs + starts orion-api/worker/beat/monitor, installs and enables Nginx, links /usr/local/bin/orion
sudo bash scripts/install_systemd.sh

# 4. TLS (recommended): place certs, then re-run the installer to switch Nginx to orion.conf
sudo mkdir -p /etc/nginx/ssl
sudo cp fullchain.pem privkey.pem /etc/nginx/ssl/
sudo bash scripts/install_systemd.sh

# 5. Verify
orion status
orion health
curl -fsS http://localhost/api/v1/pipeline/health
sudo nginx -t
```

6. **Configure the GitHub webhook**: Payload URL `https://your-domain/api/v1/webhook/github`, content type `application/json`, secret = `GITHUB_WEBHOOK_SECRET`, events **Push** and **Pull requests**. GitHub sends a `ping`; the delivery log should show `200`.

7. **First pipeline run**:

```bash
git commit --allow-empty -m "ORION first run" && git push      # in the watched repository
orion logs worker -f                                            # follow the agents
curl -s http://localhost/api/v1/pipeline/runs?limit=1 | python3 -m json.tool
# or trigger without pushing:  orion deploy /path/to/local/checkout
```

**Updating**: `sudo ORION_SRC_DIR=~/orion-src/ai-cicd-pipeline bash scripts/update_orion.sh` pulls, syncs, reinstalls dependencies when `requirements.txt` changes, migrates and reloads the API gracefully (uvicorn ≥ 0.30 restarts workers on SIGHUP). **Removing**: `sudo bash scripts/uninstall_systemd.sh`.

## Project Layout

- `app/` — FastAPI app: `agents/` (pipeline + `multimodal/`), `services/` (git, GitHub, Slack, Auto-PR, journald), `api/routes/`, `tasks/` (Celery), `daemon/` (monitor)
- `alembic/` — migrations (PostgreSQL in production, SQLite supported for local development)
- `nginx/` — `nginx.conf`, `conf.d/orion.conf` (TLS) and `orion_dev.conf`, host snippet, dev-cert script
- `systemd/` — `orion-api`, `orion-worker`, `orion-beat`, `orion-monitor` units
- `scripts/` — installer/updater/uninstaller, `orion_cli.py`, `generate_htpasswd.py`, `verify_imports.py`, `smoke_test.py`, `e2e_run.py`
- `frontend/` — single-page dashboard
- `tests/` — pytest suite and fixtures

## License

Proprietary — internal ORION distribution.
