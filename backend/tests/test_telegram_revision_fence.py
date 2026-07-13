from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.telegram_drafts import TelegramDraftEditIn, edit_telegram_draft
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.generation.revision_fence import RegenerationFenceConflict
from app.generation.telegram_schema import TelegramRewriteOutput


@pytest.mark.asyncio
async def test_telegram_draft_edit_locks_variant_and_checks_fence_before_revision(monkeypatch):
    revision_id, variant_id = uuid4(), uuid4()
    lineage = SimpleNamespace(id=revision_id, platform_variant_id=variant_id)
    variant = SimpleNamespace(id=variant_id, platform="telegram")
    events = []

    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

        async def get(self, model, identifier):
            assert model is PlatformVariantRevision and identifier == revision_id
            events.append("read_lineage")
            return lineage

        async def scalar(self, statement):
            assert statement.column_descriptions[0]["entity"] is PlatformVariant
            events.append("lock_variant")
            return variant

    async def reject_fence(session, **kwargs):
        assert kwargs == {"variant_id": variant_id}
        events.append("check_fence")
        raise RegenerationFenceConflict("Variant regeneration is in progress")

    async def unexpected_revision_lock(session, identifier):
        events.append("lock_revision")
        raise AssertionError("revision lock must follow the fence check")

    monkeypatch.setattr(
        "app.api.telegram_drafts.require_revision_write_allowed",
        reject_fence,
    )
    monkeypatch.setattr("app.api.telegram_drafts._locked_revision", unexpected_revision_lock)

    body = TelegramDraftEditIn(
        content=TelegramRewriteOutput(body="Grounded", parse_mode="HTML", buttons=[]),
        media_asset_ids=[],
    )
    with pytest.raises(HTTPException) as caught:
        await edit_telegram_draft(revision_id, body, Session())

    assert caught.value.status_code == 409
    assert events == ["read_lineage", "lock_variant", "check_fence"]
