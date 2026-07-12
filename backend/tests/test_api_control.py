from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.db.session import get_session
from app.jobs.models import AutomationControl, WorkflowEvent
from app.main import app


async def test_get_automation_control_returns_global_state():
    control = _control()
    session = FakeControlSession(control)

    response = await _request("GET", "/automation-control", session)

    assert response.status_code == 200
    assert response.json() == {
        "global_pause": False,
        "dry_run": False,
        "pause_reason": None,
        "paused_at": None,
        "updated_at": "2026-07-12T07:00:00Z",
    }
    assert session.commit_count == 0


async def test_patch_automation_control_pauses_and_resumes_with_real_timestamps():
    control = _control()
    session = FakeControlSession(control)
    before_patch = datetime.now(UTC)

    paused = await _request(
        "PATCH",
        "/automation-control",
        session,
        json={"global_pause": True, "pause_reason": "maintenance"},
    )
    resumed = await _request(
        "PATCH",
        "/automation-control",
        session,
        json={"global_pause": False},
    )

    assert paused.status_code == resumed.status_code == 200
    assert paused.json()["global_pause"] is True
    assert paused.json()["pause_reason"] == "maintenance"
    paused_at = datetime.fromisoformat(paused.json()["paused_at"])
    assert before_patch <= paused_at <= datetime.now(UTC)
    assert resumed.json()["global_pause"] is False
    assert resumed.json()["pause_reason"] is None
    assert resumed.json()["paused_at"] is None
    assert session.commit_count == 2
    assert len(session.events) == 2


async def test_patch_automation_control_updates_only_supplied_fields():
    control = _control(global_pause=True, pause_reason="keep")
    original_paused_at = control.paused_at
    session = FakeControlSession(control)

    response = await _request(
        "PATCH",
        "/automation-control",
        session,
        json={"dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["global_pause"] is True
    assert response.json()["dry_run"] is True
    assert response.json()["pause_reason"] == "keep"
    assert response.json()["paused_at"] == original_paused_at.isoformat().replace("+00:00", "Z")


async def test_patch_automation_control_rejects_empty_body():
    response = await _request("PATCH", "/automation-control", FakeControlSession(_control()), json={})

    assert response.status_code == 422


async def test_patch_automation_control_rejects_reason_over_500_characters():
    response = await _request(
        "PATCH",
        "/automation-control",
        FakeControlSession(_control()),
        json={"pause_reason": "x" * 501},
    )

    assert response.status_code == 422


class FakeControlSession:
    def __init__(self, control):
        self.control = control
        self.events = []
        self.commit_count = 0

    async def get(self, model, item_id):
        assert model is AutomationControl
        assert item_id == "global"
        return self.control

    def add(self, value):
        if isinstance(value, AutomationControl):
            self.control = value
        elif isinstance(value, WorkflowEvent):
            self.events.append(value)

    async def flush(self):
        pass

    async def commit(self):
        self.commit_count += 1


def _control(*, global_pause=False, pause_reason=None):
    paused_at = datetime(2026, 7, 12, 7, 30, tzinfo=UTC) if global_pause else None
    return AutomationControl(
        id="global",
        global_pause=global_pause,
        dry_run=False,
        pause_reason=pause_reason,
        paused_at=paused_at,
        updated_at=datetime(2026, 7, 12, 7, 0, tzinfo=UTC),
    )


async def _request(method, path, session, **kwargs):
    async def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.clear()
