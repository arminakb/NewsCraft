"""add telegram dispatch requests

Revision ID: 0012_telegram_dispatch_requests
Revises: 0011_telegram_post_packages
Create Date: 2026-07-09
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_telegram_dispatch_requests"
down_revision = "0011_telegram_post_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_dispatch_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("production_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "dispatch_payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["package_id"], ["telegram_post_packages.id"]),
        sa.ForeignKeyConstraint(["production_run_id"], ["content_production_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_dispatch_requests_run_created",
        "telegram_dispatch_requests",
        ["production_run_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_telegram_dispatch_requests_package", "telegram_dispatch_requests", ["package_id"])
    op.create_index("ix_telegram_dispatch_requests_status", "telegram_dispatch_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_telegram_dispatch_requests_status", table_name="telegram_dispatch_requests")
    op.drop_index("ix_telegram_dispatch_requests_package", table_name="telegram_dispatch_requests")
    op.drop_index("ix_telegram_dispatch_requests_run_created", table_name="telegram_dispatch_requests")
    op.drop_table("telegram_dispatch_requests")
