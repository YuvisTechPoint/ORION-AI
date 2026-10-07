# Binary-v2 / ORION — Implementation Backlog (Phase 0 → Roadmap)

**Source:** User roadmap Phases 0–29 mapped against Phase 0 audit (2026-10-06).  
**Principle:** Extend existing architecture; no monolith rewrite.

**Status key:** `Done` · `Partial` · `Next` · `Planned` · `Deferred`

---

## Phase 0 — Repository intelligence & baseline audit

| Item | Status | Deliverable |
|------|--------|-------------|
| Recursive repo inspection | **Done** | `docs/audit/ARCHITECTURE_AUDIT.md` |
| Feature matrix | **Done** | `docs/audit/FEATURE_MATRIX.md` |
| API contract matrix | **Done** | `docs/audit/API_CONTRACT_MATRIX.md` |
| Security gap report | **Done** | `docs/audit/SECURITY_GAP_REPORT.md` |
| Technical debt register | **Done** | `docs/audit/TECHNICAL_DEBT.md` |
| Test baseline | **Done** | 324 tests pass (O:242, C:54, P:28) |
| Static analysis CI | **Partial** | pytest only; no repo-wide ruff/bandit gate |
| Stack verification scripts | **Done** | `run_all_stacks.ps1`, `run_e2e_all.ps1` exist |
| Doc vs code reconciliation | **Done** | See FEATURE_MATRIX §O |

### Phase 0 hygiene (immediate, pre-Phase 1)

| ID | Task | Priority | Effort |
|----|------|----------|--------|
| H-001 | Fix ORION WS imports (`event_bus`, `channel_for`) | P0 | S | **Done** — imports wired in `app/main.py` |
| H-002 | Canonical multimodal git-logs + payment routes OR proxy to ORION | P0 | M | **Done** — `POST /api/v1/multimodal/git-logs`, `/payment` |
| H-003 | Add ORION WebSocket integration test | P0 | S | **Done** — `tests/test_websocket.py` |
| H-004 | Sync `agents.md` Part II 📋 markers with code reality | P1 | M | **Done** — §69 Phases 1–29 + status banner |
| H-005 | Unify stack catalog: hub reads `config/stacks.json` | P1 | S | **Done** — `scripts/sync_stack_catalog.ps1` + Hub BFF catalog |

---

## Phase 1 — Unified ORION Control Plane 🔴 Critical · **Done**

**Current state:** Command Hub runs FastAPI BFF (`hub/server.py`) on `:5180` with federated read/write APIs, SSE live updates, and UI explorer.

| Capability | Status | Work |
|------------|--------|------|
| Unified resource model (Org/Project/Repo/PipelineRun/…) | **Partial** | `UnifiedPipelineRun` + composite `stack:native_id` |
| Cross-stack pipeline search | **Done** | `GET /api/v1/control-plane/pipelines` |
| Global pipeline timeline | **Done** | `GET .../pipelines/{id}/timeline` |
| Unified artifact explorer | **Done** | `GET .../artifacts`, `.../artifacts/{type}` |
| Unified audit explorer | **Partial** | `GET /api/v1/control-plane/audit` |
| correlation_id / trace_id propagation | **Done** | Hub + ORION/canonical/platform middleware |
| Unified health matrix | **Done** | `GET /api/v1/control-plane/health` |
| Hub write ops (retry/resume/cancel) | **Done** | `POST .../pipelines/{id}/{action}` via stack adapters |
| SSE live pipeline updates | **Done** | `GET .../pipelines/{id}/events` |
| Hub UI pipeline explorer | **Done** | `control-plane.js` (detail, actions, EventSource) |
| Compatibility layer | **Done** | Stack APIs unchanged; adapters only |
| Tests | **Done** | `tests/hub/test_control_plane.py`, `test_correlation.py`, Playwright hub E2E |

**Acceptance:** One Hub screen inspects any stack run; correlation ID on all stacks; retry/resume/cancel proxied through hub BFF.

---

## Phase 2 — Repository & code intelligence 🔴 · **Done**

