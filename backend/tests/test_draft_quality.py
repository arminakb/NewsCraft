from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.content_production.quality import DraftQualityService, evaluate_draft_quality
from app.db.models import Base, ContentProductionRun, DraftQualityReport, EditorialBrief, TelegramDraft


def test_draft_quality_report_table_is_registered():
    table = Base.metadata.tables["draft_quality_reports"]

    assert {
        "production_run_id",
        "draft_id",
        "status",
        "score",
        "factuality_warnings_json",
        "unsupported_claims_json",
        "style_warnings_json",
        "required_revisions_json",
        "created_at",
    }.issubset(table.columns.keys())
    assert "ix_draft_quality_reports_status" in {index.name for index in table.indexes}


def test_draft_quality_migration_adds_table():
    migration = Path("alembic/versions/0009_draft_quality_reports.py").read_text()

    assert "draft_quality_reports" in migration
    assert "0008_telegram_drafts" in migration
    assert "unsupported_claims_json" in migration


def test_quality_passes_clean_draft():
    brief = _brief()
    draft = _draft(brief)

    result = evaluate_draft_quality(draft, brief)

    assert result["status"] == "passed"
    assert result["unsupported_claims"] == []
    assert result["style_warnings"] == []


def test_quality_fails_unsupported_claims_and_missing_source():
    brief = _brief()
    draft = _draft(
        brief,
        extra_line="این محصول قطعا همه ابزارهای قبلی را نابود می کند.",
        source_links=[],
    )

    result = evaluate_draft_quality(draft, brief)

    assert result["status"] == "failed"
    assert "draft_contains_claims_not_found_in_brief" in result["factuality_warnings"]
    assert "missing_source_link" in result["factuality_warnings"]
    assert result["unsupported_claims"]


def test_quality_requests_revision_for_style_warning():
    brief = _brief()
    draft = _draft(brief)
    draft.draft_text = draft.draft_text.replace(
        "The rollout starts this week.",
        "The rollout starts this week.!!",
        1,
    )

    result = evaluate_draft_quality(draft, brief)

    assert result["status"] == "revision_requested"
    assert "too_much_hype" in result["style_warnings"]
    assert "tone_mismatch" in result["style_warnings"]


async def test_quality_service_persists_report_and_transitions_run():
    brief = _brief()
    draft = _draft(brief)
    run = ContentProductionRun(
        id=draft.production_run_id,
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state="draft_ready",
    )
    session = FakeSession()

    report = await DraftQualityService(session).check_draft(run=run, draft=draft, brief=brief)

    assert isinstance(report, DraftQualityReport)
    assert report.status == "passed"
    assert run.state == "quality_passed"
    assert session.added == [report]
    assert session.flushed_count >= 3


def _brief():
    return EditorialBrief(
        id=uuid4(),
        production_run_id=uuid4(),
        angle="Explain why AI feature launch matters for AI readers.",
        key_facts_json=[
            {"claim": "The company launched a new AI feature for developers.", "source_url": "https://example.com/story"},
            {"claim": "The rollout starts this week.", "source_url": "https://example.com/story"},
        ],
        source_claims_json=[],
        unsafe_or_unverified_claims_json=[],
        audience="AI operators",
        tone="clear",
        do_not_say_json=[],
    )


def _draft(brief: EditorialBrief, *, extra_line: str | None = None, source_links=None):
    lines = [
        "تیتر: The company launched a new AI feature for developers.",
        "",
        "نکات اصلی:",
        "- The company launched a new AI feature for developers.",
        "- The rollout starts this week.",
        "",
        "منبع:",
        "- https://example.com/story",
    ]
    if extra_line:
        lines.insert(5, f"- {extra_line}")
    return TelegramDraft(
        id=uuid4(),
        production_run_id=brief.production_run_id,
        brief_id=brief.id,
        draft_text="\n".join(lines),
        title="The company launched a new AI feature for developers.",
        hashtags_json=["#خبر", "#هوش_مصنوعی"],
        source_links_json=["https://example.com/story"] if source_links is None else source_links,
        warnings_json=[],
        status="draft",
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
