from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from core.db import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True, index=True)
    repo_name = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")
    current_stage = Column(String, nullable=False, default="dev")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    stages = relationship("StageResult", back_populates="pipeline", cascade="all, delete-orphan")
    logs = relationship("LogEntry", back_populates="pipeline", cascade="all, delete-orphan")


class StageResult(Base):
    __tablename__ = "stage_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    stage_name = Column(String, nullable=False)
    result_json = Column(Text, nullable=False)
    status = Column(String, nullable=False)

    pipeline = relationship("PipelineRun", back_populates="stages")


class LogEntry(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_id = Column(String, ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    pipeline = relationship("PipelineRun", back_populates="logs")
