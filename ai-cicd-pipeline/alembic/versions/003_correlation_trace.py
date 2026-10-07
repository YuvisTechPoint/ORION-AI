"""Add correlation_id and trace_id to pipeline_runs.

Revision ID: 003_correlation_trace
Revises: 002_webhook_deliveries
Create Date: 2026-10-06
"""

from alembic import op
import sqlalchemy as sa

revision = "003_correlation_trace"
down_revision = "002_webhook_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_runs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("pipeline_runs")}
    if "correlation_id" not in cols:
        op.add_column("pipeline_runs", sa.Column("correlation_id", sa.String(length=64), nullable=True))
        op.create_index("ix_pipeline_runs_correlation_id", "pipeline_runs", ["correlation_id"], unique=False)
    if "trace_id" not in cols:
        op.add_column("pipeline_runs", sa.Column("trace_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "pipeline_runs" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("pipeline_runs")}
    if "correlation_id" in cols:
        op.drop_index("ix_pipeline_runs_correlation_id", table_name="pipeline_runs")
        op.drop_column("pipeline_runs", "correlation_id")
    if "trace_id" in cols:
        op.drop_column("pipeline_runs", "trace_id")
