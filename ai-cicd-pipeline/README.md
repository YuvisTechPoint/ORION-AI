# ORION — Autonomous AI CI/CD Pipeline

ORION is a FastAPI + Celery + PostgreSQL + Redis system that ingests GitHub webhooks, runs multi-agent analysis (code, security, QA), can open automated fix pull requests, performs gated approval, deploys with Docker, and streams live updates over WebSockets backed by Redis.

## Quick start (local)

1. Start PostgreSQL 15 and Redis 7 (or `docker compose up -d postgres redis`).
2. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`, `GITHUB_*`, and database URLs.
3. `pip install -r requirements.txt`
4. `alembic upgrade head`
5. `make dev` (API on port 8001) and `make worker` in another terminal.
6. Serve `frontend/index.html` on port 5173 (for example `npx --yes serve frontend -p 5173`).

Open `http://localhost:8001/docs` for the API and the frontend console at `http://localhost:5173`.

## Docker

`docker compose up --build` brings up Postgres, Redis, API, Celery worker, Flower, and Nginx. Generate TLS material with `bash nginx/generate_dev_ssl.sh` before enabling the HTTPS `orion.conf` include in `nginx/nginx.conf`.

## Project layout

- `app/` — FastAPI application, agents, services, tasks, daemon
- `alembic/` — database migrations
- `frontend/` — single-page DevOps console (`index.html`)
- `nginx/` — reverse proxy configs for dev and production TLS
- `systemd/` — unit files for bare-metal installs
- `scripts/` — CLI, smoke tests, install helpers

## License

Proprietary — internal ORION distribution.
