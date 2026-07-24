from pathlib import Path

from app.db.model_registry import Base

MIGRATION = Path("alembic/versions/0016_llm_provider_settings.py")


def test_migration_repairs_json_null_settings_and_guards_the_shape():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0016_llm_provider_settings"' in source
    assert 'down_revision: str | None = "0015_codex_gateway"' in source
    assert "jsonb_typeof(settings->'pricing') IS DISTINCT FROM 'object'" in source
    assert "jsonb_typeof(settings->'research_budgets') IS DISTINCT FROM 'object'" in source
    assert '"ck_llm_providers_required_settings"' in source


def test_required_settings_guard_matches_model_metadata():
    providers = Base.metadata.tables["llm_providers"]
    constraint = next(
        constraint
        for constraint in providers.constraints
        if constraint.name == "ck_llm_providers_required_settings"
    )

    rendered = str(constraint.sqltext)
    assert "jsonb_typeof(settings->'pricing')" in rendered
    assert "jsonb_typeof(settings->'research_budgets')" in rendered
