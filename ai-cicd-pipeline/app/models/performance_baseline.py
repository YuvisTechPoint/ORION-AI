"""Rolling performance baseline per repository."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PerformanceBaseline(Base):
    __tablename__ = "performance_baselines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    profile: Mapped[str] = mapped_column(String(32), default="standard")
    environment: Mapped[str] = mapped_column(String(64), default="staging")
    p95_ms: Mapped[float] = mapped_column(Float, default=0.0)
    error_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
