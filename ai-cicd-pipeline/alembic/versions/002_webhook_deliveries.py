"""webhook delivery ledger

Revision ID: 002_webhook_deliveries
Revises: 001_initial
Create Date: 2026-10-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002_webhook_deliveries"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "webhook_deliveries" in existing:
        return

    is_pg = bind.dialect.name == "postgresql"
    now = sa.text("now()") if is_pg else sa.text("CURRENT_TIMESTAMP")
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    uuid_type = sa.Uuid() if is_pg else sa.String(36)

    op.create_table(
        "webhook_deliveries",
        sa.Column("delivery_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("repo_full_name", sa.String(length=255), nullable=True),
        sa.Column("commit_id", sa.String(length=40), nullable=True),
        sa.Column("pipeline_run_id", uuid_type, nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'accepted'")),
        sa.Column("response_body", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=now, nullable=False),
        sa.PrimaryKeyConstraint("delivery_id"),
    )
    op.create_index(op.f("ix_webhook_deliveries_event_type"), "webhook_deliveries", ["event_type"], unique=False)
    op.create_index(
        op.f("ix_webhook_deliveries_repo_full_name"), "webhook_deliveries", ["repo_full_name"], unique=False
    )
    op.create_index(op.f("ix_webhook_deliveries_commit_id"), "webhook_deliveries", ["commit_id"], unique=False)
    op.create_index(
        op.f("ix_webhook_deliveries_pipeline_run_id"), "webhook_deliveries", ["pipeline_run_id"], unique=False
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "webhook_deliveries" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_index(op.f("ix_webhook_deliveries_pipeline_run_id"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_commit_id"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_repo_full_name"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_event_type"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
