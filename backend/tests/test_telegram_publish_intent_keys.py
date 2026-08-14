from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram.process_support import enqueue_telegram_publish_intent
from app.jobs.errors import NeedsReviewJobError
from app.publishing.models import PublishJob
from app.publishing.telegram.service_contracts import (
    immediate_publish_intent_key,
    reviewed_schedule_intent_key,
)


def _key_args():
    return {
        "destination_id": uuid4(),
        "revision_id": uuid4(),
        "content_hash": "a" * 64,
    }


def test_immediate_and_reviewed_schedule_intents_use_disjoint_namespaces():
    args = _key_args()
    immediate = immediate_publish_intent_key(**args)
    scheduled = reviewed_schedule_intent_key(**args)

    assert immediate != scheduled
    assert immediate.startswith("telegram-publish:")
    assert scheduled.startswith("telegram-publish-schedule:")


class _IntentSession:
    """Minimal session recording the PublishJob lookups the intent performs."""

    def __init__(self, *, results):
        self.results = list(results)
        self.added = []

    async def scalar(self, statement):
        if not self.results:
            raise AssertionError(f"Unexpected scalar query: {statement}")
        return self.results.pop(0)

    def add(self, value):
        self.added.append(value)

    async def flush(self):  # pragma: no cover - the guard raises before flushing
        raise AssertionError("A refused intent must not flush")


def _publishable_revision():
    return SimpleNamespace(
        id=uuid4(),
        content={
            "body": "Reviewed Telegram copy",
            "source_item_id": str(uuid4()),
            "source_url": "https://t.me/source/42",
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "rtl",
            "dry_run": False,
        },
        evidence_map=[
            {
                "evidence_snapshot_id": str(uuid4()),
                "evidence_key": "telegram.source.42",
                "source_url": "https://t.me/source/42",
                "locator": "chars:0-8",
                "excerpt_sha256": "e" * 64,
            }
        ],
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        content_hash="c" * 64,
    )


@pytest.mark.asyncio
async def test_immediate_intent_refuses_to_shadow_a_reviewed_schedule():
    """Namespaced keys must not allow two live intents for one revision.

    The reviewed schedule already owns this (destination, revision); minting an
    immediate intent as well would dispatch the same revision to Telegram twice.
    """

    revision = _publishable_revision()
    destination = SimpleNamespace(id=uuid4())
    scheduled_intent = PublishJob(
        id=uuid4(),
        destination_id=destination.id,
        platform_variant_revision_id=revision.id,
        status="scheduled",
        idempotency_key=reviewed_schedule_intent_key(
            destination_id=destination.id,
            revision_id=revision.id,
            content_hash=revision.content_hash,
        ),
        payload_hash=revision.content_hash,
    )
    session = _IntentSession(results=[None, scheduled_intent])

    with pytest.raises(NeedsReviewJobError) as excinfo:
        await enqueue_telegram_publish_intent(
            session,
            revision=revision,
            destination=destination,
        )

    assert excinfo.value.code == "telegram_publish_already_scheduled"
    assert not [item for item in session.added if isinstance(item, PublishJob)]
