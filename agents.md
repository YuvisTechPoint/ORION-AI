# ORION / Binary-v2 — Master Agents & Platform Reference

> **Document class:** Production architecture, operations reference, and strategic expansion roadmap  
> **Audience:** Platform engineers, SRE, security reviewers, agent extenders, product/architecture stakeholders  
> **Coverage:** Implemented baseline (Hub + 3 stacks) + target AI-native DevSecOps/SRE control plane  
> **Positioning:** **ORION — AI-Native Software Delivery & Reliability Control Plane**  
> **Repository:** `Binary-v2` — shared venv `.venv/`, verify via `.\run_e2e_all.ps1 -Offline`

**Binary-v2** (branded **ORION** in the CI/CD stack) is a multi-stack, AI-assisted DevOps automation platform. It combines autonomous pipeline agents, multimodal analysis APIs, cross-stack intelligence, webhook idempotency, checkpoint resume, SLO alerting, and production-oriented security controls.

> **Quick reference (§1–§23 baseline):** [`docs/AGENTS_QUICKREF.md`](docs/AGENTS_QUICKREF.md) — portable architecture summary.  
> **This file** is the full reference (§1–§47 baseline + §48–§71 expansion roadmap).

**This document has two parts:**

| Part | Sections | Purpose |
|------|----------|---------|
| **Part I — Baseline** | §1–§47 | What is **implemented today** (agents, APIs, schemas, runbooks) |
| **Part II — Expansion** | §48–§71 | Strategic evolution toward an **AI-native DevSecOps/SRE control plane** |

**Status legend (Part II):** `✅` shipped · `🔄` partial foundation · `📋` planned · `🚫` explicitly deferred

### Document conventions

| Symbol | Meaning |
|--------|---------|
| **ORION** | `ai-cicd-pipeline/` stack (primary production CI/CD) |
| **Canonical** | `backend/` + `frontend/` stack |
| **DevOps** | `devops-platform/` stack |
| **Hub** | `hub/` Command Hub launcher |
| `✅` / `—` | Feature present / not present in that stack |
| `🔄` / `📋` | Partial foundation / planned (Part II) |
| **Gate** | Hard or soft block before deployment |
| **Artifact** | JSON persisted to DB or in-memory state |

---

## Table of contents

### Core platform

