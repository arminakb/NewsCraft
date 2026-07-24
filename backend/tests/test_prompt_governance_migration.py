from pathlib import Path

MIGRATION = Path("alembic/versions/0017_prompt_governance.py")


def test_prompt_governance_migration_extends_schema_head_and_preserves_existing_routes():
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "0017_prompt_governance"' in source
    assert 'down_revision: str | None = "0016_llm_provider_settings"' in source
    assert '"activated_at"' in source
    assert '"activation_reason"' in source
    assert '"uq_prompt_template_versions_one_active"' in source
    assert '"prompt_policy"' in source
    assert 'server_default="pinned"' in source
    assert '"ck_automation_routes_prompt_policy"' in source
