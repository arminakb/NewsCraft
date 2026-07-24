from pathlib import Path

MIGRATION = Path("alembic/versions/0018_editorial_profile_default.py")


def test_editorial_profile_migration_normalizes_and_guards_default_selection():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0018_editorial_profile_default"' in source
    assert 'down_revision: str | None = "0017_prompt_governance"' in source
    assert "row_number() OVER" in source
    assert '"uq_brand_profiles_one_default"' in source
    assert 'postgresql_where=sa.text("is_default")' in source
