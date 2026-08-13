from datetime import UTC, datetime
from uuid import uuid4

from app.db.models import ContentItem, Source
from app.ingestion.repository import _content_item_values, _preserve_more_complete_content
from app.sources.base import ParsedSourceItem

FULL_BODY = (
    "Full stored article body with several complete paragraphs describing the "
    "model release, the benchmark results and the rollout schedule."
)
FULL_HTML = f"<p>{FULL_BODY}</p>"
EXCERPT = "Short excerpt."

DERIVED_TIMESTAMPS = {"first_seen_at", "last_seen_at", "created_at", "updated_at"}


def _source() -> Source:
    return Source(
        id=uuid4(),
        platform="rss",
        name="AI News",
        source_group="ai",
        language_hint="en",
    )


def _parsed_item(content_text: str, content_html: str | None, origin: str) -> ParsedSourceItem:
    return ParsedSourceItem(
        external_id_raw="item-1",
        external_id_norm="item-1",
        source_url="https://publisher.test/story",
        source_url_norm="https://publisher.test/story",
        canonical_url_candidate="https://publisher.test/story",
        title="Model release ships broad benchmark gains",
        summary="Summary line.",
        content_html=content_html,
        content_text=content_text,
        author="Reporter",
        categories=["ai"],
        published_raw="2026-08-13T09:00:00Z",
        published_at=datetime(2026, 8, 13, 9, 0, tzinfo=UTC),
        date_parse_status="parsed",
        parser_meta={"content_origin": origin},
    )


def _comparable(values: dict) -> dict:
    return {key: value for key, value in values.items() if key not in DERIVED_TIMESTAMPS}


def test_duplicate_ingestion_does_not_replace_longer_canonical_content() -> None:
    source = _source()
    existing = ContentItem(
        content_text=FULL_BODY,
        content_html_sanitized=FULL_HTML,
        metrics={"content_origin": "source_provided", "classification": {"category": "AI"}},
    )
    excerpt_item = _parsed_item(EXCERPT, f"<p>{EXCERPT}</p>", "source_excerpt")
    incoming = _content_item_values(source, excerpt_item)

    merged = _preserve_more_complete_content(source, existing, excerpt_item, incoming)

    assert merged["content_text"] == existing.content_text
    assert merged["content_html_sanitized"] == existing.content_html_sanitized
    assert merged["metrics"]["content_origin"] == "source_provided"


def test_preserved_content_also_preserves_the_values_derived_from_it() -> None:
    source = _source()
    existing = ContentItem(
        content_text=FULL_BODY,
        content_html_sanitized=FULL_HTML,
        metrics={"content_origin": "source_provided"},
    )
    excerpt_item = _parsed_item(EXCERPT, f"<p>{EXCERPT}</p>", "source_excerpt")
    incoming = _content_item_values(source, excerpt_item)

    merged = _preserve_more_complete_content(source, existing, excerpt_item, incoming)

    full_item = _parsed_item(FULL_BODY, FULL_HTML, "source_provided")
    expected = _content_item_values(source, full_item)

    assert _comparable(merged) == _comparable(expected)
    # The excerpt on its own is too thin to rewrite; the preserved body is not.
    assert incoming["is_rewrite_ready"] is False
    assert "insufficient_facts" in incoming["rewrite_blockers"]
    assert merged["is_rewrite_ready"] is True
    assert "insufficient_facts" not in merged["rewrite_blockers"]


def test_duplicate_ingestion_accepts_more_complete_content() -> None:
    source = _source()
    existing = ContentItem(
        content_text=EXCERPT,
        content_html_sanitized=f"<p>{EXCERPT}</p>",
        metrics={"content_origin": "source_excerpt"},
    )
    full_item = _parsed_item(FULL_BODY, FULL_HTML, "source_provided")
    incoming = _content_item_values(source, full_item)

    assert _preserve_more_complete_content(source, existing, full_item, incoming) is incoming
