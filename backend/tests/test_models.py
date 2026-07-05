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
