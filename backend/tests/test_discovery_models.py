from datetime import UTC, datetime

from app.discovery.models import DiscoveryItem, ExtractedArticle


def test_discovery_item_stores_source_metadata():
    item = DiscoveryItem(
        source_platform="gdelt",
        source_name="GDELT",
        external_id="https://example.com/a",
        title="Example",
        url="https://example.com/a",
        summary="Summary",
        published_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
        image_url="https://example.com/i.jpg",
        author=None,
        categories=["AI"],
        metadata={"domain": "example.com"},
    )

    assert item.source_platform == "gdelt"
    assert item.url == "https://example.com/a"
    assert item.metadata["domain"] == "example.com"


def test_extracted_article_records_status_and_warnings():
    article = ExtractedArticle(
        url="https://example.com/a",
        final_url="https://example.com/a",
        title="Example",
        summary="Summary",
        content_text="Full article text",
        content_html=None,
        author="Reporter",
        published_at=None,
        image_url=None,
        extraction_status="ok",
        extraction_warnings=[],
    )

    assert article.extraction_status == "ok"
    assert article.content_text == "Full article text"
