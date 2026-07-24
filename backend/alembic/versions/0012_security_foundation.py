"""add authorization audit and encrypted secret storage

Revision ID: 0012_security_foundation
Revises: 0011_article_collections
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0012_security_foundation"
down_revision: str | None = "0011_article_collections"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "encrypted_secrets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("octet_length(ciphertext) >= 16", name="ck_encrypted_secrets_ciphertext_length"),
        sa.CheckConstraint("octet_length(nonce) = 12", name="ck_encrypted_secrets_nonce_length"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_type", "owner_id", "purpose", name="uq_encrypted_secret_owner_purpose"),
    )
    op.create_index("ix_encrypted_secrets_key_version", "encrypted_secrets", ["key_version"])

    op.create_table(
        "security_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("required_scope", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('attempted', 'succeeded', 'rejected', 'failed')",
            name="ck_security_audit_outcome",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_security_audit_created", "security_audit_events", [sa.text("created_at DESC")])
    op.create_index(
        "ix_security_audit_actor_created",
        "security_audit_events",
        ["actor_type", "actor_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_security_audit_resource_created",
        "security_audit_events",
        ["resource_type", "resource_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_security_audit_resource_created", table_name="security_audit_events")
    op.drop_index("ix_security_audit_actor_created", table_name="security_audit_events")
    op.drop_index("ix_security_audit_created", table_name="security_audit_events")
    op.drop_table("security_audit_events")
    op.drop_index("ix_encrypted_secrets_key_version", table_name="encrypted_secrets")
    op.drop_table("encrypted_secrets")