1. [Vision, scope & design principles](#1-vision-scope--design-principles)
2. [System design overview](#2-system-design-overview)
3. [Stack topology & ports](#3-stack-topology--ports)
4. [Pipeline architecture (all stacks)](#4-pipeline-architecture-all-stacks)
5. [Autonomous agents (complete catalog)](#5-autonomous-agents-complete-catalog)
6. [Multimodal agents](#6-multimodal-agents)
7. [Orchestration, lifecycle & control plane](#7-orchestration-lifecycle--control-plane)

### APIs & protocols

8. [API reference (unified)](#8-api-reference-unified)
9. [Cross-stack intelligence & gate fusion](#9-cross-stack-intelligence--gate-fusion)
10. [WebSocket protocol reference](#24-websocket-protocol-reference)
11. [Pipeline state machines](#25-pipeline-state-machines)
12. [Artifact schema registry](#26-artifact-schema-registry)
13. [HTTP error catalog](#41-http-error-catalog)

### Security & compliance

14. [Security conduct & trust boundaries](#10-security-conduct--trust-boundaries)
15. [Encrypted & hardened deployment plan](#11-encrypted--hardened-deployment-plan)
16. [Authentication & RBAC deep dive](#30-authentication--rbac-deep-dive)
17. [Rate limiting & edge security (nginx)](#31-rate-limiting--edge-security-nginx)

### Operations & observability

18. [Observability, SLO & operations](#12-observability-slo--operations)
19. [Health vs readiness field reference](#33-health-vs-readiness-field-reference)
20. [Gate fusion algorithm (full)](#35-gate-fusion-algorithm-full)
21. [SLO & intelligence formulas](#36-slo--intelligence-formulas)
22. [Operational runbooks](#45-operational-runbooks)

### Data & advanced subsystems

23. [Data model & persistence](#13-data-model--persistence)
24. [Text analysis utilities](#14-text-analysis-utilities)
25. [Agent memory & hybrid retriever](#38-agent-memory--hybrid-retriever)
26. [Heuristic & LLM fallback matrix](#37-heuristic--llm-fallback-matrix)
27. [Celery & executor matrix](#32-celery--executor-matrix)

### Integration & remediation

28. [Auto-PR advanced runbook](#27-auto-pr-advanced-runbook)
29. [Deployment & rollback deep dive](#28-deployment--rollback-deep-dive)
30. [Monitoring agent specification](#29-monitoring-agent-specification)
31. [GitHub integration reference](#43-github-integration-reference)
32. [Integrations (GitHub, Slack, Docker, Celery)](#17-integrations-github-slack-docker-celery)

### UI, testing & infra

33. [User interfaces & Command Hub](#15-user-interfaces--command-hub)
34. [Command Hub & frontend routing spec](#34-command-hub--frontend-routing-spec)
35. [Configuration reference](#16-configuration-reference)
36. [Testing & E2E verification matrix](#39-testing--e2e-verification-matrix)
37. [Docker Compose topologies](#40-docker-compose-topologies)
38. [Launchers & scripts](#19-launchers--scripts)

### Reference appendices

39. [Multimodal agent schema catalog](#42-multimodal-agent-schema-catalog)
40. [Audit trail & operator actions](#44-audit-trail--operator-actions)
41. [Feature completion matrix](#20-feature-completion-matrix)
42. [Extension guide](#21-extension-guide)
43. [Suggested roadmap & ops technology](#22-suggested-roadmap--ops-technology)
44. [Glossary](#46-glossary)
45. [Quick reference cards](#47-quick-reference-cards)
46. [Related documentation](#23-related-documentation)

### Part II — Strategic expansion (AI-native control plane)

48. [Executive assessment & maturity model](#48-executive-assessment--maturity-model)
49. [Strategic positioning](#49-strategic-positioning)
50. [Six control planes architecture](#50-six-control-planes-architecture)
51. [Baseline → target mapping](#51-baseline--target-mapping)
52. [Feature Group A — Intelligent Risk Engine](#52-feature-group-a--intelligent-risk-engine)
53. [Feature Group B — Advanced DevSecOps & supply chain](#53-feature-group-b--advanced-devsecops--supply-chain)
54. [Feature Group C — AI code engineering & test intelligence](#54-feature-group-c--ai-code-engineering--test-intelligence)
55. [Feature Group D — Release engineering & progressive delivery](#55-feature-group-d--release-engineering--progressive-delivery)
56. [Feature Group E — SRE & incident intelligence](#56-feature-group-e--sre--incident-intelligence)
57. [Feature Group F — Observability 2.0 & error budgets](#57-feature-group-f--observability-20--error-budgets)
58. [Feature Group G — AI governance & agent safety](#58-feature-group-g--ai-governance--agent-safety)
59. [Feature Group H — Policy-as-code & compliance](#59-feature-group-h--policy-as-code--compliance)
60. [Feature Group I — Cost & FinOps intelligence](#60-feature-group-i--cost--finops-intelligence)
61. [Feature Group J — Repository intelligence & DevOps RAG](#61-feature-group-j--repository-intelligence--devops-rag)
62. [Feature Group K — Environment, chaos & DR intelligence](#62-feature-group-k--environment-chaos--dr-intelligence)
63. [Feature Group L — Kubernetes & cloud-native](#63-feature-group-l--kubernetes--cloud-native)
64. [Feature Group M — Advanced Command Hub & fleet ops](#64-feature-group-m--advanced-command-hub--fleet-ops)
65. [Feature Group N — DORA & predictive release intelligence](#65-feature-group-n--dora--predictive-release-intelligence)
66. [Feature Group O — Event-driven architecture & agent registry](#66-feature-group-o--event-driven-architecture--agent-registry)
67. [Feature Group P — Artifact intelligence & release passports](#67-feature-group-p--artifact-intelligence--release-passports)
68. [Target control plane architecture](#68-target-control-plane-architecture)
69. [Priority roadmap (Phases 1–5)](#69-priority-roadmap-phases-15)
70. [Top 15 features & killer workflow](#70-top-15-features--killer-workflow)
71. [Anti-patterns — what NOT to add](#71-anti-patterns--what-not-to-add)

---

## 1. Vision, scope & design principles

### 1.1 Vision

ORION is evolving from an **AI-assisted CI/CD pipeline** into an **AI-native DevSecOps/SRE control plane** — analyzing code, predicting release risk, validating security and quality, orchestrating deployments, monitoring production, and safely automating remediation.

> **One-line:** An autonomous platform that turns every code change into an evidence-backed risk assessment, gated delivery decision, and observable production outcome.

Today ORION **automates the full software delivery loop** from code change to deployed, monitored service—with AI agents as specialized reviewers, testers, approvers, and operators. Human operators retain override via retry, resume, cancel, manual approval, and Auto-PR workflows.

**North-star outcomes:**

| Outcome | How ORION delivers it |
|---------|----------------------|
| **Shift-left quality** | Parallel full scan (code + security + QA) before any deploy |
| **Explainable gates** | JSON artifacts + gate fusion risk scores, not black-box chat |
| **Safe automation** | Hard security scanner rules; LLM cannot override bandit severity |
| **Operational resilience** | Checkpoint resume, webhook idempotency, auto-rollback monitoring |
| **Cross-stack visibility** | Intelligence dashboards + Command Hub SLO panel |
| **Developer velocity** | Auto-PR remediation branches; heuristic mode without API keys |

### 1.2 Advanced platform capabilities (production-ready)

| Capability | Description | Primary stack |
|------------|-------------|---------------|
| **Parallel full scan** | Code + security + QA concurrent with DB lock serialization | ORION |
| **Real SAST/SCA** | bandit + pip-audit with LLM enrichment | ORION |
| **Locust stress gate** | p95 + error rate thresholds vs staging | ORION |
| **Docker deploy + rollback** | Build, health check, LKG image restore | ORION, DevOps |
| **Simulated deploy path** | Full pipeline without Docker daemon | All stacks |
| **Monitoring auto-rollback** | 2× rollback recommendation → redeploy LKG | ORION |
| **Webhook delivery ledger** | `X-GitHub-Delivery` idempotent 202 replay | All stacks |
| **Inflight deduplication** | Same repo+commit non-terminal → 202 duplicate | ORION |
| **Stage checkpoint resume** | Skip ingest/scan/stress/approval from artifacts | All stacks |
| **Operator audit trail** | Actor, roles, action on retry/resume/cancel | All stacks |
| **Gate fusion engine** | Unified risk score 0–100 across four gates | All stacks |
| **Change risk engine** | Multi-dimensional change risk + blast radius from diff paths | ORION (+ core module in canonical) |
| **Service dependency graph** | Compose/K8s/OpenAPI heuristic graph + downstream hints | ORION |
| **SBOM generation** | CycloneDX subset from requirements/package.json | ORION |
| **Secrets Guardian** | Pattern scan + `blocked_secrets` gate on critical findings | ORION |
| **Container security** | Dockerfile heuristic scan (root, :latest, secrets) | ORION |
| **IaC security** | Terraform/K8s/Compose policy heuristics | ORION |
| **Test intelligence** | Changed-file test selection + flaky history | ORION |
| **Release passport** | Pre-deploy evidence rollup artifact | ORION |
| **Autonomous fix loop** | Sandbox verify → patch confidence → Auto-PR | ORION |
| **Progressive canary delivery** | 5→25→50→100% with health gates | ORION |
| **PR intelligence** | GitHub review comments with risk summary | ORION |
| **SLO intelligence + Slack** | Success/failure/blocked rates with deduped alerts | All stacks |
| **Hybrid file retriever** | Keyword + fuzzy path scoring for LLM context | Canonical |
| **SQLite agent memory** | Last N prompt/response pairs per agent scope | Canonical |
| **Memory Gateway (ORION-ARCH-001)** | Governed L1–L6 write/read API, redaction, episodic pipeline summaries | ORION + Canonical (shared `shared/memory_gateway/`) |
| **Platform event backbone** | `pipeline.started` / `pipeline.completed` domain events (Redis Streams + in-memory) | ORION + Canonical; Hub federates recent events |
| **Correlated log monitoring** | Log type + gate verdict fusion hints | All stacks |
| **Multimodal analysis suite** | 6 on-demand agents (logs, git, payment, triage, …) | ORION (+ proxy) |
| **Prometheus metrics** | HTTP counters, pipeline counters, webhook counters | ORION, Canonical |
| **Grafana dashboard JSON** | Import-ready ops dashboard | `observability/grafana/` |
| **Rate limiting** | App middleware + nginx edge zones | All stacks |
| **Multi-key RBAC** | JSON API keys with role sets | ORION, Canonical |
| **GitHub OAuth + HMAC state** | Signed OAuth state (canonical); session cookies | Canonical, ORION |
| **Playwright + pytest E2E** | Full offline verification matrix | Repo root |

### 1.3 Scope (in scope)

| Area | Description |
|------|-------------|
| **CI/CD pipelines** | Ingest → analyze → test → stress → approve → deploy → monitor |
| **Quality gates** | Code, security, QA, stress with hard blocks before deploy |
| **Multimodal analysis** | Logs, GitHub Actions, git history, payments, Dockerfiles, incident triage |
| **Auto-remediation** | Auto-PR branches for fixable findings (ORION + canonical) |
| **Cross-stack ops** | Unified intelligence dashboard, SLO alerts, Command Hub |
| **Developer UX** | Web dashboards, WebSocket live logs, REST APIs |

### 1.4 Out of scope (current)

- Unified OAuth across all three stacks (each stack has its own auth model today)
- Vector RAG / embedding store on ORION and devops (canonical has hybrid retriever only)
- Full LLM Auto-PR on devops-platform (registry metadata only)
- Managed cloud SaaS hosting (self-hosted / local-first)

### 1.5 Design principles

1. **Fail closed on security** — scanner severity cannot be downgraded by LLM; critical findings block deploy.
2. **Artifacts as source of truth** — every agent persists structured JSON; gates read artifacts, not chat output.
3. **Heuristic fallback** — pipelines complete without API keys using deterministic rules (`LLM_MODE=auto`, missing `ANTHROPIC_API_KEY`).
4. **Idempotent webhooks** — `X-GitHub-Delivery` ledger prevents duplicate pipeline runs.
5. **Minimal scope diffs** — three stacks share patterns (gate fusion, SLO, text analysis) without forced monolith.
6. **Observable by default** — `/health`, `/ready`, `/metrics`, intelligence dashboards on every stack.
7. **Defense in depth** — app rate limits + nginx zones + RBAC + secret redaction layers.
8. **Replay-safe webhooks** — delivery ledger returns cached 202; inflight dedup prevents double runs.
9. **Recoverable pipelines** — checkpoint artifacts enable resume without re-cloning or re-scanning.
10. **Observable gates** — every block status maps to a named artifact and fusion violation string.

---

## 2. System design overview

### 2.1 Logical architecture

```mermaid
flowchart TB
    subgraph External
        GH[GitHub Webhooks / API]
        SL[Slack Webhooks]
        PROM[Prometheus / Grafana]
    end

    subgraph Hub["Command Hub :5180"]
        HUI[hub.js — health + intelligence polling]
    end

    subgraph Canonical["Canonical Stack :8000 / :5173"]
        CB[FastAPI backend]
        CO[Orchestrator]
        CF[React frontend]
    end

    subgraph ORION["ORION CI/CD :8001"]
        OB[FastAPI app.main]
        OO[PipelineOrchestrator]
        OUI[Dashboard /ui/]
        CEL[Celery / inline executor]
    end

    subgraph DevOps["DevOps Platform :8002 / :3000"]
        DB[FastAPI backend]
        DR[pipeline_runner]
        DF[React frontend]
        PG[(PostgreSQL)]
        RD[(Redis / Celery)]
    end

    GH --> OB
    GH --> CB
    GH --> DB
    HUI --> CB
    HUI --> OB
    HUI --> DB
    OB --> CEL
    DR --> RD
    DR --> PG
    OO --> SL
    CO --> SL
    DR --> SL
    CB --> PROM
    OB --> PROM
    DB --> PROM
    PROM --> SL
```

### 2.2 Control flow (ORION — primary production path)

```
GitHub push / POST /api/v1/pipeline/trigger / dashboard trigger
        │
        ▼
Webhook ledger (X-GitHub-Delivery idempotency)
        │
        ▼
PipelineOrchestrator.execute_pipeline()
  ├─ 1  Ingestion           git clone, diff, metadata artifacts
  ├─ 2–4 FullScanOrchestrator (parallel, serialized DB lock)
  │       ├─ CodeAnalysisAgent   → code_analysis
  │       ├─ SecurityAgent       → security_scan
  │       └─ QAAgent             → qa_report
  ├─ 5  StressTestAgent     Locust vs STAGING_URL → stress_report
  ├─ 6  ApprovalAgent       hard rules + LLM → approval
  ├─ 7  DeploymentAgent     docker | simulate | skip | auto
  └─ 8  MonitoringAgent     background poll → monitoring_summary / monitoring_alert
        │
        ▼
Terminal status: deployed | approved | blocked_* | rejected | failed | rolled_back | cancelled
```

### 2.3 Analysis modes

| Mode | When | Behavior |
|------|------|----------|
| **llm** | `ANTHROPIC_API_KEY` configured | Claude JSON responses with retry |
| **heuristic** | No key or LLM error | Deterministic rules in agent or `heuristic_llm.py` |
| **simulated** | QA with no `tests/` directory | Explicit skip/pass with `skipped: true` (ORION/canonical) |

### 2.4 Shared libraries (cross-stack parity)

| Module | Canonical | ORION | DevOps |
|--------|-----------|-------|--------|
| Gate fusion | `backend/core/gate_fusion.py` | `app/utils/gate_fusion.py` | `app/utils/gate_fusion.py` |
| SLO compute | `backend/core/slo.py` | `app/services/slo.py` | `app/utils/slo.py` |
| SLO alerts | `backend/core/slo_alerts.py` | `app/utils/slo_alerts.py` | `app/utils/slo_alerts.py` |
| SLO Slack notify | `backend/core/slo_alert_notifier.py` | `app/services/slo_alert_notifier.py` | `app/services/slo_alert_notifier.py` |
| Text analysis | `backend/core/text_analysis.py` | `app/utils/text_analysis.py` | via `/api/tools/text-*` |
| Security scanners | `shared/security_scanners.py` (via `backend/core/security_scanners.py`) | SecurityAgent + shared | DevOps SecurityAgent + shared |
| Memory Gateway | `services/memory_gateway_client.py` | `services/memory_gateway_service.py` | — |
| Platform events | `services/platform_events.py` | `services/platform_events.py` | — |
| Rate limit (Redis) | `shared/rate_limit_redis.py` | middleware | middleware |

---

## 3. Stack topology & ports

| Stack | Code path | API | UI | Primary role |
|-------|-----------|-----|-----|--------------|
| **Command Hub** | `hub/` | — | **5180** | Launcher, live health, cross-stack intelligence panel |
| **Canonical DevOps** | `backend/` + `frontend/` | **8000** | **5173** | Submit-code / archive / GitHub zip pipelines |
| **ORION CI/CD** | `ai-cicd-pipeline/` | **8001**† | `/ui/` on API | GitHub webhook → 9-stage pipeline + multimodal |
| **DevOps Platform** | `devops-platform/` | **8002**‡ | **3000**§ | Postgres + Celery agents, ORION multimodal proxy |

† `run_all_stacks.ps1` uses port **8001**; ORION `.env` default `APP_PORT=8000` when run standalone.  
‡ Docker Compose may default to **8000**; launcher uses **8002** to avoid conflict with canonical.  
§ DevOps UI defaults **3000**; launcher auto-falls back to **3001**/**3002** when the port is busy (e.g. another Vite app). Set `DEVOPS_UI_PORT` to pin. Verify title contains **Multi-Agent DevOps Platform**.

**Shared Python venv:** `Binary-v2/.venv`  
**Verify all stacks:** `.\run_e2e_all.ps1 -Offline` (run canonical pytest from `backend/` directory)

---

## 4. Pipeline architecture (all stacks)

### 4.1 ORION CI/CD (`ai-cicd-pipeline/`)

| Stage | Component | Artifact(s) | Block status |
|-------|-----------|-------------|--------------|
| Ingest | Orchestrator + GitService | `metadata`, `diff` | `failed` on clone error |
| Full scan | FullScanOrchestrator (parallel) | `full_scan_combined`, per-agent artifacts | `blocked_code`, `blocked_security`, `blocked_tests` |
| Stress | StressTestAgent | `stress_report` | `blocked_stress` |
| Approval | ApprovalAgent | `approval` | `rejected` |
| Deploy | DeploymentAgent | `deployment_info`, `last_known_good_image` | `failed`, `rolled_back` |
| Monitor | MonitoringAgent (async) | `monitoring_summary`, `monitoring_alert` | 2× rollback → `auto_rolled_back` |

**Executor:** `PIPELINE_EXECUTOR=auto|celery|inline` — Celery when Redis answers, else in-process.  
**Deploy:** `DEPLOY_MODE=auto|docker|simulate|skip`.

### 4.2 Canonical (`backend/services/orchestrator.py`)

| Stage | Agents | Artifacts in `PipelineState` |
|-------|--------|-------------------------------|
| Dev / full scan | FullScanOrchestrator (sequential) | `full_scan_combined`, `code_analysis`, `security`, `qa` |
| Auto-PR (optional) | AutoPRService | `auto_pr_registry` |
| Stress | StressAgent | `stress` |
| Approval | PipelineAgent (LLM gate decisions) | `approval`, gate decisions |
| Deploy | DeploymentAgent | `deployment` |
| Monitor | MonitoringAgent via `/analyze-logs` | `monitoring` |

**Unique:** hybrid retriever (`RETRIEVER_BACKEND`), SQLite agent memory (`AGENT_MEMORY_ENABLED`), correlated log monitoring.

### 4.3 DevOps Platform (`devops-platform/backend/app/orchestrator/pipeline_runner.py`)

| Stage | Agent | `StageResult.stage` key |
|-------|-------|-------------------------|
| Fetch | inline | metadata in `metadata_json` |
| Code | CodeAnalysisAgent | `code_analysis` |
| Security | SecurityAgent | `security` |
| QA | QAAgent | `qa` |
| Stress | StressAgent | `stress` |
| Approval | ApprovalAgent (gate fusion) | `approval` |
| Deploy | DeploymentAgent | `deployment` |
| Monitor | MonitoringAgent | `monitoring` |

**Statuses:** `PipelineStatus` enum — `PENDING` → … → `COMPLETED` | `BLOCKED` | `FAILED` | `CANCELLED`.

---

## 5. Autonomous agents (complete catalog)

### 5.1 Base classes

#### ORION `BaseAgent` (`ai-cicd-pipeline/app/agents/base_agent.py`)

| Method | Purpose |
|--------|---------|
| `async execute() -> dict` | Main agent work unit |
| `_call_claude_json()` | LLM with JSON schema retry; `{_llm_error: ...}` on failure |
| `_save_artifact(type, content, raw_output=...)` | Persist to `pipeline_artifacts` + WebSocket event |
| `_prepare_llm_text()` | Secret redaction + truncation via text_analysis |

#### DevOps `BaseAgent` (`devops-platform/backend/app/agents/base_agent.py`)

Sync `run(AgentInput) -> AgentOutput`; writes `AgentLog` + `StageResult`.

#### Canonical agents (`backend/agents/`)

LLM-driven via `LLMClient`; optional memory + retriever injection from orchestrator.

---

### 5.2 ORION pipeline agents

| # | Agent | File | Model env | Artifact | Gate |
|---|-------|------|-----------|----------|------|
| 1 | **CodeAnalysisAgent** | `code_analysis_agent.py` | `CODE_ANALYSIS_MODEL` | `code_analysis` | `severity: fail` → `blocked_code` |
| 2 | **SecurityAgent** | `security_agent.py` | `SECURITY_MODEL` | `security_scan` | `highest_severity` > `MAX_SECURITY_SEVERITY` → `blocked_security` |
| 3 | **QAAgent** | `qa_agent.py` | `QA_MODEL` | `qa_report` | `verdict: fail` → `blocked_tests` |
| 4 | **StressTestAgent** | `stress_test_agent.py` | `STRESS_MODEL` | `stress_report` | `performance_verdict: fail` → `blocked_stress` |
| 5 | **ApprovalAgent** | `approval_agent.py` | `APPROVAL_MODEL` | `approval` | `decision: rejected` → `rejected` |
| 6 | **DeploymentAgent** | `deployment_agent.py` | `DEPLOYMENT_MODEL` | `deployment_info`, `last_known_good_image` | deploy failure → `failed` / rollback |
| 7 | **MonitoringAgent** | `monitoring_agent.py` | `MONITORING_MODEL` | `monitoring_summary`, `monitoring_alert` | 2× rollback recommendation → `auto_rolled_back` |
| — | **FullScanOrchestrator** | `full_scan_orchestrator.py` | — | `full_scan_combined` | Runs 1–3 concurrently; all complete before gate eval |
| — | **PipelineOrchestrator** | `orchestrator.py` | indirect | orchestration | Coordinates all stages, Auto-PR, audit, resume |

#### Agent tool details (ORION)

**CodeAnalysisAgent**
- Tools: pylint (changed `.py`, max 20), AST scan (undefined names, unused imports, missing docstrings)
- Heuristic fail: ≥3 pylint/AST errors OR ≥5 warnings → `warn`
- Uses: `files_in_diff()`, `diff_stats()`, `_prepare_llm_text()` on diff

**SecurityAgent**
- Tools: **bandit** (full repo), **pip-audit** (pinned `==` deps in `requirements.txt`)
- LLM **cannot downgrade** scanner severity; unpinned deps → `not_audited`

**QAAgent**
- No `tests/` or `test/` → **simulated pass** (`skipped: true`, `analysis_mode: simulated`)
- Real: pytest with JSON report; failures mapped to file-level `issues` for Auto-PR
- Infrastructure errors (pytest missing) → pass with warning, not block

**StressTestAgent**
- Tool: Locust against `STAGING_URL`
- Fail: error rate >5% OR p95 >2000 ms
- Warn: error rate >1% OR p95 >1000 ms
- Unreachable staging → warn (not fail)

**ApprovalAgent**
- Hard rules first: code fail, security above threshold, QA fail, stress fail → reject without LLM override

**DeploymentAgent**
- Modes: see [§4.1](#41-orion-cicd-ai-cicd-pipeline)
- Docker: build → run → health check → rollback on failure
- Simulated: records success without Docker (`deployment_info.simulated=true`)

**MonitoringAgent**
- Polls container logs, `/health`, journald (`JOURNALD_ENABLED`)
- Simulated deploy → single-pass simulated monitoring window

---

### 5.3 Canonical pipeline agents

| Agent | File | Role | Notes |
|-------|------|------|-------|
| CodeAnalysisAgent | `agents/code_analysis.py` | LLM code review | Artifact: `code_analysis` |
| SecurityAgent | `agents/security.py` | bandit + pip-audit + LLM enrichment | `SECURITY_SCANNERS_ENABLED`; scanner severity authoritative; artifact: `security` |
| PipelineAgent | `agents/pipeline.py` | Stage transition decisions | Approval / gate LLM |
| StressAgent | `agents/stress.py` | Heuristic load gate | Artifact: `stress` |
| DeploymentAgent | `agents/deployment.py` | Deploy decision JSON | Artifact: `deployment` |
| MonitoringAgent | `agents/monitoring.py` | Log anomaly + journald | Via `/analyze-logs` |
| FullScanOrchestrator | `agents/full_scan_orchestrator.py` | Sequential scan | `full_scan_combined` |

**Memory & retrieval (canonical only):**
- `services/memory_store.py` — `SQLiteAgentMemoryStore` / `InMemoryAgentMemoryStore` (per-agent turn history)
- `services/memory_gateway_client.py` — shared **Memory Gateway** (L2 episodic on terminal pipeline; see §38.3)
- `services/pipeline_terminal_hooks.py` — idempotent `pipeline.completed` + episodic extract on terminal status
- `services/retriever.py` — `HybridFileRetriever`, `FileChunkRetriever`, `NoOpRetriever`

---

### 5.4 DevOps platform agents

| Agent | File | Gate behavior |
|-------|------|---------------|
| CodeAnalysisAgent | `code_analysis.py` | score <60 or critical issue → fail |
| SecurityAgent | `security.py` | critical vuln or `overall_risk: critical` → `BLOCKED` |
| QAAgent | `qa_agent.py` | pytest fail; no tests → explicit skip message |
| StressAgent | `stress_agent.py` | load smoke fail |
| ApprovalAgent | `approval_agent.py` | `fuse_stage_results()` fail → reject |
| DeploymentAgent | `deployment.py` | `DEPLOY_MODE` modes |
| MonitoringAgent | `monitoring.py` | post-deploy log scan |

---

## 6. Multimodal agents

Invoked on-demand via `POST /api/v1/multimodal/*` (ORION/canonical) or proxied from devops.

All extend **`BaseMultimodalAgent`** — file uploads + text, `_analyze_json()` with heuristic fallback, standalone artifacts.

| Agent | Aliases | Artifact type | Primary use |
|-------|---------|---------------|-------------|
| **LogAnalysisAgent** | `log`, `log_analysis` | `log_analysis` | Server/build/git/deploy/memory logs |
| **GitHubLogAgent** | `github`, `github_actions` | `github_log_analysis` | Actions workflow failures |
| **GitLogAgent** | `git`, `git_logs` | `git_log_analysis` | Local/remote git history |
| **PaymentAgent** | `payment` | `payment_analysis` | CSV/PDF payment reconciliation |
| **DockerfileAgent** | `docker`, `dockerfile` | `dockerfile_analysis` | Dockerfile hardening + optional auto-PR |
| **ProductionTriageAgent** | `triage`, `production_triage` | `production_triage` | P1 incident triage from screenshots/logs |

**ORION routes:** `app/api/routes/multimodal.py` — `AGENT_ALIASES` registry  
**Canonical routes:** `backend/api/multimodal.py`  
**DevOps:** `app/routers/multimodal_proxy.py` → `ORION_API_URL`

**LogAnalysisAgent enhancements:**
- Auto tail truncation (`tail_lines`)
- Heuristic: `detected_log_type`, `error_signatures`, `structured_timeline`
- Pattern fixes: `ModuleNotFoundError` → suggested `pip install …`

**Upload limits:** ORION 25 MB; canonical `MULTIMODAL_MAX_FILE_BYTES` (default 8 MB)

---

## 7. Orchestration, lifecycle & control plane

### 7.1 Triggers

| Stack | Trigger sources |
|-------|-----------------|
| ORION | GitHub `push` webhook, `POST /api/v1/pipeline/trigger`, dashboard |
| Canonical | `POST /submit-code`, `/submit-archive`, `/submit-github`, `POST /api/v1/webhook/github` |
| DevOps | `POST /webhook/github`, `POST /api/pipeline/trigger` |

### 7.2 Operator actions

| Action | ORION | Canonical | DevOps |
|--------|-------|-----------|--------|
| **Retry** (full restart) | `POST /api/v1/pipeline/runs/{id}/retry` | `POST /pipelines/{id}/retry` | `POST /api/pipeline/{id}/retry` |
| **Resume** (checkpoint) | `POST /api/v1/pipeline/runs/{id}/resume` | `POST /pipelines/{id}/resume` | `POST /api/pipeline/{id}/resume` |
| **Cancel** | `POST /api/v1/pipeline/runs/{id}/cancel` | `POST /pipelines/{id}/cancel` | `POST /api/pipeline/{id}/cancel` |
| **Audit trail** | `GET /runs/{id}/audit` | `GET /pipelines/{id}/audit` | `GET /api/pipeline/{id}/audit` |
| **Manual deploy** | via approval flow | `POST /trigger-deployment` | `POST /api/pipeline/{id}/deploy` |

### 7.3 Resume checkpoint semantics

**ORION** skips completed stages when artifacts exist:
- Skip ingest if `metadata`
- Skip full scan if `full_scan_combined` or all three scan artifacts
- Skip stress if `stress_report`
- Skip approval if prior `approval.decision == approved`

**Canonical** skips when `resume=True`:
- Skip full scan if `full_scan_combined`
- Skip auto-PR if `auto_pr_registry` exists
- Skip stress if `stress` artifact exists

**DevOps** skips stages with existing `StageResult` rows when `metadata_json.resume=true`.

### 7.4 Auto-PR

| Stack | Branch pattern | Artifact |
|-------|----------------|----------|
| ORION | `orion/fix-<category>-<run>` | `auto_pr_registry` |
| Canonical | AutoPRService branches | `auto_pr_registry` |
| DevOps | metadata registry on block | `metadata_json` |

Status `blocked_with_prs_sent` when fix PRs are opened and pipeline waits for merge.

### 7.5 WebSocket live events

| Stack | Endpoint | Events |
|-------|----------|--------|
| ORION | `WS /ws/pipeline/{id}` | `stage-update`, `agent-complete` |
| Canonical | `WS /ws/pipeline-status/{id}` | stage/status messages |
| DevOps | `WS /ws/{pipeline_id}` | stage log stream |

Auth: `?api_key=` when `API_REQUIRE_AUTH=true` (ORION/devops).

### 7.6 Platform events & Memory Gateway hooks

Distinct from per-pipeline **WebSocket** events (§7.5 / §24): cross-plane **platform events** use `shared/event_bus/` (`PlatformEvent` envelope, stream key `orion:platform:events`).

| Hook | ORION | Canonical |
|------|-------|-----------|
| `pipeline.started` | `PipelineOrchestrator.execute_pipeline` (non-resume) | `publish_pipeline_started()` on submit |
| `pipeline.completed` | Terminal `_set_status` | `run_terminal_hooks()` on terminal status |
| L2 episodic memory | `extract_pipeline_episodic_memory()` | `extract_canonical_episodic_memory()` |
| Agent context injection | `BaseAgent._inject_memory_prefix()` when `MEMORY_GATEWAY_ENABLED` | — (gateway read via client) |

**Rules:** Memory context is **advisory only** (MEM-04) — never an input to gate fusion. Writes pass secret redaction and injection quarantine (MEM-03).

**ADRs:** `docs/adr/001-memory-gateway.md`, `docs/adr/002-event-backbone.md` · **Wave tracker:** `docs/audit/ORION_SPEC_WAVE_STATUS.md`

---

## 8. API reference (unified)

### 8.1 Health & ops (all stacks)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness + diagnostic JSON |
| GET | `/ready` | Readiness (DB, executor, preflight) |
| GET | `/metrics` | Prometheus text exposition |

### 8.2 ORION (`ai-cicd-pipeline/app/main.py`)

**Prefix:** `/api/v1`

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/webhook/github` | HMAC | Push webhook + delivery ledger |
| POST | `/webhook/github/pr` | HMAC | Merged PR branch cleanup |
| GET | `/pipeline/runs` | optional | List runs |
| GET | `/pipeline/runs/{id}` | optional | Run detail |
| GET | `/pipeline/runs/{id}/artifacts` | optional | All artifacts |
| GET | `/pipeline/runs/{id}/artifacts/{type}` | optional | Single artifact |
| GET | `/pipeline/runs/{id}/audit` | optional | Audit trail |
| POST | `/pipeline/runs/{id}/retry` | operator | Full retry |
| POST | `/pipeline/runs/{id}/resume` | operator | Checkpoint resume |
| POST | `/pipeline/runs/{id}/cancel` | operator | Cancel |
| POST | `/pipeline/trigger` | operator | Manual trigger |
| GET | `/intelligence/dashboard` | optional | SLO + gate fusion + alerts |
| GET | `/production/checklist` | optional | Production hardening score + items |
| GET | `/production/ready` | optional | Runtime + hardening gate (503 if not ready in prod) |
| POST | `/tools/text-analyze` | optional | Text utilities batch |
| POST | `/tools/text-sanitize` | optional | Sanitize + redact |
| POST | `/tools/text-compare` | optional | Similarity |
| POST | `/multimodal/analyze` | optional | Multimodal router |
| POST | `/multimodal/triage` | optional | Production triage |
| POST | `/multimodal/git-logs` | optional | Git log analysis |
| POST | `/multimodal/payment` | optional | Payment analysis |
| GET | `/auth/github` | open | OAuth start |
| GET | `/auth/github/callback` | open | OAuth callback |
| GET | `/auth/me`, `/logout`, `/status` | session | Session info |

Headers: `X-ORION-API-Key`, `X-Hub-Signature-256`, `X-GitHub-Delivery`, `X-GitHub-Event`

**Prefix:** `/api/v2` (ORION-ARCH-001 Wave 1 foundations)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/memory/health` | open | Gateway enabled/backend/SQLite path |
| POST | `/memory/records` | optional | Governed memory write |
| POST | `/memory/context` | optional | Packed advisory context for repo namespace |
| GET | `/events/recent` | optional | Recent platform events (`limit`, `event_type`) |

### 8.3 Canonical (`backend/main.py`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/submit-code` | rate limit | Start pipeline from code payload |
| POST | `/submit-archive` | rate limit | Zip upload pipeline |
| POST | `/submit-github` | rate limit | GitHub archive pipeline |
| GET | `/pipeline-status/{id}` | open | Status |
| GET | `/pipelines` | open | List |
| POST | `/pipelines/{id}/cancel` | optional | Cancel |
| POST | `/pipelines/{id}/retry` | optional | Retry |
| POST | `/pipelines/{id}/resume` | optional | Resume |
| GET | `/pipelines/{id}/audit` | optional | Audit |
| POST | `/trigger-deployment` | approver key | Manual deploy |
| POST | `/analyze-logs` | open | Monitoring + gate correlation |
| POST | `/api/v1/webhook/github` | HMAC | Push webhook + ledger |
| POST | `/api/v1/webhook/github/pr` | HMAC | PR merge webhook |
| GET | `/api/v1/intelligence/dashboard` | open | Intelligence |
| GET | `/runtime-config` | open | Frontend preflight |
| POST | `/api/v1/multimodal/analyze` | optional | Multimodal |
| POST | `/api/v1/multimodal/triage` | optional | Triage |

### 8.4 DevOps Platform

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/webhook/github` | HMAC | GitHub webhook |
| POST | `/api/pipeline/trigger` | optional | Start pipeline |
| GET | `/api/pipelines` | open | List |
| GET | `/api/pipeline/{id}` | open | Detail + logs + stages |
| GET | `/api/pipeline/{id}/status` | open | Light status |
| GET | `/api/pipeline/{id}/audit` | open | Audit |
| POST | `/api/pipeline/{id}/retry` | optional | Retry |
| POST | `/api/pipeline/{id}/resume` | optional | Resume |
| POST | `/api/pipeline/{id}/cancel` | optional | Cancel |
| POST | `/api/pipeline/{id}/logs/analyze` | open | Log analyze + fusion |
| POST | `/api/pipeline/{id}/deploy` | `X-Deployment-Key` | Manual deploy |
| GET | `/api/intelligence/dashboard` | open | Intelligence |
| POST | `/api/multimodal/analyze` | optional | ORION proxy |
| POST | `/api/tools/text-*` | open | Text tools |

### 8.5 Command Hub BFF (`hub/server.py`)

**Prefix:** `/api/v1/control-plane` (federation; propagates `X-Correlation-ID`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Hub + stack health matrix |
| GET | `/pipelines` | Federated pipeline list |
| GET | `/operations` | Operations Center (SLO, fleet, policy/security/performance/**memory** panels, **platform_events**) |
| GET | `/platform-events` | Proxy ORION `GET /api/v2/events/recent` |
| GET | `/intelligence` | Fan-out stack intelligence dashboards |
| GET | `/fleet` | ORION fleet intelligence |
| GET | `/pipelines/{stack:native_id}/timeline` | Unified timeline |
| POST | `/pipelines/{stack:native_id}/retry` | Federated retry |
| POST | `/pipelines/{stack:native_id}/resume` | Federated resume |
| POST | `/pipelines/{stack:native_id}/cancel` | Federated cancel |

---

## 9. Cross-stack intelligence & gate fusion

### 9.1 Intelligence dashboards

| Stack | Endpoint | Response highlights |
|-------|----------|---------------------|
| Canonical | `GET /api/v1/intelligence/dashboard` | pass_rate, top_blockers, SLO, alerts, retriever/memory flags |
| ORION | `GET /api/v1/intelligence/dashboard` | deploy_mode, executor, llm_mode, auto_pr, **memory_gateway**, **platform_event_bus** |
| DevOps | `GET /api/intelligence/dashboard` | redis_available, approval_agent, ORION proxy flag |

**Command Hub** (`hub/hub.js`) polls all three every few seconds and renders SLO success, readiness, gate blockers, alert banner.

### 9.2 Gate fusion (`fuse_stage_results`)

Merges code, security, QA, stress into:
- `verdict`: `pass` | `warn` | `fail`
- `violations`, `warnings`, `risk_score` (0–100)
- `recommended_action`

Used in intelligence blockers, ApprovalAgent (devops), correlated monitoring.

### 9.3 SLO & alerts

**Compute** (`compute_pipeline_slo`): `success_rate`, `blocked_rate`, `failure_rate`, `mean_duration_seconds` over recent runs.

**Evaluate** (`evaluate_slo_alerts`):
- `slo_success_low` — success below 70% (min 3 runs)
- `slo_failure_high` — failure above 25%
- `slo_blocked_high` — blocked above 40%

**Notify** (`notify_slo_alerts`): posts to Slack with per-code cooldown (`SLO_ALERT_COOLDOWN_SECONDS`, default 3600).

---

## 10. Security conduct & trust boundaries

### 10.1 Security principles

| Principle | Implementation |
|-----------|----------------|
| **Authenticate webhooks** | HMAC-SHA256 `X-Hub-Signature-256`; never use GitHub PAT as webhook secret |
| **Never commit secrets** | Use `.env` (gitignored); redact before LLM via `redact_secrets()` |
| **Least privilege API keys** | RBAC roles: `admin`, `operator`, `approver` in `AUTH_API_KEYS_JSON` |
| **Rate limit abuse surfaces** | submit, webhook, multimodal, trigger endpoints |
| **Fail closed on auth** | `API_REQUIRE_AUTH=true` in production (ORION auto-enforces in prod) |
| **Sandbox user code** | Archive/pytest runs in temp dirs; document trust boundary for `/submit-archive` |
| **Idempotent delivery** | `webhook_deliveries` table keyed by `X-GitHub-Delivery` |

### 10.2 Authentication matrix

| Mechanism | ORION | Canonical | DevOps |
|-----------|-------|-----------|--------|
| GitHub OAuth | ✅ `/api/v1/auth/github` | ✅ same pattern | — |
| Session cookies | Signed via `SESSION_SECRET_KEY` | Same | — |
| API keys | `X-ORION-API-Key` + `AUTH_API_KEYS_JSON` | `AuthService` + DB `User` | `X-ORION-API-Key`, `DEPLOYMENT_API_KEY` |
| RBAC | `OrionAuthService.require_roles()` | roles in JSON + DB | binary key match |
| WebSocket auth | `?api_key=` | optional | `?api_key=` |

**ORION roles (typical):**
- `admin` — all operations
- `operator` — retry, cancel, resume, trigger
- `approver` — deployment approval (canonical `/trigger-deployment`)

### 10.3 Secret handling in agents

Before any LLM call, text passes through:
1. `sanitize_for_agent()` — unicode normalize
2. `redact_secrets()` — API keys, tokens, PEM blocks, common patterns
3. `truncate_with_context()` — head+tail for large diffs/logs

### 10.4 Scanner trust (ORION SecurityAgent)

- Bandit and pip-audit outputs are **authoritative**
- LLM may add context but **cannot reduce** scanner severity
- Unpinned requirements → listed as `not_audited`

### 10.5 Production checklist

**Automated (ORION):**

| Check | Mechanism |
|-------|-----------|
| Hardening score 0–100 | `GET /api/v1/production/checklist` — `app/utils/production_hardening.py` |
| Fail-closed startup | `settings.validate_startup()` in ORION lifespan (secrets, Postgres, API keys) |
| Combined readiness | `GET /api/v1/production/ready` — `/ready` + hardening (503 when `APP_ENV=production` and not ready) |
| Cross-stack preflight | `scripts/production_preflight.py` — validates all three `.env.production` files |
| CLI | `orion production checklist` · `orion production ready` |

**Manual checklist (real cloud deploy):**

- [ ] Rotate `SECRET_KEY`, `SESSION_SECRET_KEY`, `GITHUB_WEBHOOK_SECRET`, all API keys
- [ ] Set `APP_ENV=production` and `API_REQUIRE_AUTH=true` (auto-enabled on ORION when `APP_ENV=production`)
- [ ] Configure `AUTH_API_KEYS_JSON` with scoped RBAC keys (or `ORION_API_KEY`)
- [ ] Use dedicated webhook secret (never `GITHUB_TOKEN`)
- [ ] Enable HTTPS termination (nginx `orion.conf` or cloud LB)
- [ ] Restrict `CORS_ORIGINS` to known UI origins (no `*`)
- [ ] Use PostgreSQL + Redis (`docker-compose.prod.yml`); enable TLS on managed Postgres
- [ ] Enable recommended gates: `PROMPT_INJECTION_GATE_ENABLED`, `POLICY_ENFORCEMENT_ENABLED`, `UNIFIED_RISK_GATE_ENABLED`
- [ ] Never commit `.env` / `.env.production` — root `.env.example` uses placeholders only
- [ ] Replace auto-generated GitHub/Slack/LLM tokens before external exposure

**Local production simulation (`PRODUCTION_LOCAL_SIM=true`):** Auth + gates on, SQLite + inline executor — for laptops without Docker. Not a substitute for Postgres/Celery in real production. See [§11.6](#116-production-deployment-paths).

---

## 11. Encrypted & hardened deployment plan

Recommended production topology with encryption in transit and at rest.

### 11.1 Network & TLS

```
                    ┌─────────────────┐
   Internet ───────►│ TLS Termination │  nginx / cloud LB (TLS 1.2+)
                    │  (HTTPS :443)   │
                    └────────┬────────┘
                             │ HTTP internal (VPC only)
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
   ORION API :8001    Canonical :8000      DevOps :8002
```

- **In transit:** TLS at edge; internal mTLS optional between services
- **Webhooks:** GitHub → HTTPS only; validate HMAC on raw body
- **Session cookies:** `https_only=True`, `same_site=lax` or `strict` in production

### 11.2 Secrets management (recommended)

| Layer | Dev | Production |
|-------|-----|------------|
| App secrets | `.env` file (gitignored) | Vault / AWS Secrets Manager / Azure Key Vault |
| DB credentials | local SQLite / docker env | Rotated Postgres user; TLS connection string |
| API keys | `AUTH_API_KEYS_JSON` | Per-service keys with expiry; audit access |
| LLM keys | `ANTHROPIC_API_KEY` | Scoped key; rate limits; no logging of prompts with secrets |

### 11.3 Data at rest

| Data | Encryption approach |
|------|---------------------|
| Postgres (devops/ORION prod) | Provider-managed disk encryption (RDS, Cloud SQL) |
| SQLite (local dev) | File permissions; not for production |
| Artifacts (JSON in DB) | Already redacted at ingest; optional column-level encryption for PII |
| Agent memory (canonical SQLite) | `AGENT_MEMORY_ENABLED` store — encrypt file or move to encrypted DB |
| Webhook ledger | No sensitive payload storage; response bodies are status metadata |

### 11.4 Hardening controls

| Control | Technology |
|---------|------------|
| WAF / rate limit | nginx `limit_req`, cloud WAF, in-app `RateLimitMiddleware` |
| Container isolation | Docker deploy with non-root user, read-only rootfs where possible |
| SBOM / deps | pip-audit in ORION SecurityAgent; CI `pip audit` / Dependabot |
| Audit | `audit_trail` artifacts + operator action logs on retry/cancel/resume |
| Monitoring | Prometheus scrape `/metrics`; Grafana dashboard in `observability/grafana/` |
| Alerting | Slack SLO alerts + pipeline blocked/failed notifications |

### 11.5 Zero-trust operator access

1. Operators authenticate via GitHub OAuth or scoped API key
2. Sensitive actions (retry, resume, cancel, trigger) require `operator` role
3. Deploy approval requires `approver` role or `X-Deployment-Key`
4. All actions append to audit trail with actor + roles + timestamp

### 11.6 Production deployment paths

| Path | When | Infra | Env files |
|------|------|-------|-----------|
| **Development** | Daily coding | SQLite, inline executor | `.env` per stack |
| **Local production sim** | Auth/gate testing without Docker | SQLite, `PRODUCTION_LOCAL_SIM=true` | `scripts/generate_production_env.py --local-sim` |
| **Production (self-hosted)** | Real deploy | `docker-compose.prod.yml` — Postgres + Redis | `*.env.production` from `*.env.production.example` |

**Launcher:** `.\run_production.ps1` — optional `-GenerateSecrets`, `-LocalSim`, `-SkipDocker`, `-SkipPreflight`

```
generate_production_env.py  →  .env.production (×3) + .env.prod.infra
production_preflight.py     →  exit 1 on placeholder / hardening failures
run_production.ps1          →  Docker infra + preflight + run_all_stacks.ps1 (per-stack env)
```

**Per-stack production templates:**

| Stack | Template | Module |
|-------|----------|--------|
| ORION | `ai-cicd-pipeline/.env.production.example` | `production_hardening.py`, `validate_startup()` |
| Canonical | `backend/.env.production.example` | `check_required_env_vars()` |
| DevOps | `devops-platform/.env.production.example` | `Settings.validate_startup()` |

**Postgres databases** (created by `docker/postgres-init/01-databases.sql`): `orion`, `canonical`, `devops_platform`

**TLS (local nginx testing):** `scripts/generate_local_tls.ps1` → `observability/tls/local/` — mount per `ai-cicd-pipeline/nginx/conf.d/orion.conf`

Full guide: `docs/PRODUCTION_RUNBOOK.md`

---

## 12. Observability, SLO & operations

### 12.1 Metrics (Prometheus)

| Stack | Key series |
|-------|------------|
| ORION | `orion_http_requests_total`, `orion_http_request_duration_seconds_*`, `orion_pipeline_runs_total`, `orion_webhook_deliveries_total` |
| Canonical | `canonical_http_requests_total`, `canonical_pipeline_submissions_total` |
| DevOps | `devops_platform_up` |

Scrape config example: `observability/grafana/README.md`  
Dashboard JSON: `observability/grafana/orion-dashboard.json`

### 12.2 Readiness vs liveness

| Endpoint | Checks |
|----------|--------|
| `/health` | Process up, config summary, LLM mode |
| `/ready` | DB connectivity, executor (ORION), preflight secrets (canonical) |

Command Hub displays readiness badges per stack.

### 12.3 Slack notifications

| Event | Source |
|-------|--------|
| Pipeline started / blocked / completed / failed | Stack `SlackService` |
| SLO breach | `notify_slo_alerts()` on intelligence dashboard poll |
| Production triage (high severity) | Canonical multimodal optional alert |

Config: `SLACK_WEBHOOK_URL`, `SLO_ALERT_SLACK_ENABLED`, `SLO_ALERT_COOLDOWN_SECONDS`

### 12.4 Runbook snippets

**Pipeline blocked on security (ORION):**
1. `GET /api/v1/pipeline/runs/{id}/artifacts/security_scan`
2. Fix findings or adjust `MAX_SECURITY_SEVERITY` (non-prod only)
3. `POST .../retry` or `/resume` if checkpoint exists

**Webhook duplicate deliveries:**
- Expected: second delivery returns `202` with cached `response_body` from ledger

**SLO alert storm:**
- Increase `SLO_ALERT_COOLDOWN_SECONDS`; fix underlying gate blockers via intelligence `top_blockers`

---

## 13. Data model & persistence

### 13.1 ORION (`ai-cicd-pipeline/`)

**Tables:**
- `pipeline_runs` — UUID, commit, branch, repo, status (40+ values), timestamps
- `pipeline_artifacts` — JSON/JSONB content, 22 valid types
- `webhook_deliveries` — idempotent GitHub delivery ledger

**Migrations:** `alembic/versions/001_initial.py`, `002_webhook_deliveries.py`

**Valid artifact types:** `metadata`, `diff`, `code_analysis`, `security_scan`, `qa_report`, `stress_report`, `change_risk_report`, `service_graph`, `sbom`, `secrets_scan`, `container_security_scan`, `iac_security_scan`, `test_intelligence`, `release_passport`, `approval`, `deployment_info`, `last_known_good_image`, `monitoring_summary`, `monitoring_alert`, `full_scan_combined`, `auto_pr_registry`, `audit_trail`, multimodal types (see §6)

**Terminal statuses:** `deployed`, `approved`, `blocked_*`, `rejected`, `failed`, `rolled_back`, `auto_rolled_back`, `cancelled`

### 13.2 Canonical

**Tables (`backend/models/db_models.py`):**
- `pipeline_runs`, `stage_results`, `logs`, `users`, `webhook_deliveries`

**State:** In-memory / SQLite `PipelineState` via `services/state_store.py` (primary runtime)

**Agent memory:** separate SQLite table via `SQLiteAgentMemoryStore`

### 13.3 DevOps Platform

**Tables (`app/models.py`):**
- `pipeline_runs`, `agent_logs`, `stage_results`, `webhook_deliveries`

**Migrations:** `devops-platform/backend/alembic/versions/001_initial.py`, `002_webhook_deliveries.py`

### 13.4 Audit trails

| Stack | Storage | API |
|-------|---------|-----|
| ORION | artifact `audit_trail` | `GET /runs/{id}/audit` |
| Canonical | `state.artifacts.audit_trail` | `GET /pipelines/{id}/audit` |
| DevOps | `audit_trail.py` service | `GET /api/pipeline/{id}/audit` |

Events: `pipeline.retry`, `pipeline.resume`, `pipeline.cancel`, deployment approvals, etc.

---

## 14. Text analysis utilities

**Modules (parity):**
- `backend/core/text_analysis.py`
- `ai-cicd-pipeline/app/utils/text_analysis.py`

### 14.1 Functions

| Function | Use case |
|----------|----------|
| `redact_secrets()` | Strip API keys, tokens, PEM before LLM/logs |
| `sanitize_for_agent()` | Normalize unicode + redact |
| `truncate_with_context()` | Head+tail truncation for large diffs/logs |
| `files_in_diff()` / `diff_stats()` | Diff parsing without repo checkout |
| `classify_log_type()` | server_timeout · build_error · deployment_crash · … |
| `extract_error_signatures()` | Deduplicated error fingerprints |
| `extract_stack_traces()` | Parse Python tracebacks |
| `extract_log_timeline()` | Timestamp + severity events |
| `parse_commit_message()` | Conventional commit parser |
| `similarity_ratio()` | Fuzzy text comparison |
| `string_metrics()` | Lines, words, error counts, fingerprint |
| `run_text_operations()` | Batch operations for API |

### 14.2 API

```bash
curl -s -X POST http://localhost:8001/api/v1/tools/text-analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"ERROR connection timed out","operations":["metrics","classify_log","errors","sanitize"]}'
```

**Valid `operations`:** `metrics` · `redact` · `redact_secrets` · `sanitize` · `classify_log` · `timeline` · `errors` · `error_signatures` · `stack_traces` · `truncate` · `fingerprint` · `diff_stats` · `commit`

**Endpoints:**

| Stack | Paths |
|-------|-------|
| ORION / Canonical | `POST /api/v1/tools/text-analyze`, `/text-sanitize`, `/text-compare` |
| DevOps | `POST /api/tools/text-analyze`, `/text-sanitize`, `/text-compare` |

---

## 15. User interfaces & Command Hub

| Surface | Path | URL | Features |
|---------|------|-----|----------|
| **Command Hub** | `hub/` | `:5180` | Stack cards, health/ready probes, intelligence panel, **control-plane BFF**, Operations Center (platform events + memory telemetry) |
| **Canonical console** | `frontend/` | `:5173` | `#/pipeline`, `#/intelligence`, `#/operations`; NavHub bar |
| **ORION dashboard** | `ai-cicd-pipeline/frontend/` | `:8001/ui/` | 9-stage timeline, WebSocket logs, multimodal modals, retry/cancel/resume |
| **DevOps UI** | `devops-platform/frontend/` | `:3000` (fallback `:3001`/`:3002`) | Pipeline view, WS hook, multimodal via ORION proxy |

If `:3000` shows a non-ORION app, stop that process or read the launcher banner for the actual DevOps UI port.

**Frontend env (`frontend/.env.example`):** `VITE_API_BASE_URL`, `VITE_HUB_URL`, `VITE_ORION_API_URL`, `VITE_DEVOPS_API_URL`, etc.

---

## 16. Configuration reference

### 16.1 Core environment variables (all stacks)

| Variable | Affects |
|----------|---------|
| `ANTHROPIC_API_KEY` | All LLM agents (heuristic if missing) |
| `*_MODEL` per agent | Claude model slug per stage |
| `DEPLOY_MODE` | `auto` · `docker` · `simulate` · `skip` |
| `STAGING_URL` | Stress + deploy health checks |
| `SLACK_WEBHOOK_URL` | Pipeline + SLO Slack alerts |
| `SLO_ALERT_SLACK_ENABLED` | Toggle SLO Slack (default `true`) |
| `SLO_ALERT_COOLDOWN_SECONDS` | Alert dedupe window (default `3600`) |
| `GITHUB_WEBHOOK_SECRET` | Webhook HMAC (not the GitHub token) |
| `GITHUB_TOKEN` | Clone, statuses, Auto-PR |
| `API_REQUIRE_AUTH` | Protect pipeline + tools APIs |
| `AUTH_API_KEYS_JSON` | Multi-key RBAC map |
| `MEMORY_GATEWAY_ENABLED` | Governed memory API (default `true`) |
| `MEMORY_SQLITE_PATH` | Wave 1 memory store path (`.local/orion-memory.db`) |
| `EVENT_BUS_ENABLED` | Platform domain events (default `true`) |
| `EVENT_BUS_BACKEND` | `auto` · `memory` · `redis` |
| `APP_ENV` | `production` enables fail-closed auth + startup validation |
| `PRODUCTION_LOCAL_SIM` | `true` — SQLite allowed in production mode (local sim only) |

**Production env files (gitignored):** copy `*.env.production.example` → `.env.production` per stack, or run `python scripts/generate_production_env.py`.

### 16.2 ORION-specific (`ai-cicd-pipeline/.env.example`)

| Variable | Purpose |
|----------|---------|
| `PIPELINE_EXECUTOR` | `auto` · `celery` · `inline` |
| `MAX_SECURITY_SEVERITY` | Security gate threshold |
| `STRESS_TEST_*` | Locust users, duration, spawn rate |
| `MONITORING_*` | Poll interval, window, health timeout |
| `ORION_API_KEY` | Legacy automation key |
| `RATE_LIMIT_*` | In-app rate limiting |
| `CONTAINER_REGISTRY`, `APP_NAME` | Docker deploy targets |

Per-agent models:
```
CODE_ANALYSIS_MODEL=claude-sonnet-4-20250514
SECURITY_MODEL=claude-sonnet-4-20250514
QA_MODEL=claude-sonnet-4-20250514
STRESS_MODEL=claude-sonnet-4-20250514
APPROVAL_MODEL=claude-sonnet-4-20250514
DEPLOYMENT_MODEL=claude-sonnet-4-20250514
MONITORING_MODEL=claude-sonnet-4-20250514
```

Memory Gateway + platform events (Wave 1):

```
MEMORY_GATEWAY_ENABLED=true
MEMORY_BACKEND=sqlite
MEMORY_SQLITE_PATH=.local/orion-memory.db
MEMORY_QUARANTINE_ENABLED=true
EVENT_BUS_ENABLED=true
EVENT_BUS_BACKEND=auto
```

### 16.3 Canonical-specific

| Variable | Purpose |
|----------|---------|
| `QA_MODE` | `simulated` · `real` |
| `LLM_MODE` | `auto` · `mock` · `live` |
| `AGENT_MEMORY_ENABLED` | SQLite agent memory |
| `RETRIEVER_BACKEND` | `hybrid` · `files` · `chunk` · `noop` |
| `AUTO_PR_ENABLED` | Auto-PR on blockers |
| `AUTO_REDEPLOY_ON_BLOCKED` | Auto-remediation path |
| `PIPELINE_EXECUTOR` | Queue backend selection |
| `MULTIMODAL_*` | Auth, size limits, timeouts |
| `MEMORY_GATEWAY_*`, `EVENT_BUS_*` | Same semantics as ORION (shared gateway SQLite path) |
| `SECURITY_SCANNERS_ENABLED` | bandit + pip-audit in full scan |

### 16.4 DevOps-specific

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` / `SYNC_DATABASE_URL` | Postgres async + sync |
| `REDIS_URL`, `CELERY_*` | Celery broker |
| `ORION_API_URL` | Multimodal proxy target |
| `DEPLOYMENT_API_KEY` | Manual deploy header |
| `AUTO_PR_ENABLED` | Registry on block |

---

## 17. Integrations (GitHub, Slack, Docker, Celery)

| Integration | ORION | Canonical | DevOps |
|-------------|-------|-----------|--------|
| GitHub push webhook | ✅ HMAC + ledger | ✅ HMAC + ledger | ✅ HMAC + ledger |
| GitHub PR webhook | ✅ branch cleanup | ✅ Auto-PR merge | — |
| Commit statuses | ✅ `GitHubService` | ✅ | ✅ |
| Slack pipeline alerts | ✅ | ✅ | ✅ |
| Slack SLO alerts | ✅ | ✅ | ✅ |
| Docker deploy | ✅ DeploymentAgent | LLM agent | ✅ deployment.py |
| Celery/Redis | ✅ optional | memory/redis queue | ✅ primary path |
| Auto-PR | ✅ full service | ✅ full service | metadata only |

---

## 18. Testing & verification

### 18.1 Test locations

| Path | Coverage |
|------|----------|
| `backend/tests/` | API, orchestrator, gate fusion, intelligence, SLO, webhook ledger, resume, multimodal, retriever |
| `ai-cicd-pipeline/tests/` | Agents, orchestrator, webhook, multimodal, migrations, runtime, security |
| `devops-platform/tests/` | Webhooks, agents, approval, pipeline API, WS, dispatch, audit |
| `e2e/tests/` | Playwright hub + optional stack `/ready` smoke |

### 18.2 Commands

```powershell
# Full offline verification
.\run_e2e_all.ps1 -Offline

# Canonical only (must cd into backend)
cd backend; ..\.venv\Scripts\pytest tests/ -v

# ORION unit tests
cd ai-cicd-pipeline; ..\.venv\Scripts\pytest tests/test_agents/ tests/test_text_analysis.py -v

# Playwright hub
cd e2e; npx playwright test tests/hub.spec.ts tests/stacks.spec.ts
```

### 18.3 ORION offline E2E

`ai-cicd-pipeline/scripts/e2e_run.py --scenario pass --offline` — spins sample repo + staging mock + full pipeline.

---

## 19. Launchers & scripts

| Script | Purpose |
|--------|---------|
| `run_all_stacks.ps1` | Hub :5180 + canonical :8000/:5173 + ORION :8001 + devops :8002/:3000+ (auto port fallback) |
| `scripts/run_preflight_check.ps1` | Wrapper for `production_preflight.py` (exit code gate) |
| `run_local_all.ps1` | Canonical only (+ optional `-WithHub`) |
| `stop_local_all.ps1` | Stop PIDs from `.local_stacks.json` |
| `run_e2e_all.ps1` | Full test matrix |
| `run_production.ps1` | Production launcher (secrets, Docker, preflight, all stacks) |
| `scripts/generate_production_env.py` | Generate `.env.production` + `.env.prod.infra` with secure secrets |
| `scripts/production_preflight.py` | Cross-stack production validation (exit code gate) |
| `scripts/generate_local_tls.ps1` | Self-signed certs for local nginx TLS |
| `scripts/sync_stack_catalog.ps1` | Sync `hub/stacks.json` from stack config |
| `docker-compose.prod.yml` | Shared Postgres + Redis for production |
| `ai-cicd-pipeline/scripts/run_local.ps1` | ORION only (SQLite dev, or Postgres when `APP_ENV=production`) |
| `ai-cicd-pipeline/scripts/stop_local.ps1` | Stop ORION background processes |

Process metadata: `.local_stacks.json` / `.local_processes.json` (gitignored). Production manifest (non-secret hints): `.local/production_manifest.json`.

---

## 20. Feature completion matrix

| Capability | Canonical | ORION CI/CD | DevOps Platform |
|------------|-----------|-------------|-----------------|
| Pipeline orchestration | ✅ submit/archive/GitHub | ✅ 9-stage webhook | ✅ Celery orchestrator |
| Real security scanners | ✅ bandit + pip-audit (shared) | ✅ bandit + pip-audit + semgrep hooks | ✅ bandit + pip-audit (shared) |
| Memory Gateway (Wave 1) | ✅ episodic + client | ✅ `/api/v2/memory` + agent inject | — |
| Platform event backbone | ✅ publish | ✅ publish + `/api/v2/events` | — |
| QA real / simulated | ✅ `QA_MODE` | ✅ pytest + simulated | ✅ pytest skip msg |
| Stress testing | ✅ simulated/heuristic | ✅ Locust | ✅ smoke |
| Deploy without Docker | ✅ simulate | ✅ `DEPLOY_MODE` | ✅ `DEPLOY_MODE` |
| Monitoring stage | ✅ `/analyze-logs` | ✅ MonitoringAgent | ✅ MonitoringAgent |
| Text analyze API | ✅ | ✅ | ✅ |
| Gate fusion | ✅ | ✅ | ✅ |
| Intelligence dashboard | ✅ | ✅ | ✅ |
| Command Hub panel | ✅ polls all | ✅ | ✅ |
| SLO + Slack alerts | ✅ | ✅ | ✅ |
| Webhook delivery ledger | ✅ | ✅ | ✅ |
| Stage resume | ✅ | ✅ | ✅ |
| Audit trail API | ✅ | ✅ | ✅ |
| Rate limiting | ✅ | ✅ | ✅ |
| Multi-key RBAC | ✅ | ✅ | ✅ |
| Hybrid retriever | ✅ | — | — |
| Agent memory | ✅ SQLite turns | ✅ agent memory + gateway | — |
| Auto-PR (full) | ✅ | ✅ | metadata only |
| Multimodal agents | ✅ native | ✅ native | ✅ ORION proxy |
| Prometheus `/metrics` | ✅ | ✅ | ✅ |
| Grafana dashboard | ✅ shared JSON | ✅ | ✅ |
| Playwright smoke | ✅ hub + stacks | — | — |
| WebSocket live logs | ✅ | ✅ | ✅ |
| GitHub commit statuses | ✅ | ✅ | ✅ |
| Full scan concurrency | sequential | **parallel** | sequential |
| Production hardening API | — | ✅ checklist + ready | — |
| `validate_startup()` fail-closed | ✅ production | ✅ production | ✅ production |

---

## 21. Extension guide

### 21.1 Add a new ORION pipeline stage agent

1. Subclass `BaseAgent` in `app/agents/my_agent.py`
2. Implement `async def execute(self) -> dict`
3. Call `_save_artifact("my_report", result)`
4. Wire into `PipelineOrchestrator` at the desired stage
5. Add artifact type to `VALID_ARTIFACT_TYPES` in `app/models/pipeline_artifact.py`
6. Add tests under `tests/test_agents/`

### 21.2 Add a multimodal agent

1. Subclass `BaseMultimodalAgent`
2. Set `artifact_type` class attribute
3. Implement `system_prompt()` and optional `_heuristic()`
4. Register alias in `app/api/routes/multimodal.py` → `AGENT_ALIASES`
5. Document in this file

### 21.3 Use text utilities in a new agent

```python
from app.utils.text_analysis import sanitize_for_agent, classify_log_type, string_metrics

text = sanitize_for_agent(raw_user_input)
metrics = string_metrics(text)
log_kind = classify_log_type(text)
```

### 21.4 Add canonical gate to orchestrator

Extend `submit_code()` stage block; persist artifact; call `fuse_stage_results()` before approval; append audit event on operator actions.

---

## 22. Suggested roadmap & ops technology

> **Strategic expansion roadmap:** See **Part II §69** for phased P0–P5 feature priorities (risk engine, blast radius, canary, evidence graph, etc.). This section covers **near-term ops** and recommended tooling for the **current baseline**.

### 22.1 Near-term enhancements

| Item | Benefit | Suggested tech |
|------|---------|----------------|
| Unified OAuth | Single sign-on across stacks | OAuth2 proxy or shared auth service |
| ORION agent memory | Context across runs | Port canonical `SQLiteAgentMemoryStore` |
| Vector RAG on logs | Better triage | pgvector / Chroma + embedding API |
| Full devops Auto-PR | Parity with ORION | Wire `AutoPRService` + GitHub App |
| OpenTelemetry traces | Distributed pipeline tracing | OTel SDK + Jaeger/Tempo |
| Signed artifacts | Tamper-evident audit | Sigstore / cosign on artifact export |

### 22.2 Recommended ops stack

| Layer | Tool |
|-------|------|
| Metrics | Prometheus scraping `/metrics` |
| Dashboards | Grafana (`observability/grafana/orion-dashboard.json`) |
| Logs | Loki or ELK; correlate with `classify_log_type` |
| Alerts | Slack webhooks + optional PagerDuty |
| CI verification | `run_e2e_all.ps1` in GitHub Actions |
| Secrets | Vault / cloud secret manager |
| Container deploy | Docker + registry (`CONTAINER_REGISTRY`) |
| Queue | Redis + Celery (devops/ORION production path) |
| DB | PostgreSQL with TLS (production) |

### 22.3 Capacity & SLO targets (suggested)

| Metric | Target |
|--------|--------|
| Pipeline success rate | ≥ 70% over rolling 20 runs |
| Failure rate | ≤ 25% |
| Blocked rate | ≤ 40% (investigate if higher) |
| p95 HTTP API latency | < 2s (excluding long-running pipeline POST) |
| Webhook processing | < 5s to `202 Accepted` |
| Mean pipeline duration | Track via SLO `mean_duration_seconds` |

---

## 23. Related documentation

| Document | Path |
|----------|------|
| Root README | `README.md` |
| ORION setup & security | `ai-cicd-pipeline/README.md` |
| Canonical API | `backend/README.md` |
| DevOps Docker/Celery | `devops-platform/README.md` |
| Grafana import | `observability/grafana/README.md` |
| **Production runbook** | `docs/PRODUCTION_RUNBOOK.md` |
| Implementation backlog | `docs/audit/IMPLEMENTATION_BACKLOG.md` |
| ORION architecture spec (source) | `docs/ORION_Architecture_and_Implementation_Specification.docx` |
| Wave 1 tracker (memory + events) | `docs/audit/ORION_SPEC_WAVE_STATUS.md` |
| **Advanced expansion report** | `docs/ORION_Advanced_Feature_Expansion_Report.md` |
| ADR 001 Memory Gateway | `docs/adr/001-memory-gateway.md` |
| ADR 002 Event backbone | `docs/adr/002-event-backbone.md` |
| Build guide (historical) | `AI_CICD_Pipeline_Copilot_Build_Guide.md` |

---

## 24. WebSocket protocol reference

Real-time pipeline visibility uses three distinct WebSocket implementations. **Do not assume event shapes are portable across stacks.**

### 24.1 ORION — `WS /ws/pipeline/{pipeline_id}`

**File:** `ai-cicd-pipeline/app/main.py`, events via `app/services/events.py`

**Redis channel:** `pipeline:{run_id}` (when Redis available); in-process fallback otherwise.

**Envelope:** every message includes `run_id` and `ts` (ISO8601 UTC).

| `kind` | Trigger | Payload fields |
|--------|---------|----------------|
| `snapshot` | Client connect | `status`, `error_message` |
| `stage-update` | Status transition | `stage`, `status` (same value) |
| `agent-complete` | Full-scan agent done | `stage`, `result_keys[]` |
| `artifact` | `_save_artifact()` | `artifact_type`, `agent`, `summary` |
| `heartbeat` | Every 15s idle | `run_id` only |
| `cancelled` / `failed` | Terminal | `stage`, `status` |

**Limits:** 200 events retained per run; max 200 tracked runs; queue maxsize 1000.

**Auth (`API_REQUIRE_AUTH=true`):** session cookie OR query `?api_key=` / `?token=` — close code **4401** on failure.

**Agent stage map (`AGENT_STAGE`):**

| Combined key | WS stage |
|--------------|----------|
| `code_issues` | `analyzing_code` |
| `security_issues` | `analyzing_security` |
| `qa_issues` | `running_qa` |

**Example:**

```json
{
  "run_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "ts": "2026-10-06T02:00:00+00:00",
  "kind": "stage-update",
  "stage": "running_stress",
  "status": "running_stress"
}
```

---

### 24.2 Canonical — dual endpoints

#### `WS /ws/pipeline-status/{pipeline_id}`

**Snapshot on connect:**

```json
{
  "type": "snapshot",
  "pipeline_id": "uuid",
  "stage": "qa",
  "status": "running",
  "history": [{"ts": "...", "stage": "dev", "message": "Full scan completed"}]
}
```

**Live event (`_publish_pipeline_event`):**

```json
{
  "type": "pipeline_stage",
  "pipeline_id": "uuid",
  "stage": "stress",
  "status": "running",
  "message": "Stress test result: pass",
  "timestamp": "2026-10-06T02:00:00"
}
```

#### `WS /ws/analyze-logs`

**Client → server:** `AnalyzeLogsRequest` JSON `{pipeline_id?, logs, multimodal_inputs?}`

**Server → client:**

```json
{"type": "monitoring_result", "pipeline_id": "...", "result": { /* MonitoringResult */ }}
{"type": "error", "message": "..."}
```

**Auth:** `?api_key=` or `?token=` when `AUTH_ENABLED` / `API_REQUIRE_AUTH`.

**Event bus:** `backend/core/queue.py` — memory deque or Redis list topic `pipeline:{id}`.

---

### 24.3 DevOps — `WS /ws/{pipeline_id}`

**Redis publish wrapper** (`app/redis_publish.py`):

```json
{
  "pipeline_id": "uuid",
  "event": { /* inner */ }
}
```

**Global channel:** `pipeline_events` (not per-run).

| Inner `type` | Fields |
|--------------|--------|
| `status_change` | `pipeline_id`, `old_status`, `new_status`, `timestamp` |
| `log` | `stage`, `level`, `message`, `timestamp` |
| `artifact` | `stage`, `data` |
| `alert` | `message`, `severity` |

**Frontend** (`usePipelineWS.ts`): exponential backoff reconnect, max 5 attempts, cap 16s. Optional `?api_key=` from `VITE_ORION_API_KEY`.

---

## 25. Pipeline state machines

### 25.1 ORION status catalog (22 values)

**Source:** `ai-cicd-pipeline/app/models/pipeline_run.py`

```
queued → ingesting → analyzing_code → analyzing_security → running_qa
  → running_stress → awaiting_approval → deploying → deployed → monitoring
```

**Block terminals:** `blocked_code`, `blocked_security`, `blocked_tests`, `blocked_stress`, `blocked_with_prs_sent`, `rejected`

**Failure terminals:** `failed`, `rolled_back`, `auto_rolled_back`, `cancelled`

**Success terminals:** `deployed`, `approved` (when `DEPLOY_MODE=skip`)

| Set | Members |
|-----|---------|
| `TERMINAL_STATUSES` | All block + failure + success terminals |
| `RETRYABLE_STATUSES` | All `blocked_*` + `failed` + `rejected` |
| `RESUMABLE_STATUSES` (API) | `failed`, `rejected`, `blocked_stress` only |

**Resume skip rules** (`orchestrator.execute_pipeline(resume=True)`):

| Checkpoint artifact | Skipped stage |
|--------------------|---------------|
| `metadata` | Re-ingest (clone) |
| `full_scan_combined` or all scan artifacts | Full scan |
| `stress_report` | Stress test |
| `approval.decision == approved` | Approval agent |

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> ingesting
    ingesting --> analyzing_code
    analyzing_code --> running_stress: scan pass
    analyzing_code --> blocked_code: code fail
    analyzing_code --> blocked_security: sec fail
    analyzing_code --> blocked_tests: qa fail
    running_stress --> awaiting_approval: pass
    running_stress --> blocked_stress: fail
    awaiting_approval --> deploying: approved
    awaiting_approval --> rejected: rejected
    deploying --> deployed: success
    deploying --> rolled_back: health fail
    deployed --> monitoring
    monitoring --> auto_rolled_back: 2x rollback rec
```

---

### 25.2 Canonical stages

**`Stage` literal:** `dev`, `qa`, `stress`, `approval`, `deployment`, `monitoring`, `blocked`, `blocked_with_prs_sent`, `completed`, `failed`, `rolled_back`, `cancelled`

| Action | Allowed statuses |
|--------|------------------|
| Retry | `blocked`, `blocked_with_prs_sent`, `failed`, `cancelled` |
| Resume | Above + `cancelling`, `running` (requires `full_scan_combined` checkpoint) |

---

### 25.3 DevOps `PipelineStatus`

```
PENDING → DEV → QA → STRESS → APPROVAL → DEPLOYMENT → MONITORING → COMPLETED
```

| Action | Allowed |
|--------|---------|
| Retry | `BLOCKED`, `FAILED`, `CANCELLED` |
| Resume | `FAILED`, `CANCELLED` (uses `StageResult` cache) |

---

## 26. Artifact schema registry

**ORM:** `pipeline_artifacts` — columns: `id`, `pipeline_run_id`, `artifact_type`, `content` (JSON/JSONB), `raw_output`, `agent_model`, `tokens_used`, `duration_seconds`, `created_at`.

**Valid types:** see `VALID_ARTIFACT_TYPES` in `app/models/pipeline_artifact.py` (22 types).

### 26.1 `metadata`

```json
{
  "repo": "owner/repo",
  "branch": "main",
  "commit": "abc123...",
  "pusher": "developer",
  "commit_message": "feat: add inventory API",
  "changed_files": ["src/app.py", "tests/test_app.py"]
}
```

### 26.2 `diff`

```json
{
  "diff": "unified diff text (truncated at 200KB in DB)",
  "truncated": true
}
```

### 26.3 `code_analysis`

```json
{
  "issues": [{"file": "src/x.py", "line": 12, "type": "undefined-name", "description": "...", "suggestion": "..."}],
  "severity": "pass|warn|fail",
  "summary": "human readable",
  "good_practices_found": [],
  "critical_issues_count": 0,
  "warnings_count": 2,
  "analysis_mode": "llm|heuristic"
}
```

**Heuristic fail rule:** ≥3 pylint/AST errors OR ≥5 warnings → severity `warn`; explicit `fail` from LLM or ≥ threshold errors.

### 26.4 `security_scan`

```json
{
  "vulnerabilities": [{"type": "hardcoded_password", "severity": "high", "file": "...", "line": 1, "cve": null, "recommendation": "..."}],
  "highest_severity": "critical|high|medium|low",
  "security_score": 72,
  "summary": "...",
  "immediate_actions": ["Rotate exposed credential"],
  "scanners": {"bandit": {"status": "completed"}, "dependencies": {"audited": 5, "not_audited": 2}},
  "analysis_mode": "llm|heuristic"
}
```

**Gate:** `exceeds_threshold(highest_severity, MAX_SECURITY_SEVERITY)` → `blocked_security`. LLM **cannot** lower scanner severity.

### 26.5 `qa_report`

```json
{
  "verdict": "pass|fail",
  "test_summary": {"total": 10, "passed": 10, "failed": 0, "errors": 0, "skipped": 0},
  "issues": [{"file": "tests/test_x.py", "line": 44, "type": "AssertionError", "description": "..."}],
  "summary": "...",
  "skipped": false,
  "analysis_mode": "simulated|llm|heuristic"
}
```

**No tests directory:** `skipped: true`, `verdict: pass`, `analysis_mode: simulated`.

### 26.6 `stress_report`

```json
{
  "performance_verdict": "pass|warn|fail",
  "p95_ms": 842.5,
  "error_rate_pct": 0.2,
  "performance_score": 88,
  "bottlenecks": ["database connection pool"],
  "summary": "...",
  "skipped": false,
  "analysis_mode": "llm|heuristic"
}
```

| Condition | Verdict |
|-----------|---------|
| error_rate > 5% OR p95 > 2000ms | `fail` |
| error_rate > 1% OR p95 > 1000ms | `warn` |
| staging unreachable | `warn` (not fail) |

### 26.7 `approval`

```json
{
  "decision": "approved|rejected",
  "confidence": 0.92,
  "reason": "...",
  "warnings": ["QA was simulated"],
  "approval_conditions": [],
  "risk_level": "low|medium|high",
  "blocked_by": "rule_engine|llm|null",
  "analysis_mode": "llm|heuristic"
}
```

### 26.8 `deployment_info`

**Docker success:**

```json
{
  "success": true,
  "image_tag": "orion-app:abc12345",
  "environment": "staging",
  "deployed_at": "2026-10-06T02:00:00+00:00",
  "health_check_passed": true,
  "generated_dockerfile": false,
  "previous_image": "orion-app:prev1234",
  "rollback": {"rolled_back": false}
}
```

**Simulated:**

```json
{
  "success": true,
  "simulated": true,
  "health_check_passed": true,
  "summary": "Simulated deployment succeeded without Docker daemon"
}
```

**Skip (`DEPLOY_MODE=skip`):**

```json
{
  "success": false,
  "skipped": true,
  "summary": "All quality gates passed; deployment skipped because DEPLOY_MODE=skip."
}
```

### 26.9 `monitoring_summary` / `monitoring_alert`

**Summary:**

```json
{
  "checks_performed": 12,
  "alerts": 1,
  "final_status": "deployed|degraded|critical",
  "window_seconds": 1800,
  "simulated": false
}
```

**Alert:**

```json
{
  "check": 7,
  "metrics": {"error_lines": 24, "health_status": 503, "response_time_ms": 3200},
  "assessment": {"status": "critical", "recommended_action": "rollback", "summary": "..."}
}
```

**Auto-rollback:** 2 consecutive checks with `recommended_action == "rollback"` → `auto_rolled_back`.

### 26.10 `auto_pr_registry`

```json
{
  "branches": [{
    "branch_name": "orion/fix-security-a1b2c3d4",
    "pr_number": 42,
    "pr_url": "https://github.com/owner/repo/pull/42",
    "category": "security|code-quality|test-failures|dockerfile",
    "issues_count": 3,
    "files": ["src/auth.py"],
    "merged": false,
    "deleted": false,
    "error": null
  }],
  "reason": "prs-opened|no-prs-opened|auto-pr-disabled|github-token-and-gh-not-configured"
}
```

### 26.11 `audit_trail`

```json
{
  "events": [{
    "ts": "2026-10-06T02:00:00+00:00",
    "action": "pipeline.retry|pipeline.resume|pipeline.cancel|pipeline.trigger",
    "actor": "github:octocat|api-key:ops-user|anonymous",
    "roles": ["operator"],
    "outcome": "queued|running|cancelled",
    "details": {"mode": "checkpoint|full"}
  }]
}
```

Max **200** events per trail (ORION artifact; canonical in `state.artifacts`).

### 26.12 `full_scan_combined`

```json
{
  "code_issues": { /* code_analysis shape */ },
  "security_issues": { /* security_scan shape */ },
  "qa_issues": { /* qa_report shape */ },
  "summary": "aggregate gate summary",
  "reasons": ["QA checks failed"]
}
```

Used by `block_status_for()` and Auto-PR grouping.

---

## 27. Auto-PR advanced runbook

### 27.1 ORION AutoPRService

**File:** `ai-cicd-pipeline/app/services/auto_pr_service.py`

| Category | Branch pattern | PR title prefix |
|----------|----------------|-----------------|
| `security` | `orion/fix-security-{run_id[:8]}` | `[ORION] Security fixes` |
| `code-quality` | `orion/fix-code-quality-{run_id[:8]}` | `[ORION] Code quality fixes` |
| `test-failures` | `orion/fix-test-failures-{run_id[:8]}` | `[ORION] Test failure fixes` |
| `dockerfile` | `orion/fix-dockerfile-{run_id[:8]}` | `[ORION] Dockerfile hardening` |

**Collision:** append `-{run_id[:6]}` suffix.

**Fix generation:** Claude returns `{file_path, fixed_content, explanation, changes_made[]}`.

**Token resolution:** session OAuth token → `GITHUB_TOKEN` env; raises if neither.

**Permissions:** `verify_permissions()` requires `repo` or `public_repo` scope.

**API version header:** `X-GitHub-Api-Version: 2022-11-28`.

**No gh CLI** in ORION — REST only.

### 27.2 Canonical AutoPRService

**File:** `backend/services/auto_pr_service.py`

**gh CLI fallback:** when no token, uses `gh auth status` + `gh repo clone` if `gh` on PATH.

**Orchestrator token candidates:** session token → settings token → gh CLI (auth `None`).

**Skip messages:**
- `"Auto PR skipped: no GitHub token available and gh CLI is not configured"`
- `"Auto PR skipped: disabled by configuration (AUTO_PR_ENABLED=false)"`

### 27.3 Auto-PR lifecycle

```mermaid
sequenceDiagram
    participant P as Pipeline
    participant A as AutoPRService
    participant GH as GitHub
    participant WH as PR Webhook
    P->>A: open_all_prs(combined_issues)
    A->>GH: create branch + commit fixes + open PR
    P->>P: status blocked_with_prs_sent
    GH->>WH: pull_request merged
    WH->>GH: delete_branch
    WH->>P: update auto_pr_registry.merged=true
```

**PR webhook:** `POST /api/v1/webhook/github/pr` — matches `branch_name` or `pr_number` in registry.

---

## 28. Deployment & rollback deep dive

### 28.1 ORION DeploymentAgent

**File:** `ai-cicd-pipeline/app/agents/deployment_agent.py`

**Mode resolution (`resolved_deploy_mode`):**

| `DEPLOY_MODE` | Result |
|---------------|--------|
| `auto` | Docker if daemon reachable (60s cache), else simulate |
| `docker` | Require Docker |
| `simulate` | Record success without container |
| `skip` | `_finish_without_deploy()` → status `approved` |

**Docker sequence:**

1. `docker version` — availability check
2. `docker build -t {image_tag} {repo_path}` — generates minimal Dockerfile if missing (python:3.11-slim + `http.server`)
3. `docker push {registry}/{image}` if `CONTAINER_REGISTRY` configured
4. `docker stop/rm {app_name}-staging`
5. `docker run -d --name {app_name}-staging -p {host}:{container} {image}`
6. Poll `GET {STAGING_URL}/health` every **5s** until **200** or `HEALTH_CHECK_TIMEOUT_SECONDS` (default 180)

**Image tag:** `{app_name}:{commit[:8]}` or `{registry}/{app_name}:{commit[:8]}`

**Rollback (`_rollback`):**

- Redeploy `previous_image` or `last_known_good_image` artifact
- Status → `rolled_back`
- Slack notification via `SlackService`

**Artifacts:** `deployment_info`, `last_known_good_image`

---

## 29. Monitoring agent specification

**File:** `ai-cicd-pipeline/app/agents/monitoring_agent.py`

### 29.1 Timing

| Config | Default | Effect |
|--------|---------|--------|
| `MONITORING_POLL_INTERVAL_SECONDS` | 30 | Sleep between checks |
| `MONITORING_WINDOW_MINUTES` | 5 | Total window ≈ `minutes × 6 × 60` = 1800s |
| `JOURNALD_ENABLED` | true | Include `journalctl` summary |

**Simulated deploy:** single pass, `checks_performed: 1`, no polling loop.

### 29.2 Metrics collected (`_collect_metrics`)

| Source | Command / probe |
|--------|-----------------|
| Container logs | `docker logs --since {interval}s --tail 200` |
| Health | HTTP status + `response_time_ms` to `{STAGING_URL}/health` |
| Journald | `orion_journald` unit summary |

### 29.3 Assessment logic

**Trigger LLM/heuristic analysis when:** errors > 5 OR exceptions > 0 OR health ≠ 200.

**Heuristic outcomes:**

| Condition | status | recommended_action |
|-----------|--------|-------------------|
| Health failing | critical | rollback |
| errors > 20 OR exceptions > 5 | degraded | alert |
| else | healthy | monitor |

**Auto-rollback counter:** increment on `rollback` recommendation; at **2 consecutive** → invoke `DeploymentAgent._rollback()` → `auto_rolled_back`.

### 29.4 Correlated monitoring (canonical)

`POST /analyze-logs` attaches `gate_correlation` from `correlate_logs_with_gates()` — see [§35](#35-gate-fusion-algorithm-full).

---

## 30. Authentication & RBAC deep dive

### 30.1 Canonical OAuth (HMAC-signed state)

**File:** `backend/api/auth.py`

```
state_token = secrets.token_urlsafe(24)
sig = HMAC-SHA256(session_secret_key, state_token)[:16 hex]
signed_state = "{state_token}.{sig}"
```

**Validation:** recompute + `hmac.compare_digest`.

**OAuth scopes:** `repo`, `read:user`, `user:email`

**Session keys stored:** `authenticated`, `github_token`, `github_username`, `github_avatar`, `github_name`, `github_email`, `token_scope`, `login_at`

**Cookie params:** `max_age=oauth_token_expiry_hours×3600`, `same_site=lax`, `https_only=false` (dev)

### 30.2 ORION OAuth

**File:** `ai-cicd-pipeline/app/api/routes/auth.py`

- State: plain `secrets.token_urlsafe(32)` in session `oauth_state`
- Production: `same_site=none`, `https_only=true`

### 30.3 API key JSON format

```json
{
  "orion-prod-automation-key-abc123xyz": {
    "user_id": "ci-bot",
    "roles": ["operator", "approver"]
  },
  "orion-readonly-key-def456uvw": {
    "user_id": "dashboard-reader",
    "roles": ["viewer"]
  }
}
```

**Env:** `AUTH_API_KEYS_JSON` (all stacks)

**Legacy ORION key:** `ORION_API_KEY` → roles `["admin", "operator"]` via `hmac.compare_digest`

**Headers accepted:** `X-ORION-API-Key`, `X-API-Key`

### 30.4 Role matrix

| Role | Permissions |
|------|-------------|
| `admin` | All operations including config |
| `operator` | retry, resume, cancel, trigger pipeline |
| `approver` | trigger-deployment, approve gates |
| `viewer` | read-only (dashboard, artifacts) |

**ORION enforcement:** `require_pipeline_operator()` on retry/resume/cancel/trigger.

**DevOps deploy:** optional `X-Deployment-Key` / `DEPLOYMENT_API_KEY` on `POST /api/pipeline/{id}/deploy`.

---

## 31. Rate limiting & edge security (nginx)

### 31.1 Application middleware

| Stack | File | Default | Window | Protected POST prefixes |
|-------|------|---------|--------|---------------------------|
| ORION | `app/middleware/rate_limit.py` | 60 (`RATE_LIMIT_REQUESTS`) | 60s | `/api/v1/webhook/`, `/api/v1/pipeline/trigger`, `/api/v1/multimodal/` |
| Canonical | `backend/core/rate_limit.py` | 60 | 60s | `/submit-code`, `/submit-archive`, `/submit-github`, `/api/v1/webhook/`, `/api/v1/multimodal/` |
| DevOps | `app/middleware/rate_limit.py` | 60 | 60s | `/webhook/`, `/api/pipeline/trigger`, `/api/multimodal/` |

**Client key:** first `X-Forwarded-For` hop → `request.client.host` → `"unknown"`

**429 response:**

```json
{"detail": "Rate limit exceeded. Retry later."}
```

Header: `Retry-After: {window_seconds}`

### 31.2 ORION nginx edge limits

**File:** `ai-cicd-pipeline/nginx/nginx.conf`

| Zone | Limit |
|------|-------|
| Webhook | 10 req/min |
| API | 60 req/min |

**Dev site:** `nginx/conf.d/orion_dev.conf`
- `/ws/` — Upgrade headers, 3600s read timeout
- `/flower/` — basic auth (`.htpasswd`)
- `/api/v1/webhook/` — proxied to app

**Prod site:** `orion.conf` via `NGINX_SITE_CONF` env

---

## 32. Celery & executor matrix

### 32.1 ORION

**Celery app:** `ai_cicd_pipeline` — `app/tasks/pipeline_tasks.py`

| Task | Name | Retries |
|------|------|---------|
| Pipeline run | `run_pipeline` | 3 × 60s countdown |
| Monitoring | `run_monitoring` | none |
| Stale reaper (beat) | `reap_stale_runs` | every 600s |

**Dispatch (`app/tasks/dispatch.py`):**

| `PIPELINE_EXECUTOR` | Behavior |
|---------------------|----------|
| `auto` | Celery if Redis PING ok, else inline asyncio |
| `celery` | Require Redis |
| `inline` | In-process; semaphore `PIPELINE_INLINE_CONCURRENCY` (default 2) |

**Startup recovery:** `recover_interrupted_runs()` — re-queue `queued`; settle others to `failed` or preserve `monitoring`.

**Stale timeout:** `STALE_RUN_TIMEOUT_MINUTES` (default 120) — non-terminal except `monitoring` → failed.

### 32.2 DevOps

**Celery app:** `devops_platform` — task `app.orchestrator.pipeline_runner.run_pipeline`

**Fallback:** daemon thread running `_run_pipeline_impl` when Redis unreachable.

---

## 33. Health vs readiness field reference

### 33.1 Canonical `/ready`

**Source:** `backend/services/preflight.py`

```json
{
  "ready": true,
  "healthy": true,
  "app_env": "dev",
  "llm_mode": "live|mock",
  "queue_backend": "memory|redis",
  "database_backend": "sqlite|postgresql",
  "database_host": "",
  "qa_mode": "simulated|real",
  "auth_enabled": false,
  "checks": {
    "redis": {"ok": true, "message": "queue backend is not redis"},
    "postgres": {"ok": true, "message": "database backend is not postgresql"}
  }
}
```

**503** when `healthy=false`. Redis check skipped if `queue_backend != redis`. Postgres skipped if not postgresql URL.

### 33.2 ORION `/ready`

**Source:** `app/services/readiness.py`

```json
{
  "ready": true,
  "timestamp": "...",
  "environment": "development|production",
  "checks": {
    "database": {"ok": true, "message": "..."},
    "redis": {"ok": true, "message": "..."},
    "executor": {"ok": true, "message": "inline|celery available"}
  }
}
```

`ready = db_ok && executor_ok`; Celery mode also requires Redis.

### 33.3 DevOps `/ready`

```json
{
  "ready": true,
  "checks": {
    "database": {"ok": true},
    "redis": {"ok": false}
  }
}
```

**Only DB blocks ready** — Redis failure is informational.

---

## 34. Command Hub & frontend routing spec

### 34.1 Hub polling (`hub/hub.js`)

| Stack | health | ready | intelligence | UI |
|-------|--------|-------|--------------|-----|
| canonical | `:8000/health` | `:8000/ready` | `:8000/api/v1/intelligence/dashboard` | `:5173` |
| orion | `:8001/health` | `:8001/ready` | `:8001/api/v1/intelligence/dashboard` | `:8001/ui/` |
| platform | `:8002/health` | `:8002/ready` | `:8002/api/intelligence/dashboard` | `:3000` |

**Refresh interval:** 15 seconds (`setInterval(refresh, 15000)`)

**Live badge criteria:** HTTP OK AND (`status==="ok"` OR `api==="ok"`)

**Intelligence panel renders:** `pipelines.total_recent`, `pass_rate`, `slo.success_rate`, `capabilities.gate_fusion`, `ready.ready`, `alerts[]`, `pipelines.top_blockers[]`

**Meta keys per stack:**
- canonical: `qa_mode`, `llm_mode`, `queue_backend`
- orion: `deploy_mode`, `executor`, `llm_mode`
- platform: `deploy_mode`, `executor`, `redis_available`

### 34.2 Frontend hash routes

**Canonical & DevOps** (`frontend/src/App.jsx`, `devops-platform/frontend`):

| Hash | View |
|------|------|
| `#/pipeline` | Pipeline submit + status (default) |
| `#/intelligence` | Cross-stack intelligence mirror |
| `#/operations` | Ops panel (retry, audit, config) |

**Query param:** `?pipeline={id}` deep-links to run.

**ORION dashboard:** single-page at `/ui/` — no hash router. Sections: `#dashboard`, modals for multimodal tools. Cross-stack pills link to Hub and other UIs.

### 34.3 Frontend env vars

```
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_HUB_URL=http://127.0.0.1:5180
VITE_ORION_API_URL=http://127.0.0.1:8001
VITE_DEVOPS_API_URL=http://127.0.0.1:8002
VITE_ORION_API_KEY=           # optional WS auth
```

---

## 35. Gate fusion algorithm (full)

**Module:** `backend/core/gate_fusion.py` (copied to ORION + devops)

### 35.1 Risk scoring table

| Signal | Violation? | Warning? | Risk Δ |
|--------|------------|----------|--------|
| code `severity == fail` | ✓ | | +35 |
| code `severity == warn` | | ✓ | +10 |
| security `critical` | ✓ | | +40 |
| security `high` | ✓ | | +25 |
| security `medium` | | ✓ | +12 |
| security `passed == false` | ✓ | | +30 |
| QA fail / `verdict==fail` | ✓ | | +30 |
| QA `skipped` | | ✓ | — |
| stress fail / `performance_verdict==fail` | ✓ | | +25 |
| stress warn | | ✓ | +8 |
| p95 > 2000ms | ✓ | | +15 |

**Cap:** `risk_score = min(100, sum(deltas))`

### 35.2 Verdict rules

| Condition | verdict | recommended_action |
|-----------|---------|-------------------|
| any violations | `fail` | Block deployment and open remediation workflow |
| warnings OR risk ≥ 20 | `warn` | Proceed with monitoring and staged rollout |
| else | `pass` | Approve for deployment |

### 35.3 `correlate_logs_with_gates(log_text, gate)`

Returns:

```json
{
  "log_type": "deployment_crash|server_timeout|...",
  "metrics": {"lines": 120, "error_lines": 8},
  "error_signatures": ["ConnectionRefusedError: ..."],
  "gate_verdict": "fail",
  "gate_risk_score": 65,
  "correlation_hints": [
    "Gate verdict is fail — prioritize violations: QA failed",
    "Log type deployment_crash with failing gate — consider rollback"
  ]
}
```

---

## 36. SLO & intelligence formulas

### 36.1 `compute_pipeline_slo(runs)`

**Success statuses:** `deployed`, `approved`, `monitoring`, `completed`, `COMPLETED`

**Blocked:** all `blocked_*`, `rejected`, `BLOCKED`, `blocked`

**Failed:** `failed`, `rolled_back`, `auto_rolled_back`, `cancelled`, `FAILED`

**Output:**

```json
{
  "window_runs": 20,
  "success_rate": 0.75,
  "blocked_rate": 0.15,
  "failure_rate": 0.10,
  "mean_duration_seconds": 142.5,
  "computed_at": "2026-10-06T02:00:00+00:00"
}
```

### 36.2 `evaluate_slo_alerts(slo)`

| Parameter | Default |
|-----------|---------|
| `min_success_rate` | 0.70 |
| `max_failure_rate` | 0.25 |
| `min_runs` | 3 |
| blocked alert threshold | > 0.40 |

**Alert codes:**

| code | severity | Trigger |
|------|----------|---------|
| `slo_success_low` | warning | success < 70% |
| `slo_failure_high` | critical | failure > 25% |
| `slo_blocked_high` | warning | blocked > 40% |

### 36.3 Slack notification dedupe

**Module:** `slo_alert_notifier.py` (all stacks)

- Key: `{stack}:{alert.code}`
- Cooldown: `SLO_ALERT_COOLDOWN_SECONDS` (default 3600)
- Triggered on intelligence dashboard GET via `BackgroundTasks`

---

## 37. Heuristic & LLM fallback matrix

### 37.1 Canonical `LLMClient`

| `LLM_MODE` | Behavior |
|------------|----------|
| `mock` | Always `heuristic_for_agent()` |
| `auto` | Live if key present; heuristic on failure |
| `live` | Live only; errors propagate |

**Heuristic handlers:** `_code_analysis`, `_security`, `_pipeline`, `_deployment`, `_monitoring_from_logs`, `_git_log`, multimodal variants — `backend/core/heuristic_llm.py`

### 37.2 ORION agents

| Trigger | Fallback |
|---------|----------|
| Missing `ANTHROPIC_API_KEY` | Per-agent `_heuristic()` |
| `_call_claude_json` failure | `{_llm_error: "..."}` + heuristic |
| Bad API key | 300s cooldown (`LLM_AUTH_COOLDOWN_SECONDS`) |

**Field marker:** `"analysis_mode": "llm|heuristic|simulated"` on every artifact.

### 37.3 Multimodal fallback

All multimodal agents implement `_heuristic()` returning valid JSON matching LLM schema minimum keys.

---

## 38. Agent memory & hybrid retriever

### 38.1 Agent memory (canonical only)

**File:** `backend/services/memory_store.py`

**SQLite table `agent_memory`:**

| Column | Type |
|--------|------|
| id | INTEGER PK AUTOINCREMENT |
| agent_name | TEXT NOT NULL |
| scope_id | TEXT NOT NULL |
| prompt_json | TEXT NOT NULL |
| response_json | TEXT NOT NULL |
| created_at | TEXT DEFAULT CURRENT_TIMESTAMP |

**API:** `get_context(agent, scope_id, limit=5)` → last N `{prompt_payload, response_payload}` pairs.

**Enabled when:** `AGENT_MEMORY_ENABLED=true` AND `database_url` starts with `sqlite`.

**Injection:** orchestrator sets `agent.memory_store` + `agent.memory_enabled` on code, security, pipeline, deployment, monitoring agents.

### 38.2 Hybrid retriever

**File:** `backend/services/retriever.py`

| `RETRIEVER_BACKEND` | Class |
|---------------------|-------|
| `hybrid`, `smart`, `advanced` | `HybridFileRetriever` |
| `files`, `chunks` | `FileChunkRetriever` |
| `noop`, `none` | `NoOpRetriever` |

**Chunk size:** 800 chars (minimum 200)

**Hybrid score:**

```
token_score = 2 × keyword_hits
fuzzy_score = SequenceMatcher(first 400/800 chars) × 5
path_boost = 1.5 if token in file path
total = token_score + fuzzy_score + path_boost  (threshold > 0.5)
```

**Returns:** top_k=3 `{path, content[:500], score}`

**Indexing:** orchestrator calls `retriever.index_files(repo_files)` on submit.

### 38.3 Memory Gateway (ORION-ARCH-001 §6)

**Library:** `shared/memory_gateway/` — single governed interface (MEM-01). All stacks that write organizational memory should use this module, not ad-hoc stores.

| Concern | Implementation |
|---------|----------------|
| Persistence (Wave 1) | `MemorySqliteStore` — `.local/orion-memory.db` |
| Layers | L1–L6 modeled; **L2 episodic** used for pipeline terminal summaries |
| Redaction | `prepare_memory_body()` fail-closed on secrets (MEM-03) |
| Injection defense | Quarantine records matching instruction-injection patterns |
| Context packing | `_pack_context()` wraps body as untrusted `[MEMORY_REF]` blocks (MEM-04) |
| Dedup | Per-tenant `content_hash` |

**ORION:** `get_memory_gateway()`, routes `memory_v2.py`, `events_v2.py`, orchestrator terminal hooks.  
**Canonical:** `memory_gateway_client.py`, `memory_extractor.py`, `pipeline_terminal_hooks.py`.  
**Hub:** `fetch_orion_platform_events()`; Operations Center `memory_panel` + `platform_events`.

**Wave 4 (planned):** Postgres + pgvector for L3 semantic retrieval without API breakage.

---

## 39. Testing & E2E verification matrix

### 39.1 Pytest locations

| Path | Count (approx) | Focus |
|------|----------------|-------|
| `backend/tests/` | 56+ | API, orchestrator, gate fusion, SLO, webhook, resume, multimodal, retriever |
| `ai-cicd-pipeline/tests/` | 168+ | Agents, webhook, orchestrator, migrations, runtime, security |
| `devops-platform/tests/` | 28+ | Webhooks, approval, pipeline API, WS, dispatch |

**Critical:** run canonical tests from `backend/` directory (import path).

### 39.2 ORION offline E2E (`scripts/e2e_run.py`)

| Flag | Purpose |
|------|---------|
| `--scenario pass\|fail\|vuln\|all` | Branch-specific expectations |
| `--offline` | No Redis/GitHub/Slack |
| `--timeout 900` | Max wait |
| `--keep` | Preserve temp repo |

| Scenario | Branch | Expected terminal |
|----------|--------|-------------------|
| pass | `main` | `approved` OR `deployed` |
| fail | `feature/discounts` | `blocked_tests` or `blocked_with_prs_sent` |
| vuln | `feature/http-client` (old requests) | `blocked_security` |

**Env pinned:** SQLite, `PIPELINE_EXECUTOR=inline`, `DEPLOY_MODE=auto`

### 39.3 Playwright (`e2e/tests/`)

| Spec | Behavior |
|------|----------|
| `hub.spec.ts` | Renders 3 stack cards, intelligence section, badge polling |
| `stacks.spec.ts` | Optional `/ready` when stacks running (skips if down) |

### 39.4 Full verification command

```powershell
.\run_e2e_all.ps1 -Offline
# Steps: canonical pytest → ORION pytest → ORION e2e_run → devops pytest → Playwright
```

---

## 40. Docker Compose topologies

### 40.1 Root `docker-compose.yml` (canonical)

| Service | Role |
|---------|------|
| backend | FastAPI :8000 |
| frontend | Vite :5173 |
| postgres | DB |
| redis | Queue |
| flower | Celery monitor |
| nginx | TLS termination |

Network: `orion_net` · Volume: `pgdata`

### 40.2 ORION `ai-cicd-pipeline/docker-compose.yml`

| Service | Role |
|---------|------|
| postgres, redis | Persistence + queue |
| app | FastAPI |
| worker, beat | Celery |
| flower | Monitor |
| nginx | Reverse proxy |

Docker socket mounted on `app` + `worker`. `STAGING_URL: http://host.docker.internal:8080`

### 40.3 DevOps `devops-platform/docker-compose.yml`

| Service | Role |
|---------|------|
| postgres, redis | DB + broker |
| backend | API :8000 (remap to 8002 in launcher) |
| celery_worker | Pipeline executor |
| frontend | :3000 |

Volumes: `postgres_data`, `redis_data`

---

## 41. HTTP error catalog

### 41.1 Global status codes

| Code | Meaning | Typical cause |
|------|---------|---------------|
| 401 | Unauthorized | Missing API key, bad webhook HMAC, WS auth fail |
| 403 | Forbidden | Insufficient role (not operator/approver) |
| 404 | Not found | Pipeline/artifact missing |
| 409 | Conflict | Retry/resume on wrong status; missing checkpoint |
| 413 | Payload too large | Archive > 50 MB |
| 422 | Unprocessable | Unknown artifact type |
| 429 | Rate limited | See §31 |
| 503 | Unavailable | `/ready` unhealthy; OAuth not configured |
| 500 | Internal | Unhandled (ORION adds detail in non-prod) |

### 41.2 ORION-specific

| Endpoint | Special response |
|----------|------------------|
| Webhook duplicate | **202** + cached `response_body` from ledger |
| Inflight dedup | **202** `{status: "duplicate", pipeline_run_id, existing_status}` |
| Resume | **409** if no checkpoint artifacts |

### 41.3 Webhook idempotency (all stacks)

Duplicate `X-GitHub-Delivery` → **202** with prior body from `webhook_deliveries` table.

---

## 42. Multimodal agent schema catalog

### 42.1 LogAnalysisAgent

**Heuristic fields:** `detected_log_type`, `error_signatures[]`, `structured_timeline[]`, `exact_fix_commands[]`, `severity`, `estimated_resolution_time_minutes`

**Log types:** `server_timeout`, `build_error`, `deployment_crash`, `memory_leak`, `database_error`, …

### 42.2 GitHubLogAgent

**Output:** `failed_jobs[]`, `root_causes[]`, `fix_suggestions[]`, `workflow_name`, `severity`

### 42.3 GitLogAgent

**Output:** `issues[]`, `risky_commits[]`, `authors[]`, `summary`

### 42.4 PaymentAgent

**Output:**

```json
{
  "failed_transactions": [{"transaction_id", "amount", "failure_reason", "recommended_retry"}],
  "error_patterns": [],
  "webhook_failures": [{"endpoint", "event_type", "failure_reason", "retry_count"}],
  "fraud_indicators": [],
  "total_failed_amount": "1234.56",
  "severity": "low|medium|high|critical",
  "immediate_actions": []
}
```

### 42.5 ProductionTriageAgent

**Severity:** P1 (outage) → P4 (informational)

**Incident types:** `outage`, `degradation`, `data_loss`, `security_breach`, `performance`

**P1/P2:** `escalate_to_human: true`

### 42.6 DockerfileAgent

**Output:** `findings[]`, `hardening_score`, `recommended_changes[]`, optional Auto-PR via `open_dockerfile_remediation_pr()`

### 42.7 Invocation

```bash
curl -X POST http://127.0.0.1:8001/api/v1/multimodal/analyze \
  -H "Content-Type: multipart/form-data" \
  -F "agent_type=log" \
  -F "text=ERROR OSError: [Errno 111] Connection refused" \
  -F "files=@/path/to/app.log"
```

**Aliases:** registered in `AGENT_ALIASES` — `log`, `github`, `git`, `payment`, `docker`, `triage`, etc.

---

## 43. GitHub integration reference

### 43.1 Commit status contexts

| Stack | Context string |
|-------|----------------|
| ORION | `ai-cicd-pipeline/pipeline` |
| Canonical | `orion-canonical/pipeline` |
| DevOps | `ORION DevOps pipeline running` |

**States:** `pending` → `success` | `failure` | `error` · Description max 140 chars.

### 43.2 Webhook security

```
expected = "sha256=" + HMAC-SHA256(secret, raw_body).hexdigest()
hmac.compare_digest(expected, X-Hub-Signature-256)
```

**Secret:** `GITHUB_WEBHOOK_SECRET` — **never** reuse `GITHUB_TOKEN`.

### 43.3 Pipeline dedup (ORION)

**Inflight query:** same `repo_full_name` + `commit_id` + non-terminal status.

**Response:**

```json
{
  "status": "duplicate",
  "pipeline_run_id": "...",
  "commit_id": "...",
  "repo_full_name": "owner/repo",
  "executor": "celery|inline",
  "existing_status": "running_stress"
}
```

### 43.4 Branch cleanup

`GitHubService.delete_branch(repo, branch)` — 404/422 treated as already deleted.

Triggered by merged Auto-PR webhook on all stacks with Auto-PR support.

### 43.5 Block evaluation (`block_status_for`)

Priority order:
1. code `severity==fail` → `blocked_code`
2. security exceeds threshold → `blocked_security`
3. QA `verdict==fail` → `blocked_tests`

`has_warnings()`: code warn OR any security finding OR any `skipped: true` sub-artifact.

---

## 44. Audit trail & operator actions

### 44.1 Recorded actions

| action | stacks | Trigger |
|--------|--------|---------|
| `pipeline.retry` | all | POST retry |
| `pipeline.resume` | all | POST resume |
| `pipeline.cancel` | all | POST cancel |
| `pipeline.trigger` | ORION/devops | Manual trigger |
| `deployment.approve` | canonical | trigger-deployment |

### 44.2 Event shape

```json
{
  "ts": "ISO8601",
  "action": "pipeline.resume",
  "actor": "github:username|api-key:user_id|anonymous",
  "roles": ["operator"],
  "outcome": "running|queued|cancelled",
  "details": {"mode": "checkpoint"}
}
```

### 44.3 Query

| Stack | Endpoint | Limit |
|-------|----------|-------|
| ORION | `GET /api/v1/pipeline/runs/{id}/audit` | last 50 events |
| Canonical | `GET /pipelines/{id}/audit` | last 50 |
| DevOps | `GET /api/pipeline/{id}/audit` | last 50 |

---

## 45. Operational runbooks

### 45.1 Pipeline blocked on security

1. Fetch artifact: `GET .../artifacts/security_scan`
2. Fix bandit/pip-audit findings or bump pinned deps
3. If intentional: adjust `MAX_SECURITY_SEVERITY` (non-prod only)
4. `POST .../retry` or `/resume` if checkpoint exists

### 45.2 Staging unreachable (stress warn)

1. Verify `STAGING_URL` reachable from worker container
2. Check Docker staging container: `docker ps | grep staging`
3. Re-run stress after fix; warn does not block unless configured

### 45.3 Auto-rollback fired

1. Check `monitoring_alert` artifacts for rollback reason
2. Inspect `deployment_info.rollback`
3. Verify `last_known_good_image` redeployed
4. Status should be `auto_rolled_back` or `rolled_back`

### 45.4 SLO alert received in Slack

1. Open Command Hub intelligence panel or `GET /intelligence/dashboard`
2. Review `top_blockers` and `alerts[].code`
3. If `slo_blocked_high`: inspect gate fusion violations across recent runs
4. Tune cooldown via `SLO_ALERT_COOLDOWN_SECONDS` if noisy

### 45.5 Webhook replay (expected)

Second delivery with same `X-GitHub-Delivery` returns **202** — not an error. Verify ledger row in `webhook_deliveries`.

### 45.6 Celery worker not processing

1. `GET /ready` — check `executor` and `redis` checks
2. Verify `REDIS_URL` and worker container logs
3. Fallback: set `PIPELINE_EXECUTOR=inline` for dev

### 45.7 Production deployment

1. Generate secrets: `python scripts/generate_production_env.py` (add `--local-sim` without Docker)
2. Preflight: `python scripts/production_preflight.py` (must exit 0)
3. Infra: `docker compose --env-file .env.prod.infra -f docker-compose.prod.yml up -d`
4. Launch: `.\run_production.ps1 -SkipInstall`
5. Verify: `orion production checklist` or `GET /api/v1/production/ready` with `X-ORION-API-Key`
6. Stop: `.\stop_local_all.ps1` ; `docker compose -f docker-compose.prod.yml down`

**Common failures:**

| Symptom | Fix |
|---------|-----|
| `validate_startup` SECRET_KEY error | Replace placeholders in `.env.production` |
| Preflight DATABASE_URL placeholder | Re-run `generate_production_env.py --force` |
| 401 on protected APIs | Set `ORION_API_KEY` / `X-ORION-API-Key` header |
| Docker unavailable | Use `.\run_production.ps1 -LocalSim` (auto-detected) |

---

## 46. Glossary

| Term | Definition |
|------|------------|
| **Agent** | Autonomous unit executing one pipeline stage or analysis task |
| **Artifact** | JSON document persisted as pipeline output |
| **Gate** | Quality checkpoint that can block deployment |
| **Gate fusion** | Unified verdict merging code/security/QA/stress |
| **Heuristic mode** | Deterministic fallback when LLM unavailable |
| **Inflight run** | Non-terminal pipeline for same repo+commit |
| **Ledger** | `webhook_deliveries` idempotency store |
| **LKG image** | Last known good container image for rollback |
| **Checkpoint resume** | Continue pipeline skipping completed stages |
| **Simulated deploy** | Records deploy success without Docker |
| **Terminal status** | Run will not progress without retry/resume |
| **PRODUCTION_LOCAL_SIM** | Production auth/gates with SQLite backend (local laptop only) |
| **Production hardening** | ORION checklist scoring auth, secrets, DB, CORS, gates |

---

## 47. Quick reference cards

### 47.1 Start everything

```powershell
.\run_all_stacks.ps1
# Hub :5180 | Canonical :8000/:5173 | ORION :8001/ui/ | DevOps :8002/:3000+ (see launcher banner if 3000 busy)
```

### 47.2 Trigger ORION pipeline manually

```bash
curl -X POST http://127.0.0.1:8001/api/v1/pipeline/trigger \
  -H "Content-Type: application/json" \
  -H "X-ORION-API-Key: YOUR_KEY" \
  -d '{"repo_full_name":"owner/repo","branch":"main","commit_id":"FULL_SHA"}'
```

### 47.3 Submit canonical code

```bash
curl -X POST http://127.0.0.1:8000/submit-code \
  -H "Content-Type: application/json" \
  -d '{"repo_name":"demo","code":"print(1)","repo_files":{"main.py":"print(1)"}}'
```

### 47.4 Intelligence dashboard

```bash
curl -s http://127.0.0.1:8001/api/v1/intelligence/dashboard | jq '.slo,.alerts,.pipelines.top_blockers'
```

### 47.5 Text analyze preflight

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/tools/text-analyze \
  -H "Content-Type: application/json" \
  -d '{"text":"ERROR ModuleNotFoundError: flask","operations":["classify_log","errors","sanitize"]}'
```

### 47.6 Production env minimum

```env
APP_ENV=production
API_REQUIRE_AUTH=true
SECRET_KEY=<64-char random hex>
SESSION_SECRET_KEY=<64-char random hex>
GITHUB_WEBHOOK_SECRET=<dedicated secret>
ANTHROPIC_API_KEY=<scoped key>
AUTH_API_KEYS_JSON={"key-id":{"user_id":"ops","roles":["operator","approver"]}}
ORION_API_KEY=<automation key for CLI>
SLACK_WEBHOOK_URL=<incoming webhook>
DEPLOY_MODE=auto
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/orion?ssl=require
REDIS_URL=redis://host:6379/0
PIPELINE_EXECUTOR=celery
PROMPT_INJECTION_GATE_ENABLED=true
POLICY_ENFORCEMENT_ENABLED=true
UNIFIED_RISK_GATE_ENABLED=true
```

Generate locally: `python scripts/generate_production_env.py` (add `--local-sim` without Docker).

### 47.7 Start production mode

```powershell
# One-shot: generate secrets + launch (auto LocalSim when Docker missing)
.\run_production.ps1 -GenerateSecrets -SkipInstall

# Verify
orion production checklist
curl -H "X-ORION-API-Key: $ORION_API_KEY" http://127.0.0.1:8001/api/v1/production/ready
```

---


# Part II — Strategic Architecture & Advanced Feature Expansion

> **Read this part as the evolution roadmap.** Part I documents the **current baseline**. Part II defines how ORION matures from an AI-assisted CI/CD pipeline into an **AI-native DevSecOps/SRE control plane** without discarding existing hard gates, artifacts, or audit patterns.

**Core strategic thesis:** The biggest opportunity is **not** adding isolated agents. It is layering **intelligence, evidence, and policy** on top of the existing 9-stage pipeline, gate fusion, and artifact model.

**Implementation status (2026-10-07):** Phases **0–30** are **complete** on ORION (`ai-cicd-pipeline/`), including **production hardening** (Phase 30). Authoritative shipped inventory: `docs/audit/IMPLEMENTATION_BACKLOG.md`. Feature-group headings below may retain original `📋` markers from the roadmap draft; **§69** and the backlog supersede them.

---

## 48. Executive assessment & maturity model

### 48.1 Current maturity (baseline vs advanced target)

| Area | Baseline (today) | Target | Part I reference |
|------|------------------|--------|------------------|
| CI/CD orchestration | ★★★★★ | ★★★★★ | §4, §7 |
| AI code analysis | ★★★★☆ | ★★★★★ | CodeAnalysisAgent §5 |
| Security | ★★★★☆ | ★★★★★ | SecurityAgent + bandit/pip-audit §5 |
| QA automation | ★★★★☆ | ★★★★★ | QAAgent §5 |
| Performance testing | ★★★★☆ | ★★★★★ | StressTestAgent §5 |
| Deployment | ★★★★☆ | ★★★★★ | DeploymentAgent §28 |
| Observability | ★★★★☆ | ★★★★★ | §12, MonitoringAgent §29 |
| Incident response | ★★★☆☆ | ★★★★★ | ProductionTriageAgent §42 — expand |
| Supply-chain security | ★★☆☆☆ | ★★★★★ | pip-audit only — SBOM planned |
| Infrastructure-as-Code | ★★☆☆☆ | ★★★★★ | DockerfileAgent partial |
| Cloud/Kubernetes | ★★☆☆☆ | ★★★★★ | Docker-only deploy today |
| AI governance | ★★☆☆☆ | ★★★★★ | analysis_mode only — expand |
| Cost optimization | ★★☆☆☆ | ★★★★★ | not tracked |
| Developer experience | ★★★☆☆ | ★★★★★ | Hub + dashboards |
| Release intelligence | ★★★☆☆ | ★★★★★ | gate fusion §35 — expand |
| Autonomous remediation | ★★★☆☆ | ★★★★★ | Auto-PR §27 — expand |
| Policy-as-code | ★★☆☆☆ | ★★★★★ | hard-coded gates only |
| Platform engineering | ★★★☆☆ | ★★★★★ | 3 stacks + Hub |
| Enterprise governance | ★★★☆☆ | ★★★★★ | RBAC + audit §30, §44 |

### 48.2 What the baseline already provides

The current system is **not greenfield**. Shipped capabilities include:

- 9-stage pipeline with **parallel** code/security/QA (ORION)
- Hard security gates (LLM cannot downgrade bandit severity)
- Locust stress gate, approval gate, Docker/simulate/skip deploy
- Monitoring with **2× rollback recommendation → auto_rollback**
- Auto-PR with category branches and PR webhook cleanup
- Multimodal agents (logs, git, payment, triage, Dockerfile)
- **Gate fusion** unified risk score 0–100 (§35)
- Stage-aware **resume**, webhook **delivery ledger**, **audit trail**
- SLO compute + Slack alerts, Prometheus/Grafana path
- Canonical **hybrid retriever** + SQLite **agent memory**
- Cross-stack **Command Hub** intelligence polling

**Preserve:** deterministic gates before LLM override (ApprovalAgent hard rules). Never let the LLM become an unrestricted administrator.

---

## 49. Strategic positioning

### 49.1 Evolution statement

| From | To |
|------|-----|
| AI CI/CD pipeline | **Autonomous Software Delivery & Reliability Control Plane** |

### 49.2 One-line description

> An autonomous DevSecOps and SRE platform that analyzes code, predicts release risk, validates security and quality, orchestrates progressive deployments, monitors production, investigates incidents, and safely automates remediation.

### 49.3 Technical positioning stack

```text
AI Engineering + DevSecOps + CI/CD + SRE + Observability
+ Software Supply Chain + Policy-as-Code + Autonomous Remediation
```

### 49.4 Portfolio narrative

For AI Product Engineer / Platform Engineering portfolios, ORION demonstrates:

- Multi-agent orchestration with artifact-backed decisions
- Hard gates + heuristic/LLM hybrid execution
- Cross-stack ops plane (Hub, intelligence, SLO)
- Roadmap toward evidence graphs and progressive delivery

---

## 50. Six control planes architecture

Target architecture — ORION as **six cooperating planes** (not six separate products):

```text
                         ┌─────────────────────────────┐
                         │       ORION COMMAND HUB     │
                         │ Fleet / Projects / Releases │
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
      ┌───────▼────────┐       ┌────────▼────────┐       ┌────────▼────────┐
      │  SOURCE PLANE  │       │ INTELLIGENCE    │       │ POLICY PLANE    │
      │ GitHub / Git    │       │ AI / ML / RAG   │       │ Rules / OPA     │
      │ PR / Commit     │       │ Risk / Reason   │       │ Compliance      │
      └───────┬────────┘       └────────┬────────┘       └────────┬────────┘
              │                         │                         │
              └─────────────────────────┼─────────────────────────┘
                                        │
                              ┌─────────▼─────────┐
                              │ DELIVERY PLANE    │
                              │ Build/Test/Deploy │
                              │ Canary / GitOps   │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │ RELIABILITY PLANE │
                              │ SRE / Observability│
                              │ Incident / Healing │
                              └─────────┬─────────┘
                                        │
                              ┌─────────▼─────────┐
                              │ GOVERNANCE PLANE  │
                              │ Audit/Cost/Access │
                              │ Compliance        │
                              └───────────────────┘
```

| Plane | Baseline today | Expansion |
|-------|----------------|-----------|
| **Command Hub** | Health + intelligence polling (§34) | Fleet view, incidents, releases dashboard |
| **Source** | GitHub webhooks, clone, diff | PR intelligence, signed commits, dependency graph |
| **Intelligence** | Gate fusion, LLM agents, retriever (canonical) | Change risk engine, DevOps RAG, model router |
| **Policy** | Hard-coded gates, MAX_SECURITY_SEVERITY | OPA/Conftest, compliance packs, promotion rules |
| **Delivery** | Docker deploy, simulate, Auto-PR | Canary, blue-green, preview envs, GitOps |
| **Reliability** | MonitoringAgent, SLO, correlated logs | Incident commander, evidence graph, chaos |
| **Governance** | Audit trail, RBAC, artifact catalog | FinOps, AgentEval, release passport, SSO |

---

## 51. Baseline → target mapping

| Expansion feature | Builds on (Part I) |
|-------------------|-------------------|
| Change Risk Engine | `fuse_stage_results()` §35, `metadata`/`diff` artifacts §26 |
| Blast radius | Service graph (new) + `full_scan_combined` |
| SBOM | `security_scan.scanners.dependencies` §26 |
| Container security | DeploymentAgent Docker path §28 |
| IaC security | DockerfileAgent §42 + Terraform/K8s parsers (new) |
| Secret Guardian | `redact_secrets()` §14 + SecurityAgent |
| Autonomous fix loop | AutoPRService §27 + sandbox (new) |
| Patch confidence | QA artifacts + new `patch_confidence` artifact |
| Test intelligence | QAAgent §5 + pytest JSON mapping |
| Canary / progressive | DeploymentAgent + MonitoringAgent §28–§29 |
| Incident commander | ProductionTriageAgent + LogAnalysisAgent §42 |
| Evidence graph | Audit trail §44 + artifact lineage (new) |
| Error budget engine | SLO §36 + intelligence dashboard §9 |
| Agent sandbox | BaseAgent execution model §5 |
| Policy engine | ApprovalAgent hard rules §5 |
| Release passport | All pipeline artifacts §26 |
| Event bus | WebSocket + Redis events §24, Celery §32 |

---

## 52. Feature Group A — Intelligent Risk Engine

**Status:** 🔄 partial (`fuse_stage_results` risk 0–100) · **Target:** ORION signature capability

### A1. Change Risk Intelligence ✅

**Status:** Shipped — `change_risk_report` artifact + `app/utils/change_risk.py` (multi-dimensional heuristic scoring, service-graph downstream enrichment).

Every commit receives a structured **ORION Change Risk Score**:

```text
ORION Change Risk Score
────────────────────────
Code Risk             18/100
Security Risk         42/100
Dependency Risk       21/100
Test Risk             63/100
Blast Radius          72/100
Production Risk       58/100
Historical Risk       44/100
AI Confidence         91%
────────────────────────
FINAL RISK             61/100
```

**Inputs:** files/LOC changed, critical paths (auth, payments, migrations), API/schema changes, dependency delta, historical failures, ownership, coverage, incidents, traffic, deploy frequency, service criticality.

**Examples:**
- `README.md` only → near-zero risk
- `auth/middleware.py` + `payments/service.py` + `migrations/*` → automatic HIGH risk, require canary + approver

**Artifact:** `change_risk_report` (persisted after stress, before approval)

### A2. Blast Radius Engine ✅

**Status:** Shipped — path-based critical categories in `change_risk.analyze_changed_paths()` plus `service_graph.downstream_hint` on `change_risk_report`.

Trace impact chain:

```text
Commit → Changed service → Dependencies → DB → Downstream APIs → Users
```

**Output:**

```text
Estimated blast radius: HIGH
Affected: payment-api, order-service, notification-service
Databases: payments_db
APIs: POST /payments, GET /orders/{id}
Recommended: extended integration tests, staging, canary, synthetic payment tests, manual approval
```

### A3. Service Dependency Graph 📋

**ORION Service Graph** — continuously updated from repos, Compose, K8s, Terraform, OpenAPI, traces, logs.

**Uses:** blast radius, deploy ordering, incident diagnosis, architecture viz, impact prediction.

---

## 53. Feature Group B — Advanced DevSecOps & supply chain

**Baseline:** ✅ bandit + pip-audit (ORION), LLM cannot downgrade severity (§5)

### B1. Expanded SAST 📋

Add Semgrep, CodeQL, language-specific rules, AST security rules alongside bandit.

### B2. Reachable SCA 📋

Move from "CVE exists" to:

> CVE exists, vulnerable function unreachable in production payment path.

**Dimensions:** version → CVE → CVSS → exploitability → reachability → production exposure.

### B3. SBOM generation 📋

Automatic SBOM artifact: app deps, OS packages, Docker layers, transitive deps.

**Formats:** CycloneDX, SPDX · **Artifact:** `sbom` (add to `VALID_ARTIFACT_TYPES`)

### B4. ContainerSecurityAgent 📋

```text
Dockerfile → Build → Image → OS scan → package scan → secret scan
→ malware scan → root/privileged check → runtime posture
```

Checks: root user, privileged mode, exposed ports, writable FS, capabilities, outdated base, provenance.

### B5. IaCSecurityAgent 📋

Analyze Terraform, K8s YAML, Helm, Compose, CloudFormation via Checkov, tfsec, kube-score, Trivy, OPA/Conftest.

Detect: public S3, `0.0.0.0/0`, privileged pods, public DB, missing encryption, hardcoded creds.

### B6. SecretGuardianAgent 📋

Beyond `redact_secrets()` — developer-facing remediation:

```text
SECRET DETECTED — AWS Access Key in config/prod.py — CRITICAL
1. Revoke  2. Rotate  3. Remove from Git history  4. Vault  5. Re-run pipeline
```

### B7. ArtifactTrustAgent 📋

Supply-chain trust chain:

```text
Signed commit → dependency verify → SBOM → build provenance → signed image → verified deploy
```

---

## 54. Feature Group C — AI code engineering & test intelligence

**Baseline:** ✅ CodeAnalysisAgent, Auto-PR, QAAgent pytest mapping (§5, §27)

### C1. AI Software Engineer Agent 📋

Pipeline: Detect → Understand → Diagnose → Generate patch → Test → Verify → Open PR

**Principle:** LLM never touches production — **isolated workspace only**.

### C2. Autonomous Fix Loop 📋

```text
Test fail → Root cause → Patch → Sandbox build → Unit tests → Security scan
→ Regression → Patch confidence → Auto PR (if threshold met)
```

### C3. Patch Confidence Score 📋

```text
Patch confidence: 94%
Compilation ✓ | Unit 127/127 ✓ | Security ✓ | Diff complexity Low
>90% → Auto PR | 70–90% → Review required | <70% → Reject
```

**Artifact:** `patch_confidence_report`

### C4. TestIntelligenceAgent 📋

Functions: test selection, prioritization, flaky detection, missing tests, regression prediction, coverage analysis, test generation, mutation testing, contract testing.

### C5. Intelligent test selection 📋

Changed `payment/service.py` → run ~412 relevant tests, not all 8,000.

### C6. Flaky test intelligence 📋

Historical stats per test: runs, pass/fail, retry-pass, flakiness %, classification (stable/flaky/new fail/env-sensitive).

### C7. AI test generation 📋

For changed functions, generate normal/zero/boundary/exception cases; validate tests themselves.

### C8. Mutation testing 📋

Controlled mutations (`>` → `>=`, etc.); mutation score + weak-area recommendations.

### C9. Contract testing 📋

OpenAPI diff across services — block breaking API releases automatically.

---

## 55. Feature Group D — Release engineering & progressive delivery

**Baseline:** ✅ Docker/simulate/skip, health rollback, auto_rollback on monitoring (§28–§29)

### D1. ORION Release Manager 📋

```text
Dev → CI → Security → Staging → Synthetic → Canary → Observe → Progressive → 100%
```

### D2. Canary deployment 📋

`5% → observe 10m → 25% → 50% → 100%` — auto-stop on error rate, p95, CPU, memory, conversion, SLO breach.

### D3. Automated rollback intelligence 📋

Enhance existing 2× rollback rule with baseline comparison, root-cause confidence, commit attribution:

```text
Error 0.8%→4.9%, p95 380ms→1.8s, POST /checkout, commit 7f8c21, rollback confidence 96%
```

### D4. Blue-green deployment 📋

Deploy green → health → synthetic → small traffic → compare telemetry → switch → retain blue.

### D5. Environment promotion engine 📋

```yaml
production:
  requires:
    security: pass
    tests: pass
    approval: true
    risk_score: < 60
    canary: pass
```

Paths: DEV → TEST → STAGING → CANARY → PRODUCTION

---

## 56. Feature Group E — SRE & incident intelligence

**Baseline:** 🔄 ProductionTriageAgent, LogAnalysisAgent, MonitoringAgent (§6, §29, §42)

### E1. ORION Incident Commander 📋

```text
Alert → Detection → Logs → Traces → Deploy correlation → Dependencies
→ RCA hypothesis → Remediation → Rollback → Postmortem
```

### E2. Automatic RCA 📋

Correlate incident + logs + metrics + traces + deployments + commits + flags + dependencies.

Example output: *Redis pool regression from release 4f2a9d at 14:29 UTC.*

### E3. Incident timeline generator 📋

Auto-build minute-by-minute timeline → feed postmortem agent.

### E4. Automated Postmortem Agent 📋

Sections: Summary, Impact, Timeline, Root Cause, Contributing Factors, Detection, Response, Resolution, Corrective/Preventive actions — **every claim evidence-linked**.

### E5. Evidence Graph 📋

**Most distinctive target feature** — relational chain:

```text
Incident INC-204 → Deployment DEP-821 → Commit 93ab21 → payment/service.py
→ test_refund_timeout → Security SEC-442
```

Answers: *"Why did this incident happen?"* with cited artifacts.

---

## 57. Feature Group F — Observability 2.0 & error budgets

**Baseline:** ✅ Prometheus metrics, SLO compute, Slack alerts (§12, §36)

### F1. OpenTelemetry-native architecture 📋

Unified logs + metrics + traces + profiles with correlation keys: `trace_id`, `span_id`, `service`, `deployment`, `commit`, `environment`.

### F2. Golden signals dashboard 📋

Per service: Latency, Traffic, Errors, Saturation — availability, p95, error rate, throughput, CPU, memory.

### F3. SLO / error budget engine 📋

Beyond breach detection:

```text
SLO 99.9% | Current 99.96% | Error budget 34% remaining
→ Freeze risky releases when 82% of monthly budget consumed
```

Integrates with promotion engine (§55 D5).

---

## 58. Feature Group G — AI governance & agent safety

**Baseline:** 🔄 per-agent models, `analysis_mode`, heuristic fallback (§16, §37)

### G1. AI Governance Plane 📋

Track: model, prompt version, tokens, latency, cost, confidence, fallback, hallucination indicators, human override.

Registries: Model, Prompt, Evaluation, Decision.

### G2. AI Model Router 📋

Route by task complexity — small model for lint explanations, reasoning model for RCA, deterministic scanner + AI explanation for security.

### G3. AI confidence + human escalation 📋

```json
{"decision": "reject", "confidence": 0.94, "human_review_required": false}
```

Rule: `confidence < 0.70` → human review queue.

### G4. AgentInputFirewall 📋

Treat repo content as **untrusted data** — classify, isolate, redact, detect prompt injection before agent execution.

Critical for PR descriptions, issues, uploaded docs in multimodal flows.

### G5. Agent permission model 📋

```yaml
security_agent:
  read: [repository, dependencies]
  write: [artifacts]
  execute: [security_scanners]
  external: none

deployment_agent:
  write: [deployment]
  execute: [docker]
  approval: {required: true}
```

### G6. Agent sandbox 📋

Filesystem, network, shell, credential, CPU, memory, timeout limits — mandatory for Auto-PR and autonomous patches.

### G7. Agent observability 📋

Per-agent: executions, success %, fallback %, latency, LLM cost, false-positive rate, human overrides.

### G8. AgentEval + prompt versioning 📋

Accuracy, consistency, groundedness, safety — compare prompt v1.8 vs v1.9 before promotion.

---

## 59. Feature Group H — Policy-as-code & compliance

**Baseline:** 🔄 hard-coded gates in ApprovalAgent / orchestrator

### H1. ORION Policy Engine 📋

```yaml
policy:
  name: production-security
  deny_if:
    critical_vulnerabilities: ">0"
    secrets_detected: ">0"
    unsigned_image: true
  require:
    tests: true
    sbom: true
    approval: true
```

Engine: OPA / Conftest integration — business rules outside Python code.

### H2. Compliance engine 📋

Policy packs: SOC 2, ISO 27001, OWASP, CIS, PCI DSS, GDPR, HIPAA.

Output control/evidence/status/owner/last-verified tables — not checkbox claims.

---

## 60. Feature Group I — Cost & FinOps intelligence

**Status:** 📋 not in baseline

### I1. FinOps Agent 📋

Track CI compute, Docker build, LLM tokens, GPU, storage, network — per repo, team, pipeline, agent, model.

### I2. AI cost optimization 📋

Detect over-provisioned models (e.g. expensive model on trivial dependency scan) → recommend deterministic + small model.

**Artifact:** `cost_report` (monthly rollup in intelligence dashboard)

---

## 61. Feature Group J — Repository intelligence & DevOps RAG

**Baseline:** 🔄 hybrid retriever + agent memory (canonical only, §38)

### J1. Repository Knowledge Graph 📋

Index: services, files, functions, APIs, dependencies, tests, owners, deployments, incidents.

Queries: *"What breaks if I change this API?"* · *"Show incidents for this module."*

### J2. ORION DevOps RAG 📋

Sources: repo, architecture docs, runbooks, incidents, PRs, deploy history, logs, alerts, OpenAPI, policies.

Answers must **cite evidence** from graph + artifacts — not hallucinate.

### J3. Runbook automation 📋

```text
Incident signature → Runbook #REDIS-004 → Approved remediation → Execute (with policy gate)
```

---

## 62. Feature Group K — Environment, chaos & DR intelligence

### K1. Ephemeral preview environments 📋

Per-PR: build → deploy `pr-{n}.preview.orion.internal` → test → Playwright → destroy.

### K2. Synthetic production monitoring 📋

Periodic login/search/checkout/payment flows — detect failures before users.

### K3. ChaosAgent 📋

Controlled: kill container, latency injection, network drop, DB restart, disk fill, CPU/memory stress — verify recovery, alerts, rollback, SLO.

### K4. Disaster recovery agent 📋

Test backup/restore/failover — report RTO/RPO observed vs target.

---

## 63. Feature Group L — Kubernetes & cloud-native

**Baseline:** Docker deploy only (§28)

### L1. KubernetesAgent 📋

Analyze Deployments, Services, Ingress, Secrets, HPA, PDB, NetworkPolicy, RBAC — missing probes, privileges, risky rollouts.

### L2. Auto-scaling intelligence 📋

Recommend HPA min/max from traffic/latency predictions.

### L3. Multi-cloud abstraction 📋

Long-term: AWS/Azure/GCP/on-prem/K8s as deployment targets via unified ORION config — not hard-coded Docker.

---

## 64. Feature Group M — Advanced Command Hub & fleet ops

**Baseline:** ✅ health + intelligence polling (§34)

### M1. ORION Operations Center 📋

Single pane: active pipelines, deployments, incidents, SLO health, aggregate risk, service health grid, active incidents, canary releases.

### M2. Fleet view 📋

Multi-repo: *"Which services are at highest risk right now?"*

### M3. Developer dashboard 📋

PRs, failed pipelines, flaky tests, security debt, CI time — **quality-focused**, not surveillance.

### M4. Team engineering health 📋

DORA + SRE metrics: deploy frequency, lead time, change failure rate, MTTR, flaky rate, security debt.

---

## 65. Feature Group N — DORA & predictive release intelligence

### N1. DORA intelligence 📋

Auto-compute four metrics + elite/high/medium/low band with **explanation of why**.

### N2. Predictive failure detection 📋

*"This deployment has 73% probability of causing rollback"* from change size, author, components, test/security signals, service history, SLO state.

**Artifact:** `release_prediction`

---

## 66. Feature Group O — Event-driven architecture & agent registry

**Baseline:** 🔄 WebSocket events, Redis pub/sub (§24), Celery tasks (§32)

### O1. Event bus 🔄 partial

**Shipped (Wave 1):** `shared/event_bus/`, `PlatformEvent` envelope, Redis Streams + in-memory fallback; `pipeline.started` / `pipeline.completed` from ORION + canonical orchestrators; Hub `GET /control-plane/platform-events`; ORION `GET /api/v2/events/recent`.

**Planned:** Full domain catalog (`CommitCreated`, `SecurityCompleted`, `IncidentDetected`, …) and agent subscriptions without orchestrator edits.

### O2. Agent registry 📋

```yaml
name: SecurityAgent
version: 2.1.0
capabilities: [sast, sca, secrets]
permissions: {...}
input_types: [repo_path, diff]
output_artifacts: [security_scan]
risk_level: high
model: ${SECURITY_MODEL}
timeout: 300
```

Extends Part I extension guide (§21) with formal metadata and discovery.

---

## 67. Feature Group P — Artifact intelligence & release passports

**Baseline:** ✅ structured artifacts + catalog (§26)

### P1. Artifact lineage 📋

```text
Commit → Build → Image → SBOM → Deployment → Runtime
```

First-class artifact objects: type, version, producer, evidence, confidence, dependencies, retention.

### P2. Release Passport ✅

Enterprise artifact per production deploy (ORION `release_passport` pre-deploy gate):

```text
Release v3.8.2 | Commit a72bc19 | Tests 1,284 PASS | Security 0 Critical
SBOM ✓ | Risk 28/100 | Canary 10m PASS | SLO PASS | 47 evidence artifacts
```

### P3. Change Passport 📋

Per-PR summary: developer, risk, files, tests, security, API/infra impact, approval, outcome.

---

## 68. Target control plane architecture

Mature ORION control plane (target state):

```text
                         ORION CONTROL PLANE
                                │
              ┌─────────────────┼─────────────────┐
              │                 │                 │
         SOURCE GRAPH       POLICY ENGINE     AI ENGINE
              │                 │                 │
       Git / GitHub         OPA / Rules       Model Router
       PR / Commit          Compliance        RAG / AgentEval
       Dependency           Governance        Agent Sandbox
              │                 │                 │
              └─────────────────┼─────────────────┘
                                │
                         RISK INTELLIGENCE
                                │
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
       CODE                    SEC                    QA
       SAST                    SCA/SBOM               Test Intel
       AI Review               Secrets/IaC            Mutation/Contract
          │                     │                     │
          └─────────────────────┼─────────────────────┘
                                │
                         RELEASE ENGINE
                                │
                 ┌──────────────┼──────────────┐
                 │              │              │
              Staging         Canary       Blue/Green
                 │              │              │
                 └──────────────┼──────────────┘
                                │
                           PRODUCTION
                                │
                   ┌────────────┼────────────┐
                   │            │            │
                Metrics       Logs         Traces (OTel)
                   │            │            │
                   └────────────┼────────────┘
                                │
                       SRE / INCIDENT AI
                                │
                    ┌───────────┼───────────┐
                    │           │           │
                   RCA       Remediation   Rollback
                    │           │           │
                    └───────────┼───────────┘
                                │
                         EVIDENCE GRAPH
                                │
                        AUDIT / GOVERNANCE
```

---

## 69. Priority roadmap (Phases 1–29)

**Status (ORION `ai-cicd-pipeline/`):** Phases **1–29 complete** — control-plane expansion through **Unified Risk Engine** (`unified_risk_intelligence`). Phases 1–5 cover 48 core features; Phases 6–29 add repository intel, supply chain, progressive delivery, SRE bundle, enterprise IAM/DR, knowledge graph, autopilot, and fused risk rollup. Canonical `backend/` retains change-risk + multimodal parity; extended phases are ORION-primary unless noted.

Phases build incrementally on Part I baseline; all planned roadmap phases are now shipped.

### Phase 1 — Highest ROI (P0)

| # | Feature | Status | Builds on |
|---|---------|--------|-----------|
| 1 | Change Risk Intelligence Engine | ✅ | Gate fusion §35, `change_risk_report` |
| 2 | Blast Radius Analysis | ✅ | `analyze_changed_paths()` + service graph downstream |
| 3 | Service Dependency Graph | ✅ | `service_graph` artifact |
| 4 | SBOM generation | ✅ | `sbom` artifact (CycloneDX subset) |
| 5 | Container Security Agent | ✅ | `container_security_scan` artifact |
| 6 | Secrets Guardian | ✅ | `secrets_scan` + `blocked_secrets` gate |
| 7 | IaC Security Agent | ✅ | `iac_security_scan` artifact |
| 8 | Intelligent Test Selection | ✅ | QAAgent + `test_intelligence` artifact |
| 9 | Flaky Test Detection | ✅ | Historical `qa_report` + flaky classification |
| 10 | Release Passport artifact | ✅ | `release_passport` pre-deploy |

### Phase 2 — Autonomous engineering (P1)

| # | Feature | Status | Key artifacts / modules |
|---|---------|--------|-------------------------|
| 11 | AI Software Engineer Agent | ✅ | `SoftwareEngineerAgent`, `fix_loop_service` |
| 12 | Autonomous Fix Loop + sandbox | ✅ | `AgentSandbox`, `fix_loop_report` |
| 13 | Patch Confidence Score | ✅ | `patch_confidence_report` (>90% auto PR) |
| 14 | AI Test Generation | ✅ | `test_generation_report` (heuristic) |
| 15 | Contract Testing Agent | ✅ | `contract_test_report` |
| 16 | Preview Environments | ✅ | `preview_environment` (simulated URL) |
| 17 | Canary Deployment | ✅ | `progressive_delivery` via canary stages |
| 18 | Progressive Delivery | ✅ | `PROGRESSIVE_DELIVERY_ENABLED`, health gates |
| 19 | Rollback Intelligence (enhanced) | ✅ | `rollback_intelligence` in monitoring |
| 20 | GitHub PR Intelligence comments | ✅ | `pr_intelligence` artifact + GitHub API |

### Phase 3 — SRE intelligence (P1)

| # | Feature | Status | Key artifacts / modules |
|---|---------|--------|-------------------------|
| 21 | Incident Commander | ✅ | `incident_commander_report`, `MonitoringAgent` hook |
| 22 | Evidence Graph | ✅ | `evidence_graph` |
| 23 | Automated RCA | ✅ | `rca_report` |
| 24 | Incident Timeline | ✅ | `incident_timeline` |
| 25 | Automated Postmortem | ✅ | `postmortem_report` |
| 26 | Runbook Automation | ✅ | `runbook_execution` |
| 27 | OpenTelemetry integration | ✅ | `otel_trace_context` (OTel-like JSON export) |
| 28 | Error Budget Engine | ✅ | `error_budget_report` + intelligence dashboard |
| 29 | Synthetic Monitoring | ✅ | `synthetic_monitoring_report` (simulated default) |
| 30 | Chaos Engineering Agent | ✅ | `chaos_report` (simulated suite) |

### Phase 4 — Enterprise (P2)

| # | Feature | Status | Key artifacts / modules |
|---|---------|--------|-------------------------|
| 31 | Policy-as-code engine | ✅ | `policy_evaluation`, `blocked_policy` gate |
| 32 | Compliance packs | ✅ | `compliance_report` (SOC2, ISO27001, OWASP, CIS) |
| 33 | Signed builds | ✅ | `signed_build_report` (simulated Cosign) |
| 34 | Multi-tenant RBAC | ✅ | `tenant_rbac_context` + `AUTH_API_KEYS_JSON` |
| 35 | FinOps Agent | ✅ | `cost_report` + dashboard `finops` rollup |
| 36 | Audit explorer | ✅ | `GET /intelligence/audit-explorer` |
| 37 | Fleet view | ✅ | `GET /intelligence/fleet` |
| 38 | Enterprise SSO | ✅ | `sso_readiness` + `SSO_SAML_*` / `SSO_OIDC_*` |

### Phase 5 — AI platform (P2)

| # | Feature | Status | Key artifacts / modules |
|---|---------|--------|-------------------------|
| 39 | Agent Registry | ✅ | `agent_registry_snapshot`, `GET /intelligence/agents` |
| 40 | Agent permission model | ✅ | `agent_permissions_report` |
| 41 | Agent sandbox policy | ✅ | `sandbox_policy_report` + `AgentSandbox` |
| 42 | Model Router | ✅ | `model_routing_plan`, `MODEL_ROUTER_ENABLED` |
| 43 | Prompt Registry | ✅ | `prompt_registry_snapshot` |
| 44 | AgentEval | ✅ | `agent_eval_report`, `AGENT_EVAL_MIN_SCORE` |
| 45 | AI Cost Optimizer | ✅ | `ai_cost_optimization` |
| 46 | Decision Ledger | ✅ | `decision_ledger` |
| 47 | Prompt Injection Firewall | ✅ | `prompt_injection_scan`, `blocked_injection`, BaseAgent sanitize |
| 48 | DevOps RAG | ✅ | `devops_rag_context`, `GET /intelligence/rag?q=` |

### Phases 6–29 — Extended control plane (ORION-primary) ✅

| Phase | Theme | Key surfaces |
|-------|-------|----------------|
| 6–11 | Test intel, performance, progressive deploy, AIOps, remediation | `test_intelligence`, `progressive_delivery`, incident bundle |
| 12–16 | Policy, compliance, cloud, catalog, operations center | `policy_evaluation`, Hub BFF `control-plane/*` |
| 17–22 | RAG, memory, mesh, governance, FinOps, release intel | `rag_intelligence`, `finops_intelligence`, `release_intelligence` |
| 23 | Advanced Command Hub | `hub/federation/operations_center.py`, `orion hub operations` |
| 24 | Enterprise IAM | `iam_intelligence`, `blocked_iam`, `orion iam` |
| 25 | Reliability / chaos | `reliability_intelligence`, `orion reliability` |
| 26 | Disaster recovery | `dr_intelligence`, `orion dr` |
| 27 | Knowledge graph | `knowledge_graph_intelligence`, `orion knowledge` |
| 28 | ORION Autopilot | `autopilot_intelligence`, `blocked_autopilot`, `orion autopilot` |
| 29 | **Unified Risk Engine** | `unified_risk_intelligence`, `blocked_unified_risk`, `orion unified-risk` |

**Final pre-deploy intelligence chain (ORION):** `developer_ux_intelligence` → `iam_intelligence` → `reliability_intelligence` → `dr_intelligence` → `knowledge_graph_intelligence` → `autopilot_intelligence` → **`unified_risk_intelligence`** → deploy.

### Developer UX: ORION CLI ✅

Installed from `ai-cicd-pipeline/scripts/orion_cli.py` (symlink `/usr/local/bin/orion` in production).  
Set `ORION_API_URL` (default `http://127.0.0.1:8001`) and `ORION_API_KEY` when `API_REQUIRE_AUTH=true`.

**Ops commands:** `status` · `restart` · `logs` · `health` · `db-migrate` · `workers` · `backup-db` · `production checklist` · `production ready`

**Developer / intelligence commands:**

```bash
# Full pipeline scan (optional wait for terminal status)
orion scan [repo_path] [--wait] [--timeout 900]

# QA-focused pipeline trigger
orion test [repo_path] [--wait]

# Local change-risk score from git diff (no API required)
orion risk HEAD [--repo-path .]

# DevOps RAG over artifacts / runbooks
orion explain incident INC-204 [--run-id <uuid>]
orion explain query why did QA fail

# Resume/retry latest blocked run (category alias or repo slug filter)
orion fix tests | orion fix test-payment

# Deploy with progressive canary when PROGRESSIVE_DELIVERY_ENABLED=true
orion deploy [repo_path] --canary

# Intelligence APIs
orion intelligence [--view dashboard|fleet|agents]

# Run inspection
orion runs list [--limit 20]
orion runs show <run_id>
orion runs artifact <run_id> change_risk_report

# Extended intelligence (Phases 23–29)
orion hub operations|fleet|intelligence
orion iam policy|status|analyze
orion reliability policy|chaos|analyze
orion dr policy|backup|analyze
orion knowledge graph|analyze
orion autopilot plan|analyze
orion unified-risk score|analyze --run-id <uuid>

# Production hardening (requires ORION_API_KEY when API_REQUIRE_AUTH=true)
orion production checklist
orion production ready
```

---

## 70. Top 15 features & killer workflow

### 70.1 Top 15 (maximum differentiation ranking)

| Rank | Feature | Value | Phase |
|------|---------|-------|-------|
| 1 | AI Change Risk Engine | ⭐⭐⭐⭐⭐ | P0 — ✅ `change_risk_report` |
| 2 | Blast Radius + Dependency Graph | ⭐⭐⭐⭐⭐ | P0 — ✅ service graph + path blast radius |
| 3 | Autonomous Fix → Test → PR loop | ⭐⭐⭐⭐⭐ | P1 — ✅ fix_loop + SoftwareEngineerAgent |
| 4 | Evidence Graph | ⭐⭐⭐⭐⭐ | P1 — ✅ `evidence_graph` |
| 5 | AI Incident Commander / RCA | ⭐⭐⭐⭐⭐ | P1 — ✅ incident commander bundle |
| 6 | Progressive Canary Deployment | ⭐⭐⭐⭐⭐ | P1 — ✅ `progressive_delivery` |
| 7 | SBOM + Supply Chain Security | ⭐⭐⭐⭐⭐ | P0 — ✅ SBOM + signed builds |
| 8 | Policy-as-Code | ⭐⭐⭐⭐⭐ | P2 — ✅ `policy_evaluation` |
| 9 | Intelligent Test Selection | ⭐⭐⭐⭐ | P0 — ✅ `test_intelligence` |
| 10 | Container + IaC Security | ⭐⭐⭐⭐ | P0 — ✅ container + IaC scans |
| 11 | Release Passport | ⭐⭐⭐⭐ | P0 — ✅ `release_passport` |
| 12 | Agent Sandbox + Permissions | ⭐⭐⭐⭐⭐ | P1/P5 — ✅ sandbox + permissions |
| 13 | AgentEval / AI Governance | ⭐⭐⭐⭐ | P5 — ✅ `agent_eval_report` |
| 14 | SLO / Error Budget Intelligence | ⭐⭐⭐⭐ | P1 — ✅ `error_budget_report` |
| 15 | DevOps RAG + Runbook Automation | ⭐⭐⭐⭐⭐ | P1 — ✅ runbook matching (heuristic) |

### 70.2 Killer end-to-end workflow (target demonstration)

```text
Developer push
    ↓
Webhook + delivery ledger (✅)
    ↓
Diff + repository intelligence (✅ metadata/diff + service graph)
    ↓
AI Change Risk + Blast Radius (✅ change_risk_report + path analysis)
    ↓
Parallel: SAST | SCA | SBOM | Secrets | IaC | AI review | Test intel (✅ FullScan + Phase 1)
    ↓
Risk fusion (✅ gate_fusion + change risk dimensions)
    ↓
AI tests / AI fix in sandbox (✅ test_generation + fix_loop + AgentSandbox)
    ↓
Auto-PR with patch confidence (✅ Auto-PR + patch_confidence + PR intelligence)
    ↓
Staging → Synthetic → Canary 5→25→50→100% (✅ progressive_delivery when enabled)
    ↓
Continuous monitoring + auto-rollback (✅ MonitoringAgent + rollback_intelligence)
    ↓
Incident → RCA → Evidence graph → Postmortem (✅ Phase 3 incident bundle on alerts)
    ↓
Unified risk fusion (✅ unified_risk_intelligence — change risk + gates + intelligence rollup)
```

CLI entry points for the demo: `orion scan --wait`, `orion risk HEAD`, `orion unified-risk analyze --run-id <uuid>`, `orion deploy --canary`, `orion explain incident INC-204`.

This workflow is **autonomous software delivery + security + reliability** — not CI/CD alone.

---

## 71. Anti-patterns — what NOT to add

Avoid feature bloat. **Do not** immediately add:

| Anti-pattern | Why |
|--------------|-----|
| 30+ independent LLM agents | Orchestration complexity without evidence |
| Generic chatbot UI | Duplicates IDE/Cursor; weak differentiation |
| Vector DB everywhere | Use RAG where evidence requires it only |
| Blockchain audit trails | Existing audit trail + artifacts sufficient |
| Autonomous production shell access | Violates agent sandbox principle |
| Overlapping dashboards | Extend Command Hub instead |
| Novel orchestration for its own sake | Event bus yes; rewrite for rewrite's sake no |
| AI decisions without deterministic gates | **Breaks ORION security philosophy** |

**Always preserve:** ApprovalAgent hard rules — code/security/QA/stress fail → reject before LLM override (§5).

---

*Document version: Binary-v2 master reference — Part I (implemented baseline) + Part II (Phases 0–29 shipped on ORION). Maintained in `agents.md` and `docs/audit/IMPLEMENTATION_BACKLOG.md`.*


