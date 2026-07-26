from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.telegram_drafts import (
    ScheduleTelegramIn,
    _locked_revision,
    require_revision_transition,
    schedule_telegram_revision,
)
from app.generation.models import PlatformVariant, PlatformVariantRevision
from app.jobs.types import JobStatus
from app.main import app
from app.publishing.telegram.service import ReviewedTelegramScheduleError
from tests.capability_fakes import AVAILABLE_CAPABILITIES


def _revision(*, approval_state: str = "approved", dry_run: bool = False):
    return SimpleNamespace(
        content={
            "body": "Grounded",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": str(uuid4()),
            "source_url": "https://t.me/source/1",
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "rtl",
            "dry_run": dry_run,
        },
        content_hash="a" * 64,
        evidence_map=[
            {
                "evidence_snapshot_id": str(uuid4()),
                "evidence_key": "telegram.source.1",
                "source_url": "https://t.me/source/1",
                "locator": "chars:0-8",
                "excerpt_sha256": "b" * 64,
            }
        ],
        validation_results=[{"gate": "telegram_schema", "ok": True, "reason": None}],
        approval_state=approval_state,
    )


@pytest.mark.parametrize("state", ["pending_review", "rejected"])
def test_publish_transition_rejects_invalid_state(state):
    revision = _revision(approval_state=state)

    with pytest.raises(HTTPException) as error:
        require_revision_transition(revision, content_hash=revision.content_hash)

    assert error.value.status_code == 409


def test_publish_transition_requires_exact_hash_and_rejects_dry_run():
    revision = _revision()
    with pytest.raises(HTTPException) as stale:
        require_revision_transition(revision, content_hash="b" * 64)
    assert stale.value.status_code == 409

    dry_run = _revision(dry_run=True)
    with pytest.raises(HTTPException) as error:
        require_revision_transition(dry_run, content_hash=dry_run.content_hash)
    assert error.value.status_code == 409


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

    output = await schedule_telegram_revision(
        revision_id,
        payload,
        session=session,
        capability_status=AVAILABLE_CAPABILITIES,
    )

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
        await schedule_telegram_revision(
            uuid4(),
            payload,
            session=_ApiSession(),
            capability_status=AVAILABLE_CAPABILITIES,
        )

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
