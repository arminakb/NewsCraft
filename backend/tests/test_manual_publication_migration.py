from pathlib import Path

from sqlalchemy import CheckConstraint

from app.db.model_registry import Base

MIGRATION = Path("alembic/versions/0008_manual_publication_plans.py")


def test_manual_publication_migration_extends_the_actual_head_and_preserves_history():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0008_manual_publication_plans"' in source
    assert 'down_revision: str | None = "0007_dispatch_creation_sequence"' in source
    assert 'ForeignKey("platform_variant_revisions.id", ondelete="RESTRICT")' in source
    assert "manual_publication_plans" in source
    assert "platform_variant_revision_id" in source
    assert "scheduled_for" in source


def test_manual_publication_migration_has_database_state_and_history_guards():
    source = MIGRATION.read_text(encoding="utf-8")

    for name in (
        "ck_manual_publication_platform",
        "ck_manual_publication_status",
        "ck_manual_publication_checklist_object",
        "ck_manual_publication_checklist_shape",
        "ck_manual_publication_ready_checklist",
        "ck_manual_publication_completion",
        "uq_manual_publication_active_revision",
        "ix_manual_publication_schedule",
        "ix_manual_publication_history",
    ):
        assert name in source
    assert "postgresql_where" in source
    assert "status IN ('planned', 'ready')" in source
    assert "AND external_url IS NOT NULL" not in source
    assert "status = 'manual_published' AND completed_at IS NOT NULL" in source
    assert "from app.manual_publication" not in source


def test_manual_publication_model_metadata_matches_migration_contract():
    table = Base.metadata.tables["manual_publication_plans"]

    assert set(table.columns.keys()) == {
        "id",
        "platform_variant_revision_id",
        "platform",
        "scheduled_for",
        "display_timezone",
        "status",
        "checklist_state",
        "external_url",
        "operator_note",
        "completed_at",
        "created_at",
        "updated_at",
    }
    assert next(iter(table.c.platform_variant_revision_id.foreign_keys)).ondelete == "RESTRICT"
    checks = {item.name for item in table.constraints if isinstance(item, CheckConstraint)}
    assert {
        "ck_manual_publication_platform",
        "ck_manual_publication_status",
        "ck_manual_publication_checklist_object",
        "ck_manual_publication_checklist_shape",
        "ck_manual_publication_ready_checklist",
        "ck_manual_publication_completion",
    } <= checks
    completion = next(
        str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint) and item.name == "ck_manual_publication_completion"
    )
    assert "AND external_url IS NOT NULL" not in completion
    assert "status = 'manual_published' AND completed_at IS NOT NULL" in completion
    readiness = next(
        str(item.sqltext)
        for item in table.constraints
        if isinstance(item, CheckConstraint) and item.name == "ck_manual_publication_ready_checklist"
    )
    assert "status = 'cancelled' OR" in readiness
    assert "status IN ('ready', 'manual_published')" in readiness
    indexes = {index.name: index for index in table.indexes}
    assert indexes["uq_manual_publication_active_revision"].unique is True
    assert {"ix_manual_publication_schedule", "ix_manual_publication_history"} <= indexes.keys()
    assert all("DESC" in str(expression).upper() for expression in indexes["ix_manual_publication_history"].expressions)
