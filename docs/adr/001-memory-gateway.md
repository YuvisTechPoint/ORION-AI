# ADR 001 — Memory Gateway (ORION-ARCH-001 §6)

## Status

Accepted — Wave 1 SQLite + Wave 4 Postgres/pgvector (`MemoryPgStore`, deterministic L3 embeddings).

## Context

ORION agents and pipelines need durable, governed memory across runs without letting LLM context become a second gate. The architecture specification (ORION-ARCH-001) requires a single write/read interface (MEM-01), secret redaction (MEM-03), advisory-only context packing (MEM-04), tenant isolation, quarantine for prompt-injection payloads, and audit logging.

## Decision

1. Implement `shared/memory_gateway/` as the cross-stack library:
   - `MemoryGateway` — sole write/read API
   - `MemorySqliteStore` — Wave 1 persistence (`.local/orion-memory.db`)
   - Layers L1–L6 modeled; L2 episodic used for pipeline summaries
2. ORION exposes `/api/v2/memory/*` and writes episodic summaries on terminal pipeline status.
3. Agent runtime may inject packed context via `read_memory_context()` when `MEMORY_GATEWAY_ENABLED=true`. Injection is labeled **untrusted / advisory only** and never feeds gate fusion.
4. Canonical stack uses `backend/services/memory_gateway_client.py` delegating to the same shared gateway.

## Consequences

- SQLite remains default for local/dev; set `MEMORY_BACKEND=postgres` (+ `pgvector` extension) for semantic L3 search without API breakage.
- Duplicate content hashes dedupe writes per tenant.
- Injection-shaped memory is quarantined, not stored as active records.

## References

- `shared/memory_gateway/`
- `ai-cicd-pipeline/app/services/memory_gateway_service.py`
- `ai-cicd-pipeline/app/api/routes/memory_v2.py`
