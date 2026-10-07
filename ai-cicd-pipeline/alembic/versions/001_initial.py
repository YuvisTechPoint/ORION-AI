"""initial ORION schema

Run with: alembic upgrade head

Revision ID: 001_initial
Revises:
Create Date: 2026-03-22
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
    # Databases bootstrapped by app.database.init_db() (create_all) already have the tables;
    # adopt them instead of failing so `alembic upgrade head` is safe on container start.
    existing = set(sa.inspect(bind).get_table_names())
    if {"pipeline_runs", "pipeline_artifacts"} <= existing:
        return

    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # SQLite (local dev) has no gen_random_uuid(); the ORM supplies uuid4 ids there.
    uuid_default = sa.text("gen_random_uuid()") if is_pg else None
    now = sa.text("now()") if is_pg else sa.text("CURRENT_TIMESTAMP")
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Uuid(), server_default=uuid_default, nullable=False),
        sa.Column("commit_id", sa.String(length=40), nullable=False),
        sa.Column("short_commit_id", sa.String(length=8), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("pusher", sa.String(length=255), nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("clone_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("has_warnings", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_pipeline_runs_commit_id"), "pipeline_runs", ["commit_id"], unique=False)
    op.create_index(op.f("ix_pipeline_runs_status"), "pipeline_runs", ["status"], unique=False)

    op.create_table(
        "pipeline_artifacts",
        sa.Column("id", sa.Uuid(), server_default=uuid_default, nullable=False),
        sa.Column("pipeline_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("content", json_type, nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("agent_model", sa.String(length=100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["pipeline_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pipeline_artifacts_artifact_type"), "pipeline_artifacts", ["artifact_type"], unique=False
    )
    op.create_index(
        op.f("ix_pipeline_artifacts_pipeline_run_id"), "pipeline_artifacts", ["pipeline_run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pipeline_artifacts_pipeline_run_id"), table_name="pipeline_artifacts")
    op.drop_index(op.f("ix_pipeline_artifacts_artifact_type"), table_name="pipeline_artifacts")
    op.drop_table("pipeline_artifacts")
    op.drop_index(op.f("ix_pipeline_runs_status"), table_name="pipeline_runs")
    op.drop_index(op.f("ix_pipeline_runs_commit_id"), table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
