from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any


class PipelineRunCreate(BaseModel):
    id: str
    repo_name: str


class PipelineRunRead(BaseModel):
    id: str
    repo_name: str
    status: str
    current_stage: str
    created_at: datetime
    updated_at: datetime


class StageResultCreate(BaseModel):
    pipeline_id: str
    stage_name: str
    result_json: dict[str, Any]
    status: str


class StageResultRead(BaseModel):
    id: int
    pipeline_id: str
    stage_name: str
    result_json: dict[str, Any]
    status: str


class LogCreate(BaseModel):
    pipeline_id: str
    message: str


class LogRead(BaseModel):
    id: int
    pipeline_id: str
    message: str
    timestamp: datetime
