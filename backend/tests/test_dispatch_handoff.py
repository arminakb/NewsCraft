from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.content_production.dispatch import TelegramDispatchService
from app.db.models import Base, ContentProductionRun, TelegramDispatchRequest, TelegramPostPackage


def test_dispatch_request_table_is_registered():
    table = Base.metadata.tables["telegram_dispatch_requests"]

    assert {
        "production_run_id",
        "package_id",
        "status",
        "dispatch_payload_json",
        "blocked_reason",
        "created_at",
        "updated_at",
        "dispatched_at",
    }.issubset(table.columns.keys())
    assert "ix_telegram_dispatch_requests_status" in {index.name for index in table.indexes}


def test_dispatch_request_migration_adds_table():
    migration = Path("alembic/versions/0012_telegram_dispatch_requests.py").read_text()

    assert "telegram_dispatch_requests" in migration
    assert "0011_telegram_post_packages" in migration
    assert "blocked_reason" in migration


async def test_dispatch_requires_final_approval():
    run = _run(state="final_approval_pending")
    package = _package(run, approval_status="pending")

    with pytest.raises(ValueError):
        await TelegramDispatchService(FakeSession()).create_dispatch_request(run=run, package=package)


async def test_dispatch_handoff_blocks_when_telegram_config_missing():
    run = _run(state="final_approved")
    package = _package(run, approval_status="approved")
    session = FakeSession()

    dispatch = await TelegramDispatchService(session).create_dispatch_request(run=run, package=package)

    assert isinstance(dispatch, TelegramDispatchRequest)
    assert dispatch.status == "blocked"
    assert dispatch.blocked_reason == "telegram_dispatch_not_configured"
    assert run.state == "dispatch_failed"
    assert run.failure_reason == "telegram_dispatch_not_configured"
    assert session.added == [dispatch]


async def test_dispatch_handoff_pending_when_configured_but_does_not_publish():
    run = _run(state="final_approved")
    package = _package(run, approval_status="approved")
    session = FakeSession()

    dispatch = await TelegramDispatchService(
        session,
        bot_token="token",
        channel_id="@channel",
    ).create_dispatch_request(run=run, package=package)

    assert dispatch.status == "pending"
    assert dispatch.blocked_reason is None
    assert dispatch.dispatched_at is None
    assert run.state == "dispatch_pending"


def _run(state: str):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state=state,
    )


def _package(run: ContentProductionRun, *, approval_status: str):
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=run.id,
        draft_id=uuid4(),
        package_json={
            "post_text": "Telegram post",
            "source_links": ["https://example.com/story"],
            "media": {"status": "missing"},
        },
        approval_status=approval_status,
    )


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed_count = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed_count += 1
