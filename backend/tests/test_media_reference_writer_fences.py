from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram.handlers import _dispatch_media, _media_decision
from app.db.models import ContentItem, MediaAsset
from app.generation.editorial_service import (
    EditorialService,
    EditVariantRequest,
    InvalidGenerationRequest,
)
from app.generation.models import ContentPack
from app.generation.telegram_schema import TelegramRewriteOutput
from app.jobs.errors import NeedsReviewJobError
from app.stories.models import StoryRevision


def _expired_media(media_id=None) -> MediaAsset:
    return MediaAsset(
        id=media_id or uuid4(),
        original_url="https://example.com/media.jpg",
        normalized_url="https://example.com/media.jpg",
        url_hash="a" * 64,
        kind="image",
        source_field="content_image",
        storage_path=None,
        checksum_sha256="b" * 64,
        fetch_status="expired",
    )


def _assert_fresh_media_lock(statement) -> None:
    assert statement._for_update_arg is not None
    assert statement.get_execution_options().get("populate_existing") is True


@pytest.mark.asyncio
async def test_editorial_telegram_edit_fresh_locks_media_before_rejecting_tombstone():
    variant_id = uuid4()
    revision_id = uuid4()
    pack_id = uuid4()
    story_revision_id = uuid4()
    story_id = uuid4()
    media = _expired_media()
    evidence_id = uuid4()
    evidence_text = "Grounded evidence"
    evidence_hash = hashlib.sha256(evidence_text.encode()).hexdigest()
    citation = {
        "evidence_snapshot_id": str(evidence_id),
        "evidence_key": "telegram:source:1",
        "source_url": "https://t.me/source/1",
        "locator": f"chars:0-{len(evidence_text)}",
        "excerpt_sha256": evidence_hash,
    }
    variant = SimpleNamespace(id=variant_id, content_pack_id=pack_id, platform="telegram")
    pack = SimpleNamespace(id=pack_id, story_revision_id=story_revision_id)
    story_revision = SimpleNamespace(id=story_revision_id, story_id=story_id)
    parent = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        content_hash="c" * 64,
        evidence_map=[citation],
        content={
            "body": "Parent",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": "replace_manually",
            "media_asset_ids": [],
            "direction": "ltr",
            "dry_run": False,
        },
    )
    snapshot = SimpleNamespace(
        id=evidence_id,
        evidence_key=citation["evidence_key"],
        content_item_id=None,
        title="Evidence",
        content_text=evidence_text,
        content_sha256=evidence_hash,
        source_url=citation["source_url"],
        authors=[],
        published_at=None,
        captured_at=datetime.now(UTC),
    )

    class Session:
        def __init__(self):
            self.scalar_values = [variant, parent]
            self.media_statement = None
            self.executed = []
            self.added = []

        async def scalar(self, statement):
            return self.scalar_values.pop(0)

        async def get(self, model, identifier):
            if model is ContentPack and identifier == pack_id:
                return pack
            if model is StoryRevision and identifier == story_revision_id:
                return story_revision
            raise AssertionError(f"unexpected object lookup: {model} {identifier}")

        async def scalars(self, statement):
            entity = statement.column_descriptions[0].get("entity")
            if entity is MediaAsset:
                self.media_statement = statement
                return [media]
            if entity.__name__ == "StoryEvidenceSnapshot":
                return [snapshot]
            if entity.__name__ == "WorkflowJob":
                return []
            raise AssertionError(f"unexpected scalar collection: {entity}")

        async def execute(self, statement):
            self.executed.append(statement)

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            return None

    session = Session()
    request = EditVariantRequest(
        base_revision_id=revision_id,
        base_content_hash=parent.content_hash,
        content=TelegramRewriteOutput(body="Edited", parse_mode="HTML", buttons=[]),
        media_asset_ids=[media.id],
        edit_note="Operator edit",
    )

    with pytest.raises(InvalidGenerationRequest, match="checksum-verified"):
        await EditorialService(session).edit_variant(variant_id, request)

    _assert_fresh_media_lock(session.media_statement)
    assert "media_assets, platform_variant_revisions" in str(session.executed[-1])
    assert session.added == []


@pytest.mark.asyncio
async def test_automation_revision_fresh_locks_and_rejects_tombstoned_media():
    content_item_id = uuid4()
    content_item = ContentItem(id=content_item_id, direction="rtl")
    source_item = SimpleNamespace(content_item_id=content_item_id)
    media = _expired_media()

    class Session:
        def __init__(self):
            self.media_statement = None
            self.executed = []

        async def get(self, model, identifier):
            assert model is ContentItem
            assert identifier == content_item_id
            return content_item

        async def scalars(self, statement):
            assert statement.column_descriptions[0].get("entity") is MediaAsset
            self.media_statement = statement
            return [media]

        async def execute(self, statement):
            self.executed.append(statement)

    session = Session()
    _, media_rows = await _dispatch_media(session, source_item)

    with pytest.raises(NeedsReviewJobError) as caught:
        _media_decision(SimpleNamespace(media_policy="preserve"), media_rows)

    assert caught.value.code == "telegram_media_expired"
    _assert_fresh_media_lock(session.media_statement)
    assert "media_assets, platform_variant_revisions" in str(session.executed[-1])
