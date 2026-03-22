import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.pipeline_artifact import PipelineArtifact

VALID_STATUSES = frozenset(
    {
        "queued",
        "ingesting",
        "analyzing_code",
        "analyzing_security",
        "running_qa",
        "running_stress",
        "awaiting_approval",
        "deploying",
        "deployed",
        "monitoring",
        "rolled_back",
        "auto_rolled_back",
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_with_prs_sent",
        "rejected",
        "failed",
    }
)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    commit_id: Mapped[str] = mapped_column(String(40), index=True)
    short_commit_id: Mapped[str] = mapped_column(String(8))
    branch: Mapped[str] = mapped_column(String(255))
    pusher: Mapped[str] = mapped_column(String(255))
    repo_full_name: Mapped[str] = mapped_column(String(255))
    clone_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), default="queued", index=True)
    has_warnings: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    artifacts: Mapped[list["PipelineArtifact"]] = relationship(
        "PipelineArtifact",
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
    )