| Capability | Status | Work |
|------------|--------|------|
| Repository fingerprinting | **Done** | `analyze_repository()` + `repository_intelligence` artifact |
| Language/framework detection | **Done** | Manifest + dependency heuristics |
| Monorepo detection | **Done** | Workspace markers + multi-package scan |
| Dependency graph | **Partial** | Composed via `service_graph` + SBOM stats in report |
| Changed-impact analysis | **Done** | `change_impact` block when diff/files provided |
| CODEOWNERS / ownership | **Done** | Parse CODEOWNERS + unowned changed paths |
| API breaking-change detection | **Partial** | OpenAPI path removal hints from diff |
| License scanning | **Done** | LICENSE + manifest fields |
| SBOM | **Partial** | SBOM stats embedded; Syft integration backlog |
| On-demand API | **Done** | `POST /api/v1/intelligence/repository` |
| Pipeline integration | **Done** | `phase1_enrichment` persists artifact |
| CLI | **Done** | `orion repo [path] [ref]` |

---

## Phase 3 — Advanced AI code review ✅ · **Done**

| Level | Status | Module |
|-------|--------|--------|
| L0 Syntax | **Done** | `code_review_intelligence` from `code_analysis` syntax/AST issues |
| L1 Static | **Done** | pylint + static issue rollup |
| L2 Semantic | **Done** | LLM/heuristic `code_analysis` severity + summary |
| L3 Architecture | **Done** | service graph + `analyze_changed_paths()` blast radius |
| L4 Security | **Done** | advisory security scan layer (non-gating) |
| L5 Performance | **Done** | stress + `performance_intelligence` baseline |
| L6 Maintainability | **Done** | warnings, docstrings, change-size heuristics |
| L7 Production risk | **Done** | `change_risk_report` dimensions |

**Artifact:** `code_review_intelligence` · **API:** `POST /api/v1/intelligence/code-review` · **CLI:** `orion code-review` · **Pipeline:** after change-risk in orchestrator.

**Bug prediction:** heuristic `bug_prediction` block with probability, confidence, and factor list.

---

## Phase 4 — Full DevSecOps security fabric 🔴 · **In progress**

| Tool | Status | Work |
|------|--------|------|
| Bandit | **Done** | SecurityAgent |
| pip-audit | **Done** | OSV/PyPI advisories for `==` pins |
| Semgrep | **Done** | `run_semgrep()` in SecurityAgent when installed |
| Gitleaks | **Done** | `run_gitleaks()` replaces heuristic secrets scan when installed |
| Trivy | **Done** | `run_trivy_config()` replaces heuristic container scan when installed |
| Checkov | **Done** | `run_checkov()` replaces heuristic IaC scan when installed |
| ZAP DAST | **Missing** | Staging-only agent backlog |

**Rule preserved:** LLM advisory only; scanners authoritative; heuristic fallback when tools not on PATH.

**Config:** `SECURITY_*_ENABLED`, `GITLEAKS_PATH`, `TRIVY_PATH`, `CHECKOV_PATH`, `SEMGREP_PATH`.

---

## Phase 5 — Software supply chain center 🔴 · **In progress**

| Item | Status | Work |
|------|--------|------|
| SBOM | **Partial** | CycloneDX subset in phase1 |
| Supply chain report artifact | **Done** | `supply_chain_report` in phase1 enrichment |
| Lockfile verification | **Done** | Fingerprints + missing lock warnings |
| CVE mapping | **Partial** | CVE refs from `security_scan` |
| EPSS | **Missing** | Backlog |
| Syft SBOM | **Done** | `run_syft()` merges CycloneDX when installed (`SBOM_SYFT_ENABLED`) |
| Sign + attest pipeline | **Partial** | Mock signed builds in phase4 |

---

## Phase 6 — Intelligent test engineering 🔴 · **In progress**

| Item | Status | Work |
|------|--------|------|
| Test discovery/selection | **Done** | `select_relevant_tests()` + layout discovery |
| Flaky detection | **Done** | `analyze_flaky_tests()` from historical `qa_report` |
| Mutation testing | **Partial** | Heuristic mutation targets + tool recommendations |
| Coverage regression gate | **Done** | `analyze_coverage_regression()` + optional `TEST_COVERAGE_GATE_ENABLED` |
| Live coverage probe | **Partial** | `probe_pytest_coverage()` when pytest-cov installed |
| TestIntelligenceAgent | **Done** | `app/agents/test_intelligence_agent.py` |
| On-demand API | **Done** | `POST /api/v1/intelligence/tests` |
| CLI | **Done** | `orion test-intel [path] [ref]` |
| AI test generation | **Partial** | phase2 `test_generation_report` linked in report |
| Contract testing | **Partial** | phase2 `contract_test_report` linked when present |

