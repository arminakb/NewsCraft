from pathlib import Path


def test_platform_spine_migration_has_stable_revision_and_tables():
    migration = Path("alembic/versions/0004_platform_spine.py").read_text(encoding="utf-8")

    assert 'revision = "0004_platform_spine"' in migration
    assert 'down_revision = "0003_content_intelligence_schema"' in migration
    for table in (
        "stories",
        "story_evidence_snapshots",
        "story_revisions",
        "story_evidence_links",
        "brand_profiles",
        "prompt_templates",
        "prompt_template_versions",
        "ai_provider_profiles",
        "research_runs",
        "research_attempts",
        "research_sources",
        "generation_runs",
        "generation_attempts",
        "content_packs",
        "platform_variants",
        "platform_variant_revisions",
        "destinations",
        "automation_routes",
        "publish_jobs",
        "publish_attempts",
        "publications",
    ):
        assert f'"{table}"' in migration


def test_platform_spine_migration_is_reversible():
    migration = Path("alembic/versions/0004_platform_spine.py").read_text(encoding="utf-8")

    assert "def downgrade() -> None:" in migration
    assert migration.count("op.drop_table(") == 21


def test_story_canonicalization_column_and_active_index_are_migrated():
    migration = Path("alembic/versions/0004_platform_spine.py").read_text(encoding="utf-8")

    assert 'sa.Column("superseded_by_id", postgresql.UUID(as_uuid=True), nullable=True)' in migration
    assert 'sa.ForeignKeyConstraint(["superseded_by_id"], ["stories.id"])' in migration
    assert '"ix_stories_active_updated"' in migration
    assert 'postgresql_where=sa.text("superseded_by_id IS NULL")' in migration
