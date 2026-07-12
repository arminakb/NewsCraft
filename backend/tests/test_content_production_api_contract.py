from __future__ import annotations

from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.db.models import ContentProductionRun, TelegramDispatchRequest, TelegramPostPackage, WorkflowEvent
from app.db.session import get_session
from app.main import app


async def test_content_production_run_endpoint_returns_run():
    run = _run(state="final_approval_pending")
    fake_session = FakeSession(items={(ContentProductionRun, run.id): run})
    _override_session(fake_session)

    response = await _get(f"/content-production/runs/{run.id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["state"] == "final_approval_pending"


async def test_content_production_package_endpoint_returns_latest_package():
    run = _run(state="final_approval_pending")
    package = _package(run)
    fake_session = FakeSession(scalar_results=[package])
    _override_session(fake_session)

    response = await _get(f"/content-production/runs/{run.id}/package")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["id"] == str(package.id)
    assert response.json()["approval_status"] == "pending"


async def test_content_production_package_approve_endpoint_uses_final_gate():
    run = _run(state="final_approval_pending")
    package = _package(run)
    fake_session = FakeSession(
        items={
            (TelegramPostPackage, package.id): package,
            (ContentProductionRun, run.id): run,
        }
    )
    _override_session(fake_session)

    response = await _post(f"/content-production/packages/{package.id}/approve")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["approval_status"] == "approved"
    assert run.state == "final_approved"
    assert fake_session.committed is True
    assert fake_session.rows(TelegramDispatchRequest) == []
    events = fake_session.rows(WorkflowEvent)
    assert [event.event_type for event in events] == ["PostPackageApproved"]
    assert events[0].aggregate_id == run.id
    assert events[0].correlation_id == run.request_id
    assert events[0].payload["package_id"] == str(package.id)


async def test_content_production_package_approve_endpoint_rejects_wrong_state():
    run = _run(state="package_ready")
    package = _package(run)
    fake_session = FakeSession(
        items={
            (TelegramPostPackage, package.id): package,
            (ContentProductionRun, run.id): run,
        }
    )
    _override_session(fake_session)

    response = await _post(f"/content-production/packages/{package.id}/approve")

    app.dependency_overrides.clear()
    assert response.status_code == 409
    assert "not waiting for final approval" in response.json()["detail"]


async def test_content_production_events_endpoint_filters_by_correlation_id():
    correlation_id = uuid4()
    event = WorkflowEvent(
        event_id=uuid4(),
        event_type="ContentProductionRequestCreated",
        aggregate_type="content_production_request",
        aggregate_id=uuid4(),
        correlation_id=correlation_id,
        payload={"topic": "AI"},
        status="pending",
        attempt_count=0,
    )
    fake_session = FakeSession(scalars_results=[[event]])
    _override_session(fake_session)

    response = await _get(f"/content-production/events?correlation_id={correlation_id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["correlation_id"] == str(correlation_id)


def _run(state: str):
    return ContentProductionRun(
        id=uuid4(),
        request_id=uuid4(),
        content_item_id=uuid4(),
        platform="telegram",
        state=state,
    )


def _package(run: ContentProductionRun):
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=run.id,
        draft_id=uuid4(),
        package_json={"post_text": "Telegram post"},
        approval_status="pending",
    )


class FakeSession:
    def __init__(self, *, items=None, scalar_results=None, scalars_results=None):
        self.items = items or {}
        self.scalar_results = list(scalar_results or [])
        self.scalars_results = list(scalars_results or [])
        self.committed = False
        self.flushed = False

    def add(self, obj):
        obj_id = getattr(obj, "event_id", None) or getattr(obj, "id", None)
        if obj_id is not None:
            self.items[(type(obj), obj_id)] = obj

    async def get(self, model, obj_id):
        return self.items.get((model, obj_id))

    async def scalar(self, stmt):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return None

    async def scalars(self, stmt):
        if self.scalars_results:
            return self.scalars_results.pop(0)
        return []

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True

    def rows(self, model):
        return [value for (row_model, _), value in self.items.items() if row_model is model]


def _override_session(fake_session: FakeSession) -> None:
    async def override():
        yield fake_session

    app.dependency_overrides[get_session] = override


async def _get(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def _post(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)