**Config:** `TEST_COVERAGE_GATE_ENABLED`, `TEST_COVERAGE_MIN_PERCENT`, `TEST_COVERAGE_MAX_REGRESSION_PERCENT`, `TEST_FLAKY_GATE_ENABLED`.

---

## Phase 7 — Performance engineering 🟠 · **In progress**

| Item | Status | Work |
|------|--------|------|
| Locust stress | **Done** | `StressTestAgent` |
| Stress profiles (smoke/spike/soak) | **Done** | `STRESS_TEST_PROFILE`, `resolve_stress_profile()` |
| Baseline p95 comparison vs history | **Done** | `compare_to_baseline()` + `performance_intelligence` artifact |
| PerformanceIntelligenceAgent | **Done** | Post-stress enrichment + API |
| On-demand API | **Done** | `POST /api/v1/intelligence/performance` |
| CLI | **Done** | `orion perf` |
| Baseline regression gate | **Done** | Optional `PERFORMANCE_BASELINE_GATE_ENABLED` |

**Config:** `STRESS_TEST_PROFILE`, `PERFORMANCE_P95_REGRESSION_PERCENT`, `PERFORMANCE_P95_REGRESSION_MS`.

---

## Phase 8 — Deployment intelligence 🟠 · **Done**

| Item | Status | Work |
|------|--------|------|
| Docker deploy | **Done** | `DeploymentAgent` |
| Progressive canary | **Done** | `run_progressive_delivery()` + `progressive_delivery` artifact |
| Blue/green | **Done** | `run_blue_green_delivery()` via `DEPLOYMENT_STRATEGY=blue_green` |
| Environment registry | **Done** | `build_environment_registry()` in deployment intel report |
| SLO-driven rollback | **Done** | `evaluate_slo_rollback_signals()` + optional `DEPLOYMENT_SLO_GATE_ENABLED` |
| DeploymentIntelligenceAgent | **Done** | Post-deploy enrichment + on-demand API |
| On-demand API | **Done** | `POST /api/v1/intelligence/deployment` |
| CLI | **Done** | `orion deploy-intel [--run-id]` |
| Pipeline artifact | **Done** | `deployment_intelligence` after phase3 observability |

**Config:** `DEPLOYMENT_STRATEGY` (`canary` \| `blue_green` \| `direct`), `DEPLOYMENT_SLO_GATE_ENABLED`, `PROGRESSIVE_DELIVERY_ENABLED`, `CANARY_STAGES`.

---

## Phase 9 — Production observability / AIOps 🟠 · **Done**

| Item | Status | Work |
|------|--------|------|
| Metrics | **Done** | Synthetic + stress signals in `observability_intelligence` |
| Logs | **Done** | `analyze_log_signals()` from monitoring assessment / excerpt |
| Traces | **Done** | OTEL context linked in `correlate_deploy_window()` |
| Service map | **Done** | `build_runtime_service_map()` overlay on `service_graph` |
| Anomaly detection | **Done** | `detect_metric_anomalies()` vs historical synthetic/stress |
| Deploy correlation | **Done** | Timeline + blast radius + trace linkage |
| ObservabilityIntelligenceAgent | **Done** | Post-deploy enrichment + on-demand API |
| On-demand API | **Done** | `POST /api/v1/intelligence/observability` |
| CLI | **Done** | `orion observability` (`aiops`, `obs`) |
| Pipeline artifact | **Done** | `observability_intelligence` after deployment intel |

**Config:** `OBSERVABILITY_ANOMALY_GATE_ENABLED`, `SYNTHETIC_MONITORING_LIVE`, `OBSERVABILITY_INTELLIGENCE_MODEL`.

---

## Phase 10 — AI Incident Command Center 🟠 · **Done**

| Item | Status | Work |
|------|--------|------|
| Incident lifecycle UI | **Done** | ORION console modal `#incidents` + `/api/v1/incidents` |
| Incident commander bundle | **Done** | `run_incident_commander()` + `incident_intelligence` artifact |
| RCA / timeline / postmortem | **Done** | Existing utils + unified intelligence report |
| Slack P0 notifications | **Done** | `send_incident_p0_alert()` on P1 via `INCIDENT_P0_SLACK_ENABLED` |
| Lifecycle transitions | **Done** | `POST /incidents/{id}/transition` + `orion incident transition` |
| On-demand trigger | **Done** | `POST /incidents/trigger` + `orion incident trigger --run-id` |

**Config:** `INCIDENT_P0_SLACK_ENABLED`, `INCIDENT_INTELLIGENCE_MODEL`, `SLACK_WEBHOOK_URL`.

