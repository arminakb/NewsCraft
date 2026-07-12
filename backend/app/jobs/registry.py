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


def build_default_registry() -> JobHandlerRegistry:
    from app.jobs.handlers import handle_ingest_collect

    registry = JobHandlerRegistry()
    registry.register("ingest.collect", handle_ingest_collect)
    return registry
