from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.content_production.sufficiency import ContentSufficiencyService, evaluate_content_sufficiency
from app.db.models import Base, ContentItem, ContentProductionRun, ContentSufficiencyReport


def test_content_sufficiency_report_table_is_registered():
    table = Base.metadata.tables["content_sufficiency_reports"]
    indexes = {index.name for index in table.indexes}

    assert {
        "production_run_id",
        "content_item_id",
        "status",
        "score",
        "reasons_json",
        "allowed_next_step",
        "blocked_steps_json",
        "minimum_needed_json",
        "input_snapshot_json",
        "created_at",
    }.issubset(table.columns.keys())
    assert {
        "ix_content_sufficiency_reports_run_created",
        "ix_content_sufficiency_reports_item_created",
        "ix_content_sufficiency_reports_status",
    }.issubset(indexes)


def test_content_sufficiency_migration_adds_report_table():
    migration = Path("alembic/versions/0005_content_sufficiency_reports.py").read_text()

    assert "content_sufficiency_reports" in migration
    assert "0004_content_production_foundation" in migration
    assert "reasons_json" in migration
    assert "blocked_steps_json" in migration


def test_title_only_content_is_insufficient_and_blocks_drafting():
    decision = evaluate_content_sufficiency(_content_item(title="AI update", content_text="", summary=""))

    assert decision.status == "insufficient"
    assert "title_only_or_empty_body" in decision.reasons
    assert "draft_generation" in decision.blocked_steps
    assert "full_article_text" in decision.minimum_needed


def test_short_rss_summary_is_partial_and_requires_article_extraction():
    decision = evaluate_content_sufficiency(
        _content_item(title="AI update", summary="Short RSS summary about AI.", content_text="")
    )

    assert decision.status == "partial"
    assert decision.allowed_next_step == "article_extraction"
    assert "rss_summary_only" in decision.reasons


def test_partial_article_content_is_partial_not_draft_ready():
    decision = evaluate_content_sufficiency(
        _content_item(
            title="AI update",
            content_text="AI article context. " * 35,
            is_rewrite_ready=False,
        )
    )

    assert decision.status == "partial"
    assert "partial_article_content" in decision.reasons
    assert "telegram_package" in decision.blocked_steps


def test_full_article_like_content_is_sufficient_for_editorial_brief():
    decision = evaluate_content_sufficiency(
        _content_item(
            title="AI update",
            content_text="AI article context with facts and source detail. " * 70,
            is_rewrite_ready=True,
        )
    )

    assert decision.status == "sufficient"
    assert decision.allowed_next_step == "editorial_brief"
    assert decision.blocked_steps == []


def test_telegram_text_with_context_can_be_sufficient():
    decision = evaluate_content_sufficiency(
        _content_item(
            item_type="telegram",
            title="AI channel post",
            content_text="متن تلگرام درباره هوش مصنوعی و چند نکته خبری معتبر. " * 12,
            is_rewrite_ready=True,
        )
    )

    assert decision.status == "sufficient"
    assert "telegram_text_has_context" in decision.reasons


def test_promotional_or_low_signal_content_is_rejected():
    decision = evaluate_content_sufficiency(
        _content_item(
            title="Buy now AI discount",
            content_text="discount coupon buy now " * 80,
            content_type="promo",
            is_rewrite_ready=True,
        )
    )

    assert decision.status == "rejected"
    assert decision.allowed_next_step is None
    assert "promotional_or_low_signal" in decision.reasons


async def test_sufficiency_service_persists_report_and_transitions_run():
    item = _content_item(
        title="AI update",
        content_text="AI article context with facts and source detail. " * 70,
        is_rewrite_ready=True,
    )
    run = ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=item.id,
        platform="telegram",
        state="shortlist_approved",
    )
    session = FakeSession()

    report = await ContentSufficiencyService(session).check_run(run, item)

    assert isinstance(report, ContentSufficiencyReport)
    assert report.status == "sufficient"
    assert run.state == "sufficiency_sufficient"
    assert session.added == [report]
    assert session.flushed_count >= 3


def _content_item(
    *,
    title: str,
    summary: str = "",
    content_text: str = "",
    item_type: str = "article",
    content_type: str = "news",
    is_rewrite_ready: bool = False,
):
    return ContentItem(
        id=uuid4(),
        item_type=item_type,
        title=title,
        summary=summary,
        content_text=content_text,
        canonical_url="https://example.com/story",
        tags=["ai"],
        sort_at=datetime(2026, 7, 9, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=25,
        content_type=content_type,
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=is_rewrite_ready,
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
