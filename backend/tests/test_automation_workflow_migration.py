from pathlib import Path

from app.db import model_registry as _model_registry  # noqa: F401
from app.db.base import Base

MIGRATION = Path("alembic/versions/0027_versioned_automations.py")
RETIREMENT_MIGRATION = Path("alembic/versions/0031_retire_obsolete_workflow_nodes.py")


def test_versioned_automation_migration_is_additive_and_follows_current_head():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0027_versioned_automations"' in source
    assert 'down_revision = "0026_remove_operator_sessions"' in source
    for table in (
        "automations",
        "automation_versions",
        "automation_templates",
        "automation_runtime_projections",
        "automation_runs",
        "automation_node_runs",
    ):
        assert f'"{table}"' in source
    assert 'op.drop_table("automation_routes")' not in source
    assert 'op.drop_table("automation_dispatches")' not in source


def test_legacy_backfill_preserves_route_identity_and_pins_prompt_snapshot():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'automation_id = route["id"]' in source
    assert '"route_id": automation_id' in source
    assert 'route["prompt_policy"] == "follow_active"' in source
    assert "prompt_checksum_sha256" in source
    assert 'active_version_id": version_id if route["enabled"] else None' in source
    for protected_field in ("cursor_state", "next_poll_at", "last_polled_at", "backfill_limit"):
        assert f"UPDATE automation_routes SET {protected_field}" not in source


def test_versions_are_database_immutable_and_run_links_are_explicit():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "trg_automation_versions_immutable" in source
    assert "automation_version_immutable" in source
    assert "automation_run_id" in source
    assert "automation_node_run_id" in source
    assert "root_workflow_job_id" in source
    assert "fk_automation_runtime_projections_owned_version" in source
    assert "fk_automation_runs_owned_version" in source


def test_versioned_automation_models_are_registered_with_safe_columns():
    tables = Base.metadata.tables

    for name in (
        "automations",
        "automation_versions",
        "automation_templates",
        "automation_runtime_projections",
        "automation_runs",
        "automation_node_runs",
    ):
        assert name in tables
    graph_columns = set(tables["automation_versions"].columns.keys())
    assert {"graph", "graph_hash", "validation_summary", "compiled_plan"}.issubset(graph_columns)
    assert {"secret", "credential", "token", "prompt_body"}.isdisjoint(graph_columns)
    assert {"automation_run_id", "automation_node_run_id"}.issubset(tables["workflow_jobs"].columns.keys())
    assert {"automation_run_id", "automation_node_run_id"}.issubset(
        tables["automation_dispatches"].columns.keys()
    )


def test_retirement_migration_archives_template_and_pauses_unsafe_active_versions():
    source = RETIREMENT_MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0031_retire_obsolete_workflow_nodes"' in source
    assert 'down_revision = "0030_new_source_item_trigger"' in source
    assert "breaking-news-telegram" in source
    assert "jsonb_array_elements" in source
    assert "automation.active_version_id" in source
    assert "automation_routes" in source
    assert "no replacement" in source
