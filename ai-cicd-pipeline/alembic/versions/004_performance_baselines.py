"""Add performance_baselines table.

Revision ID: 004_performance_baselines
Revises: 003_correlation_trace
"""

from alembic import op
import sqlalchemy as sa

revision = "004_performance_baselines"
down_revision = "003_correlation_trace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "performance_baselines" in inspector.get_table_names():
        return
    op.create_table(
        "performance_baselines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=False),
        sa.Column("profile", sa.String(length=32), nullable=False, server_default="standard"),
        sa.Column("environment", sa.String(length=64), nullable=False, server_default="staging"),
        sa.Column("p95_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("error_rate_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_performance_baselines_repo", "performance_baselines", ["repo_full_name"])


def downgrade() -> None:
    op.drop_index("ix_performance_baselines_repo", table_name="performance_baselines")
    op.drop_table("performance_baselines")
