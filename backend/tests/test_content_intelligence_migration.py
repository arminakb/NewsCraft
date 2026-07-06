from pathlib import Path


def test_content_intelligence_migration_adds_schema_fields():
    migration = Path("alembic/versions/0003_content_intelligence_schema.py").read_text()

    assert "content_type" in migration
    assert "rewrite_bucket" in migration
    assert "score_breakdown" in migration
    assert "media_quality" in migration
    assert "last_success_at" in migration
    assert "rewrite_candidates" in migration
