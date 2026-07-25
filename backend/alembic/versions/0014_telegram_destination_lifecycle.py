"""add Telegram destination and proxy lifecycle

Revision ID: 0014_telegram_destination_lifecycle
Revises: 0013_generic_llm_providers
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_telegram_destination_lifecycle"
down_revision: str | None = "0013_generic_llm_providers"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "telegram_proxy_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("proxy_type", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username_secret_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("password_secret_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reachability_status", sa.Text(), server_default="unchecked", nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("proxy_type IN ('http_connect', 'socks5')", name="ck_telegram_proxy_type"),
        sa.CheckConstraint("port BETWEEN 1 AND 65535", name="ck_telegram_proxy_port"),
        sa.CheckConstraint(
            "reachability_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
            name="ck_telegram_proxy_reachability",
        ),
        sa.ForeignKeyConstraint(["username_secret_id"], ["encrypted_secrets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["password_secret_id"], ["encrypted_secrets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_telegram_proxy_profiles_name"),
        sa.UniqueConstraint("username_secret_id", name="uq_telegram_proxy_username_secret"),
        sa.UniqueConstraint("password_secret_id", name="uq_telegram_proxy_password_secret"),
    )

    op.add_column("destinations", sa.Column("canonical_target", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("target_type", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("secret_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("destinations", sa.Column("proxy_profile_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "destinations", sa.Column("proxy_health_status", sa.Text(), server_default="unchecked", nullable=False)
    )
    op.add_column(
        "destinations", sa.Column("telegram_health_status", sa.Text(), server_default="unchecked", nullable=False)
    )
    op.add_column("destinations", sa.Column("bot_health_status", sa.Text(), server_default="unchecked", nullable=False))
    op.add_column(
        "destinations", sa.Column("target_health_status", sa.Text(), server_default="unchecked", nullable=False)
    )
    op.add_column(
        "destinations", sa.Column("administrator_status", sa.Text(), server_default="unchecked", nullable=False)
    )
    op.add_column("destinations", sa.Column("failure_code", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("verified_bot_id", sa.BigInteger(), nullable=True))
    op.add_column("destinations", sa.Column("verified_bot_username", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("verified_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("destinations", sa.Column("verified_chat_title", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("verified_chat_type", sa.Text(), nullable=True))
    op.add_column("destinations", sa.Column("ownership", sa.Text(), server_default="operator_managed", nullable=False))
    op.create_foreign_key(
        "fk_destinations_secret_id", "destinations", "encrypted_secrets", ["secret_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_destinations_proxy_profile_id",
        "destinations",
        "telegram_proxy_profiles",
        ["proxy_profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_destination_target_type",
        "destinations",
        "target_type IS NULL OR target_type IN ('username', 'numeric_id', 'legacy')",
    )
    op.create_check_constraint(
        "ck_destination_proxy_health",
        "destinations",
        "proxy_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy', 'direct')",
    )
    op.create_check_constraint(
        "ck_destination_telegram_health",
        "destinations",
        "telegram_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
    )
    op.create_check_constraint(
        "ck_destination_bot_health",
        "destinations",
        "bot_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
    )
    op.create_check_constraint(
        "ck_destination_target_health",
        "destinations",
        "target_health_status IN ('unchecked', 'checking', 'healthy', 'unhealthy')",
    )
    op.create_check_constraint(
        "ck_destination_administrator_status",
        "destinations",
        "administrator_status IN ('unchecked', 'checking', 'administrator', 'not_administrator')",
    )
    op.create_check_constraint(
        "ck_destination_ownership",
        "destinations",
        "ownership IN ('system_managed', 'operator_managed')",
    )
    op.create_unique_constraint(
        "uq_destination_platform_canonical_target", "destinations", ["platform", "canonical_target"]
    )
    op.create_unique_constraint("uq_destination_secret_id", "destinations", ["secret_id"])
    op.create_index("ix_destinations_proxy_profile_id", "destinations", ["proxy_profile_id"])

    op.create_table(
        "telegram_destination_migration_issues",
        sa.Column("destination_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issue_code", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["destination_id"], ["destinations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("destination_id", "issue_code"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO telegram_destination_migration_issues (destination_id, issue_code)
            SELECT id, 'auto_publish_review_required'
            FROM destinations
            WHERE platform = 'telegram' AND COALESCE((settings->>'allow_auto_publish')::boolean, false)
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH normalized AS (
                SELECT id,
                       CASE
                           WHEN btrim(target_ref) ~ '^@[A-Za-z][A-Za-z0-9_]{4,31}$'
                               THEN lower(btrim(target_ref))
                           WHEN btrim(target_ref) ~ '^-?(0|[1-9][0-9]*)$'
                               THEN (btrim(target_ref)::numeric)::text
                           ELSE NULL
                       END AS canonical,
                       CASE
                           WHEN btrim(target_ref) ~ '^@[A-Za-z][A-Za-z0-9_]{4,31}$' THEN 'username'
                           WHEN btrim(target_ref) ~ '^-?(0|[1-9][0-9]*)$' THEN 'numeric_id'
                           ELSE 'legacy'
                       END AS kind
                FROM destinations
                WHERE platform = 'telegram'
            ), ranked AS (
                SELECT id, canonical, kind,
                       row_number() OVER (PARTITION BY canonical ORDER BY id) AS ordinal
                FROM normalized
            )
            UPDATE destinations AS destination
            SET canonical_target = CASE WHEN ranked.canonical IS NOT NULL AND ranked.ordinal = 1
                                        THEN ranked.canonical ELSE NULL END,
                target_type = CASE WHEN ranked.canonical IS NOT NULL AND ranked.ordinal = 1
                                   THEN ranked.kind ELSE 'legacy' END,
                enabled = false,
                settings = destination.settings - 'allow_auto_publish'
            FROM ranked
            WHERE destination.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO telegram_destination_migration_issues (destination_id, issue_code)
            SELECT id, 'credential_import_required'
            FROM destinations
            WHERE platform = 'telegram'
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO telegram_destination_migration_issues (destination_id, issue_code)
            SELECT id, 'target_normalization_review_required'
            FROM destinations
            WHERE platform = 'telegram' AND canonical_target IS NULL AND target_type = 'legacy'
            ON CONFLICT DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("telegram_destination_migration_issues")
    op.drop_index("ix_destinations_proxy_profile_id", table_name="destinations")
    op.drop_constraint("uq_destination_secret_id", "destinations", type_="unique")
    op.drop_constraint("uq_destination_platform_canonical_target", "destinations", type_="unique")
    op.drop_constraint("ck_destination_ownership", "destinations", type_="check")
    op.drop_constraint("ck_destination_administrator_status", "destinations", type_="check")
    op.drop_constraint("ck_destination_target_health", "destinations", type_="check")
    op.drop_constraint("ck_destination_bot_health", "destinations", type_="check")
    op.drop_constraint("ck_destination_telegram_health", "destinations", type_="check")
    op.drop_constraint("ck_destination_proxy_health", "destinations", type_="check")
    op.drop_constraint("ck_destination_target_type", "destinations", type_="check")
    op.drop_constraint("fk_destinations_proxy_profile_id", "destinations", type_="foreignkey")
    op.drop_constraint("fk_destinations_secret_id", "destinations", type_="foreignkey")
    for column in (
        "ownership",
        "verified_chat_type",
        "verified_chat_title",
        "verified_chat_id",
        "verified_bot_username",
        "verified_bot_id",
        "failure_code",
        "administrator_status",
        "target_health_status",
        "bot_health_status",
        "telegram_health_status",
        "proxy_health_status",
        "proxy_profile_id",
        "secret_id",
        "target_type",
        "canonical_target",
    ):
        op.drop_column("destinations", column)
    op.drop_table("telegram_proxy_profiles")
