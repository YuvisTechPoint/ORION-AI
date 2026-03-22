from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import PipelineStatus


class PipelineTriggerRequest(BaseModel):
    repo_url: str = Field(..., description="Full GitHub repository URL")
    deployment_api_key: str | None = None


class PipelineTriggerResponse(BaseModel):
    pipeline_id: UUID
    status: PipelineStatus


class PipelineStatusLight(BaseModel):
    id: UUID
    status: PipelineStatus
    current_stage: str


class AgentLogOut(BaseModel):
    id: UUID
    stage: str
    level: str
    message: str
    timestamp: datetime
    artifact_json: dict[str, Any] | None = None


class StageResultOut(BaseModel):
    id: UUID
    stage: str
    passed: bool
    output_json: dict[str, Any] | None = None
    created_at: datetime


class PipelineDetailResponse(BaseModel):
    id: UUID
    repo_url: str
    commit_sha: str
    status: PipelineStatus
    created_at: datetime
    updated_at: datetime
    metadata_json: dict[str, Any] | None = None
    logs: list[AgentLogOut]
    stage_results: list[StageResultOut]


class PipelineListItem(BaseModel):
    id: UUID
    repo_url: str
    status: PipelineStatus
    created_at: datetime


class LogAnalyzeRequest(BaseModel):
    log_text: str = Field(..., min_length=1)


class LogAnalyzeResponse(BaseModel):
    summary: str
    anomalies: list[dict[str, Any]]
    alerts: list[str]
    health_status: str
    raw_artifact: dict[str, Any]


class HealthResponse(BaseModel):
    api: str
    db: str
    redis: str


class WebSocketLogEvent(BaseModel):
    type: str = "log"
    stage: str
    level: str
    message: str
    timestamp: str


class WebSocketStatusEvent(BaseModel):
    type: str = "status_change"
    pipeline_id: str
    old_status: str
    new_status: str
    timestamp: str


class WebSocketArtifactEvent(BaseModel):
    type: str = "artifact"
    stage: str
    data: dict[str, Any]


class WebSocketAlertEvent(BaseModel):
    type: str = "alert"
    message: str
    severity: str
