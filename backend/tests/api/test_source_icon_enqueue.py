"""The create-source path must schedule icon discovery through one visible seam.

Historically the enqueue was gated on ``hasattr(session, "scalar")`` and wrapped
in a catch-all that rolled back without a word, so a queue that rejected every
claim looked identical to a queue that was merely slow. These tests pin the
replacement: the seam is always consulted for icon-capable platforms, a
rejection still returns 201 (the scheduler backfill owns the retry), and the
rejection is logged with the source it belonged to.
"""

import logging
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.api.sources as sources_api
from app.db.session import get_session
from app.jobs.errors import JobCapabilityUnavailable
from app.sources.icon_discovery import ICON_PLATFORMS

CREATE_PAYLOAD = {
    "platform": "rss",
    "name": "Example Wire",
    "url": "https://example.com/feed.xml",
    "source_group": "technology",
    "language_hint": "en",
    "fetch_interval_minutes": 30,
}


class RecordingSession:
    """The smallest session the create path needs, with no durable job store."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _api(session: RecordingSession) -> FastAPI:
    api = FastAPI()
    api.include_router(sources_api.router)

    async def session_override():
        yield session

    api.dependency_overrides[get_session] = session_override
    return api


async def _create(api: FastAPI, payload: dict[str, object]):
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        return await client.post("/sources", json=payload)


async def test_create_routes_icon_capable_platforms_through_the_seam(monkeypatch):
    session = RecordingSession()
    scheduled: list[UUID] = []

    async def record(_session, source_id):
        scheduled.append(source_id)

    monkeypatch.setattr(sources_api, "_schedule_source_icon_discovery", record)

    response = await _create(_api(session), CREATE_PAYLOAD)

    assert response.status_code == 201
    assert scheduled == [UUID(response.json()["id"])]


async def test_create_skips_the_seam_for_platforms_without_icon_discovery(monkeypatch):
    session = RecordingSession()
    scheduled: list[UUID] = []

    async def record(_session, source_id):
        scheduled.append(source_id)

    monkeypatch.setattr(sources_api, "_schedule_source_icon_discovery", record)
    payload = dict(CREATE_PAYLOAD, platform="telegram_public", url="https://t.me/example")

    response = await _create(_api(session), payload)

    assert response.status_code == 201
    assert payload["platform"] not in ICON_PLATFORMS
    assert scheduled == []


async def test_rejected_enqueue_is_logged_and_rolled_back(monkeypatch, caplog):
    session = RecordingSession()
    source_id = uuid4()

    async def reject(_session, _source_id, *, origin):
        raise JobCapabilityUnavailable(
            code="job_capability_unavailable",
            job_type="source.icon_discovery",
            retry_after_seconds=60,
        )

    monkeypatch.setattr(sources_api, "enqueue_source_icon_discovery", reject)

    with caplog.at_level(logging.WARNING, logger=sources_api.__name__):
        await sources_api._schedule_source_icon_discovery(session, source_id)

    assert session.rollbacks == 1
    assert session.commits == 0
    record = next(entry for entry in caplog.records if entry.levelno == logging.WARNING)
    assert record.source_id == str(source_id)
    assert record.error_code == "job_capability_unavailable"


async def test_enqueue_faults_are_not_swallowed(monkeypatch):
    """Only a declared capability rejection is tolerated; real faults surface."""

    session = RecordingSession()

    async def explode(_session, _source_id, *, origin):
        raise TypeError("enqueue signature changed")

    monkeypatch.setattr(sources_api, "enqueue_source_icon_discovery", explode)

    with pytest.raises(TypeError):
        await sources_api._schedule_source_icon_discovery(session, uuid4())

    assert session.rollbacks == 0
