# ADR 002 — Platform Event Backbone (ORION-ARCH-001 §5.3)

## Status

Accepted — Wave 1 in-memory + Redis Streams interface.

## Context

Cross-plane features (Hub operations, fleet view, incident correlation) need a normalized domain event stream distinct from per-pipeline WebSocket events. The specification defines `PlatformEvent` envelopes with `event_type`, `correlation_id`, `tenant_id`, `trace_id`, and JSON `payload`.

## Decision

1. Implement `shared/event_bus/` with:
   - `PlatformEvent` model
   - `InMemoryPlatformEventBus` for dev/test and Redis fallback
   - `RedisStreamPlatformEventBus` publishing to `orion:platform:events`
2. ORION publishes `pipeline.started` and `pipeline.completed` from `PipelineOrchestrator`.
3. ORION exposes `GET /api/v2/events/recent` for operators and Hub federation.
4. Backend selection via `EVENT_BUS_BACKEND=auto|memory|redis` (auto prefers Redis when reachable).

## Consequences

- WebSocket pipeline events (`app/services/events.py`) remain unchanged for live UI.
- Platform events are durable when Redis is available; otherwise recent history is process-local.
- Downstream consumers (Hub BFF, audit explorer) can subscribe without orchestrator edits.

## References

- `shared/event_bus/`
- `ai-cicd-pipeline/app/services/platform_events.py`
- `ai-cicd-pipeline/app/api/routes/events_v2.py`
