# Binary-v2 / ORION — Feature Matrix (Phase 0)

**Legend**

| Status | Meaning |
|--------|---------|
| **Production** | Real integration, tested, used in pipeline/UI |
| **Partial** | Heuristic, simulated, or report-only; not full external tool |
| **Foundation** | Core logic exists; missing propagation/UI/E2E |
| **Mock** | Deterministic placeholder explicitly marked simulated |
| **Doc-only** | Described in agents.md/README but no code path |
| **Missing** | Not implemented |

**Stacks:** `H` Hub · `C` Canonical · `O` ORION · `P` Platform

---

## A. Core pipeline & orchestration

| Feature | C | O | P | Status | Evidence / notes |
|---------|---|---|---|--------|------------------|
| GitHub push webhook | ✅ | ✅ | ✅ | Production | HMAC + ledger |
| Manual pipeline trigger | ❌ | ✅ | ✅ | Production | ORION `/pipeline/trigger` |
| Submit code/archive/GitHub zip | ✅ | ❌ | ❌ | Production | Canonical only |
| 9-stage orchestrator | ❌ | ✅ | partial | Production / Partial | Platform sequential |
| Parallel full scan (code+sec+QA) | ❌ | ✅ | ❌ | Production | ORION FullScanOrchestrator |
| Resume from checkpoint | ✅ | ✅ | ✅ | Production | |
| Retry / cancel | ✅ | ✅ | ✅ | Production | |
| Webhook delivery ledger | ✅ | ✅ | partial | Production | |
| Pipeline dedup (in-flight) | ❌ | ✅ | ❌ | Production | ORION |
| Auto-PR on block | ✅ | ✅ | partial | Production | |
| Gate fusion | ✅ | ✅ | ✅ | Production | |
| Change risk score | ✅ | ✅ | ❌ | Production / Heuristic | |
| Prompt injection gate | ❌ | ✅ | ❌ | Production | `blocked_injection` |
| Secrets scan gate | ❌ | ✅ | ❌ | Production | `blocked_secrets` |
| Policy-as-code gate | ❌ | ✅ | ❌ | Partial | Heuristic policies; post-approval |
| Agent eval gate | ❌ | ✅ | ❌ | Foundation | Off by default |

---

## B. Code analysis

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| pylint | ❌ | ✅ | ❌ | Production |
| AST scan | ❌ | ✅ | ❌ | Production |
| LLM code review | ✅ | ✅ | ✅ | Partial (heuristic fallback) |
| Regex rule engine | ✅ | ❌ | ❌ | Production |
| Semantic / architecture review (L3+) | ❌ | partial | ❌ | Mock (LLM prompt only) |
| Bug prediction / concurrency analysis | ❌ | ❌ | ❌ | Missing |
| Generated-code detection | ❌ | ❌ | ❌ | Missing |

---

## C. Security (DevSecOps fabric)

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Bandit SAST | ❌ | ✅ | ❌ | Production |
| pip-audit SCA | ❌ | ✅ | ❌ | Partial | Unpinned deps → not_audited |
| Semgrep | ❌ | ❌ | ❌ | Missing |
| Trivy container scan | ❌ | partial | ❌ | Partial | Regex/heuristic container_security |
| Gitleaks | ❌ | partial | ❌ | Partial | secrets_guardian heuristic |
| Checkov / IaC | ❌ | partial | ❌ | Partial | iac_security heuristic |
| DAST / OWASP ZAP | ❌ | ❌ | ❌ | Missing |
| Runtime security agent | ❌ | ❌ | ❌ | Missing |
| LLM cannot downgrade scanner | ❌ | ✅ | partial | Production | ORION SecurityAgent |
| MAX_SECURITY_SEVERITY gate | ❌ | ✅ | ✅ | Production |

---

## D. Supply chain

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| SBOM generation | ❌ | partial | ❌ | Partial | Heuristic CycloneDX-like JSON |
| Dependency graph | ❌ | partial | ❌ | Partial | service_graph |
| Knowledge graph | ❌ | ✅ | ❌ | Phase 27 | `knowledge_graph_intelligence`, unified graph + queries, `orion knowledge` CLI |
| ORION Autopilot | ❌ | ✅ | ❌ | Phase 28 | `autopilot_intelligence`, policy-gated L0–L6 plan, `orion autopilot` CLI |
| Unified Risk Engine | ❌ | ✅ | ❌ | Phase 29 | `unified_risk_intelligence`, fused score across gates + intelligence, `orion unified-risk` CLI |
| CVE / OSV / Grype | ❌ | ❌ | ❌ | Missing |
| License compliance scan | ❌ | partial | ❌ | Partial | compliance_packs |
| Signed builds / Cosign | ❌ | mock | ❌ | Mock | simulated unless strict |
| Build attestation / provenance | ❌ | mock | ❌ | Mock |
| Syft integration | ❌ | ❌ | ❌ | Missing |

