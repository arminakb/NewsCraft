from app.db.models import Base


def test_ingestion_tables_are_registered():
    expected = {
        "sources",
        "ingest_runs",
        "raw_payloads",
        "source_items",
        "content_items",
        "item_identities",
        "media_assets",
        "item_media",
        "content_drafts",
    }

    assert expected.issubset(set(Base.metadata.tables))


def test_content_drafts_indexes_content_item_id():
    indexes = {index.name for index in Base.metadata.tables["content_drafts"].indexes}

    assert "ix_content_drafts_content_item" in indexes


def test_content_intelligence_schema_fields_are_registered():
    content_columns = set(Base.metadata.tables["content_items"].columns.keys())
    media_columns = set(Base.metadata.tables["media_assets"].columns.keys())
    source_columns = set(Base.metadata.tables["sources"].columns.keys())

    assert {
        "content_type",
        "content_type_confidence",
        "classification_reasons",
        "classification_metadata",
        "rewrite_bucket",
        "freshness_bucket",
        "source_tier",
        "quality_status",
        "is_rewrite_ready",
        "rewrite_ready_reason",
        "rewrite_blockers",
        "score_breakdown",
        "ranking_metadata",
        "title_quality",
        "title_was_generated",
        "content_intent",
    }.issubset(content_columns)
    assert {
        "media_quality",
        "media_confidence",
        "is_primary_candidate",
        "is_primary",
        "media_source_type",
        "asset_role",
    }.issubset(media_columns)
    assert {
        "last_success_at",
        "last_failure_at",
        "failure_count",
        "last_http_status",
        "last_error_type",
        "last_error_message",
        "last_parse_count",
        "last_suitable_count",
        "last_media_count",
        "health_status",
        "disabled_reason",
    }.issubset(source_columns)


def test_rewrite_candidates_table_is_registered():
    table = Base.metadata.tables["rewrite_candidates"]

    assert {
        "content_item_id",
        "bucket_type",
        "priority_score",
        "status",
        "reason",
        "created_at",
        "updated_at",
    }.issubset(set(table.columns.keys()))
    assert "uq_rewrite_candidates_content_bucket" in {constraint.name for constraint in table.constraints}
