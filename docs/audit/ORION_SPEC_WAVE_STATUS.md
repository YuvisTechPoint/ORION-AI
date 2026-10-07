# ORION-ARCH-001 Wave Status

Tracker aligned to `docs/ORION_Architecture_and_Implementation_Specification.docx` delivery waves.

**Legend:** ✅ shipped · 🔄 partial / Wave 1 interface · 📋 planned

| Wave | Theme | Status | Notes |
|------|-------|--------|-------|
| 0 | Unified control plane, repo intel, code review | ✅ | Hub federation, intelligence APIs, change risk |
| 1 | DevSecOps, supply chain, test/perf intel + **foundations** | ✅ | Memory Gateway + Event Bus + Hub federation **shipped**; external scanner depth continues in Wave 2 |
| 2 | Progressive delivery, AIOps, incident, remediation | ✅ | ORION phases 8–11 artifacts |
| 3 | Policy, approvals, RAG/memory mesh, governance, FinOps | ✅ | Heuristic + hybrid OPA; full pgvector in Wave 4 |
| 4 | Multimodal, K8s, catalog, release intel, Hub advanced, DR, knowledge, autopilot, unified risk | ✅ | ORION phases 14–29 |
| 5 | Release passport polish, enterprise hardening | ✅ | Production checklist, CI, baselines |

## Wave 1 foundation items (this increment)

| ID | Requirement | Status | Evidence |
|----|-------------|--------|----------|
| MEM-01 | Single memory write/read API | ✅ | `shared/memory_gateway/gateway.py` |
| MEM-03 | Secret redaction fail-closed | ✅ | `shared/memory_gateway/redaction.py` |
| MEM-04 | Advisory-only context packing | ✅ | `_pack_context()` + BaseAgent prefix |
| EVT-01 | Platform event envelope | ✅ | `shared/event_bus/models.py` |
| EVT-02 | Redis Streams + in-memory fallback | ✅ | `shared/event_bus/bus.py` |
| ORION-API | `/api/v2/memory`, `/api/v2/events` | ✅ | `memory_v2.py`, `events_v2.py` |
| ORION-HOOK | Pipeline terminal episodic write | ✅ | `orchestrator._set_status` |
| ORION-HOOK | `pipeline.started` / `pipeline.completed` events | ✅ | `orchestrator.execute_pipeline` |
| CANONICAL | Gateway client adapter | ✅ | `backend/services/memory_gateway_client.py` |
| CANONICAL | Episodic extractor + terminal hooks | ✅ | `memory_extractor.py`, `pipeline_terminal_hooks.py` |
| HUB | Platform events federation | ✅ | `GET /control-plane/platform-events`, ops center panel |

## Wave 4 follow-ups (not in scope for Wave 1 closure)

| Item | Status |
|------|--------|
| Postgres + pgvector memory store | 📋 |
| Embedding-based semantic retrieval (L3) | 📋 |
| Hub live Redis subscriber (SSE) | 📋 |

## Verification

```powershell
cd ai-cicd-pipeline
..\.venv\Scripts\pytest tests/test_memory_gateway.py tests/test_platform_events.py tests/test_memory_v2_api.py -v
.\run_e2e_all.ps1 -Offline
```

*Cross-reference: `docs/adr/001-memory-gateway.md`, `docs/adr/002-event-backbone.md`, `docs/audit/FEATURE_MATRIX.md`*
