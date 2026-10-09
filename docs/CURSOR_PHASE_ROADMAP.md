# Binary-v2 / ORION — Cursor Phase Implementation Roadmap

**Purpose:** Phase-wise prompts and acceptance criteria for evolving Binary-v2 into a production-grade **AI DevSecOps Control Plane** without replacing the three-stack topology.

**Authoritative status:** [`docs/audit/IMPLEMENTATION_BACKLOG.md`](audit/IMPLEMENTATION_BACKLOG.md) (Phases **0–30** tracked in code)  
**Architecture reference:** [`agents.md`](../agents.md) · [`docs/AGENTS_QUICKREF.md`](AGENTS_QUICKREF.md)  
**Strategic report:** [`docs/ORION_Advanced_Feature_Expansion_Report.md`](ORION_Advanced_Feature_Expansion_Report.md)  
**Verify:** `.\run_e2e_all.ps1 -Offline` · **Production:** `.\run_production.ps1`

---

## Recommended product direction

**Binary-v2 / ORION → Autonomous AI DevSecOps Control Plane**

End-to-end loop:

> **Repository → Intelligence → Code/Security/QA → Supply Chain → Performance → Approval → Deployment → Verification → Monitoring → Incident Response → Remediation → Audit → Learning**

**Preserve:** gate fusion, artifacts as source of truth, webhook idempotency, heuristic fallback, RBAC, audit trails, resume/retry/cancel, three stacks (Hub, Canonical, ORION, DevOps).

**Do not:** build a fourth monolith; duplicate shared capabilities; present heuristic/simulated artifacts as external-tool production integrations without labeling them.

---

## GLOBAL ORION ENGINEERING CONTRACT

> **Paste this block at the top of every Cursor phase prompt.**

```text
GLOBAL ORION ENGINEERING CONTRACT

You are extending an existing production-oriented multi-stack platform.

DO NOT:
- rewrite the repository from scratch
- replace working architecture unnecessarily
- create duplicate implementations
- create mock features presented as production features
- create UI-only features without backend support
- bypass existing security gates
- allow LLM output to downgrade authoritative security scanner results
- remove existing APIs
- silently change API contracts
- bypass audit logging
- store secrets in source code
- hard-code credentials
- disable existing tests to make the build pass
- replace real integrations with fake responses
- introduce a second implementation of an existing shared capability without architectural justification

ALWAYS:
1. Inspect the existing implementation before modifying it.
2. Reuse existing agents, services, utilities and models where appropriate.
3. Preserve backward compatibility.
4. Add database migrations for persistent schema changes.
5. Add API tests for every new API.
6. Add agent tests for every new agent.
7. Add frontend tests for critical workflows.
8. Add E2E coverage for operator workflows.
9. Add structured artifacts for every autonomous decision.
10. Add audit events for security-sensitive/operator actions.
11. Propagate correlation_id and trace_id.
12. Apply RBAC/policy checks to privileged operations.
13. Fail closed for security-critical decisions.
14. Provide deterministic fallback behavior where LLM availability is optional.
15. Validate every LLM response against a strict schema.
16. Never trust natural-language model output as the sole source of truth for a security gate.
17. Update documentation after implementation.
18. Update the feature matrix.
19. Run existing tests before and after the change.
20. Report exactly what was implemented, what remains, and which tests passed.

IMPLEMENTATION STYLE:
production-quality code, typed interfaces, structured logging, explicit error handling,
idempotent operations, retry/backoff where appropriate, database transactions where required,
concurrency safety, secure defaults, observable operations, incremental migrations,
no unnecessary dependencies.

DEFINITION OF DONE:
A feature is complete only when persistence, validation, authorization, observability,
frontend integration (if applicable), tests, documentation, and failure handling
are implemented to the degree appropriate for that feature—not when an endpoint or mock exists alone.
```

---

## Phase status matrix (0–29)

