from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.content_production.telegram_drafts import TelegramDraftService, build_telegram_draft_payload
from app.db.models import Base, ContentProductionRun, EditorialBrief, TelegramDraft


def test_telegram_drafts_table_is_registered():
    table = Base.metadata.tables["telegram_drafts"]

    assert {
        "production_run_id",
        "brief_id",
        "draft_text",
        "title",
        "hashtags_json",
        "source_links_json",
        "warnings_json",
        "status",
        "created_at",
        "updated_at",
    }.issubset(table.columns.keys())
    assert "ix_telegram_drafts_production_run_created" in {index.name for index in table.indexes}


def test_telegram_drafts_migration_adds_table():
    migration = Path("alembic/versions/0008_telegram_drafts.py").read_text()

    assert "telegram_drafts" in migration
    assert "0007_editorial_briefs" in migration
    assert "source_links_json" in migration


def test_draft_payload_uses_only_brief_facts_not_unsafe_claims():
    brief = _brief()

    payload = build_telegram_draft_payload(brief)

    assert "تیتر:" in payload["draft_text"]
    assert "نکات اصلی:" in payload["draft_text"]
    assert "The company launched a new AI feature" in payload["draft_text"]
    assert "unverified acquisition rumor" not in payload["draft_text"]
    assert payload["source_links"] == ["https://example.com/story"]
    assert "#خبر" in payload["hashtags"]
    assert payload["warnings"]


async def test_telegram_draft_service_persists_draft_and_transitions_run():
    run = ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state="brief_ready",
    )
    brief = _brief(production_run_id=run.id)
    session = FakeSession()

    draft = await TelegramDraftService(session).create_draft(run=run, brief=brief)

    assert isinstance(draft, TelegramDraft)
    assert draft.production_run_id == run.id
    assert draft.brief_id == brief.id
    assert draft.status == "draft"
    assert run.state == "draft_ready"
    assert session.added == [draft]
    assert session.flushed_count >= 3


def _brief(production_run_id=None):
    return EditorialBrief(
        id=uuid4(),
        production_run_id=production_run_id or uuid4(),
        angle="Explain why AI feature launch matters for AI readers.",
        key_facts_json=[
            {
                "claim": "The company launched a new AI feature for developers.",
                "source_url": "https://example.com/story",
            },
            {
                "claim": "The rollout starts this week.",
                "source_url": "https://example.com/story",
            },
        ],
        source_claims_json=[
            {
                "claim": "The company launched a new AI feature.",
                "source_url": "https://example.com/story",
            }
        ],
        unsafe_or_unverified_claims_json=[
            {"claim": "unverified acquisition rumor", "reason": "unsafe_or_unverified_language"}
        ],
        audience="AI operators",
        tone="clear",
        do_not_say_json=["Do not present unverified claims as confirmed."],
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