---

## Phase 11 — Autonomous remediation 🟠 · **Done**

| Level | Status | Work |
|-------|--------|------|
| L0 Explain | **Done** | `explain` block from `build_run_diagnostics()` |
| L1 Recommend | **Done** | remediation steps + runbook links |
| L2 Patch proposal | **Done** | Auto-PR patch generation artifacts |
| L3 Patch + verify | **Done** | `fix_loop_report` + `patch_confidence_report` |
| L4 Auto-PR | **Done** | `AutoPRService` + `auto_pr_registry` |
| L5 Auto test/retry | **Deferred** | `REMEDIATION_L5_AUTO_RETRY_ENABLED` (default off) |
| L6 Auto deploy | **Deferred** | `REMEDIATION_L6_AUTO_DEPLOY_ENABLED` (default off) |
| RemediationIntelligenceAgent | **Done** | `remediation_intelligence` artifact on block/fix |
| API | **Done** | `GET /remediation/levels`, `POST /remediation/analyze` |
| CLI | **Done** | `orion remediate levels|analyze|show` |

**Config:** `REMEDIATION_AUTONOMY_MAX_LEVEL` (default `L4`), `REMEDIATION_L5_AUTO_RETRY_ENABLED`, `REMEDIATION_L6_AUTO_DEPLOY_ENABLED`.

---

## Phase 12 — Policy-as-code 🟠 · **Done**

| Item | Status | Work |
|------|--------|------|
| Policy engine | **Done** | `evaluate_policies()` + scoped merge |
| Org/repo/env policies | **Done** | `POLICY_*_RULES_JSON` + `resolve_effective_policies()` |
| AI autonomy policies | **Done** | `evaluate_ai_autonomy_policies()` caps L4–L6 + auto-PR |
| Policy intelligence artifact | **Done** | `policy_intelligence` at approval gate |
| API | **Done** | `GET /policies/catalog`, `/effective`, `POST /evaluate` |
| CLI | **Done** | `orion policy catalog|effective|evaluate` |

**Config:** `POLICY_ORG_RULES_JSON`, `POLICY_REPO_RULES_JSON`, `POLICY_ENV_RULES_JSON`, `POLICY_AI_AUTONOMY_MAX_LEVEL`, `POLICY_AI_AUTONOMY_ENFORCEMENT_ENABLED`.

---

## Phase 13 — Enterprise approvals 🟠 · **Done**

| Item | Status | Work |
|------|--------|------|
| Multi-person approval | **Done** | `enterprise_approval` artifact + workflow JSON |
| Four-eyes / signed approvals | **Done** | `APPROVAL_FOUR_EYES_ENABLED`, HMAC `APPROVAL_SIGNATURE_SECRET` |
| ApprovalAgent | **Done** | single-stage automated gate (unchanged) |
| Enterprise pause/resume | **Done** | `awaiting_approval` + `POST /approvals/runs/{id}/sign` auto-resume |
| On-demand API | **Done** | `GET /api/v1/approvals/workflow`, `.../runs/{id}`, `POST .../sign` |
| CLI | **Done** | `orion approve workflow|status|sign` |

**Config:** `APPROVAL_REQUIRED_COUNT`, `APPROVAL_FOUR_EYES_ENABLED`, `APPROVAL_SIGNED_REQUIRED`, `APPROVAL_*_WORKFLOW_JSON`, `ENTERPRISE_APPROVAL_ENFORCEMENT_ENABLED`, `ENTERPRISE_APPROVAL_SIMULATED`.

---

## Phase 14 — Multimodal expansion 🟡 · **Done**

| Item | Status | Work |
|------|--------|------|
| Agent catalog (8 agents) | **Done** | `multimodal_registry.py` + `GET /multimodal/catalog` |
| Input router | **Done** | `multimodal_router.py` + `POST /multimodal/route` |
| CiBuildLogAgent | **Done** | Jenkins/GitLab/CircleCI log analysis |
| MetricsSnapshotAgent | **Done** | Prometheus/Grafana export review |
| Unified intelligence | **Done** | `multimodal_intelligence` artifact + pipeline hook |
| On-demand API | **Done** | `POST /api/v1/intelligence/multimodal` |
| CLI | **Done** | `orion multimodal catalog|route|intel` |

**New artifact types:** `ci_build_log_analysis`, `metrics_snapshot_analysis`, `multimodal_intelligence`.

---

## Phase 15 — Kubernetes / cloud 🟡 · **Done**

