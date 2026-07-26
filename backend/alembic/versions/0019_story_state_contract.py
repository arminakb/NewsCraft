"""enforce story state contract

Revision ID: 0019_story_state_contract
Revises: 0018_editorial_profile_default
"""

from alembic import op

revision = "0019_story_state_contract"
down_revision = "0018_editorial_profile_default"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE stories SET status = 'inbox' WHERE status = 'open'")
    op.alter_column("stories", "status", server_default="inbox")
    op.create_check_constraint(
        "ck_stories_status",
        "stories",
        "status IN ('inbox', 'shortlisted', 'rejected', 'drafted', 'telegram_provisional')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stories_status", "stories", type_="check")
    op.alter_column("stories", "status", server_default="open")
    op.execute("UPDATE stories SET status = 'open' WHERE status = 'inbox'")
