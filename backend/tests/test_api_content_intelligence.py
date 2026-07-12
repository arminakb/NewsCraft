from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api.content import list_content_items
from app.api.schemas import ContentItemOut


@pytest.mark.asyncio
async def test_content_items_query_supports_content_intelligence_filters():
    session = CapturingSession([])

    await list_content_items(
        content_type="news",
        rewrite_bucket="daily_news",
        is_rewrite_ready=True,
        source_tier="tier_a",
        quality_status="good",
        sort="score",
        limit=25,
        session=session,
    )

    sql = _compiled_sql(session.statement)
    assert "content_items.content_type = %(content_type_1)s" in sql
    assert "content_items.rewrite_bucket = %(rewrite_bucket_1)s" in sql
    assert "content_items.is_rewrite_ready IS true" in sql
    assert "content_items.source_tier = %(source_tier_1)s" in sql
    assert "content_items.quality_status = %(quality_status_1)s" in sql
    assert "ORDER BY content_items.score DESC, content_items.sort_at DESC" in sql
    assert "LIMIT %(param_1)s" in sql


def test_content_item_schema_exposes_content_intelligence_fields():
    content_item = SimpleNamespace(
        id=uuid4(),
        item_type="article",
        title="AI News",
        summary="Summary",
        canonical_url="https://example.com/a",
        language_code="en",
        direction="ltr",
        status="new",
        score=42,
        tags=["ai"],
        metrics={},
        sort_at=datetime(2026, 7, 3, tzinfo=UTC),
        primary_image_id=None,
        primary_media=None,
        content_type="news",
        rewrite_bucket="daily_news",
        is_rewrite_ready=True,
        rewrite_ready_reason="ready",
        rewrite_blockers=[],
        classification_reasons=["fresh_news"],
        source_tier="tier_a",
        freshness_bucket="fresh",
        quality_status="good",
        score_breakdown={"final_score": 42},
    )

    payload = ContentItemOut.model_validate(content_item).model_dump()

    assert payload["content_type"] == "news"
    assert payload["rewrite_bucket"] == "daily_news"
    assert payload["is_rewrite_ready"] is True
    assert payload["rewrite_ready_reason"] == "ready"
    assert payload["rewrite_blockers"] == []
    assert payload["classification_reasons"] == ["fresh_news"]
    assert payload["source_tier"] == "tier_a"
    assert payload["freshness_bucket"] == "fresh"
    assert payload["quality_status"] == "good"
    assert payload["score_breakdown"] == {"final_score": 42}


def test_content_item_schema_exposes_generation_evidence_and_source_metadata():
    source_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        item_type="telegram_post",
        title="Source post",
        summary="Short summary",
        content_text="Complete source post body",
        content_html_sanitized="<p>Complete source post body</p>",
        canonical_url="https://t.me/source/42",
        language_code="fa",
        direction="rtl",
        authors=["Source Channel"],
        published_at=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        primary_source_id=source_id,
        status="new",
        score=80,
        tags=["news"],
        metrics={},
        sort_at=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        primary_image_id=None,
        primary_media=None,
        content_type="news",
        rewrite_bucket="daily_news",
        is_rewrite_ready=True,
        rewrite_ready_reason="ready",
        rewrite_blockers=[],
        classification_reasons=["news signal"],
        classification_metadata={"source_name": "Source Channel", "source_platform": "telegram_public"},
        source_tier="tier_b",
        freshness_bucket="fresh",
        quality_status="needs_review",
        score_breakdown={},
    )

    payload = ContentItemOut.model_validate(item).model_dump()

    assert payload["content_text"] == "Complete source post body"
    assert payload["content_html_sanitized"] == "<p>Complete source post body</p>"
    assert payload["authors"] == ["Source Channel"]
    assert payload["published_at"] == datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    assert payload["primary_source_id"] == source_id
    assert payload["classification_metadata"]["source_name"] == "Source Channel"


class CapturingSession:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def scalars(self, stmt):
        self.statement = stmt
        return self.rows


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))