---

## E. Test intelligence

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| pytest execution | partial | ✅ | ✅ | Production when tests/ exist |
| Simulated QA pass (no tests/) | ✅ | ✅ | ✅ | Mock (explicit skipped) |
| Intelligent test selection | ❌ | ✅ | ❌ | Partial | test_intelligence + QA targets |
| Test generation | ❌ | partial | ❌ | Mock | report artifact |
| Flaky test detection | ❌ | ❌ | ❌ | Missing |
| Mutation testing | ❌ | ❌ | ❌ | Missing |
| Contract testing | ❌ | partial | ❌ | Partial | contract_testing util |
| Coverage gate | ❌ | ❌ | ❌ | Missing |
| Playwright E2E in pipeline | ❌ | ❌ | ❌ | Missing | Repo has hub Playwright only |

---

## F. Performance engineering

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Locust load test | ❌ | ✅ | ✅ | Production |
| Staging URL required | ❌ | ✅ | ✅ | Production |
| p95 regression gate vs baseline | ❌ | partial | partial | Partial | warn/fail thresholds, no main baseline store |
| Spike/soak/endurance profiles | ❌ | ❌ | ❌ | Missing |
| PerformanceIntelligenceAgent | ❌ | ❌ | ❌ | Missing |
| Resource saturation metrics | ❌ | partial | ❌ | Partial | monitoring heuristics |

---

## G. Deployment & progressive delivery

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Docker build/run/health | ❌ | ✅ | ✅ | Production |
| Simulate deploy | ✅ | ✅ | ✅ | Production |
| Skip deploy | ❌ | ✅ | ✅ | Production |
| Canary 5→25→50→100% | ❌ | partial | ❌ | Partial | progressive_delivery heuristic |
| Blue/green | ❌ | ❌ | ❌ | Missing |
| Environment registry | ❌ | partial | ❌ | Foundation | preview_environment artifact |
| Rollback on health fail | ❌ | ✅ | partial | Production |
| Rollback intelligence (SLO-driven) | ❌ | partial | ❌ | Partial | rollback_intelligence |
| Feature flags | ❌ | ❌ | ❌ | Missing |

---

## H. Observability / AIOps

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Post-deploy monitoring agent | partial | ✅ | ✅ | Partial |
| Prometheus metrics | partial | ✅ | stub | Partial |
| Grafana dashboard JSON | ❌ | doc | ❌ | Foundation | manual import |
| OpenTelemetry export | ❌ | mock | ❌ | Mock | JSON artifact only |
| Distributed tracing | ❌ | ❌ | ❌ | Missing |
| Error budget engine | ❌ | ✅ | partial | Partial |
| Synthetic monitoring | ❌ | partial | ❌ | Partial | live optional flag |
| Chaos / reliability | ❌ | ✅ | ❌ | Phase 25 | `reliability_intelligence`, policy-driven chaos suite, `orion reliability` CLI |
| Disaster recovery | ❌ | ✅ | ❌ | Phase 26 | `dr_intelligence`, pg_dump/SQLite backup, RTO/RPO gates, `orion dr` CLI |
| Anomaly detection | ❌ | partial | ❌ | Partial | monitoring heuristics |
| correlation_id propagation | ❌ | ❌ | ❌ | Missing |

---

## I. Incident response

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Production triage multimodal | ✅ | ✅ | proxy | Partial |
| Incident commander bundle | ❌ | partial | ❌ | Partial | triggered from monitoring |
| RCA engine | ❌ | partial | ❌ | Partial | heuristic |
| Evidence graph | ❌ | partial | ❌ | Partial |
| Postmortem generator | ❌ | partial | ❌ | Partial |
| Runbook automation | ❌ | partial | ❌ | Partial |
| Incident Center UI | ❌ | ❌ | ❌ | Missing |
| P0–P4 lifecycle management | ❌ | ❌ | ❌ | Missing |

---