| Phase | Priority | Main outcome | Repo status | Detail |
|------:|:--------:|--------------|-------------|--------|
| 0 | 🔴 | Repository audit | **Done** | [`IMPLEMENTATION_BACKLOG`](audit/IMPLEMENTATION_BACKLOG.md#phase-0--repository-intelligence--baseline-audit) · audit docs in `docs/audit/` |
| 1 | 🔴 | Unified control plane | **Done** (partial org model) | Hub BFF `hub/server.py`, `control-plane.js`, federation adapters |
| 2 | 🔴 | Repository intelligence | **Done** | `repository_intelligence`, `orion repo` |
| 3 | 🔴 | Advanced code review | **Done** | L0–L7 `code_review_intelligence` |
| 4 | 🔴 | DevSecOps fabric | **Partial** | bandit/pip-audit/Semgrep hooks; deepen Trivy/Gitleaks/ZAP |
| 5 | 🔴 | Supply chain | **Partial** | SBOM, `supply_chain_report`; Sigstore/reachable SCA backlog |
| 6 | 🔴 | Test intelligence | **Done** | `test_intelligence`, flaky, contract tests |
| 7 | 🟠 | Performance engineering | **Partial** | Locust + `performance_intelligence`, baselines |
| 8 | 🟠 | Progressive delivery | **Done** | `progressive_delivery`, canary stages |
| 9 | 🟠 | AIOps / observability | **Partial** | OTEL hooks, `observability_intelligence` |
| 10 | 🟠 | Incident center | **Done** | Incident bundle artifacts + triage multimodal |
| 11 | 🟠 | Autonomous remediation | **Done** | fix loop, sandbox, Auto-PR, patch confidence |
| 12 | 🟠 | Policy engine | **Partial** | heuristic + hybrid **OPA** |
| 13 | 🟠 | Enterprise approvals | **Done** | `enterprise_approval` |
| 14 | 🟡 | Multimodal expansion | **Partial** | 6 core agents; K8s/Terraform agents backlog |
| 15 | 🟡 | Kubernetes / cloud | **Partial** | `kubernetes_manifest_scan`, `cloud_intelligence` |
| 16 | 🟡 | Service catalog / IDP | **Done** | `service_catalog`, Hub fleet |
| 17 | 🟡 | RAG + memory | **Partial** | canonical retriever; ORION **Memory Gateway** Wave 1; pgvector 📋 |
| 18 | 🟡 | Agent mesh | **Done** | `agent_mesh_intelligence`, registry |
| 19 | 🟡 | AI governance | **Done** | eval, injection gate, decision ledger |
| 20 | 🟡 | FinOps | **Partial** | `cost_report`, `finops_intelligence` |
| 21 | 🟡 | Release intelligence | **Done** | `release_intelligence`, passport |
| 22 | 🟡 | Developer UX | **Done** | `orion` CLI, VS Code extension, GitHub App hooks |
| 23 | 🟢 | Advanced Command Hub | **Done** | Operations Center, platform events panel |
| 24 | 🟢 | Enterprise IAM | **Partial** | `iam_intelligence`, SSO readiness |
| 25 | 🟢 | Reliability / chaos | **Partial** | `reliability_intelligence`, `chaos_report` simulated |
| 26 | 🟢 | Disaster recovery | **Partial** | `dr_intelligence` |
| 27 | 🟢 | Knowledge graph | **Done** | `knowledge_graph_intelligence` |
| 28 | 🟢 | ORION Autopilot | **Done** | `autopilot_intelligence`, policy-gated |
| 29 | 🟢 | Unified risk engine | **Done** | `unified_risk_intelligence` |
| — | — | Production hardening | **Done** | Phase **30** in backlog |

**Interpretation:** ORION-primary **scaffolding is shipped** (artifacts + gates + Hub). **Next engineering** = replace heuristics with real external tools, cross-stack parity, and Wave 4 memory (pgvector).

---

## Recommended implementation order (for new Cursor sessions)

Do **not** paste all 29 phases in one prompt. Use one phase per session + engineering contract.

```
Current baseline (Phases 0–30 scaffolding)
    → Harden Phase 4–5 (real Semgrep/Trivy/Gitleaks, reachable SCA, attestations)
    → Harden Phase 9 (OTEL export production path)
    → Wave 4 Phase 17 (pgvector + semantic memory)
    → Phase 1 gaps (full Org/Project registry persistence if required)
    → Real cloud deploy (Postgres, TLS, secrets rotation)
```

Strongest portfolio narrative:

**Unified Control Plane → Repo Intel → DevSecOps/Supply Chain → Test/Perf → Progressive Deploy → AIOps → Incidents → Remediation → Policy → RAG/Mesh → Autopilot**

---

## Appendix A — Phase 0 Cursor prompt (baseline audit)

Use when re-auditing after major refactors or fork.

```text
[Paste GLOBAL ORION ENGINEERING CONTRACT above]

You are working on the Binary-v2 / ORION multi-stack DevOps platform.

Before implementing any new feature, perform a complete repository audit.

Repository topology:
- hub/, backend/, frontend/, ai-cicd-pipeline/, devops-platform/, e2e/, observability/, scripts/

Stacks:
- Command Hub :5180
- Canonical :8000 / :5173
- ORION CI/CD :8001
- DevOps Platform :8002 / :3000+

TASK:
1. Recursively inspect the repository.
2. Build architecture inventory (APIs, routers, services, agents, orchestrators, models, DB, migrations, UI, WS, workers, integrations, env, tests, scripts).
3. Identify implemented / partial / mock / duplicated / dead code / contract drift / security / tests gaps.
4. Do NOT rewrite working architecture for style only.
5. Preserve existing endpoints unless compatibility layer is required.
6. Generate or update: ARCHITECTURE_AUDIT.md, FEATURE_MATRIX.md, API_CONTRACT_MATRIX.md, SECURITY_GAP_REPORT.md, TECHNICAL_DEBT.md, IMPLEMENTATION_BACKLOG.md under docs/audit/.
7. Run full test suite; record baseline.
8. Verify run_all_stacks.ps1 and run_e2e_all.ps1 -Offline.

Do NOT implement the future roadmap in this session—establish an accurate baseline only.
Compare documentation to code; do not claim features that are not implemented.
```

---

## Appendix B — Phase 1 Cursor prompt (unified control plane)

Use for **remaining Phase 1 gaps** (e.g. persistent org/project registry, unified agent activity feed)—not to rebuild shipped Hub BFF.

```text
[Paste GLOBAL ORION ENGINEERING CONTRACT above]

Implement unified ORION Control Plane enhancements without destroying the three-stack architecture.

OBJECTIVE: Extend Command Hub (hub/server.py) as central operational plane for Canonical, ORION, DevOps.

Already shipped (do not duplicate): federated pipelines, timeline, artifacts, audit (partial), health matrix, correlation_id middleware, retry/resume/cancel adapters, SSE events, control-plane.js, Operations Center.

Implement or complete:
1. Unified resource model (Organization, Project, Repository, Environment, PipelineRun, Stage, Agent, Artifact, Deployment, Incident, Approval, Alert) with stable IDs and stack provenance.
2. Pipeline explorer filters (repo, branch, commit, status, stack, date, duration, failed stage, security severity).
3. Global timeline alignment across stacks (normalize stage names in hub/federation/timeline.py).
4. Unified artifact + audit explorers (search, pagination).
5. correlation_id / trace_id on webhook → pipeline → Celery → WS → Slack.
6. Unified health matrix extensions (LLM, staging, registry) without breaking existing /health endpoints.
7. Tests: hub federation, Playwright, correlation propagation.

Acceptance:
- One Hub screen inspects any stack run
- One correlation ID traces across services
- Stack APIs remain functional; adapters only
- run_e2e_all.ps1 -Offline passes
```

---

## Appendix C — Phases 2–29 (scope summaries)

Full feature lists and agent names are in the user roadmap and in [`IMPLEMENTATION_BACKLOG.md`](audit/IMPLEMENTATION_BACKLOG.md). When starting a phase:

1. Read the backlog section for that phase.
2. Grep the codebase for existing artifacts/agents (avoid duplicates).
3. Extend ORION orchestrator enrichment or Hub federation—not a new stack.
4. Update `FEATURE_MATRIX.md` and `agents.md` if user-facing.

| Phase | Focus |
|------:|-------|
| 2 | RepositoryIntelligence, impact, SBOM, secrets, licenses |
| 3 | Multi-layer code review L0–L7 |
| 4 | SAST/SCA/DAST/secrets/container/IaC agents + real tools |
| 5 | Supply chain center, attestations, Sigstore concepts |
| 6 | TestIntelligence, selection, flaky, mutation, contracts |
| 7 | PerformanceIntelligence, regression gates |
| 8 | Deployment registry, canary/blue-green, verification |
| 9 | OTEL, traces, anomaly, deployment correlation |
| 10 | Incident lifecycle, RCA, postmortem |
| 11 | Remediation levels 0–6, policy-gated autonomy |
| 12 | ORION Policy Engine (YAML + OPA) |
| 13 | Multi-person approvals, escalation |
| 14 | Additional multimodal agents |
| 15 | K8s/Helm/Terraform agents |
| 16 | Service catalog / developer portal |
| 17 | pgvector RAG + memory layers |
| 18 | Agent mesh runtime |
| 19 | AI governance, prompts, eval |
| 20 | FinOps dashboards |
| 21 | Release center |
| 22 | CLI, VS Code, GitHub App |
| 23 | Operations console navigation |
| 24 | Enterprise IAM, SSO, ABAC |
| 25 | Reliability, chaos, DLQ |
| 26 | DR backup/restore |
| 27 | Global search, knowledge graph |
| 28 | Autopilot modes MANUAL→AUTONOMOUS |
| 29 | Unified ORION Risk Engine |

---

## What to prioritize next (post-scaffolding)

| Priority | Work item | Phases |
|:--------:|-----------|--------|
| P0 | Real scanner integrations (Semgrep, Trivy, Gitleaks) + reachable SCA | 4–5 |
| P0 | Cross-stack scanner parity documentation + DevOps depth | 4 |
| P1 | Production OTEL collector path | 9 |
| P1 | Postgres/pgvector memory (Wave 4) | 17 |
| P1 | Hub live platform-event SSE | 1, 23 — **Done** (`GET /control-plane/platform-events/stream`) |
| P2 | Multi-person approval workflows (beyond artifact) | 13 |
| P2 | Real cloud deploy runbook execution | 30 |

---

*Maintainers: update the phase status table when backlog sections change. Last aligned with IMPLEMENTATION_BACKLOG Phases 0–30 + ORION-ARCH-001 Wave 1.*
