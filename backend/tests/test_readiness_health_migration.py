from pathlib import Path

from app.db.model_registry import Base
from app.db.schema import SCHEMA_HEAD

MIGRATION = Path("alembic/versions/0010_readiness_health_indexes.py")


def test_phase_9_migration_is_single_head_and_adds_bounded_queue_index():
    source = MIGRATION.read_text(encoding="utf-8")

    assert SCHEMA_HEAD == "0010_readiness_health_indexes"
    assert 'revision: str = "0010_readiness_health_indexes"' in source
    assert 'down_revision: str | None = "0009_operational_retention"' in source
    assert '"ix_workflow_jobs_operational_health"' in source
    assert '["job_type", "status", "scheduled_for"]' in source


def test_phase_9_operational_health_index_matches_model_metadata():
    workflow_jobs = Base.metadata.tables["workflow_jobs"]
    index = next(index for index in workflow_jobs.indexes if index.name == "ix_workflow_jobs_operational_health")

    assert [column.name for column in index.columns] == ["job_type", "status", "scheduled_for"]
