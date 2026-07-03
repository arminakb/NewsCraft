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
    }

    assert expected.issubset(set(Base.metadata.tables))
