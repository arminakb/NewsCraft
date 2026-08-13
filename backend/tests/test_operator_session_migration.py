from pathlib import Path

from app.db import model_registry as _model_registry  # noqa: F401
from app.db.base import Base

CREATE_MIGRATION = Path("alembic/versions/0025_operator_sessions.py")
REMOVE_MIGRATION = Path("alembic/versions/0026_remove_operator_sessions.py")


def test_obsolete_operator_sessions_are_removed_by_forward_migration():
    create_source = CREATE_MIGRATION.read_text(encoding="utf-8")
    remove_source = REMOVE_MIGRATION.read_text(encoding="utf-8")

    assert 'revision = "0025_operator_sessions"' in create_source
    assert 'revision = "0026_remove_operator_sessions"' in remove_source
    assert 'down_revision = "0025_operator_sessions"' in remove_source
    assert 'op.drop_table("operator_sessions")' in remove_source
    assert "operator_sessions" not in Base.metadata.tables
