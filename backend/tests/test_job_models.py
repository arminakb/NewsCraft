from app.db.model_registry import Base
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus


def test_job_enum_values_are_stable_cross_release_contracts():
    assert [value.value for value in JobStatus] == [
        "queued",
        "running",
        "succeeded",
        "failed",
        "needs_review",
        "cancelled",
    ]
    assert [value.value for value in JobErrorClass] == ["retryable", "needs_review", "permanent"]
    assert [value.value for value in JobOrigin] == ["manual", "scheduler", "automation", "retry"]


def test_workflow_job_columns_support_leases_retries_progress_and_attention():
    columns = set(Base.metadata.tables["workflow_jobs"].columns.keys())
    assert {
        "job_type",
        "status",
        "payload",
        "result",
        "priority",
        "idempotency_key",
        "origin",
        "pause_sensitive",
        "scheduled_for",
        "attempt_count",
        "max_attempts",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "progress",
        "progress_message",
        "error_class",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    } == columns - {"id"}


def test_all_job_engine_tables_have_the_locked_columns():
    expected = {
        "workflow_events": {
            "id",
            "workflow_job_id",
            "event_type",
            "actor",
            "event_data",
            "created_at",
        },
        "workflow_schedules": {
            "id",
            "schedule_key",
            "source_id",
            "name",
            "job_type",
            "payload",
            "schedule_kind",
            "timezone",
            "local_time",
            "interval_minutes",
            "next_run_at",
            "enabled",
            "pause_sensitive",
            "last_enqueued_at",
            "created_at",
            "updated_at",
        },
        "automation_controls": {
            "id",
            "global_pause",
            "dry_run",
            "pause_reason",
            "paused_at",
            "updated_at",
        },
    }

    for table_name, columns in expected.items():
        assert columns == set(Base.metadata.tables[table_name].columns.keys())


def test_source_and_publish_models_link_to_scheduler_and_queue():
    assert "next_fetch_at" in Base.metadata.tables["sources"].columns
    assert "workflow_job_id" in Base.metadata.tables["publish_jobs"].columns


def test_runtime_heartbeat_supports_multiple_capability_workers():
    table = Base.metadata.tables["runtime_heartbeats"]

    assert set(table.columns.keys()) == {
        "component_id",
        "component_type",
        "capabilities",
        "observed_at",
        "metadata",
    }
    assert table.c.component_id.primary_key is True
    assert table.c.observed_at.nullable is False


def test_job_engine_metadata_has_locked_indexes_and_constraints():
    index_names = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert {
        "ix_workflow_jobs_claim",
        "ix_workflow_jobs_lease_expiry",
        "ix_workflow_jobs_attention",
        "ix_workflow_events_job_created",
        "ix_workflow_events_created",
        "ix_workflow_schedules_due",
        "ix_runtime_heartbeats_type_observed",
        "ix_sources_next_fetch_at",
    }.issubset(index_names)

    workflow_jobs = Base.metadata.tables["workflow_jobs"]
    constraint_names = {constraint.name for constraint in workflow_jobs.constraints}
    assert "ck_workflow_jobs_progress" in constraint_names
    assert "uq_workflow_jobs_idempotency_key" in constraint_names

    publish_job_targets = {
        foreign_key.target_fullname
        for foreign_key in Base.metadata.tables["publish_jobs"].c.workflow_job_id.foreign_keys
    }
    assert publish_job_targets == {"workflow_jobs.id"}


def test_runtime_metadata_attribute_maps_to_reserved_database_column():
    from app.jobs.models import RuntimeHeartbeat

    assert RuntimeHeartbeat.runtime_metadata.property.columns[0].name == "metadata"
