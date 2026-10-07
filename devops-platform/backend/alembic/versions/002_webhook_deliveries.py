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

    dialect = bind.dialect.name
    uuid_type = postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    json_type = postgresql.JSONB() if dialect == "postgresql" else sa.JSON()

    op.create_table(
        "webhook_deliveries",
        sa.Column("delivery_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False, index=True),
        sa.Column("repo_url", sa.String(2048), nullable=True),
        sa.Column("pipeline_id", uuid_type, nullable=True, index=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="accepted"),
        sa.Column("response_body", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "webhook_deliveries" not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table("webhook_deliveries")
