"""retire Telegram workflow node types without rewriting saved graphs

Revision ID: 0031_retire_obsolete_workflow_nodes
Revises: 0030_new_source_item_trigger
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031_retire_obsolete_workflow_nodes"
down_revision = "0030_new_source_item_trigger"
branch_labels = None
depends_on = None

_RETIRED_NODE_TYPES = ("telegram_new_item", "generate_telegram")


def _retired_graph_exists(alias: str) -> str:
    values = ", ".join(f"'{value}'" for value in _RETIRED_NODE_TYPES)
    return (
        f"EXISTS (SELECT 1 FROM jsonb_array_elements({alias}.graph::jsonb -> 'nodes') AS node "
        f"WHERE node ->> 'type' IN ({values}))"
    )


def upgrade() -> None:
    # Keep the immutable template/version row as provenance, but stop exposing it as a starting point.
    op.execute(
        sa.text(
            "UPDATE automation_templates SET archived_at = COALESCE(archived_at, now()) "
            "WHERE seed_key = 'breaking-news-telegram' AND archived_at IS NULL"
        )
    )

    # Active versions with retired nodes must not continue running. Their graph stays intact so the editor can
    # show node_type_unsupported and require an explicit operator decision; no replacement is inferred.
    op.execute(
        sa.text(
            "UPDATE automations AS automation SET lifecycle = 'paused' "
            "WHERE automation.lifecycle = 'active' "
            "AND EXISTS (SELECT 1 FROM automation_versions AS version "
            "WHERE version.id = automation.active_version_id AND "
            f"{_retired_graph_exists('version')})"
        )
    )
    op.execute(
        sa.text(
            "UPDATE automation_routes AS route SET enabled = false, "
            "paused_at = COALESCE(route.paused_at, now()) "
            "FROM automation_runtime_projections AS projection "
            "JOIN automation_versions AS version ON version.id = projection.automation_version_id "
            "WHERE projection.route_id = route.id AND "
            f"{_retired_graph_exists('version')}"
        )
    )


def downgrade() -> None:
    # Restoring the archived seed is safe; paused live automations are intentionally not reactivated because the
    # migration cannot distinguish their prior lifecycle from an operator pause made after retirement.
    op.execute(
        sa.text(
            "UPDATE automation_templates SET archived_at = NULL "
            "WHERE seed_key = 'breaking-news-telegram' AND ownership = 'system_managed'"
        )
    )
