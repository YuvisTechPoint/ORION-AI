from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Severity = Literal["low", "medium", "high"]
Modality = Literal["code", "log", "config", "image_ref", "metrics"]
Stage = Literal[
    "dev",
    "qa",
    "stress",
    "approval",
    "deployment",
    "blocked",
    "blocked_with_prs_sent",
    "completed",
    "failed",
    "rolled_back",
]


class AgentIssue(BaseModel):
    type: str
    severity: Severity
    line: str
    fix: str
    snippet: str | None = None


class CodeAnalysisResult(BaseModel):
    summary: str
    issues: list[AgentIssue] = Field(default_factory=list)
    quality_score: int = Field(default=100, ge=0, le=100)
    suggestions: list[str] = Field(default_factory=list)


class SecurityResult(BaseModel):
    summary: str
    issues: list[AgentIssue] = Field(default_factory=list)
    blocked: bool = False


class MonitoringResult(BaseModel):
    summary: str
    anomalies: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class PipelineDecision(BaseModel):
    next_stage: Stage
    reason: str
    approved: bool = False


class DeploymentResult(BaseModel):
    status: Literal["deployed", "rolled_back", "failed"]
    reason: str
    environment: str = "staging"


class SubmitCodeRequest(BaseModel):
    repo_name: str
    code: str
    diff: str | None = None
    config_text: str | None = None
    repo_files: dict[str, str] | None = None
    multimodal_inputs: list["MultiModalInput"] | None = None
    enable_auto_pr: bool = False
    repo_full_name: str | None = None
    clone_url: str | None = None
    branch: str = "main"


class SubmitCodeResponse(BaseModel):
    pipeline_id: str
    current_stage: Stage
    status: str


class TriggerDeploymentRequest(BaseModel):
    pipeline_id: str
    approved_by: str | None = None


class AnalyzeLogsRequest(BaseModel):
    pipeline_id: str | None = None
    logs: str
    multimodal_inputs: list["MultiModalInput"] | None = None


class PipelineState(BaseModel):
    pipeline_id: str = Field(default_factory=lambda: str(uuid4()))
    repo_name: str
    current_stage: Stage = "dev"
    status: str = "running"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    history: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    queue_backend: str
    llm_mode: Literal["live", "mock"]
    qa_mode: str
    auth_enabled: bool


class MultiModalInput(BaseModel):
    modality: Modality
    content: str
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuntimeConfigResponse(BaseModel):
    app_env: str
    llm_mode: Literal["live", "mock"]
    queue_backend: str
    database_backend: str
    database_host: str
    qa_mode: str
    auth_enabled: bool
    healthy: bool
    checks: dict[str, Any]
