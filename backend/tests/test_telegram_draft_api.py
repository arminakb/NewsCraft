from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.telegram_drafts import (
    ScheduleTelegramIn,
    TelegramDraftEditIn,
    _draft_out,
    _locked_revision,
    build_manual_revision,
    require_revision_transition,
    schedule_telegram_revision,
    validate_revision_evidence,
)
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.jobs.types import JobStatus
from app.main import app
from app.publishing.telegram.service import ReviewedTelegramScheduleError


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


async def test_draft_projection_redacts_legacy_validation_results():
    variant_id = uuid4()
    revision = SimpleNamespace(
        id=uuid4(),
        platform_variant_id=variant_id,
        parent_revision_id=None,
        generation_attempt_id=None,
        revision_number=1,
        content={"body": "draft", "media_asset_ids": []},
        content_hash="a" * 64,
        evidence_map=[],
        validation_results=[
            {
                "gate": "provider_failed",
                "ok": False,
                "reason": "authorization: Bearer telegram-validation-canary",
            }
        ],
        approval_state="pending_review",
        approval_note=None,
        approved_at=None,
        created_by="generation",
        created_at=datetime.now(UTC),
    )

    class Session:
        async def get(self, model, identifier):
            if model is PlatformVariant and identifier == variant_id:
                return SimpleNamespace(platform="telegram")
            return None

        async def scalar(self, _statement):
            return None

    output = await _draft_out(Session(), revision)

    assert "telegram-validation-canary" not in str(output)
    assert output["validation_results"][0]["reason"] == "authorization:[REDACTED]"


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


def test_reviewed_schedule_route_and_strict_request_contract_are_public():
    operations = {(path, method.upper()) for path, row in app.openapi()["paths"].items() for method in row}
    assert ("/telegram/drafts/{revision_id}/schedule", "POST") in operations

    parsed = ScheduleTelegramIn.model_validate(
        {
            "content_hash": "a" * 64,
            "destination_id": str(uuid4()),
            "scheduled_for": "2026-07-13T09:00:00+03:30",
        }
    )
    assert parsed.scheduled_for == datetime(2026, 7, 13, 5, 30, tzinfo=UTC)

    for invalid in (
        {
            "content_hash": "A" * 64,
            "destination_id": str(uuid4()),
            "scheduled_for": "2026-07-13T05:30:00Z",
        },
        {
            "content_hash": "a" * 64,
            "destination_id": str(uuid4()),
            "scheduled_for": "2026-07-13T05:30:00",
        },
        {
            "content_hash": "a" * 64,
            "destination_id": str(uuid4()),
            "scheduled_for": "2026-07-13T05:30:00Z",
            "immediate": True,
        },
    ):
        with pytest.raises(ValidationError):
            ScheduleTelegramIn.model_validate(invalid)


class _ApiTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class _ApiSession:
    def __init__(self):
        self.transactions = 0

    def begin(self):
        self.transactions += 1
        return _ApiTransaction()


@pytest.mark.asyncio
async def test_reviewed_schedule_endpoint_returns_job_accepted_and_exact_replay_flag(monkeypatch):
    revision_id = uuid4()
    workflow_id = uuid4()
    payload = ScheduleTelegramIn(
        content_hash="a" * 64,
        destination_id=uuid4(),
        scheduled_for=datetime(2026, 7, 13, 5, 30, tzinfo=UTC),
    )
    session = _ApiSession()
    observed = []

    async def schedule(_session, *, revision_id, request):
        observed.append((_session, revision_id, request))
        return SimpleNamespace(
            workflow_job=SimpleNamespace(id=workflow_id, status=JobStatus.QUEUED),
            created=False,
        )

    monkeypatch.setattr("app.api.telegram_drafts.schedule_reviewed_telegram", schedule)

    output = await schedule_telegram_revision(revision_id, payload, session=session)

    assert output.job_id == workflow_id
    assert output.status == JobStatus.QUEUED
    assert output.deduplicated is True
    assert observed == [(session, revision_id, payload)]
    assert session.transactions == 1


@pytest.mark.asyncio
async def test_reviewed_schedule_endpoint_maps_domain_conflicts_to_http_409(monkeypatch):
    payload = ScheduleTelegramIn(
        content_hash="a" * 64,
        destination_id=uuid4(),
        scheduled_for=datetime(2026, 7, 13, 5, 30, tzinfo=UTC),
    )

    async def conflict(*args, **kwargs):
        raise ReviewedTelegramScheduleError("schedule_conflict", "Schedule conflicts")

    monkeypatch.setattr("app.api.telegram_drafts.schedule_reviewed_telegram", conflict)

    with pytest.raises(HTTPException) as caught:
        await schedule_telegram_revision(uuid4(), payload, session=_ApiSession())

    assert caught.value.status_code == 409
    assert caught.value.detail == "Schedule conflicts"


@pytest.mark.asyncio
async def test_locked_draft_serializes_variant_then_refreshes_exact_revision():
    revision_id = uuid4()
    variant_id = uuid4()
    provisional = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        approval_state="pending_review",
    )
    variant = SimpleNamespace(id=variant_id, platform="telegram")
    refreshed = SimpleNamespace(
        id=revision_id,
        platform_variant_id=variant_id,
        approval_state="approved",
    )

    class Session:
        def __init__(self):
            self.results = [provisional, variant, refreshed, revision_id]
            self.statements = []

        async def scalar(self, statement):
            self.statements.append(statement)
            return self.results.pop(0)

    session = Session()
    result = await _locked_revision(session, revision_id)

    assert result is refreshed
    entities = [statement.column_descriptions[0].get("entity") for statement in session.statements]
    assert entities[:3] == [
        PlatformVariantRevision,
        PlatformVariant,
        PlatformVariantRevision,
    ]
    assert "FOR UPDATE" not in str(session.statements[0])
    assert "FOR UPDATE" in str(session.statements[1])
    assert "FOR UPDATE" in str(session.statements[2])
    assert session.statements[1].get_execution_options().get("populate_existing") is True
    assert session.statements[2].get_execution_options().get("populate_existing") is True
