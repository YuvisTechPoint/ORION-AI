import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.pipeline_run import PipelineRun

VALID_ARTIFACT_TYPES = frozenset(
    {
        "diff",
        "metadata",
        "code_analysis",
        "security_scan",
        "qa_report",
        "stress_report",
        "approval",
        "deployment_info",
        "monitoring_alert",
        "last_known_good_image",
        "full_scan_combined",
        "auto_pr_registry",
        "payment_analysis",
        "git_log_analysis",
    }
)


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    pipeline_run: Mapped["PipelineRun"] = relationship(
        "PipelineRun", back_populates="artifacts"
    )
