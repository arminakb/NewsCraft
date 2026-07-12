from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.events import redact_event_data
from app.jobs.models import AutomationControl, WorkflowEvent

_UNSET = object()


class AutomationControlService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_control(self) -> AutomationControl:
        control = await self.session.get(AutomationControl, "global")
        if control is None:
            control = AutomationControl(id="global", global_pause=False, dry_run=False)
            self.session.add(control)
            await self.session.flush()
        return control

    async def update_control(
        self,
        *,
        global_pause: bool | object = _UNSET,
        dry_run: bool | object = _UNSET,
        pause_reason: str | None | object = _UNSET,
        now: datetime | None = None,
    ) -> AutomationControl:
        observed_at = now or datetime.now(UTC)
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        control = await self.get_control()
        changes: dict[str, Any] = {}

        if global_pause is not _UNSET and global_pause != control.global_pause:
            pause_value = bool(global_pause)
            changes["global_pause"] = pause_value
            control.global_pause = pause_value
            if pause_value:
                control.paused_at = observed_at
                changes["paused_at"] = observed_at.isoformat()
            else:
                control.paused_at = None
                control.pause_reason = None
                changes["paused_at"] = None
                changes["pause_reason"] = None

        if dry_run is not _UNSET and dry_run != control.dry_run:
            control.dry_run = bool(dry_run)
            changes["dry_run"] = control.dry_run

        if pause_reason is not _UNSET and control.global_pause and pause_reason != control.pause_reason:
            control.pause_reason = None if pause_reason is None else str(pause_reason)
            changes["pause_reason"] = control.pause_reason

        if changes:
            control.updated_at = observed_at
            self.session.add(
                WorkflowEvent(
                    workflow_job_id=None,
                    event_type="automation.control_updated",
                    actor="operator",
                    event_data=redact_event_data(changes),
                    created_at=observed_at,
                )
            )
            await self.session.flush()
        return control