| Item | Status | Work |
|------|--------|------|
| Kubernetes manifest scan | **Done** | `kubernetes_manifest.py` + phase1 `kubernetes_manifest_scan` |
| KubernetesManifestAgent | **Done** | multimodal `kubernetes`/`k8s` alias |
| Multi-cloud target registry | **Done** | `cloud_target_registry.py` (docker, k8s, AWS, Azure, GCP) |
| Cloud intelligence | **Done** | `cloud_intelligence` artifact + pre-deploy optional gate |
| On-demand API | **Done** | `GET /intelligence/cloud/targets`, `POST /intelligence/cloud` |
| CLI | **Done** | `orion cloud targets|analyze` |

**Config:** `KUBERNETES_MANIFEST_SCAN_ENABLED`, `CLOUD_DEPLOY_TARGET`, `CLOUD_TARGET_JSON`, `CLOUD_INTELLIGENCE_GATE_ENABLED`.

---

## Phase 16 — Service catalog / IDP 🟡 · **Done**

| Deliverable | Path / API |
|-------------|------------|
| Service catalog builder | `app/utils/service_catalog.py` |
| Catalog registry + IDP golden paths | `app/utils/service_catalog_registry.py` |
| Catalog intelligence + fleet overlay | `app/utils/service_catalog_intelligence.py` |
| Enrichment persistence | `app/services/catalog_enrichment.py` |
| Phase 1 scan | `SERVICE_CATALOG_SCAN_ENABLED` → `service_catalog` artifact |
| Orchestrator | optional `blocked_catalog` gate; post-deploy `service_catalog_intelligence` |
| API | `GET /intelligence/catalog/idp`, `GET /intelligence/catalog/services`, `POST /intelligence/catalog` |
| CLI | `orion catalog idp|services|fleet|analyze` |
| Config | `SERVICE_CATALOG_JSON`, `IDP_GOLDEN_PATHS_JSON`, `SERVICE_CATALOG_GATE_ENABLED`, `SERVICE_CATALOG_MIN_COMPLETENESS_PERCENT` |
| Tests | `tests/test_service_catalog_intelligence.py` |

---

## Phase 17 — RAG + memory 🟡 · **Done**

| Deliverable | Path / API |
|-------------|------------|
| Agent memory store (SQLite / in-memory) | `app/services/memory_store.py` |
| Hybrid file retriever | `app/services/hybrid_retriever.py` |
| Enhanced DevOps RAG (hybrid scoring + file + memory) | `app/utils/devops_rag.py` |
| RAG intelligence report | `app/utils/rag_intelligence.py` |
| Enrichment persistence | `app/services/rag_enrichment.py` |
| BaseAgent memory inject + record | `app/agents/base_agent.py` |
| Orchestrator | index repo at ingest; memory/retriever on `db.info` |
| API | `GET/POST /intelligence/rag`, `GET /intelligence/memory` |
| CLI | `orion rag query|analyze`, `orion memory list|context` |
| Config | `AGENT_MEMORY_*`, `RETRIEVER_BACKEND`, `RAG_INDEX_*` |
| Tests | `tests/test_rag_intelligence.py` |

**Artifacts:** `rag_intelligence`, `agent_memory_snapshot` (plus existing `devops_rag_context`).

---

## Phase 18 — Agent mesh 🟡 · **Done**

| Deliverable | Path / API |
|-------------|------------|
| Mesh topology (stages, events, edges) | `app/utils/agent_mesh_topology.py` |
| O2-style agent descriptors | `app/utils/agent_mesh_registry.py` |
| Intent + event router | `app/utils/agent_mesh_router.py` |
| Mesh coverage intelligence | `app/utils/agent_mesh_intelligence.py` |
| Enrichment persistence | `app/services/mesh_enrichment.py` |
| Phase 5 | `agent_mesh_snapshot`, `agent_mesh_intelligence` artifacts |
| Orchestrator | optional `blocked_mesh` gate via `AGENT_MESH_GATE_ENABLED` |
| API | `GET /mesh/topology`, `GET /mesh/agents`, `POST /mesh/route`, `POST /mesh`, `GET /agents?mesh=true` |
| CLI | `orion mesh agents|topology|route|analyze` |
| Config | `AGENT_MESH_OVERRIDES_JSON`, `AGENT_MESH_GATE_ENABLED`, `AGENT_MESH_MIN_COVERAGE_PERCENT` |
| Tests | `tests/test_agent_mesh_intelligence.py` |

