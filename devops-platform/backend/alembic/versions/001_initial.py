"""initial schema

Revision ID: 001_initial
Revises:
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB() if dialect == "postgresql" else sa.JSON()
    status_type = sa.String(32)

    op.create_table(
        "pipeline_runs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("repo_url", sa.String(2048), nullable=False),
        sa.Column("commit_sha", sa.String(64), nullable=False, server_default=""),
        sa.Column("status", status_type, nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("metadata_json", json_type, nullable=True),
    )
    op.create_table(
        "agent_logs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("pipeline_id", uuid_type, sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("level", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("artifact_json", json_type, nullable=True),
    )
    op.create_table(
        "stage_results",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("pipeline_id", uuid_type, sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("output_json", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("stage_results")
    op.drop_table("agent_logs")
    op.drop_table("pipeline_runs")