## J. Autonomous remediation

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Auto-PR fix branches | ✅ | ✅ | partial | Production |
| Fix loop service | ❌ | partial | ❌ | Partial |
| SoftwareEngineerAgent | ❌ | ✅ | ❌ | Production |
| Patch confidence | ❌ | partial | ❌ | Partial |
| PR intelligence | ❌ | partial | ❌ | Partial |
| Agent sandbox | ❌ | partial | ❌ | Partial |
| Level 6 autonomous deploy | ❌ | ❌ | ❌ | Missing (by design) |

---

## K. Policy, governance, enterprise

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Policy engine (YAML-like rules) | ❌ | partial | ❌ | Partial |
| Compliance packs (SOC2/ISO/OWASP) | ❌ | partial | ❌ | Partial | scoring heuristics |
| Multi-tenant RBAC | partial | partial | partial | Partial | API keys + roles |
| Enterprise SSO / IAM | ✅ | partial | ❌ | Phase 24 | `iam_intelligence` artifact, SSO/MFA/RBAC gates, `orion iam` CLI |
| FinOps cost rollup | ❌ | partial | ❌ | Partial |
| Audit explorer API | ❌ | ✅ | partial | Partial |
| Fleet view | ❌ | ✅ | ❌ | Partial |
| Human approval workflows (multi-person) | ❌ | ❌ | ❌ | Missing |

---

## L. AI platform

| Feature | C | O | P | Status |
|---------|---|---|---|--------|
| Agent registry | ❌ | ✅ | ❌ | Partial |
| Model router | ❌ | partial | ❌ | Partial |
| Prompt registry | ❌ | partial | ❌ | Partial |
| AgentEval | ❌ | partial | ❌ | Partial |
| Decision ledger | ❌ | partial | ❌ | Partial |
| DevOps RAG | ❌ | partial | ❌ | Partial | keyword/heuristic, no pgvector |
| Prompt injection firewall | ❌ | ✅ | ❌ | Production |
| Agent mesh / PlannerAgent | ❌ | ❌ | ❌ | Missing |
| Memory Gateway (governed L1–L6 API) | partial | ✅ | ❌ | Wave 1 | SQLite store; `/api/v2/memory`; episodic on terminal pipeline (canonical + ORION) |
| Platform event backbone | partial | ✅ | ❌ | Wave 1 | Redis Streams + in-memory; Hub `/control-plane/platform-events` |
| Organizational memory (pgvector) | ❌ | partial | ❌ | Wave 4 | L3 semantic retrieval not yet on pgvector |

---

## M. Multimodal intelligence

| Agent / route | C | O | P |
|---------------|---|---|---|
| Log analysis | ✅ | ✅ | proxy |
| GitHub Actions log | ✅ | ✅ | proxy |
| Git log dedicated route | ❌ | ✅ | proxy |
| Payment reconciliation | ❌ | ✅ | proxy |
| Dockerfile hardening | ✅ | ✅ | ❌ |
| Production triage | ✅ | ✅ | ❌ |
| Screenshot / K8s / Terraform agents | ❌ | ❌ | ❌ |

---

## N. Command Hub & developer UX

| Feature | Status | Notes |
|---------|--------|-------|
| Unified launcher | Production | `run_all_stacks.ps1` |
| Hub health polling | Production | |
| Cross-stack intelligence panel | Production | read-only |
| Unified pipeline explorer | Production | Hub `control-plane.js` |
| Unified artifact explorer | Production | `GET /control-plane/artifacts` |
| Federated audit search | Partial | `GET /control-plane/audit` |
| Operations Center | Production | `GET /control-plane/operations` + hub UI |
| Federated intelligence fan-out | Production | `GET /control-plane/intelligence` |
| ORION developer CLI | Production | `ai-cicd-pipeline/scripts/orion_cli.py` |
| VS Code extension | Production | `developer/vscode-orion/` + `GET /developer/vscode` |
| GitHub App | Production | manifest + `POST /webhook/github/app` |

---

## O. Documentation vs implementation gaps

| Document claim | Reality |
|----------------|---------|
| `agents.md` §69 Phases 1–5 all ✅ | ORION has artifacts + gates; many are **heuristic**, not external tools |
| Part II §58–§67 many 📋 | Several are **Partial/Foundation** in ORION already — doc markers stale |
| Part II §70 killer workflow all ✅ | Accurate for ORION happy-path; not all steps are production-grade OTEL/canary |
| Canonical parity with ORION | **No** — lighter scanners, simulated QA default |
| Unified control plane | **No** — Hub is launcher |

---

*Cross-reference: ARCHITECTURE_AUDIT.md, IMPLEMENTATION_BACKLOG.md*