---

## Phase 19 — AI governance 🟡 · **Done**

| Deliverable | Path / API |
|-------------|------------|
| Governance policy catalog | `app/utils/ai_governance_registry.py` |
| Unified governance intelligence | `app/utils/ai_governance_intelligence.py` |
| Enrichment persistence | `app/services/governance_enrichment.py` |
| Phase 5 rollup | `ai_governance_intelligence` artifact (eval + router + ledger + cost + escalations) |
| Orchestrator | optional `blocked_governance` gate via `AI_GOVERNANCE_GATE_ENABLED` |
| API | `GET /governance/policy`, `GET /governance/escalations`, `POST /governance` |
| CLI | `orion governance policy|escalations|analyze` |
| Config | `AI_GOVERNANCE_*`, `AI_GOVERNANCE_POLICY_JSON` |
| Tests | `tests/test_ai_governance_intelligence.py` |

---

## Phase 20 — FinOps ✅ Done

| Item | Path / surface |
|------|----------------|
| Budget registry | `app/utils/finops_registry.py` |
| Cost compute (enhanced) | `app/utils/finops.py` |
| Intelligence rollup | `app/utils/finops_intelligence.py` |
| Enrichment persistence | `app/services/finops_enrichment.py` |
| Phase 5 rollup | `finops_intelligence` artifact (cost + tokens + fleet + optimization) |
| Orchestrator | optional `blocked_finops` gate via `FINOPS_GATE_ENABLED` (after mesh) |
| API | `GET /finops/budgets`, `GET /finops`, `POST /finops` |
| CLI | `orion finops budgets|cost|fleet|analyze` |
| Config | `FINOPS_BUDGET_*`, `FINOPS_GATE_ENABLED`, `FINOPS_BUDGET_JSON` |
| Tests | `tests/test_finops_intelligence.py` |

---

## Phase 21 — Release intelligence ✅ Done

| Item | Path / surface |
|------|----------------|
| Policy registry | `app/utils/release_intelligence_registry.py` |
| DORA + prediction + promotion | `app/utils/release_intelligence.py` |
| Enrichment persistence | `app/services/release_enrichment.py` |
| Pre-deploy rollup | `release_intelligence` artifact (passport + DORA + prediction + promotion) |
| Orchestrator | after `release_passport`; optional `blocked_release` via `RELEASE_INTELLIGENCE_GATE_ENABLED` |
| API | `GET /release/policy`, `GET /release/dora`, `GET /release`, `POST /release` |
| CLI | `orion release policy|dora|passport|analyze` |
| Config | `RELEASE_*`, `RELEASE_POLICY_JSON` |
| Tests | `tests/test_release_intelligence.py` |

---

## Phase 22 — Developer UX ✅ Done

| Item | Path / surface |
|------|----------------|
| UX registry | `app/utils/developer_ux_registry.py` |
| GitHub App registry + service | `app/utils/github_app_registry.py`, `app/services/github_app_service.py` |
| Intelligence rollup | `app/utils/developer_ux_intelligence.py` |
| Enrichment | `app/services/developer_ux_enrichment.py` → `developer_ux_intelligence` artifact |
| VS Code extension | `developer/vscode-orion/` (status bar, runs, trigger, dashboard) |
| GitHub App manifest | `developer/github-app/app.manifest.json` |
| Webhook | `POST /webhook/github/app` (installation, PR, checks) |
| API | `GET /developer/catalog|vscode|github-app|status`, `POST /developer/analyze` |
| CLI | `orion dev status|catalog|vscode|github-app|analyze` |
| Config | `GITHUB_APP_*` |
| Tests | `tests/test_developer_ux.py` |

---

## Phase 23 — Advanced Command Hub ✅ Done

| Item | Path / surface |
|------|----------------|
| Intelligence fan-out | `hub/federation/intelligence_fanout.py` |
| Operations center rollup | `hub/federation/operations_center.py` |
| Models | `StackIntelligenceSnapshot`, `OperationsCenterReport` |
| API | `GET /control-plane/operations`, `/intelligence`, `/fleet` |
| Hub UI | `operations-center.js` — KPIs, service grid, blockers, alerts |
| CLI | `orion hub operations|fleet|intelligence|health|pipelines` |
| Tests | `tests/hub/test_operations_center.py` |

---

## Phase 24 — Enterprise IAM ✅ Done

