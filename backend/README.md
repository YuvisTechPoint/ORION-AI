# Multi-Agent, Multi-Modal DevOps Automation Platform (Backend)

Production-ready prototype backend using FastAPI + modular agent architecture.

## 1. Project Setup

```text
backend/
  agents/
    base.py
    code_analysis.py
    security.py
    pipeline.py
    deployment.py
    monitoring.py
  core/
    config.py
    llm_client.py
    logging_config.py
    queue.py
  api/
    routes.py
  services/
    orchestrator.py
    state_store.py
  models/
    schemas.py
  main.py
  requirements.txt
  .env.example
  Dockerfile
frontend/
samples/
  submit_code_request.json
  logs.txt
docker-compose.yml
```

## 2. Core LLM Client

`core/llm_client.py` contains `LLMClient`:
- API key based
- Generic endpoint/model configuration
- Strict JSON expectation
- Safe fallback JSON when API key is missing or request fails

This keeps agent logic prompt-driven and makes RAG replacement straightforward.

## 3. Agent Implementations

Implemented independent prompt-driven agents:
- `CodeAnalysisAgent`
- `SecurityAgent`
- `PipelineAgent`
- `DeploymentAgent`
- `MonitoringAgent`

Each agent:
- Accepts multi-modal text inputs (code, logs, config text)
- Uses its own prompt template
- Returns strict JSON
- Inherits extension hook from `BaseAgent` for future memory, tools, and retrieval context

## 4. Orchestrator

`services/orchestrator.py` runs full workflow:
1. Developer submits code
2. Code analysis runs
3. Security scan runs
4. High severity findings block pipeline
5. QA simulation pass/fail
6. Stress simulation pass/fail
7. Approval decision via Pipeline Agent
8. Deployment decision via Deployment Agent
9. Final state persisted in SQLite

Also supports:
- Manual deployment trigger
- Monitoring analysis for logs
- Event publication through switchable queue backend (in-memory or Redis)

## 5. API Layer

Endpoints:
- `POST /submit-code`
- `GET /pipeline-status/{id}`
- `POST /trigger-deployment`
- `POST /analyze-logs`
- `POST /api/v1/multimodal/analyze`
- `POST /api/v1/multimodal/triage`

### Multimodal Notes

- `analyze` supports `agent_type` values:
  - `payment`
  - `log_analysis`
  - `github_actions`
  - `docker`
  - `production_triage`
- For `docker`, if high/critical findings exist and `repo_full_name` + `GITHUB_TOKEN` are present, ORION opens a remediation PR automatically.
- For `triage`, if response contains `escalate_to_human=true`, ORION posts a Slack escalation when `SLACK_WEBHOOK_URL` is configured.

## 6. Sample Run

### Local Run

1. Create env file:
```bash
cp .env.example .env
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Start API:
```bash
uvicorn main:app --reload
```

4. Submit code sample:
```bash
curl -X POST http://127.0.0.1:8000/submit-code \
  -H "Content-Type: application/json" \
  -d @../samples/submit_code_request.json
```

5. Query status:
```bash
curl http://127.0.0.1:8000/pipeline-status/<PIPELINE_ID>
```

6. Analyze logs:
```bash
curl -X POST http://127.0.0.1:8000/analyze-logs \
  -H "Content-Type: application/json" \
  -d "{\"logs\": \"$(cat ../samples/logs.txt)\"}"
```

### Docker Run (full stack)

From workspace root:
```bash
docker compose up --build
```

API available at `http://localhost:8000`.
Dashboard available at `http://localhost:5173`.

## Queue Backend

In .env:
- QUEUE_BACKEND=memory
- QUEUE_BACKEND=redis
- REDIS_URL=redis://redis:6379/0

State store options:
- DATABASE_URL=sqlite:///./devops_platform.db
- DATABASE_URL=postgresql://devops:devops@postgres:5432/devops

Agent context options:
- AGENT_MEMORY_ENABLED=false
- RETRIEVER_BACKEND=none

## Multi-Modal Envelope

`SubmitCodeRequest` and `AnalyzeLogsRequest` also accept `multimodal_inputs` entries:
- `code`
- `log`
- `config`
- `image_ref` (future placeholder)
- `metrics` (future placeholder)

## Realism Notes

- LLM reasoning is used for agent decisions and findings.
- Deterministic rules in `core/rule_engine.py` augment quality/security checks for predictable baseline detection.

## Tests

Run from backend folder:
```bash
pytest
```

## Runtime Ops Checks

- `GET /runtime-config` returns effective runtime modes and infra check results.
- `python scripts/preflight_check.py` prints the same report and exits non-zero on failed required checks.

## Example Output (submit-code)

```json
{
  "pipeline_id": "4f26ec07-c2df-4a11-b4ca-ad7d3d8f0190",
  "current_stage": "completed",
  "status": "completed"
}
```

## Notes on Future-Ready Design

The architecture is prepared for:
- Per-agent RAG augmentation (hook in `BaseAgent._prepare_payload`)
- Vector DB integration (FAISS/Pinecone) by plugging retrieval step before prompt build
- Tool usage per agent through `tools` contract in `BaseAgent`
- Agent memory toggle and context enrichment

No business-critical flow is hardcoded inside prompt templates; agents remain replaceable components.
