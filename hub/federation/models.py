"""Normalized control-plane resource models (read-only federation view)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

StackId = Literal["canonical", "orion", "platform"]


class UnifiedPipelineRun(BaseModel):
    id: str
    stack: StackId
    native_id: str
    organization: str = "default"
    project: str = ""
    repository: str = ""
    branch: str | None = None
    commit_sha: str | None = None
    short_commit: str | None = None
    status: str
    environment: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    failed_stage: str | None = None
    security_severity: str | None = None
    pusher: str | None = None
    error_message: str | None = None
    deep_link: str | None = None


class UnifiedArtifact(BaseModel):
    id: str
    stack: StackId
    run_id: str
    native_run_id: str
    artifact_type: str
    summary: str | None = None
    verdict: str | None = None
    created_at: str | None = None
    correlation_id: str | None = None


class UnifiedAuditEvent(BaseModel):
    id: str
    stack: StackId
    run_id: str
    native_run_id: str
    action: str
    actor: str | None = None
    outcome: str | None = None
    timestamp: str | None = None
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class StackHealth(BaseModel):
    stack: StackId
    title: str
    api_base: str
    health: str = "unknown"
    ready: str = "unknown"
    health_payload: dict[str, Any] = Field(default_factory=dict)
    ready_payload: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None


class UnifiedHealthMatrix(BaseModel):
    generated_at: str
    hub_status: str = "ok"
    stacks: list[StackHealth] = Field(default_factory=list)


class TimelineStage(BaseModel):
    key: str
    label: str
    state: Literal["pending", "active", "completed", "failed", "skipped"] = "pending"
    timestamp: str | None = None


class UnifiedTimeline(BaseModel):
    stack: StackId
    run_id: str
    native_run_id: str
    correlation_id: str | None = None
    current_status: str
    stages: list[TimelineStage] = Field(default_factory=list)


class FederatedPipelineList(BaseModel):
    total: int
    items: list[UnifiedPipelineRun]
    filters: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class StackIntelligenceSnapshot(BaseModel):
    stack: StackId
    title: str
    available: bool = False
    pass_rate: float | None = None
    slo: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    top_blockers: list[str] = Field(default_factory=list)
    finops: dict[str, Any] = Field(default_factory=dict)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class OperationsCenterReport(BaseModel):
    generated_at: str
    correlation_id: str | None = None
    active_pipelines: int = 0
    blocked_pipelines: int = 0
    deployed_recent: int = 0
    incidents_open: int = 0
    canary_active: int = 0
    alerts: list[dict[str, Any]] = Field(default_factory=list)
    top_blockers: list[str] = Field(default_factory=list)
    slo_summary: dict[str, Any] = Field(default_factory=dict)
    fleet: dict[str, Any] = Field(default_factory=dict)
    stack_intelligence: list[StackIntelligenceSnapshot] = Field(default_factory=list)
    service_grid: list[dict[str, Any]] = Field(default_factory=list)
    policy_panel: dict[str, Any] = Field(default_factory=dict)
    security_panel: dict[str, Any] = Field(default_factory=dict)
    performance_panel: dict[str, Any] = Field(default_factory=dict)
    memory_panel: dict[str, Any] = Field(default_factory=dict)
    platform_events: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
