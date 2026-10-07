# Binary-v2 / ORION — Architecture Audit (Phase 0)

**Audit date:** 2026-10-06  
**Scope:** Full repository baseline before roadmap Phases 1–29  
**Method:** Recursive code inspection, test execution, doc-vs-code comparison  
**Rule:** Capabilities listed here are evidenced in code unless marked *documented only*.

---

## 1. Executive summary

Binary-v2 is a **three-stack DevOps platform** plus a static **Command Hub**:

| Stack | Path | API | UI | Role |
|-------|------|-----|-----|------|
| Command Hub | `hub/` | — | `:5180` | Health-aware launcher + cross-stack intelligence readout |
| Canonical DevOps | `backend/` + `frontend/` | `:8000` | `:5173` | Submit-code / archive / GitHub zip pipelines |
| ORION CI/CD | `ai-cicd-pipeline/` | `:8001` | `:8001/ui/` | Primary production-oriented 9-stage webhook pipeline |
| DevOps Platform | `devops-platform/` | `:8002` | `:3000` | Celery-backed QA + stress + deploy agents |

**Primary implementation surface:** `ai-cicd-pipeline/` (~242 tests, Alembic migrations, 64 artifact types, phase 1–5 enrichment modules).

**Command Hub today:** launcher + read-only intelligence aggregation — **not** a unified control plane (no federated API, auth, or pipeline control).

**Documentation drift:** `agents.md` §69 marks Phases 1–5 ✅ in ORION, but Part II §58–§67 still marks many shipped ORION capabilities as 📋. Treat **code + tests** as source of truth.

---

## 2. Repository topology

```
Binary-v2/
├── hub/                    # Static Command Hub (hub.js, stacks.json)
├── config/stacks.json      # Canonical stack catalog (ORION navigation API consumes)
├── backend/                # Canonical FastAPI
├── frontend/               # Canonical React (Vite :5173)
├── ai-cicd-pipeline/       # ORION primary stack
├── devops-platform/        # Platform stack (backend + frontend)
├── e2e/                    # Playwright (hub smoke only)
├── observability/          # Grafana JSON + README (no Prometheus bundle)
├── scripts/                # run_all_stacks.ps1, run_e2e_all.ps1, root orion_cli (ops)
└── agents.md               # Master reference (~3500 lines)
```

---

## 3. ORION CI/CD (`ai-cicd-pipeline/`)

### 3.1 Pipeline flow

```
GitHub push / POST /api/v1/pipeline/trigger
  → PipelineOrchestrator
      1. Ingestion (clone, diff, metadata)
      2–4. FullScanOrchestrator (parallel: Code, Security, QA)
      Phase 1 enrichment + secrets gate
      Phase 2 enrichment
      5. StressTestAgent (Locust)
      Change risk artifact
      Phase 4 pre-enrichment (policy eval, no block)
      6. ApprovalAgent
      Phase 4 policy gate
      Phase 5 enrichment (+ optional agent eval gate)
      Release passport, PR intelligence
      7. DeploymentAgent (docker | simulate | skip | auto)
      Phase 3 observability post-deploy
      8. MonitoringAgent (background)
```

### 3.2 API surface (40+ routes)

Routers under `/api/v1`: `auth`, `webhook`, `pipeline`, `text_tools`, `intelligence`, `runtime`, `multimodal`.  
Root: `/health`, `/ready`, `/metrics`, `WS /ws/pipeline/{id}`, static `/ui`.

### 3.3 Agents

**Pipeline:** CodeAnalysis, Security, QA, StressTest, Approval, Deployment, Monitoring, SoftwareEngineer, FullScanOrchestrator, PipelineOrchestrator.

**Multimodal:** Log, GitHubLog, GitLog, Payment, Dockerfile, ProductionTriage.

### 3.4 Persistence

| Model | Table |
|-------|-------|
| `PipelineRun` | `pipeline_runs` |
| `PipelineArtifact` | `pipeline_artifacts` |
| `WebhookDelivery` | `webhook_deliveries` |

Migrations: `001_initial`, `002_webhook_deliveries`.

### 3.5 Execution

- `PIPELINE_EXECUTOR`: `auto` | `celery` | `inline`
- Celery tasks: `run_pipeline`, `run_monitoring`, `reap_stale_runs`
- Redis pub/sub for cross-process WebSocket relay

### 3.6 Phase enrichment (ORION-extended)

| Layer | Service | Key utils |
|-------|---------|-----------|
| P1 | `phase1_enrichment.py` | change_risk, service_graph, sbom, secrets, container/iac, test_intelligence, release_passport |
| P2 | `phase2_enrichment.py` | fix_loop, patch_confidence, contract_testing, test_generation, progressive_delivery, preview_env |
| P3 | `phase3_enrichment.py` | evidence_graph, rca, incident_commander, otel_context, error_budget, synthetic, chaos |
| P4 | `phase4_enrichment.py` | policy_engine, compliance, signed_builds, tenant_rbac, finops, audit_explorer, fleet, SSO readiness |
| P5 | `phase5_enrichment.py` | agent_registry, permissions, sandbox, model_router, prompt_registry, agent_eval, decision_ledger, devops_rag, prompt_injection |

**Maturity:** Real scanners (bandit, pip-audit, pylint, pytest, Locust, Docker) on core path. Many phase utils are **heuristic/report-only** (see FEATURE_MATRIX.md).

---

## 4. Canonical stack (`backend/` + `frontend/`)

### 4.1 Entry points

- `POST /submit-code`, `/submit-archive`, `/submit-github`
- `GET /pipeline-status/{id}`, `/pipelines`, retry/resume/cancel/audit
- `POST /analyze-logs`, `WS /ws/analyze-logs`, `WS /ws/pipeline-status/{id}`
- OAuth GitHub session auth
- Intelligence: `GET /api/v1/intelligence/dashboard` only

