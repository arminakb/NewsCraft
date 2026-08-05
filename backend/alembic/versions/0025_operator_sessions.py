"""add revocable local operator sessions

Revision ID: 0025_operator_sessions
Revises: 0024_date_time_settings
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0025_operator_sessions"
down_revision = "0024_date_time_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operator_sessions",
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("principal_id", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_operator_session_token_hash"),
        sa.CheckConstraint("jsonb_typeof(scopes) = 'array'", name="ck_operator_session_scopes_array"),
        sa.CheckConstraint(
            "status IN ('active', 'expired', 'revoked')",
            name="ck_operator_session_status",
        ),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(
        "ix_operator_sessions_status_expiry",
        "operator_sessions",
        ["status", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operator_sessions_status_expiry", table_name="operator_sessions")
    op.drop_table("operator_sessions")
