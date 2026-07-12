from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.content_production.briefs import EditorialBriefService, build_editorial_brief_payload
from app.db.models import (
    ArticleExtractionResult,
    Base,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    EditorialBrief,
    WebEnrichmentResult,
)


def test_editorial_brief_table_is_registered():
    table = Base.metadata.tables["editorial_briefs"]

    assert {
        "production_run_id",
        "angle",
        "key_facts_json",
        "source_claims_json",
        "unsafe_or_unverified_claims_json",
        "audience",
        "tone",
        "do_not_say_json",
        "created_at",
    }.issubset(table.columns.keys())
    assert "ix_editorial_briefs_production_run_created" in {index.name for index in table.indexes}


def test_editorial_brief_migration_adds_table():
    migration = Path("alembic/versions/0007_editorial_briefs.py").read_text()

    assert "editorial_briefs" in migration
    assert "0006_extraction_enrichment_results" in migration
    assert "unsafe_or_unverified_claims_json" in migration


def test_brief_payload_separates_confirmed_and_unverified_claims():
    item = _content_item()
    extraction = _extraction(
        item,
        content_text=(
            "The company launched a new AI feature for developers. "
            "The article says the rollout starts this week. "
            "Reportedly, it may replace several existing tools."
        ),
    )
    enrichment = _enrichment(item)
    request = _request()

    payload = build_editorial_brief_payload(item=item, request=request, extraction=extraction, enrichment=enrichment)

    assert payload["audience"] == "AI operators"
    assert payload["tone"] == "clear"
    assert any("launched a new AI feature" in fact["claim"] for fact in payload["key_facts"])
    assert any("Reportedly" in claim["claim"] for claim in payload["unsafe_or_unverified_claims"])
    assert any(
        claim["reason"] == "secondary_web_enrichment_not_primary_truth"
        for claim in payload["unsafe_or_unverified_claims"]
    )
    assert "Do not present unverified or secondary claims as confirmed." in payload["do_not_say"]


def test_brief_payload_blocks_failed_extraction_as_full_evidence():
    item = _content_item()
    extraction = _extraction(item, status="failed", content_text="Fallback summary")

    payload = build_editorial_brief_payload(item=item, extraction=extraction)

    assert "Do not rely on failed or fallback extraction as full article evidence." in payload["do_not_say"]


async def test_editorial_brief_service_persists_brief_and_transitions_run():
    item = _content_item()
    run = ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=item.id,
        platform="telegram",
        state="sufficiency_sufficient",
    )
    session = FakeSession()

    brief = await EditorialBriefService(session).create_brief(
        run=run,
        item=item,
        request=_request(),
        extraction=_extraction(item),
    )

    assert isinstance(brief, EditorialBrief)
    assert run.state == "brief_ready"
    assert brief.key_facts_json
    assert session.added == [brief]
    assert session.flushed_count >= 3


def _content_item():
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI feature launch",
        summary="The company launched a new AI feature.",
        content_text="The company launched a new AI feature for developers.",
        canonical_url="https://example.com/story",
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
        is_rewrite_ready=True,
    )


def _request():
    return ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        tone="clear",
        audience="AI operators",
        max_candidates=5,
    )


def _extraction(item: ContentItem, status: str = "ok", content_text: str | None = None):
    return ArticleExtractionResult(
        id=uuid4(),
        production_run_id=uuid4(),
        content_item_id=item.id,
        status=status,
        source_url=item.canonical_url,
        final_url=item.canonical_url,
        title=item.title,
        summary=item.summary,
        content_text=content_text or "The company launched a new AI feature for developers.",
        warnings_json=[],
        metadata_json={},
    )


def _enrichment(item: ContentItem):
    return WebEnrichmentResult(
        id=uuid4(),
        production_run_id=uuid4(),
        content_item_id=item.id,
        provider_name="fake",
        status="ok",
        query_json={},
        findings_json=[
            {
                "title": "Secondary report",
                "url": "https://publisher.test/related",
                "snippet": "A secondary source says customers are testing it.",
                "relevance_status": "relevant",
                "relevance_score": 0.8,
                "matched_signals": ["title_term_overlap"],
                "rejection_reason": None,
                "accepted_for_evidence": True,
            }
        ],
        source_attribution_json=[],
        warnings_json=[],
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
