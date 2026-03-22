import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


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
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class PipelineRunListResponse(BaseModel):
    total: int
    items: list[PipelineRunResponse]
    filters: dict[str, Any] = {}
