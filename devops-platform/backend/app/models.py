import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PipelineStatus(str, enum.Enum):
    PENDING = "PENDING"
    DEV = "DEV"
    QA = "QA"
    STRESS = "STRESS"
    APPROVAL = "APPROVAL"
    DEPLOYMENT = "DEPLOYMENT"
    MONITORING = "MONITORING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, name="pipeline_status_enum"),
        default=PipelineStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    logs: Mapped[list["AgentLog"]] = relationship(
        "AgentLog", back_populates="pipeline", cascade="all, delete-orphan"
    )
    stage_results: Mapped[list["StageResult"]] = relationship(
        "StageResult", back_populates="pipeline", cascade="all, delete-orphan"
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    artifact_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    pipeline: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="logs")


class StageResult(Base):
    __tablename__ = "stage_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(default=False)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pipeline: Mapped["PipelineRun"] = relationship("PipelineRun", back_populates="stage_results")
