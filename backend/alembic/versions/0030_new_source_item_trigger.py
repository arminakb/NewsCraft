"""add New Source Item trigger runs

Revision ID: 0030_new_source_item_trigger
Revises: 0029_collection_article_trigger
"""

from __future__ import annotations

from alembic import op

revision = "0030_new_source_item_trigger"
down_revision = "0029_collection_article_trigger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_automation_runs_trigger_kind", "automation_runs", type_="check")
    op.create_check_constraint(
        "ck_automation_runs_trigger_kind",
        "automation_runs",
        "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'collection_article_added', "
        "'new_source_item', 'legacy')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_automation_runs_trigger_kind", "automation_runs", type_="check")
    op.create_check_constraint(
        "ck_automation_runs_trigger_kind",
        "automation_runs",
        "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'collection_article_added', 'legacy')",
    )
