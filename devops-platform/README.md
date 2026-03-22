# Multi-Agent DevOps Automation Platform

Production-oriented stack: **FastAPI** (async SQLAlchemy), **Celery** + **Redis**, **PostgreSQL**, **Anthropic** agents with JSON contracts, **React 18 + Vite + TypeScript + Tailwind**, WebSockets for live pipeline logs.

## Prerequisites

- Docker & Docker Compose
- Or locally: Python 3.11+, Node 20+, PostgreSQL 15, Redis 7

## Quick start (Docker)

1. Copy environment file:

   ```bash
   cp .env.example .env
   ```

2. Set `ANTHROPIC_API_KEY` (required for LLM agents). Optional: `GITHUB_TOKEN` for higher GitHub API rate limits.

3. From `devops-platform/`:

   ```bash
   docker compose up --build
   ```

4. Open the UI at **http://localhost:3000** and the API at **http://localhost:8000**.

5. Health check: **GET** `http://localhost:8000/health`

## Local development (without Docker frontend container)

- Backend API: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000`
- Celery worker: `cd backend && celery -A app.celery_app worker --loglevel=info`
- Frontend: `cd frontend && npm install && npm run dev` (uses Vite on port 3000)

Point the frontend at your API with `VITE_API_URL` and `VITE_WS_URL` (see `.env.example`).

## Tests

From `devops-platform/` (uses SQLite for tests):

```bash
pip install -r backend/requirements.txt
pytest
```

## Layout

- `backend/app` — FastAPI app, agents, orchestrator, routers
- `frontend/src` — React UI, WebSocket hook, REST client
- `tests/` — pytest (webhooks, orchestrator security gate, security agent)

## API highlights

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/pipeline/trigger` | Start pipeline for a GitHub repo URL |
| GET | `/api/pipeline/{id}` | Pipeline detail, logs, stage results |
| GET | `/api/pipeline/{id}/status` | Lightweight status |
| WS | `/ws/{pipeline_id}` | Real-time log/status events |
| POST | `/webhook/github` | GitHub webhook (HMAC when secret set) |

## License

Proprietary / your license.
