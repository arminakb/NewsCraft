from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from app.content_production.enrichment import (
    ArticleExtractionService,
    EnrichmentFinding,
    EnrichmentResponse,
    NullWebEnrichmentProvider,
    WebEnrichmentService,
    build_enrichment_query,
)
from app.db.models import ArticleExtractionResult, Base, ContentItem, ContentProductionRun, WebEnrichmentResult


def test_extraction_and_enrichment_tables_are_registered():
    assert "article_extraction_results" in Base.metadata.tables
    assert "web_enrichment_results" in Base.metadata.tables
    assert "ix_article_extraction_results_run_created" in {
        index.name for index in Base.metadata.tables["article_extraction_results"].indexes
    }
    assert "ix_web_enrichment_results_run_created" in {
        index.name for index in Base.metadata.tables["web_enrichment_results"].indexes
    }


def test_extraction_enrichment_migration_adds_result_tables():
    migration = Path("alembic/versions/0006_extraction_enrichment_results.py").read_text()

    assert "article_extraction_results" in migration
    assert "web_enrichment_results" in migration
    assert "0005_content_sufficiency_reports" in migration
    assert "source_attribution_json" in migration


async def test_article_extraction_service_reuses_existing_extractor_and_persists_result():
    html = "<html><body><article><p>Extracted article body with reliable detail.</p></article></body></html>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html"})
    )
    session = FakeSession()
    item = _content_item()
    run = _run(item, state="sufficiency_partial")

    async with httpx.AsyncClient(transport=transport) as client:
        result = await ArticleExtractionService(session, client=client).extract_for_run(run, item)

    assert isinstance(result, ArticleExtractionResult)
    assert result.status == "ok"
    assert "Extracted article body" in result.content_text
    assert result.metadata_json["truth_priority"] == "original_source_url"
    assert run.state == "article_extracted"
    assert session.added == [result]


async def test_article_extraction_service_persists_failure_without_raising():
    session = FakeSession()
    item = _content_item(canonical_url=None)
    run = _run(item, state="sufficiency_partial")

    result = await ArticleExtractionService(session).extract_for_run(run, item)

    assert result.status == "failed"
    assert result.error_message == "missing_source_url"
    assert "missing_source_url" in result.warnings_json
    assert run.state == "article_extracting"


async def test_web_enrichment_service_uses_provider_and_stores_attribution():
    session = FakeSession()
    item = _content_item()
    run = _run(item, state="article_extracted")
    provider = FakeProvider(
        EnrichmentResponse(
            status="ok",
            findings=[
                EnrichmentFinding(
                    title="Related source",
                    url="https://publisher.test/related",
                    snippet="Supporting context from another source.",
                    source_name="Publisher",
                    reliability="secondary",
                )
            ],
        )
    )

    result = await WebEnrichmentService(session, provider=provider).enrich_run(run, item)

    assert isinstance(result, WebEnrichmentResult)
    assert result.status == "ok"
    assert result.provider_name == "fake"
    assert result.query_json["title"] == item.title
    assert result.query_json["source_domain"] == "example.com"
    assert result.findings_json[0]["url"] == "https://publisher.test/related"
    assert result.source_attribution_json[0]["truth_priority"] == "web_enrichment_secondary"
    assert run.state == "enriched"


async def test_null_enrichment_provider_records_skipped_without_fake_success():
    session = FakeSession()
    item = _content_item()
    run = _run(item, state="sufficiency_partial")

    result = await WebEnrichmentService(session, provider=NullWebEnrichmentProvider()).enrich_run(run, item)

    assert result.status == "skipped"
    assert result.provider_name == "none"
    assert result.findings_json == []
    assert "no_enrichment_provider_configured" in result.warnings_json
    assert run.state == "enriching"


def test_enrichment_query_uses_strong_identifiers():
    item = _content_item()
    item.classification_metadata = {"source_name": "Example Source"}
    item.authors = ["Reporter"]

    query = build_enrichment_query(item)

    assert query.title == item.title
    assert query.source_name == "Example Source"
    assert query.source_url == item.canonical_url
    assert query.source_domain == "example.com"
    assert query.published_date == "2026-07-09"
    assert query.author == "Reporter"


def _content_item(canonical_url: str | None = "https://example.com/story"):
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI source story",
        summary="Short source summary",
        content_text="Short source summary",
        canonical_url=canonical_url,
        tags=["ai"],
        sort_at=datetime(2026, 7, 9, tzinfo=UTC),
        published_at=datetime(2026, 7, 9, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=25,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=False,
    )


def _run(item: ContentItem, *, state: str):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=item.id,
        platform="telegram",
        state=state,
    )


class FakeProvider:
    provider_name = "fake"

    def __init__(self, response: EnrichmentResponse):
        self.response = response

    async def search(self, query):
        self.query = query
        return self.response


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
