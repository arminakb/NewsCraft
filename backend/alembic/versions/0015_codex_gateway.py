"""add Codex Gateway pairing and credential lifecycle

Revision ID: 0015_codex_gateway
Revises: 0014_telegram_destination_lifecycle
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_codex_gateway"
down_revision: str | None = "0014_telegram_destination_lifecycle"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "codex_pairing_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_prefix", sa.Text(), nullable=False),
        sa.Column("code_hash", sa.LargeBinary(), nullable=False),
        sa.Column("device_name", sa.Text(), nullable=False),
        sa.Column(
            "requested_scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_type", sa.Text(), nullable=False),
        sa.Column("created_by_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(code_hash) = 32",
            name="ck_codex_pairing_code_hash",
        ),
        sa.CheckConstraint(
            "length(code_prefix) = 12",
            name="ck_codex_pairing_code_prefix",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(requested_scopes) = 'array'",
            name="ck_codex_pairing_scopes_array",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'paired', 'cancelled', 'expired')",
            name="ck_codex_pairing_session_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_prefix"),
    )
    op.create_index(
        "ix_codex_pairing_sessions_status_expiry",
        "codex_pairing_sessions",
        ["status", "expires_at"],
    )

    op.create_table(
        "codex_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("device_name", sa.Text(), nullable=False),
        sa.Column("credential_prefix", sa.Text(), nullable=False),
        sa.Column("credential_hash", sa.LargeBinary(), nullable=False),
        sa.Column("credential_fingerprint", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pairing_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(credential_hash) = 32",
            name="ck_codex_connection_credential_hash",
        ),
        sa.CheckConstraint(
            "length(credential_prefix) = 12",
            name="ck_codex_connection_credential_prefix",
        ),
        sa.CheckConstraint(
            "length(credential_fingerprint) = 16",
            name="ck_codex_connection_fingerprint",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(scopes) = 'array'",
            name="ck_codex_connection_scopes_array",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_codex_connection_status",
        ),
        sa.ForeignKeyConstraint(
            ["pairing_session_id"],
            ["codex_pairing_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("credential_prefix"),
        sa.UniqueConstraint("pairing_session_id"),
    )
    op.create_index(
        "ix_codex_connections_status_expiry",
        "codex_connections",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_codex_connections_last_heartbeat",
        "codex_connections",
        ["last_heartbeat_at"],
    )

    op.create_table(
        "codex_rate_limit_buckets",
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(key_hash) = 32",
            name="ck_codex_rate_limit_key_hash",
        ),
        sa.CheckConstraint(
            "request_count > 0",
            name="ck_codex_rate_limit_count",
        ),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_codex_rate_limit_updated",
        "codex_rate_limit_buckets",
        ["updated_at"],
    )
    op.create_table(
        "codex_idempotency_records",
        sa.Column("key_hash", sa.LargeBinary(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "octet_length(key_hash) = 32",
            name="ck_codex_idempotency_key_hash",
        ),
        sa.PrimaryKeyConstraint("key_hash"),
    )
    op.create_index(
        "ix_codex_idempotency_created",
        "codex_idempotency_records",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_codex_idempotency_created", table_name="codex_idempotency_records")
    op.drop_table("codex_idempotency_records")
    op.drop_index("ix_codex_rate_limit_updated", table_name="codex_rate_limit_buckets")
    op.drop_table("codex_rate_limit_buckets")
    op.drop_index("ix_codex_connections_last_heartbeat", table_name="codex_connections")
    op.drop_index("ix_codex_connections_status_expiry", table_name="codex_connections")
    op.drop_table("codex_connections")
    op.drop_index(
        "ix_codex_pairing_sessions_status_expiry",
        table_name="codex_pairing_sessions",
    )
    op.drop_table("codex_pairing_sessions")
