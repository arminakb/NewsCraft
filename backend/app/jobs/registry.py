from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.providers.registry import ProviderRegistry
from app.jobs.errors import DuplicateJobHandlerError, UnknownJobTypeError
from app.jobs.types import JobExecution, JobType


@dataclass(frozen=True, slots=True)
class JobContext:
    """Resources owned by one handler invocation.

    The handler may commit, roll back, or expire this session. The runner owns
    session closure and uses different sessions for claim, heartbeat, and
    terminal workflow transitions.
    """

    session: AsyncSession
    providers: ProviderRegistry


# External or material side effects performed by a handler must have a durable
# idempotency key, checkpoint, or ambiguity receipt that makes lease replay safe.
type JobHandler = Callable[[JobExecution, JobContext], Coroutine[Any, Any, dict[str, Any]]]


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: JobType | str, handler: JobHandler) -> None:
        key = str(job_type)
        if key in self._handlers:
            raise DuplicateJobHandlerError(key)
        self._handlers[key] = handler

    def get(self, job_type: JobType | str) -> JobHandler:
        key = str(job_type)
        try:
            return self._handlers[key]
        except KeyError:
            raise UnknownJobTypeError(key) from None

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
    telegram_route_resolver: Any | None = None,
    research_backend_resolver: Any | None = None,
    icon_discovery_service: Any | None = None,
    export_root: str | Path = "/data/exports",
    media_root: str | Path = "/data/media",
) -> JobHandlerRegistry:
    from app.automations.definitions.handler_wrapper import with_automation_projection
    from app.jobs.handlers import handle_ingest_collect, handle_source_collection_continuous_cycle
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
        from app.jobs.canary import SOURCE_GENERATION_CANARY, handle_worker_canary

        registry.register(SOURCE_GENERATION_CANARY, handle_worker_canary)
        registry.register(JobType.INGEST_COLLECT, handle_ingest_collect)
        registry.register(JobType.INGEST_COLLECTION_CONTINUOUS_CYCLE, handle_source_collection_continuous_cycle)
        registry.register(JobType.MANUAL_INTAKE, handle_manual_intake)
        registry.register(JobType.STORY_GROUP_PENDING, group_pending_content)
    if "source" in selected:
        from app.automations.telegram.handlers import build_telegram_route_handlers

        assert source_registry is not None
        assert media_stager is not None
        route_handlers = build_telegram_route_handlers(source_registry, media_stager)
        registry.register(JobType.TELEGRAM_ROUTE_BACKFILL, route_handlers.backfill)
        registry.register(JobType.TELEGRAM_ROUTE_DRY_RUN, with_automation_projection(route_handlers.dry_run))
        registry.register(JobType.TELEGRAM_ROUTE_INITIALIZE, route_handlers.initialize)
        registry.register(JobType.TELEGRAM_ROUTE_POLL, route_handlers.poll)
        if icon_discovery_service is not None:
            from app.sources.icon_discovery import ICON_JOB_TYPE, build_source_icon_discovery_handler

            registry.register(
                ICON_JOB_TYPE,
                build_source_icon_discovery_handler(icon_discovery_service),
            )
    if "generation" in selected:
        from app.automations.definitions.schedule_execution import build_scheduled_automation_handler
        from app.automations.telegram.handlers import build_telegram_process_handler
        from app.exports.handlers import build_export_handler
        from app.generation.canonical_generation import build_canonical_generation_handler
        from app.generation.package_generation import build_pack_generation_handler
        from app.generation.variant_regeneration import build_regenerate_handler
        from app.retention.handlers import build_retention_handler

        registry.register(
            JobType.TELEGRAM_ROUTE_PROCESS,
            with_automation_projection(build_telegram_process_handler(profile_resolver)),
        )
        registry.register(
            JobType.CONTENT_PACK_GENERATE,
            with_automation_projection(build_canonical_generation_handler(profile_resolver)),
        )
        registry.register(
            JobType.CONTENT_PACK_GENERATE_TELEGRAM,
            with_automation_projection(build_pack_generation_handler(profile_resolver)),
        )
        registry.register(JobType.CONTENT_PACK_REGENERATE, build_regenerate_handler(profile_resolver))
        registry.register(
            JobType.AUTOMATION_RUN_START,
            with_automation_projection(build_scheduled_automation_handler(profile_resolver)),
        )
        registry.register(
            JobType.BUILD_EXPORT,
            with_automation_projection(
                build_export_handler(export_root=Path(export_root), media_root=Path(media_root)),
            ),
        )
        registry.register(
            JobType.EXECUTE_RETENTION,
            build_retention_handler(
                export_root=Path(export_root),
                media_root=Path(media_root),
            ),
        )
    if research_backend_resolver is not None:
        from app.research.handlers import build_research_story_handler

        registry.register(
            JobType.RESEARCH_STORY,
            with_automation_projection(build_research_story_handler(research_backend_resolver)),
        )
    if "publishing" in selected:
        from app.jobs.canary import PUBLISHING_CANARY, handle_worker_canary
        from app.publishing.telegram.handlers import build_telegram_publish_handlers

        assert telegram_client is not None
        assert destination_secret_resolver is not None
        publish_handlers = build_telegram_publish_handlers(
            telegram_client,
            destination_secret_resolver,
            route_resolver=telegram_route_resolver,
        )
        registry.register(PUBLISHING_CANARY, handle_worker_canary)
        registry.register(JobType.TELEGRAM_DESTINATION_CHECK, publish_handlers.destination_check)
        registry.register(JobType.TELEGRAM_PROXY_CHECK, publish_handlers.proxy_check)
        registry.register(JobType.TELEGRAM_PUBLISH, with_automation_projection(publish_handlers.publish))
    return registry