### 4.2 Agents

LLM/heuristic pipeline agents (no bandit/pylint/Locust/Docker). QA via `qa_runner.py` when `QA_MODE=real` (default **simulated**).

### 4.3 Persistence

JSON blob state in `pipelines` table (SQLite/Postgres). SQLAlchemy models `PipelineRun`/`StageResult`/`LogEntry` exist but appear **unused**. No Alembic.

### 4.4 Frontend gaps

`AnalyzerModals.jsx` calls `/api/v1/multimodal/git-logs` and `/payment` — **routes not implemented** on canonical backend (ORION has them).

---

## 5. DevOps Platform (`devops-platform/`)

- Sequential pipeline runner with resume
- Agents: CodeAnalysis, Security, QA, Stress, Approval, Deployment, Monitoring
- `POST /api/multimodal/analyze` **proxies to ORION**
- Port **8002** in multi-stack launcher (docker-compose still documents 8000)
- 28 pytest cases

---

## 6. Command Hub (`hub/`)

- Serves static UI on `:5180`
- Polls health + intelligence from three stacks every 15s
- Opens stack UIs in new tabs
- Uses `hub/stacks.json` (not `config/stacks.json`)
- No write/control APIs

---

## 7. Shared cross-stack patterns

| Pattern | Canonical | ORION | Platform |
|---------|-----------|-------|----------|
| Gate fusion | ✅ | ✅ | ✅ |
| SLO + Slack alerts | ✅ | ✅ | ✅ |
| Text analyze API | ✅ | ✅ | ✅ (no `/v1`) |
| Webhook ledger | ✅ | ✅ | partial |
| Intelligence dashboard | minimal | full | moderate |
| Multimodal agents | 2 routes | 4 routes | proxy to ORION |

Duplicated modules: `text_analysis.py`, gate fusion, SLO, multimodal agent classes — intentional parity, maintenance cost.

---

## 8. Observability

| Component | Status |
|-----------|--------|
| ORION `/metrics` | Rich Prometheus (HTTP, pipeline, webhooks) |
| Canonical `/metrics` | Moderate |
| Platform `/metrics` | Stub (`devops_platform_up 1`) |
| Grafana dashboard JSON | Manual import only |
| Prometheus in-repo | **Not bundled** |
| OpenTelemetry export | Artifact stub only (`otel_context.py`) |
| `correlation_id` | **Not implemented** in app code |
| `trace_id` | Synthetic in OTEL artifact only |

---

## 9. Background workers & integrations

| Integration | ORION | Canonical | Platform |
|-------------|-------|-----------|----------|
| PostgreSQL | ✅ | optional | ✅ |
| Redis/Celery | ✅ | optional memory queue | ✅ |
| GitHub webhooks | ✅ | ✅ | ✅ |
| Slack | ✅ | ✅ | ✅ |
| Docker deploy | ✅ | ❌ | ✅ |
| Anthropic LLM | ✅ | optional HF/OpenAI | optional |

---

## 10. Test baseline (2026-10-06)

| Suite | Command | Result |
|-------|---------|--------|
| ORION | `ai-cicd-pipeline/tests/` | **242 passed** |
| Canonical | `PYTHONPATH=backend pytest backend/tests/` | **54 passed** |
| Platform | `PYTHONPATH=devops-platform/backend pytest devops-platform/tests/` | **28 passed** |
| **Total** | | **324 passed** |

Playwright (`e2e/`): 5 smoke tests (hub cards + optional `/ready`); does not validate pipelines.

Static analysis: no repo-wide pylint/ruff/mypy CI gate configured; individual stacks use pytest.

---

## 11. Critical code findings

### 11.1 ORION WebSocket handler missing imports

`app/main.py` uses `channel_for`, `event_bus`, and `redis_available` in `pipeline_ws` without importing `channel_for` / `event_bus` from `app.services.events`. `redis_available` is only imported inside `/health`. **Live WebSocket connections likely raise `NameError` at runtime** — no WS tests exist.

### 11.2 Canonical frontend/backend contract mismatch

Git-log and payment multimodal routes missing on `:8000`.

### 11.3 Config duplication

Three stack catalogs: `config/stacks.json`, `hub/stacks.json`, hardcoded fallbacks in `hub.js` and platform frontend.

### 11.4 Root `scripts/orion_cli.py`

Production systemd tool defaulting to `:8000`; developer CLI is `ai-cicd-pipeline/scripts/orion_cli.py` on `:8001`.

---

## 12. Architecture strengths (preserve)

- Artifact-as-source-of-truth model with typed `VALID_ARTIFACT_TYPES`
- Gate fusion + hard security gates (scanner severity not LLM-downgradable)
- Webhook idempotency ledger
- Auto-PR with category branches
- Resume/retry/cancel with checkpoint artifacts
- Heuristic fallback when LLM unavailable
- Three-stack independence with shared intelligence contract
- ORION CLI developer commands (scan, test, risk, explain, fix, deploy --canary)

---

## 13. Recommended next architectural move

Per roadmap **Phase 1 (Unified ORION Control Plane)**: extend Command Hub + `config/stacks.json` into federated pipeline/artifact/audit views **via adapters**, without monolith merge. Fix ORION WebSocket imports and canonical multimodal route parity as P0 hygiene.

---

*Generated by Phase 0 repository audit. See also: FEATURE_MATRIX.md, API_CONTRACT_MATRIX.md, SECURITY_GAP_REPORT.md, TECHNICAL_DEBT.md, IMPLEMENTATION_BACKLOG.md.*
