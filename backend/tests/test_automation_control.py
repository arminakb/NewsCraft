from datetime import UTC, datetime

import pytest

from app.jobs.control import AutomationControlService


class FakeSession:
    def __init__(self):
        self.control = None
        self.added = []

    async def get(self, model, key):
        return self.control if key == "global" else None

    def add(self, value):
        if value.__class__.__name__ == "AutomationControl":
            self.control = value
        self.added.append(value)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_control_is_global_singleton_and_noop_patch_emits_no_event():
    session = FakeSession()
    service = AutomationControlService(session)

    control = await service.get_control()
    await service.update_control(now=datetime(2026, 7, 11, tzinfo=UTC))

    assert control.id == "global"
    assert await service.get_control() is control
    assert [item.event_type for item in session.added if hasattr(item, "event_type")] == []


@pytest.mark.asyncio
async def test_control_pause_resume_and_omitted_fields_follow_patch_semantics():
    session = FakeSession()
    service = AutomationControlService(session)
    paused_at = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)

    paused = await service.update_control(global_pause=True, pause_reason="maintenance", now=paused_at)
    dry_run = await service.update_control(dry_run=True, now=datetime(2026, 7, 11, 8, 1, tzinfo=UTC))
    resumed = await service.update_control(global_pause=False, now=datetime(2026, 7, 11, 8, 2, tzinfo=UTC))

    assert paused is dry_run is resumed
    assert resumed.global_pause is False
    assert resumed.dry_run is True
    assert resumed.paused_at is None
    assert resumed.pause_reason is None
    events = [item for item in session.added if hasattr(item, "event_type")]
    assert [event.event_type for event in events] == ["automation.control_updated"] * 3
    assert all(event.workflow_job_id is None and event.actor == "operator" for event in events)


@pytest.mark.asyncio
async def test_pause_reason_change_while_paused_retains_original_paused_at():
    session = FakeSession()
    service = AutomationControlService(session)
    first = datetime(2026, 7, 11, 8, 0, tzinfo=UTC)

    await service.update_control(global_pause=True, pause_reason="first", now=first)
    control = await service.update_control(pause_reason="second", now=datetime(2026, 7, 11, 9, 0, tzinfo=UTC))

    assert control.paused_at == first
    assert control.pause_reason == "second"
