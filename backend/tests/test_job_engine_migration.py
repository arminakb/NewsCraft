from pathlib import Path

MIGRATION = Path("alembic/versions/0005_job_engine_and_scheduling.py")


def _migration_source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_job_engine_migration_has_stable_revision_and_all_five_tables():
    migration = _migration_source()

    assert 'revision = "0005_job_engine_and_scheduling"' in migration
    assert 'down_revision = "0004_platform_spine"' in migration
    for table_name in (
        "workflow_jobs",
        "workflow_events",
        "workflow_schedules",
        "automation_controls",
        "runtime_heartbeats",
    ):
        assert f'op.create_table(\n        "{table_name}"' in migration


def test_job_engine_migration_adds_deferred_columns_foreign_key_and_indexes():
    migration = _migration_source()

    assert 'op.add_column("sources", sa.Column("next_fetch_at"' in migration
    assert 'op.add_column("publish_jobs", sa.Column("workflow_job_id"' in migration
    assert 'op.create_foreign_key(\n        "fk_publish_jobs_workflow_job_id_workflow_jobs"' in migration
    for index_name in (
        "ix_workflow_jobs_claim",
        "ix_workflow_jobs_lease_expiry",
        "ix_workflow_jobs_attention",
        "ix_workflow_events_job_created",
        "ix_workflow_events_created",
        "ix_workflow_schedules_due",
        "ix_runtime_heartbeats_type_observed",
        "ix_sources_next_fetch_at",
    ):
        assert f'"{index_name}"' in migration


def test_job_engine_migration_seeds_exactly_one_global_control():
    migration = _migration_source()

    assert migration.count('"id": "global"') == 1
    assert '"global_pause": False' in migration
    assert '"dry_run": False' in migration


def test_job_engine_downgrade_removes_deferred_columns_before_job_tables():
    downgrade = _migration_source().split("def downgrade() -> None:", maxsplit=1)[1]

    publish_drop = 'op.drop_column("publish_jobs", "workflow_job_id")'
    source_drop = 'op.drop_column("sources", "next_fetch_at")'
    first_table_drop = 'op.drop_table("runtime_heartbeats")'
    assert downgrade.index(publish_drop) < downgrade.index(first_table_drop)
    assert downgrade.index(source_drop) < downgrade.index(first_table_drop)
    assert (
        downgrade.index('op.drop_constraint(\n        "fk_publish_jobs_workflow_job_id_workflow_jobs"')
        < downgrade.index(publish_drop)
    )
    assert downgrade.index('op.drop_table("workflow_events")') < downgrade.index('op.drop_table("workflow_jobs")')
