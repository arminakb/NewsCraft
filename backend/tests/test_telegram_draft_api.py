from __future__ import annotations

import hashlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.telegram_drafts import (
    TelegramDraftEditIn,
    build_manual_revision,
    require_revision_transition,
    validate_revision_evidence,
)


def _parent(*, approval_state: str = "pending_review", dry_run: bool = False):
    source_item_id = uuid4()
    media_id = uuid4()
    evidence_id = uuid4()
    text = "captured evidence"
    digest = hashlib.sha256(text.encode()).hexdigest()
    parent = SimpleNamespace(
        id=uuid4(),
        platform_variant_id=uuid4(),
        revision_number=2,
        content={
            "body": "parent",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": str(source_item_id),
            "source_url": "https://t.me/source/1",
            "media_policy": "preserve",
            "media_asset_ids": [str(media_id)],
            "direction": "rtl",
            "dry_run": dry_run,
        },
        content_hash="a" * 64,
        evidence_map=[
            {
                "evidence_snapshot_id": str(evidence_id),
                "evidence_key": "telegram.source.1",
                "source_url": "https://t.me/source/1",
                "locator": f"chars:0-{len(text)}",
                "excerpt_sha256": digest,
            }
        ],
        approval_state=approval_state,
    )
    snapshot = SimpleNamespace(
        id=evidence_id,
        evidence_key="telegram.source.1",
        source_url="https://t.me/source/1",
        content_text=text,
        content_sha256=digest,
    )
    return parent, snapshot, media_id


def test_manual_edit_creates_immutable_pending_child_and_preserves_provenance():
    parent, snapshot, media_id = _parent()
    body = TelegramDraftEditIn.model_validate(
        {
            "content": {"body": "edited", "parse_mode": "HTML", "buttons": []},
            "media_asset_ids": [media_id],
        }
    )

    child = build_manual_revision(parent, body, [snapshot], next_revision_number=3)

    assert parent.content["body"] == "parent"
    assert child.parent_revision_id == parent.id
    assert child.revision_number == 3
    assert child.generation_attempt_id is None
    assert child.approval_state == "pending_review"
    assert child.content["body"] == "edited"
    assert child.content["source_item_id"] == parent.content["source_item_id"]
    assert child.content["dry_run"] is False
    assert child.evidence_map == parent.evidence_map
    assert child.validation_results == [{"gate": "telegram_schema", "ok": True, "reason": None}]
    assert child.content_hash != parent.content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_key", "wrong"),
        ("source_url", "https://example.com/wrong"),
        ("locator", "chars:1-4"),
        ("excerpt_sha256", "f" * 64),
    ],
)
def test_manual_edit_rejects_mismatched_immutable_evidence(field, value):
    parent, snapshot, _ = _parent()
    parent.evidence_map[0][field] = value

    with pytest.raises(HTTPException) as error:
        validate_revision_evidence(parent.evidence_map, [snapshot])

    assert error.value.status_code == 409


def test_manual_edit_rejects_missing_snapshot():
    parent, _, _ = _parent()

    with pytest.raises(HTTPException) as error:
        validate_revision_evidence(parent.evidence_map, [])

    assert error.value.status_code == 409


@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("approved", "approve"),
        ("rejected", "approve"),
        ("approved", "reject"),
        ("rejected", "publish"),
        ("pending_review", "publish"),
    ],
)
def test_revision_transitions_reject_stale_or_invalid_state(state, action):
    parent, _, _ = _parent(approval_state=state)

    with pytest.raises(HTTPException) as error:
        require_revision_transition(parent, action=action, content_hash=parent.content_hash)

    assert error.value.status_code == 409


def test_revision_transition_requires_exact_hash_and_dry_run_cannot_publish():
    parent, _, _ = _parent()
    with pytest.raises(HTTPException) as stale:
        require_revision_transition(parent, action="approve", content_hash="b" * 64)
    assert stale.value.status_code == 409

    approved_dry_run, _, _ = _parent(approval_state="approved", dry_run=True)
    with pytest.raises(HTTPException) as dry_run:
        require_revision_transition(
            approved_dry_run,
            action="publish",
            content_hash=approved_dry_run.content_hash,
        )
    assert dry_run.value.status_code == 409
