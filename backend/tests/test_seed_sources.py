from app.ingestion.seed_sources import SEED_SOURCES


def test_seed_catalog_has_50_active_sources():
    assert len(SEED_SOURCES) == 50
    assert all(source["active"] for source in SEED_SOURCES)
    assert {source["language_hint"] for source in SEED_SOURCES} >= {"en", "fa"}


def test_seed_catalog_has_expected_groups():
    groups = {source["source_group"] for source in SEED_SOURCES}

    assert {"ai", "tech", "economy", "farsi_news", "farsi_economy", "farsi_tech"}.issubset(groups)
