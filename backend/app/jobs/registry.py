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
    capabilities: tuple[str, ...] | None = None,
    source_registry: Any | None = None,
    media_stager: Any | None = None,
    profile_resolver: Any | None = None,
    telegram_client: Any | None = None,
    destination_secret_resolver: Any | None = None,
    research_backend_resolver: Any | None = None,
) -> JobHandlerRegistry:
    from app.jobs.handlers import handle_ingest_collect
    from app.stories.handlers import group_pending_content, handle_manual_intake

    if capabilities is None:
        selected = {"ingestion"}
        if source_registry is not None or media_stager is not None:
            selected.add("source")
        if profile_resolver is not None:
            selected.add("generation")
        if telegram_client is not None or destination_secret_resolver is not None:
            selected.add("publishing")
    else:
        selected = set(capabilities)
    unknown = selected - {"ingestion", "source", "generation", "publishing"}
    if unknown:
        raise ValueError(f"unsupported worker capabilities: {', '.join(sorted(unknown))}")
    if (source_registry is None) != (media_stager is None):
        raise ValueError("source_registry and media_stager must be supplied together")
    if (telegram_client is None) != (destination_secret_resolver is None):
        raise ValueError("telegram_client and destination_secret_resolver must be supplied together")
    if "source" in selected and source_registry is None:
        raise ValueError("source capability requires source_registry and media_stager")
    if "generation" in selected and profile_resolver is None:
        raise ValueError("generation capability requires profile_resolver")
    if "publishing" in selected and telegram_client is None:
        raise ValueError("publishing capability requires telegram_client and destination_secret_resolver")

    registry = JobHandlerRegistry()
    if "ingestion" in selected:
        registry.register("ingest.collect", handle_ingest_collect)
        registry.register("manual_intake", handle_manual_intake)
        registry.register("story.group_pending", group_pending_content)
    if "source" in selected:
        from app.automations.telegram.handlers import build_telegram_route_handlers

        handlers = build_telegram_route_handlers(source_registry, media_stager)
        registry.register("telegram.route.backfill", handlers.backfill)
        registry.register("telegram.route.dry_run", handlers.dry_run)
        registry.register("telegram.route.initialize", handlers.initialize)
        registry.register("telegram.route.poll", handlers.poll)
    if "generation" in selected:
        from app.automations.telegram.handlers import build_telegram_process_handler

        registry.register(
            "telegram.route.process",
            build_telegram_process_handler(profile_resolver),
        )
    if research_backend_resolver is not None:
        from app.research.handlers import build_research_story_handler

        registry.register(
            "research_story",
            build_research_story_handler(research_backend_resolver),
        )
    if "publishing" in selected:
        from app.publishing.telegram.handlers import build_telegram_publish_handlers

        handlers = build_telegram_publish_handlers(telegram_client, destination_secret_resolver)
        registry.register("telegram.destination.check", handlers.destination_check)
        registry.register("telegram.publish", handlers.publish)
    return registry
