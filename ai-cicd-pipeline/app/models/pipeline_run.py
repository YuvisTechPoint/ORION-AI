import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, Uuid, func
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
        "approved",
        "monitoring",
        "rolled_back",
        "auto_rolled_back",
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_dast",
        "blocked_secrets",
        "blocked_policy",
        "blocked_injection",
        "blocked_agent_eval",
        "blocked_governance",
        "blocked_mesh",
        "blocked_finops",
        "blocked_release",
        "blocked_iam",
        "blocked_reliability",
        "blocked_dr",
        "blocked_knowledge",
        "blocked_autopilot",
        "blocked_unified_risk",
        "blocked_cloud",
        "blocked_with_prs_sent",
        "rejected",
        "failed",
        "cancelled",
    }
)

TERMINAL_STATUSES = frozenset(
    {
        "deployed",
        # every gate passed but no deployment target is configured (DEPLOY_MODE=skip / no Docker)
        "approved",
        "rolled_back",
        "auto_rolled_back",
        "blocked_code",
        "blocked_security",
        "blocked_tests",
        "blocked_stress",
        "blocked_dast",
        "blocked_secrets",
        "blocked_policy",
        "blocked_injection",
        "blocked_agent_eval",
        "blocked_governance",
        "blocked_mesh",
        "blocked_finops",
        "blocked_release",
        "blocked_iam",
        "blocked_reliability",
        "blocked_dr",
        "blocked_knowledge",
        "blocked_autopilot",
        "blocked_unified_risk",
        "blocked_cloud",
        "blocked_with_prs_sent",
        "rejected",
        "failed",
        "cancelled",
    }
)

RETRYABLE_STATUSES = frozenset(
    {s for s in VALID_STATUSES if s.startswith("blocked_")} | {"failed", "rejected"}
)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    # Python-side default keeps SQLite (tests) working; Postgres migration also sets gen_random_uuid().
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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

    def __repr__(self) -> str:
        return f"<PipelineRun {self.id} commit={self.short_commit_id} status={self.status}>"
