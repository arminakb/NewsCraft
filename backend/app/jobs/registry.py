from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.providers.registry import ProviderRegistry
from app.jobs.errors import DuplicateJobHandlerError, UnknownJobTypeError
from app.jobs.models import WorkflowJob


@dataclass(frozen=True, slots=True)
class JobContext:
    session: AsyncSession
    providers: ProviderRegistry


type JobHandler = Callable[[WorkflowJob, JobContext], Awaitable[dict[str, Any]]]


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str, handler: JobHandler) -> None:
        if job_type in self._handlers:
            raise DuplicateJobHandlerError(job_type)
        self._handlers[job_type] = handler

    def get(self, job_type: str) -> JobHandler:
        try:
            return self._handlers[job_type]
        except KeyError:
            raise UnknownJobTypeError(job_type) from None

    def job_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))


def build_default_registry(
    *,
    source_registry: Any | None = None,
    media_stager: Any | None = None,
    profile_resolver: Any | None = None,
) -> JobHandlerRegistry:
    from app.jobs.handlers import handle_ingest_collect

    if (source_registry is None) != (media_stager is None):
        raise ValueError("source_registry and media_stager must be supplied together")

    registry = JobHandlerRegistry()
    registry.register("ingest.collect", handle_ingest_collect)
    if source_registry is not None and media_stager is not None:
        from app.automations.telegram.handlers import build_telegram_route_handlers

        handlers = build_telegram_route_handlers(source_registry, media_stager)
        registry.register("telegram.route.backfill", handlers.backfill)
        registry.register("telegram.route.dry_run", handlers.dry_run)
        registry.register("telegram.route.initialize", handlers.initialize)
        registry.register("telegram.route.poll", handlers.poll)
    if profile_resolver is not None:
        from app.automations.telegram.handlers import build_telegram_process_handler

        registry.register(
            "telegram.route.process",
            build_telegram_process_handler(profile_resolver),
        )
    return registry
