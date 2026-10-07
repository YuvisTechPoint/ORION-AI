# Binary-v2 / ORION — Technical Debt (Phase 0)

Prioritized engineering debt evidenced in code and tests. Not stylistic refactors.

---

## P0 — Fix before production hardening

| ID | Item | Location | Impact |
|----|------|----------|--------|
| TD-001 | WebSocket `NameError`: missing `event_bus`, `channel_for` imports | `ai-cicd-pipeline/app/main.py` | **Resolved** (H-001) |
| TD-002 | Canonical frontend calls missing multimodal routes | `backend/api/multimodal.py` git-logs + payment | **Resolved** (H-002) |
| TD-003 | `agents.md` Part II 📋 markers stale vs §69 ✅ | `agents.md` §69 Phases 1–29 | **Resolved** (H-004) |
| TD-004 | No WebSocket tests | `tests/test_websocket.py` | **Resolved** (H-003) |

---

## P1 — Architectural / maintainability

| ID | Item | Location | Notes |
|----|------|----------|-------|
| TD-010 | Triplicated stack config | `config/stacks.json`, `hub/stacks.json`, `hub.js`, `stacks.ts` | Drift risk |
| TD-011 | Triplicated `text_analysis.py` | backend, ORION, platform | Parity maintenance |
| TD-012 | Triplicated gate fusion / SLO | all stacks | Consider shared package |
| TD-013 | Unused SQLAlchemy models | `backend/models/db_models.py` | Dead schema confusion |
| TD-014 | No Alembic on canonical | `backend/` | Manual `create_all` only |
| TD-015 | Two `orion_cli.py` implementations | `scripts/` vs `ai-cicd-pipeline/scripts/` | Different defaults/ports |
| TD-016 | Platform docker-compose port 8000 vs launcher 8002 | `devops-platform/docker-compose.yml` | Doc/ops mismatch |
| TD-017 | Hub ignores `config/stacks.json` | `scripts/sync_stack_catalog.ps1` + BFF catalog | **Resolved** (H-005) |
| TD-018 | Sequential full scan on canonical | `full_scan_orchestrator.py` | Slower than ORION parallel |

---

## P2 — Observability & operations

| ID | Item | Notes |
|----|------|-------|
| TD-020 | No `correlation_id` anywhere in app code | Blocks unified tracing |
| TD-021 | OTEL artifact is stub JSON only | Not exported to collector |
| TD-022 | Prometheus not bundled | Manual Grafana setup |
| TD-023 | Platform `/metrics` stub | No HTTP latency series |
| TD-024 | `datetime.utcnow()` deprecation warnings | canonical orchestrator |
| TD-025 | No centralized structured logging schema | Hard to correlate across stacks |

---

## P3 — Testing gaps

| ID | Item | Current state |
|----|------|---------------|
| TD-030 | Frontend unit tests | 0 on canonical, ORION, platform UIs |
| TD-031 | Playwright coverage | Hub smoke only (5 tests) |
| TD-032 | Cross-stack integration tests | None automated |
| TD-033 | Multimodal route parity tests | Missing for canonical |
| TD-034 | Policy gate edge cases | Partial (`test_orchestrator_gates.py`) |
| TD-035 | Progressive delivery E2E | None |
| TD-036 | Auth-required mode test matrix | Incomplete |

**Baseline counts (2026-10-06):** ORION 242 · Canonical 54 · Platform 28 · **324 total**

---

## P4 — Security & compliance debt

| ID | Item |
|----|------|
| TD-040 | Heuristic scans not labeled distinctly in all UI surfaces |
| TD-041 | Auth off by default — relies on operator config |
| TD-042 | No secret scanning on canonical/platform pipelines |
| TD-043 | Simulated QA default on canonical (`QA_MODE=simulated`) |
| TD-044 | No dependency CVE database integration beyond pip-audit pinned deps |
| TD-045 | RAG retrieval without explicit chunk-level redaction audit |

---

## P5 — Documentation debt

| ID | Item |
|----|------|
| TD-050 | `agents.md` 3500+ lines — Part I/II status inconsistency |
| TD-051 | README stack ports scattered across files |
| TD-052 | Phase numbering confusion (prior §69 P0–P5 vs new roadmap Phases 0–29) |
| TD-053 | FEATURE_MATRIX not previously maintained — now in `docs/audit/` |

---

## P6 — Performance & reliability

| ID | Item |
|----|------|
| TD-060 | Full scan DB lock serialization (`_orion_lock`) — intentional but limits throughput |
| TD-061 | Inline executor runs pipeline in API process — resource contention |
| TD-062 | Stale run reaper 600s interval — slow orphan recovery |
| TD-063 | No circuit breaker on external GitHub/Anthropic calls |
| TD-064 | No idempotency keys on manual trigger API (dedup by repo+commit only) |

---

## P7 — Intentional deferrals (not debt)

These are **by design** per engineering contract:

- Level 6 autonomous production remediation globally disabled
- Kubernetes/cloud agents not started
- pgvector RAG not started
- Monolith merge of three stacks rejected

---

## Suggested paydown sequence (aligns with roadmap)

1. TD-001, TD-002, TD-004 (stability)
2. TD-010, TD-017 (Phase 1 control plane prep)
3. TD-020 (correlation middleware)
4. TD-011 consolidation evaluation (shared lib, not big-bang)
5. TD-030–036 (test expansion with each phase)

---

*Tracked items should move to IMPLEMENTATION_BACKLOG.md when scheduled.*
