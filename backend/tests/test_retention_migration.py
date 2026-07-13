from pathlib import Path

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.db.model_registry import Base

MIGRATION = Path("alembic/versions/0009_operational_retention.py")


def _check_names(table_name: str) -> set[str | None]:
    table = Base.metadata.tables[table_name]
    return {constraint.name for constraint in table.constraints if isinstance(constraint, CheckConstraint)}


def _unique_names(table_name: str) -> set[str | None]:
    table = Base.metadata.tables[table_name]
    return {constraint.name for constraint in table.constraints if isinstance(constraint, UniqueConstraint)}


def test_retention_migration_follows_manual_publication_head_and_seeds_global_policy():
    assert MIGRATION.exists()
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0009_operational_retention"' in source
    assert 'down_revision: str | None = "0008_manual_publication_plans"' in source
    assert '"retention_policies"' in source
    assert '"retention_runs"' in source
    assert '"id": "global"' in source
    for field, default in (
        ("raw_payload_days", 30),
        ("completed_job_days", 90),
        ("attempt_metadata_days", 90),
        ("export_artifact_days", 14),
        ("unreferenced_media_days", 30),
    ):
        assert f'"{field}": {default}' in source
    assert "from app.retention" not in source


def test_retention_migration_freezes_database_guards_and_safe_downgrade():
    source = MIGRATION.read_text(encoding="utf-8")

    for name in (
        "ck_retention_policy_singleton",
        "ck_retention_policy_raw_payload_days",
        "ck_retention_policy_completed_job_days",
        "ck_retention_policy_attempt_metadata_days",
        "ck_retention_policy_export_artifact_days",
        "ck_retention_policy_unreferenced_media_days",
        "ck_retention_run_status",
        "ck_retention_run_policy_snapshot_object",
        "ck_retention_run_candidate_snapshot_array",
        "ck_retention_run_cleanup_intent_snapshot_array",
        "ck_retention_run_count_snapshot_object",
        "ck_retention_run_error_snapshot_array",
        "ck_retention_run_preview_expiry",
        "uq_retention_runs_preview_token",
        "uq_retention_runs_workflow_job_id",
        "ix_retention_runs_status_created",
        "ix_retention_runs_preview_expiry",
    ):
        assert name in source
    assert 'ForeignKey("workflow_jobs.id", ondelete="RESTRICT")' in source
    assert 'op.drop_table("retention_runs")' in source
    assert 'op.drop_table("retention_policies")' in source
    assert source.index('op.drop_table("retention_runs")') < source.index('op.drop_table("retention_policies")')


def test_retention_policy_metadata_is_a_bounded_global_singleton():
    table = Base.metadata.tables["retention_policies"]

    assert set(table.columns.keys()) == {
        "id",
        "raw_payload_days",
        "completed_job_days",
        "attempt_metadata_days",
        "export_artifact_days",
        "unreferenced_media_days",
        "created_at",
        "updated_at",
    }
    assert table.c.id.primary_key is True
    assert str(table.c.id.server_default.arg) == "'global'"
    assert {
        "ck_retention_policy_singleton",
        "ck_retention_policy_raw_payload_days",
        "ck_retention_policy_completed_job_days",
        "ck_retention_policy_attempt_metadata_days",
        "ck_retention_policy_export_artifact_days",
        "ck_retention_policy_unreferenced_media_days",
    } <= _check_names("retention_policies")

    defaults = {
        "raw_payload_days": "30",
        "completed_job_days": "90",
        "attempt_metadata_days": "90",
        "export_artifact_days": "14",
        "unreferenced_media_days": "30",
    }
    for column_name, expected in defaults.items():
        column = table.c[column_name]
        assert column.nullable is False
        assert str(column.server_default.arg) == expected


def test_retention_run_metadata_preserves_preview_and_execution_audit():
    table = Base.metadata.tables["retention_runs"]

    assert set(table.columns.keys()) == {
        "id",
        "workflow_job_id",
        "status",
        "preview_token",
        "schema_revision",
        "policy_snapshot",
        "candidate_snapshot",
        "cleanup_intent_snapshot",
        "count_snapshot",
        "error_snapshot",
        "previewed_at",
        "preview_expires_at",
        "queued_at",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }
    assert table.c.workflow_job_id.nullable is True
    workflow_job_fk = next(iter(table.c.workflow_job_id.foreign_keys))
    assert workflow_job_fk.target_fullname == "workflow_jobs.id"
    assert workflow_job_fk.ondelete == "RESTRICT"
    assert {
        "uq_retention_runs_preview_token",
        "uq_retention_runs_workflow_job_id",
    } <= _unique_names("retention_runs")

    assert str(table.c.status.server_default.arg) == "previewed"
    assert str(table.c.schema_revision.server_default.arg) == "0009_operational_retention"
    for column_name in (
        "policy_snapshot",
        "candidate_snapshot",
        "cleanup_intent_snapshot",
        "count_snapshot",
        "error_snapshot",
    ):
        assert isinstance(table.c[column_name].type, JSONB)
        assert table.c[column_name].nullable is False
    assert {
        "ck_retention_run_status",
        "ck_retention_run_policy_snapshot_object",
        "ck_retention_run_candidate_snapshot_array",
        "ck_retention_run_cleanup_intent_snapshot_array",
        "ck_retention_run_count_snapshot_object",
        "ck_retention_run_error_snapshot_array",
        "ck_retention_run_preview_expiry",
    } <= _check_names("retention_runs")
    assert table.c.preview_expires_at.nullable is False
    assert table.c.queued_at.nullable is True
    assert table.c.started_at.nullable is True
    assert table.c.finished_at.nullable is True
    assert {"ix_retention_runs_status_created", "ix_retention_runs_preview_expiry"} <= {
        index.name for index in table.indexes
    }
