"""persist application date and time settings

Revision ID: 0024_date_time_settings
Revises: 0023_source_soft_deletion
"""

import sqlalchemy as sa

from alembic import op

revision = "0024_date_time_settings"
down_revision = "0023_source_soft_deletion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "date_time_settings",
        sa.Column("id", sa.Text(), server_default=sa.text("'global'"), nullable=False),
        sa.Column("timezone", sa.Text(), server_default=sa.text("'Asia/Tehran'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 'global'", name="ck_date_time_settings_singleton"),
        sa.CheckConstraint(
            "char_length(timezone) BETWEEN 1 AND 255 AND timezone = btrim(timezone)",
            name="ck_date_time_settings_timezone_shape",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(table, [{"id": "global", "timezone": "Asia/Tehran"}])


def downgrade() -> None:
    op.drop_table("date_time_settings")
