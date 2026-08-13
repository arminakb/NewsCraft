"""add versioned Automation definitions and legacy projections

Revision ID: 0027_versioned_automations
Revises: 0026_remove_operator_sessions
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0027_versioned_automations"
down_revision = "0026_remove_operator_sessions"
branch_labels = None
depends_on = None


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_graph(route: Mapping[str, Any], prompt_version_id: uuid.UUID, checksum: str) -> dict[str, object]:
    filters = dict(cast(dict[str, object], route["content_filters"] or {}))
    trigger: dict[str, object] = {
        "id": "trigger-1",
        "type": "telegram_new_item",
        "config": {
            "source_id": str(route["source_id"]),
            "access_mode": route["access_mode"],
            "poll_interval_seconds": route["poll_interval_seconds"],
        },
    }
    nodes: list[dict[str, object]] = [trigger]
    edges: list[dict[str, str]] = []
    previous_id = "trigger-1"
    previous_port = "story"

    filter_config = {
        key: filters[key]
        for key in ("include_terms", "exclude_terms", "min_text_characters", "require_media")
        if key in filters
    }
    if filter_config:
        nodes.append({"id": "filter-1", "type": "filter_content", "config": filter_config})
        edges.append(
            {
                "source_node_id": previous_id,
                "source_port": previous_port,
                "target_node_id": "filter-1",
                "target_port": "story",
            }
        )
        previous_id, previous_port = "filter-1", "accepted"

    research_profile_id = filters.get("research_provider_profile_id")
    if route["research_mode"] != "off" and research_profile_id:
        nodes.append(
            {
                "id": "research-1",
                "type": "research",
                "config": {
                    "provider_profile_id": str(research_profile_id),
                    "mode": route["research_mode"],
                },
            }
        )
        edges.append(
            {
                "source_node_id": previous_id,
                "source_port": previous_port,
                "target_node_id": "research-1",
                "target_port": "story",
            }
        )
        previous_id, previous_port = "research-1", "story"

    generate_config: dict[str, object] = {
        "editorial_profile_id": str(route["brand_profile_id"]),
        "provider_profile_id": str(route["ai_provider_profile_id"]),
        "prompt_template_version_id": str(prompt_version_id),
        "prompt_checksum_sha256": checksum,
        "media_policy": route["media_policy"],
        "attribution_policy": route["attribution_policy"],
    }
    if filters.get("model"):
        generate_config["model"] = filters["model"]
    if route["custom_footer"]:
        generate_config["custom_footer"] = route["custom_footer"]
    nodes.append({"id": "generate-1", "type": "generate_telegram", "config": generate_config})
    edges.append(
        {
            "source_node_id": previous_id,
            "source_port": previous_port,
            "target_node_id": "generate-1",
            "target_port": "story",
        }
    )
    nodes.append({"id": "review-1", "type": "human_review", "config": {}})
    edges.append(
        {
            "source_node_id": "generate-1",
            "source_port": "draft",
            "target_node_id": "review-1",
            "target_port": "draft",
        }
    )
    nodes.append(
        {
            "id": "publish-1",
            "type": "telegram_publish",
            "config": {
                "destination_id": str(route["destination_id"]),
                "quiet_hours": route["quiet_hours"] or None,
                "retry_policy": route["retry_policy"] or {},
            },
        }
    )
    edges.append(
        {
            "source_node_id": "review-1",
            "source_port": "approved",
            "target_node_id": "publish-1",
            "target_port": "draft",
        }
    )
    layout = {node["id"]: {"x": 80 + index * 260, "y": 120} for index, node in enumerate(nodes)}
    return {
        "schema_version": 1,
        "entry_node_id": "trigger-1",
        "nodes": sorted(nodes, key=lambda item: str(item["id"])),
        "edges": sorted(
            edges,
            key=lambda item: (
                item["source_node_id"],
                item["source_port"],
                item["target_node_id"],
                item["target_port"],
            ),
        ),
        "output_node_ids": ["publish-1"],
        "metadata": {"layout": dict(sorted(layout.items()))},
    }


def _resolve_prompt(connection: sa.Connection, route: Mapping[str, Any]) -> tuple[uuid.UUID, str]:
    prompt_id = route["prompt_template_version_id"]
    if route["prompt_policy"] == "follow_active":
        active = connection.execute(
            sa.text(
                "SELECT v.id, v.checksum_sha256 "
                "FROM prompt_template_versions v "
                "JOIN prompt_templates t ON t.id = v.prompt_template_id "
                "WHERE t.purpose_key = 'telegram_rewrite' AND v.is_active IS TRUE "
                "ORDER BY v.version DESC LIMIT 1"
            )
        ).mappings().first()
        if active is not None:
            return active["id"], active["checksum_sha256"]
    pinned = connection.execute(
        sa.text("SELECT id, checksum_sha256 FROM prompt_template_versions WHERE id = :id"),
        {"id": prompt_id},
    ).mappings().one()
    return pinned["id"], pinned["checksum_sha256"]


def _backfill_legacy_routes() -> None:
    connection = op.get_bind()
    routes = connection.execute(sa.text("SELECT * FROM automation_routes ORDER BY id")).mappings().all()
    for route in routes:
        automation_id = route["id"]
        version_id = uuid.uuid4()
        route_data = cast(Mapping[str, Any], route)
        prompt_version_id, checksum = _resolve_prompt(connection, route_data)
        graph = _canonical_graph(route_data, prompt_version_id, checksum)
        graph_json = _json(graph)
        graph_hash = hashlib.sha256(graph_json.encode("utf-8")).hexdigest()
        if route["enabled"] and route["paused_at"]:
            lifecycle = "paused"
        elif route["enabled"]:
            lifecycle = "active"
        else:
            lifecycle = "inactive"
        connection.execute(
            sa.text(
                "INSERT INTO automations "
                "(id, name, description, lifecycle, owner_type, owner_id, revision, created_at, updated_at) "
                "VALUES (:id, :name, :description, :lifecycle, 'legacy_migrated', 'migration:0027', 1, "
                ":created_at, :updated_at)"
            ),
            {
                "id": automation_id,
                "name": route["name"],
                "description": "Migrated Telegram automation route",
                "lifecycle": lifecycle,
                "created_at": route["created_at"],
                "updated_at": route["updated_at"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO automation_versions "
                "(id, automation_id, version, schema_version, graph, graph_hash, compiler_version, compiled_plan, "
                "validation_summary, creation_actor_type, creation_actor_id, creation_reason, created_at) "
                "VALUES (:id, :automation_id, 1, 1, CAST(:graph AS jsonb), :graph_hash, 'legacy-route-v1', "
                "CAST(:compiled_plan AS jsonb), CAST(:validation_summary AS jsonb), 'internal_service', "
                "'migration:0027', :creation_reason, :created_at)"
            ),
            {
                "id": version_id,
                "automation_id": automation_id,
                "graph": graph_json,
                "graph_hash": graph_hash,
                "compiled_plan": _json(
                    {
                        "compiler_version": "legacy-route-v1",
                        "projection_type": "telegram_route",
                        "route_id": str(automation_id),
                    }
                ),
                "validation_summary": _json(
                    {
                        "valid": False,
                        "graph_hash": graph_hash,
                        "findings": [
                            {
                                "code": "automation_validation_required",
                                "severity": "warning",
                                "message": "Legacy backfill requires current resource-readiness validation.",
                                "recovery_action": "Validate the migrated workflow before changing activation.",
                            }
                        ],
                        "scope": "legacy_backfill",
                        "resource_readiness": "not_checked",
                        "legacy_prompt_policy": route["prompt_policy"],
                    }
                ),
                "creation_reason": f"legacy route backfill; prompt_policy={route['prompt_policy']}",
                "created_at": route["created_at"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE automations SET active_version_id = :active_version_id, draft_version_id = :draft_version_id "
                "WHERE id = :id"
            ),
            {
                "id": automation_id,
                "active_version_id": version_id if route["enabled"] else None,
                "draft_version_id": version_id,
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO automation_runtime_projections "
                "(automation_id, automation_version_id, route_id, projection_type, created_at, updated_at) "
                "VALUES (:automation_id, :version_id, :route_id, 'telegram_route', :created_at, :updated_at)"
            ),
            {
                "automation_id": automation_id,
                "version_id": version_id,
                "route_id": automation_id,
                "created_at": route["created_at"],
                "updated_at": route["updated_at"],
            },
        )


def upgrade() -> None:
    op.create_table(
        "automations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lifecycle", sa.Text(), server_default="inactive", nullable=False),
        sa.Column("owner_type", sa.Text(), server_default="operator_managed", nullable=False),
        sa.Column("owner_id", sa.Text(), server_default="local-owner", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("activation_idempotency_key", sa.Text(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "lifecycle IN ('inactive', 'active', 'paused', 'archived')",
            name="ck_automations_lifecycle",
        ),
        sa.CheckConstraint(
            "owner_type IN ('system_managed', 'operator_managed', 'legacy_migrated')",
            name="ck_automations_owner_type",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_automations_revision"),
        sa.CheckConstraint(
            "(lifecycle = 'archived') = (archived_at IS NOT NULL)",
            name="ck_automations_archived_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_automations_idempotency_key"),
    )
    op.create_index("ix_automations_lifecycle_updated", "automations", ["lifecycle", sa.text("updated_at DESC")])

    op.create_table(
        "automation_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("graph_hash", sa.Text(), nullable=False),
        sa.Column("compiler_version", sa.Text(), nullable=True),
        sa.Column("compiled_plan", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "validation_summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("creation_actor_type", sa.Text(), nullable=False),
        sa.Column("creation_actor_id", sa.Text(), nullable=False),
        sa.Column("creation_reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_automation_versions_version"),
        sa.CheckConstraint("schema_version = 1", name="ck_automation_versions_schema_version"),
        sa.CheckConstraint("char_length(graph_hash) = 64", name="ck_automation_versions_graph_hash"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "id", name="uq_automation_versions_automation_id"),
        sa.UniqueConstraint("automation_id", "version", name="uq_automation_versions_number"),
        sa.UniqueConstraint("automation_id", "idempotency_key", name="uq_automation_versions_idempotency"),
    )
    op.create_index(
        "ix_automation_versions_automation_created",
        "automation_versions",
        ["automation_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_automation_versions_automation_graph_hash",
        "automation_versions",
        ["automation_id", "graph_hash"],
    )
    op.create_foreign_key(
        "fk_automations_active_version",
        "automations",
        "automation_versions",
        ["id", "active_version_id"],
        ["automation_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_automations_draft_version",
        "automations",
        "automation_versions",
        ["id", "draft_version_id"],
        ["automation_id", "id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "automation_runtime_projections",
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("projection_type", sa.Text(), server_default="telegram_route", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "projection_type IN ('telegram_route')",
            name="ck_automation_runtime_projections_type",
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["automation_id", "automation_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automation_runtime_projections_owned_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["route_id"], ["automation_routes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("automation_id"),
        sa.UniqueConstraint("route_id", name="uq_automation_runtime_projections_route_id"),
    )
    op.create_index(
        "ix_automation_runtime_projections_version",
        "automation_runtime_projections",
        ["automation_version_id"],
    )

    op.create_table(
        "automation_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_key", sa.Text(), nullable=False),
        sa.Column("seed_version", sa.Integer(), nullable=False),
        sa.Column("ownership", sa.Text(), server_default="system_managed", nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("complexity", sa.Text(), nullable=False),
        sa.Column("graph_seed", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "capability_requirements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("seed_version >= 1", name="ck_automation_templates_seed_version"),
        sa.CheckConstraint(
            "ownership IN ('system_managed', 'operator_managed')",
            name="ck_automation_templates_ownership",
        ),
        sa.CheckConstraint(
            "complexity IN ('starter', 'intermediate', 'advanced')",
            name="ck_automation_templates_complexity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seed_key", "seed_version", name="uq_automation_templates_seed_version"),
    )
    op.create_index(
        "ix_automation_templates_active",
        "automation_templates",
        ["seed_key"],
        postgresql_where=sa.text("archived_at IS NULL"),
    )

    op.create_table(
        "automation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("root_workflow_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger_kind", sa.Text(), nullable=False),
        sa.Column("trigger_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("current_node_id", sa.Text(), nullable=True),
        sa.Column("resource_snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("safe_error_code", sa.Text(), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "trigger_kind IN ('manual', 'schedule', 'telegram_new_item', 'legacy')",
            name="ck_automation_runs_trigger_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'waiting_for_review', 'succeeded', 'warning', "
            "'failed', 'cancelled')",
            name="ck_automation_runs_status",
        ),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["automation_id", "automation_version_id"],
            ["automation_versions.automation_id", "automation_versions.id"],
            name="fk_automation_runs_owned_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["root_workflow_job_id"], ["workflow_jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("root_workflow_job_id", name="uq_automation_runs_root_workflow_job_id"),
    )
    op.create_index(
        "ix_automation_runs_automation_created", "automation_runs", ["automation_id", sa.text("created_at DESC")]
    )
    op.create_index(
        "ix_automation_runs_status_created", "automation_runs", ["status", sa.text("created_at DESC")]
    )
    op.create_index("ix_automation_runs_version", "automation_runs", ["automation_version_id"])
    op.create_index(
        "ix_automation_runs_dry_run_created", "automation_runs", ["dry_run", sa.text("created_at DESC")]
    )

    op.create_table(
        "automation_node_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("workflow_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("automation_dispatch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("platform_variant_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publish_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("output_summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("retry_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("safe_error_code", sa.Text(), nullable=True),
        sa.Column("safe_error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("attempt >= 1", name="ck_automation_node_runs_attempt"),
        sa.CheckConstraint(
            "status IN ('pending', 'queued', 'running', 'succeeded', 'warning', 'failed', 'skipped', "
            "'waiting_for_review')",
            name="ck_automation_node_runs_status",
        ),
        sa.ForeignKeyConstraint(["automation_run_id"], ["automation_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_job_id"], ["workflow_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["automation_dispatch_id"], ["automation_dispatches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generation_run_id"], ["generation_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["platform_variant_revision_id"], ["platform_variant_revisions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["publish_job_id"], ["publish_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_run_id", "node_id", "attempt", name="uq_automation_node_runs_attempt"),
    )
    for name, columns in (
        ("ix_automation_node_runs_run_status", ["automation_run_id", "status"]),
        ("ix_automation_node_runs_workflow_job", ["workflow_job_id"]),
        ("ix_automation_node_runs_dispatch", ["automation_dispatch_id"]),
        ("ix_automation_node_runs_research", ["research_run_id"]),
        ("ix_automation_node_runs_generation", ["generation_run_id"]),
        ("ix_automation_node_runs_revision", ["platform_variant_revision_id"]),
        ("ix_automation_node_runs_publish_job", ["publish_job_id"]),
        ("ix_automation_node_runs_publication", ["publication_id"]),
    ):
        op.create_index(name, "automation_node_runs", columns)

    op.add_column("workflow_jobs", sa.Column("automation_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("workflow_jobs", sa.Column("automation_node_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_workflow_jobs_automation_run_id",
        "workflow_jobs",
        "automation_runs",
        ["automation_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflow_jobs_automation_node_run_id",
        "workflow_jobs",
        "automation_node_runs",
        ["automation_node_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_workflow_jobs_automation_run", "workflow_jobs", ["automation_run_id"])
    op.create_index("ix_workflow_jobs_automation_node_run", "workflow_jobs", ["automation_node_run_id"])

    op.add_column(
        "automation_dispatches", sa.Column("automation_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "automation_dispatches", sa.Column("automation_node_run_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_automation_dispatches_automation_run_id",
        "automation_dispatches",
        "automation_runs",
        ["automation_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_automation_dispatches_automation_node_run_id",
        "automation_dispatches",
        "automation_node_runs",
        ["automation_node_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_automation_dispatch_run", "automation_dispatches", ["automation_run_id"])
    op.create_index("ix_automation_dispatch_node_run", "automation_dispatches", ["automation_node_run_id"])

    _backfill_legacy_routes()

    op.execute(
        "CREATE FUNCTION newscraft_reject_automation_version_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'automation_version_immutable' USING ERRCODE = 'integrity_constraint_violation'; "
        "END; $$"
    )
    op.execute(
        "CREATE TRIGGER trg_automation_versions_immutable BEFORE UPDATE OR DELETE ON automation_versions "
        "FOR EACH ROW EXECUTE FUNCTION newscraft_reject_automation_version_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_automation_versions_immutable ON automation_versions")
    op.execute("DROP FUNCTION IF EXISTS newscraft_reject_automation_version_mutation()")

    op.drop_index("ix_automation_dispatch_node_run", table_name="automation_dispatches")
    op.drop_index("ix_automation_dispatch_run", table_name="automation_dispatches")
    op.drop_constraint(
        "fk_automation_dispatches_automation_node_run_id", "automation_dispatches", type_="foreignkey"
    )
    op.drop_constraint("fk_automation_dispatches_automation_run_id", "automation_dispatches", type_="foreignkey")
    op.drop_column("automation_dispatches", "automation_node_run_id")
    op.drop_column("automation_dispatches", "automation_run_id")

    op.drop_index("ix_workflow_jobs_automation_node_run", table_name="workflow_jobs")
    op.drop_index("ix_workflow_jobs_automation_run", table_name="workflow_jobs")
    op.drop_constraint("fk_workflow_jobs_automation_node_run_id", "workflow_jobs", type_="foreignkey")
    op.drop_constraint("fk_workflow_jobs_automation_run_id", "workflow_jobs", type_="foreignkey")
    op.drop_column("workflow_jobs", "automation_node_run_id")
    op.drop_column("workflow_jobs", "automation_run_id")

    op.drop_table("automation_node_runs")
    op.drop_table("automation_runs")
    op.drop_table("automation_templates")
    op.drop_table("automation_runtime_projections")
    op.drop_constraint("fk_automations_draft_version", "automations", type_="foreignkey")
    op.drop_constraint("fk_automations_active_version", "automations", type_="foreignkey")
    op.drop_table("automation_versions")
    op.drop_table("automations")