| Item | Path / surface |
|------|----------------|
| IAM policy registry | `app/utils/iam_registry.py` |
| SSO + RBAC + session hygiene | `app/utils/iam_intelligence.py` (extends `enterprise_sso.py`) |
| Enrichment persistence | `app/services/iam_enrichment.py` → `iam_intelligence` artifact |
| Orchestrator | after `developer_ux_intelligence`; optional `blocked_iam` via `IAM_GATE_ENABLED` |
| API | `GET /iam/policy`, `/iam/sso`, `/iam/status`, `POST /iam/analyze` |
| CLI | `orion iam policy|sso|status|analyze` |
| Config | `IAM_*`, `SSO_SAML_METADATA_URL`, `SSO_OIDC_CLIENT_ID` |
| Tests | `tests/test_iam_intelligence.py` |

---

## Phase 25 — Reliability / chaos ✅ Done

| Item | Path / surface |
|------|----------------|
| Experiment catalog + policy | `app/utils/reliability_registry.py` |
| Enhanced chaos suite | `app/utils/chaos_engineering.py` (5 experiments, resilience scores) |
| Intelligence rollup | `app/utils/reliability_intelligence.py` (chaos + synthetic + error budget) |
| Enrichment | `app/services/reliability_enrichment.py` → `reliability_intelligence` artifact |
| Orchestrator | after `iam_intelligence`; optional `blocked_reliability` via `RELIABILITY_GATE_ENABLED` |
| Phase 3 post-deploy | `phase3_enrichment.py` uses policy-driven chaos suite |
| API | `GET /reliability/policy|experiments|chaos|status`, `POST /reliability/analyze`, `POST /reliability/chaos/{name}` |
| CLI | `orion reliability policy|experiments|chaos|status|analyze` (alias `chaos`) |
| Config | `CHAOS_*`, `RELIABILITY_*` |
| Tests | `tests/test_reliability_intelligence.py` |

---

## Phase 26 — Disaster recovery ✅ Done

| Item | Path / surface |
|------|----------------|
| DR policy registry | `app/utils/dr_registry.py` (RTO/RPO, retention, backup dir) |
| Backup service | `app/utils/dr_backup.py` (PostgreSQL pg_dump + SQLite file copy) |
| DR intelligence | `app/utils/dr_intelligence.py` (freshness, restore drill, gates) |
| Enrichment | `app/services/dr_enrichment.py` → `dr_intelligence` artifact |
| Orchestrator | after `reliability_intelligence`; optional `blocked_dr` via `DR_GATE_ENABLED` |
| API | `GET /dr/policy|backups|status`, `POST /dr/backup`, `POST /dr/analyze` |
| CLI | `orion dr policy|backups|backup|status|analyze` + `orion backup-db` (alias) |
| Config | `DR_*` |
| Tests | `tests/test_dr_intelligence.py` |

---

## Phase 27 — Knowledge graph ✅ Done

| Item | Path / surface |
|------|----------------|
| Graph policy registry | `app/utils/knowledge_graph_registry.py` |
| Unified graph builder | `app/utils/knowledge_graph.py` (service + repo + SBOM + artifacts + evidence) |
| Intelligence + queries | `app/utils/knowledge_graph_intelligence.py` |
| Enrichment | `app/services/knowledge_graph_enrichment.py` → `knowledge_graph_intelligence` artifact |
| Orchestrator | after `dr_intelligence`; optional `blocked_knowledge` via `KNOWLEDGE_GRAPH_GATE_ENABLED` |
| DevOps RAG | `knowledge_graph_intelligence` added to citable artifacts |
| API | `GET /knowledge/policy|graph|status`, `POST /knowledge/analyze` |
| CLI | `orion knowledge policy|graph|status|analyze` (aliases `graph`, `kg`) |
| Config | `KNOWLEDGE_GRAPH_*` |
| Tests | `tests/test_knowledge_graph_intelligence.py` |

---

## Phase 28 — ORION Autopilot ✅ Done

| Item | Path / surface |
|------|----------------|
| Action catalog + policy | `app/utils/autopilot_registry.py` |
| Policy-gated planner | `app/utils/autopilot_planner.py` (L0–L6 actions, simulate-only default) |
| Intelligence rollup | `app/utils/autopilot_intelligence.py` (+ AI autonomy policy fusion) |
| Enrichment | `app/services/autopilot_enrichment.py` → `autopilot_intelligence` artifact |
| Orchestrator | after `knowledge_graph_intelligence`; optional `blocked_autopilot` via `AUTOPILOT_GATE_ENABLED` |
| API | `GET /autopilot/policy|catalog|plan|status`, `POST /autopilot/analyze` |
| CLI | `orion autopilot policy|catalog|plan|status|analyze` (alias `ap`) |
| Config | `AUTOPILOT_*` (simulate-only default `true`) |
| Tests | `tests/test_autopilot_intelligence.py` |

