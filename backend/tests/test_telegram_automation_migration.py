from pathlib import Path


def test_telegram_vertical_migration_extends_release_one_head():
    migration = Path("alembic/versions/0006_telegram_automation_vertical.py").read_text(encoding="utf-8")

    assert 'revision: str = "0006_telegram_automation_vertical"' in migration
    assert 'down_revision: str | None = "0005_job_engine_and_scheduling"' in migration
    for table in (
        "telegram_source_configs",
        "automation_dispatches",
        "publish_operation_receipts",
    ):
        assert f'"{table}"' in migration
    assert "uq_automation_dispatch_route_source" in migration
    assert "uq_publish_operation_job_key" in migration
    assert "ck_telegram_source_access_mode" in migration


def test_telegram_vertical_migration_downgrades_only_release_two_tables():
    migration = Path("alembic/versions/0006_telegram_automation_vertical.py").read_text(encoding="utf-8")

    for table in (
        "publish_operation_receipts",
        "automation_dispatches",
        "telegram_source_configs",
    ):
        assert f'op.drop_table("{table}")' in migration


def test_telegram_vertical_migration_supports_the_locked_long_revision_id():
    migration = Path("alembic/versions/0006_telegram_automation_vertical.py").read_text(encoding="utf-8")

    assert len("0006_telegram_automation_vertical") > 32
    widen = 'op.alter_column("alembic_version", "version_num", type_=sa.String(length=64))'
    assert migration.index(widen) < migration.index('op.create_table(\n        "telegram_source_configs"')
