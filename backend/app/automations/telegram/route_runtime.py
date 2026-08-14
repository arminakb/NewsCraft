from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.automations.telegram.handler_contracts import _LoadedRoute
from app.automations.telegram.registry import TelegramSourceRegistry
from app.automations.telegram.route_fetch import _defer_route_job
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution


@dataclass(frozen=True, slots=True)
class TelegramRouteDependencies:
    source_registry: TelegramSourceRegistry
    media_stager: Any
    page_budget: int
    clock: Callable[[], datetime]
    # Explicit queue writer for route continuations. ``None`` means the
    # helpers build one from the job's own session; tests inject a fake.
    job_repository: JobRepository | None = None

    def now(self) -> datetime:
        return self.clock()


async def _defer_if_paused(
    job: JobExecution,
    context: JobContext,
    loaded: _LoadedRoute,
    *,
    dependencies: TelegramRouteDependencies,
) -> dict[str, Any] | None:
    if not loaded.control.global_pause and loaded.route.paused_at is None:
        return None
    deferred_until = dependencies.now() + timedelta(seconds=max(loaded.route.poll_interval_seconds, 30))
    await _defer_route_job(
        context,
        repository=dependencies.job_repository,
        route=loaded.route,
        job=job,
        scheduled_for=deferred_until,
    )
    await context.session.commit()
    return {
        "held": True,
        "reason": "global_pause" if loaded.control.global_pause else "route_pause",
        "deferred_until": deferred_until.isoformat(),
    }
