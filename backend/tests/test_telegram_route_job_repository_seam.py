from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.automations.telegram import route_fetch
from app.automations.telegram.route_fetch import (
    _defer_route_job,
    _enqueue_continuation,
    _enqueue_forward_continuation,
    _persist_forward_progress,
)

pytestmark = pytest.mark.anyio


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(created=True, job=SimpleNamespace(id=uuid4()))


@pytest.mark.parametrize(
    "helper",
    [
        _defer_route_job,
        _enqueue_continuation,
        _enqueue_forward_continuation,
        _persist_forward_progress,
    ],
)
def test_queue_helpers_take_an_explicit_repository_not_a_media_stager(helper):
    """The queue writer is a named parameter, never sniffed off the stager.

    These helpers used to run
    ``media_stager if hasattr(media_stager, "enqueue_job") else JobRepository(...)``,
    so a media stager that happened to grow an ``enqueue_job`` attribute would
    silently become the queue.
    """

    parameters = inspect.signature(helper).parameters
    assert "media_stager" not in parameters
    repository = parameters["repository"]
    assert repository.kind is inspect.Parameter.KEYWORD_ONLY
    assert repository.default is None


async def test_defer_route_job_ignores_a_stager_that_looks_like_a_repository(monkeypatch):
    """A stager exposing ``enqueue_job`` must not be mistaken for the queue."""

    session_repository = _Recorder()
    stager_shaped_like_a_repository = _Recorder()
    monkeypatch.setattr(route_fetch, "JobRepository", lambda session: session_repository)

    context = SimpleNamespace(session=object())
    route = SimpleNamespace(id=uuid4())
    job = SimpleNamespace(id=uuid4(), job_type="telegram.route.poll", payload={})

    await _defer_route_job(
        context,
        route=route,
        job=job,
        scheduled_for=None,
    )

    assert len(session_repository.calls) == 1
    assert stager_shaped_like_a_repository.calls == []
