from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.db.models import Source
from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.discovery.service import DiscoveryIngestionService


class FakeDiscoveryRepository:
    def __init__(self):
        self.source = Source(
            id=uuid4(),
            platform="gdelt",
            name="GDELT",
            feed_url="https://api.gdeltproject.org/api/v2/doc/doc",
            source_group="discovery",
            language_hint="en",
            default_timezone="UTC",
            active=True,
        )
        self.events = []
        self.parsed_items = []

    async def ensure_discovery_source(self, platform: str) -> Source:
        self.events.append(("ensure_source", platform))
        return self.source

    async def save_raw_payload(self, **kwargs):
        self.events.append(("raw_payload", kwargs["request_url"]))
        return SimpleNamespace(id=uuid4())

    async def upsert_source_item(self, **kwargs):
        parsed_item = kwargs["parsed_item"]
        self.parsed_items.append(parsed_item)
        self.events.append(("source_item", parsed_item.external_id_norm))
        return SimpleNamespace(id=uuid4(), content_item_id=None)

    async def upsert_content_item(self, **kwargs):
        self.events.append(("content_item", kwargs["parsed_item"].title))
        return SimpleNamespace(id=uuid4())

    async def attach_identities(self, **kwargs):
        self.events.append(("identities", len(kwargs["identities"])))

    async def upsert_media_assets(self, parsed_item):
        self.events.append(("media_assets", len(parsed_item.media_candidates)))
        return [
            SimpleNamespace(id=uuid4(), normalized_url=candidate.normalized_url, kind=candidate.kind)
            for candidate in parsed_item.media_candidates
        ]

    async def attach_item_media(self, **kwargs):
        self.events.append(("item_media", len(kwargs["media_assets"])))


async def test_discovery_ingestion_service_persists_discovery_items_and_dedupes_canonical_urls():
    repository = FakeDiscoveryRepository()
    run_id = uuid4()
    service = DiscoveryIngestionService(repository=repository)
    items = [
        _discovery_item("https://example.com/a?utm_source=x"),
        _discovery_item("https://example.com/a"),
    ]
    extracted = {
        items[0].url: _extracted_article(items[0].url, final_url="https://example.com/a", title="Extracted title"),
        items[1].url: _extracted_article(items[1].url, final_url="https://example.com/a", title="Duplicate title"),
    }

    stats = await service.ingest_discovery_items(run_id, "gdelt", items, extracted)

    assert stats == {"seen": 2, "persisted": 1, "duplicates": 1, "media_candidates": 1}
    assert [event[0] for event in repository.events] == [
        "ensure_source",
        "raw_payload",
        "source_item",
        "content_item",
        "identities",
        "media_assets",
        "item_media",
    ]
    parsed = repository.parsed_items[0]
    assert parsed.title == "Extracted title"
    assert parsed.source_url_norm == "https://example.com/a"
    assert parsed.canonical_url_candidate == "https://example.com/a"
    assert parsed.content_text == "Full extracted text"
    assert parsed.media_candidates[0].source_field == "article_primary_image"
    assert parsed.parser_meta["source_platform"] == "gdelt"
    assert parsed.parser_meta["extraction_status"] == "ok"


def _discovery_item(url: str) -> DiscoveryItem:
    return DiscoveryItem(
        source_platform="gdelt",
        source_name="GDELT",
        external_id=url,
        title="Discovery title",
        url=url,
        summary="Discovery summary",
        published_at=datetime(2026, 7, 5, 12, tzinfo=UTC),
        image_url="https://example.com/fallback.jpg",
        author=None,
        categories=["AI"],
        metadata={"domain": "example.com"},
    )


def _extracted_article(url: str, final_url: str, title: str) -> ExtractedArticle:
    return ExtractedArticle(
        url=url,
        final_url=final_url,
        title=title,
        summary="Extracted summary",
        content_text="Full extracted text",
        content_html="<p>Full extracted text</p>",
        author="Reporter",
        published_at=datetime(2026, 7, 5, 13, tzinfo=UTC),
        image_url="https://example.com/image.jpg",
        extraction_status="ok",
        extraction_warnings=[],
    )
