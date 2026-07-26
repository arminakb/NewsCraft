from pathlib import Path


def test_editorial_state_migration_extends_the_current_head_and_adds_database_guards() -> None:
    migration = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0021_editorial_state_contracts.py"
    ).read_text()

    assert 'down_revision = "0020_article_query_indexes"' in migration
    assert "ck_research_runs_status" in migration
    assert "ck_generation_runs_status" in migration
    assert "ck_content_packs_status" in migration
    assert "'queued', 'running', 'succeeded', 'needs_review', 'failed'" in migration
    assert "'running', 'succeeded', 'completed', 'failed'" in migration
    assert "'draft', 'ready'" in migration