---

## Phase 29 — Unified Risk Engine ✅ Done

| Item | Path / surface |
|------|----------------|
| Policy registry + dimension weights | `app/utils/unified_risk_registry.py` |
| Fusion engine | `app/utils/unified_risk_engine.py` (change risk + gate fusion + release prediction + intelligence gates) |
| Intelligence rollup | `app/utils/unified_risk_intelligence.py` |
| Enrichment | `app/services/unified_risk_enrichment.py` → `unified_risk_intelligence` artifact |
| Orchestrator | after `autopilot_intelligence`; optional `blocked_unified_risk` via `UNIFIED_RISK_GATE_ENABLED` |
| DevOps RAG | `unified_risk_intelligence` added to citable artifacts |
| API | `GET /unified-risk/policy|score|status`, `POST /unified-risk/analyze` |
| CLI | `orion unified-risk policy|score|status|analyze` (aliases `urisk`, `ur`) |
| Config | `UNIFIED_RISK_*` |
| Tests | `tests/test_unified_risk_intelligence.py` |

---

## Phase 30 — Production hardening & deployment ✅ Done

| Item | Path / surface |
|------|----------------|
| Production hardening checklist | `app/utils/production_hardening.py` |
| Production APIs | `GET /api/v1/production/checklist`, `GET /api/v1/production/ready` |
| ORION `validate_startup()` | Postgres + API keys + secrets (with `PRODUCTION_LOCAL_SIM` escape hatch) |
| DevOps / canonical startup validation | `devops-platform/backend/app/config.py`, `backend/core/config.py` |
| Secret generator | `scripts/generate_production_env.py` (`--local-sim` for no Docker) |
| Cross-stack preflight | `scripts/production_preflight.py`, `scripts/run_preflight_check.ps1` |
| Production launcher | `run_production.ps1` (`-GenerateSecrets`, `-LocalSim`) |
| Docker infra | `docker-compose.prod.yml`, `docker/postgres-init/01-databases.sql` |
| Env templates | `*.env.production.example` (ORION, canonical, DevOps) |
| TLS helper | `scripts/generate_local_tls.ps1` |
| Runbook | `docs/PRODUCTION_RUNBOOK.md` |
| CLI | `orion production checklist`, `orion production ready` |
| Tests | `tests/test_production_hardening.py` |
| Docs | `agents.md` §10.5, §11.6, §45.7, §47.7; `docs/AGENTS_QUICKREF.md` |
| DevOps UI port fallback | `run_all_stacks.ps1` — `3000` → `3001`/`3002` when port busy |

---

## Recommended sprint sequence (your priority alignment)

```
Done:    Phase 0 audit + hygiene H-001..H-005
Done:    Phases 1–30 (Unified Control Plane → Production hardening)
Next:    Real cloud deploy (Docker Postgres, TLS edge, real GitHub/Slack secrets)
Verify:  .\run_production.ps1 -SkipInstall  |  .\run_e2e_all.ps1 -Offline
```

---

## Mapping: prior ORION §69 phases → new roadmap

| Prior ORION work (agents.md §69) | New roadmap |
|----------------------------------|-------------|
| P0 change risk, SBOM, secrets, test intel | Phases 2, 5, 6 (partial — harden with real tools) |
| P1 fix loop, canary, incident bundle | Phases 8, 10, 11 |
| P2 policy, compliance, FinOps | Phases 12, 20, 24 |
| P3 observability, error budget | Phase 9 |
| P4 enterprise SSO, fleet | Phases 16, 24 |
| P5 agent registry, RAG, eval | Phases 17, 18, 19 |
| ORION developer CLI | Phase 22 (partial ✅) |

**Interpretation:** Prior phases delivered **ORION-primary scaffolding** (artifacts + heuristics + gates). New roadmap Phases 1–29 add ** federation, real tooling, and enterprise surfaces** without discarding scaffolding.

---

## Definition of done (per engineering contract)

Each backlog item closes only when: persistence (if needed), validation, auth, tests, docs, and UI/API integration match the feature class — not when a mock endpoint exists.

---

*Update this file at the end of each roadmap phase. Baseline audit: 2026-10-06.*
