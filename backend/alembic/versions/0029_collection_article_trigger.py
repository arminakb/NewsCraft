"""add Feed collection article trigger runs

Revision ID: 0029_collection_article_trigger
Revises: 0028_automation_execution
"""

from __future__ import annotations

from alembic import op

revision = "0029_collection_article_trigger"
down_revision = "0028_automation_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_automation_runs_trigger_kind", "automation_runs", type_="check")
    op.create_check_constraint(
        "ck_automation_runs_trigger_kind",
        "automation_runs",
        "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'collection_article_added', 'legacy')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_automation_runs_trigger_kind", "automation_runs", type_="check")
    op.create_check_constraint(
        "ck_automation_runs_trigger_kind",
        "automation_runs",
        "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'legacy')",
    )
