from __future__ import annotations

from dataclasses import fields
from typing import Any, get_type_hints

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.generation.providers.registry import ProviderRegistry
from app.jobs.errors import DuplicateJobHandlerError, UnknownJobTypeError
from app.jobs.models import WorkflowJob
from app.jobs.registry import JobContext, JobHandlerRegistry, build_default_registry


async def _handler(job: WorkflowJob, context: JobContext) -> dict[str, Any]:
    return {"job_id": str(job.id), "provider_names": context.providers.names()}


def test_job_context_has_exact_locked_fields_and_types():
    assert tuple(field.name for field in fields(JobContext)) == ("session", "providers")
    assert get_type_hints(JobContext) == {
        "session": AsyncSession,
        "providers": ProviderRegistry,
    }


def test_job_handler_registry_registers_and_returns_exact_handler():
    registry = JobHandlerRegistry()

    registry.register("custom.run", _handler)

    assert registry.get("custom.run") is _handler
    assert registry.job_types() == ("custom.run",)


def test_job_handler_registry_rejects_duplicate_job_types():
    registry = JobHandlerRegistry()
    registry.register("custom.run", _handler)

    with pytest.raises(DuplicateJobHandlerError, match="custom.run"):
        registry.register("custom.run", _handler)


def test_job_handler_registry_reports_unknown_job_type():
    with pytest.raises(UnknownJobTypeError, match="missing.run"):
        JobHandlerRegistry().get("missing.run")


def test_job_handler_registry_returns_sorted_job_types():
    registry = JobHandlerRegistry()
    registry.register("z.run", _handler)
    registry.register("a.run", _handler)

    assert registry.job_types() == ("a.run", "z.run")


def test_default_registry_contains_only_ingest_collect_without_loading_task_5_handler():
    registry = build_default_registry()

    assert registry.job_types() == ("ingest.collect",)
    assert callable(registry.get("ingest.collect"))


def test_generation_dependency_registers_only_real_telegram_process_handler():
    resolver = object()

    registry = build_default_registry(profile_resolver=resolver)

    assert registry.job_types() == ("ingest.collect", "telegram.route.process")
    assert callable(registry.get("telegram.route.process"))
