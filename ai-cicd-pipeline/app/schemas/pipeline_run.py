import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PipelineRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    commit_id: str
    short_commit_id: str
    branch: str
    pusher: str
    repo_full_name: str
    clone_url: str
    status: str
    has_warnings: bool
    error_message: str | None
    correlation_id: str | None = None
    trace_id: str | None = None
    created_at: datetime | None
    updated_at: datetime | None
    completed_at: datetime | None


class PipelineRunListResponse(BaseModel):
    total: int
    items: list[PipelineRunResponse]
    # `runs` mirrors `items` for clients written against the build guide's schema.
    runs: list[PipelineRunResponse] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
