from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.session import async_session
from app.generation.providers.registry import ProviderRegistry, build_default_provider_registry
from app.jobs.errors import (
    NeedsReviewJobError,
    PermanentJobError,
    RetryableJobError,
    UnknownJobTypeError,
)
from app.jobs.registry import JobContext, JobHandlerRegistry, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.runtime import RuntimeHeartbeatService, build_component_id
from app.jobs.types import JobErrorClass

logger = logging.getLogger(__name__)

RepositoryFactory = Callable[[AsyncSession], JobRepository]
RuntimeServiceFactory = Callable[[AsyncSession], RuntimeHeartbeatService]


class WorkerRunner:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = async_session,
        handler_registry: JobHandlerRegistry | None = None,
        provider_registry: ProviderRegistry | None = None,
        repository_factory: RepositoryFactory = JobRepository,
        runtime_service_factory: RuntimeServiceFactory = RuntimeHeartbeatService,
        worker_id: str | None = None,
        capabilities: tuple[str, ...] = ("generation", "ingestion", "source"),
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = settings.worker_lease_seconds,
        heartbeat_seconds: float = settings.worker_heartbeat_seconds,
    ) -> None:
        self.session_factory = session_factory
        self.handler_registry = handler_registry or build_default_registry()
        self.provider_registry = provider_registry or build_default_provider_registry()
        self.repository_factory = repository_factory
        self.runtime_service_factory = runtime_service_factory
        self.worker_id = worker_id or build_component_id("worker")
        self.capabilities = tuple(sorted(set(capabilities)))
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds

    async def run_once(self, allowed_job_types: tuple[str, ...] | None = None) -> bool:
        observed_at = self._now()
        await self._record_runtime_heartbeat(observed_at)

        async with self.session_factory() as session:
            repository = self.repository_factory(session)
            job = await repository.claim_next_job(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                allowed_job_types=allowed_job_types,
                now=observed_at,
            )
            await session.commit()
            if job is None:
                return False

            stop_heartbeat = asyncio.Event()
            heartbeat_started = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                self._lease_heartbeat_loop(job.id, stop_heartbeat, heartbeat_started),
                name=f"job-heartbeat:{job.id}",
            )
            await heartbeat_started.wait()

            cancellation: asyncio.CancelledError | None = None
            result: dict[str, Any] | None = None
            failure: tuple[JobErrorClass, str, str, datetime | None] | None = None
            try:
                try:
                    handler = self.handler_registry.get(job.job_type)
                except UnknownJobTypeError:
                    raise PermanentJobError(
                        code="unknown_job_type", message="No handler is registered for this job type"
                    ) from None

                handler_task = asyncio.create_task(
                    handler(job, JobContext(session=session, providers=self.provider_registry)),
                    name=f"job-handler:{job.id}",
                )
                try:
                    result = await asyncio.shield(handler_task)
                except asyncio.CancelledError as exc:
                    cancellation = exc
                    result = await handler_task
            except RetryableJobError as exc:
                failure = (JobErrorClass.RETRYABLE, exc.code, exc.message, exc.retry_at)
            except NeedsReviewJobError as exc:
                failure = (JobErrorClass.NEEDS_REVIEW, exc.code, exc.message, None)
            except PermanentJobError as exc:
                failure = (JobErrorClass.PERMANENT, exc.code, exc.message, None)
            except Exception:  # noqa: BLE001 - boundary maps unknown failures without leaking details
                failure = (
                    JobErrorClass.RETRYABLE,
                    "unhandled_exception",
                    "Unhandled job handler exception",
                    None,
                )
            finally:
                stop_heartbeat.set()
                await heartbeat_task

            completion_time = self._now()
            if failure is None:
                await repository.finish_job(
                    job_id=job.id,
                    worker_id=self.worker_id,
                    result=result or {},
                    now=completion_time,
                )
                logger.info(
                    "job completed id=%s type=%s state=succeeded attempt=%s",
                    job.id,
                    job.job_type,
                    job.attempt_count,
                )
            else:
                error_class, error_code, error_message, requested_retry_at = failure
                retry_at = (
                    requested_retry_at or completion_time + timedelta(seconds=30)
                    if error_class == JobErrorClass.RETRYABLE
                    else None
                )
                await repository.fail_job(
                    job_id=job.id,
                    worker_id=self.worker_id,
                    error_class=error_class,
                    error_code=error_code,
                    error_message=error_message,
                    retry_at=retry_at,
                    now=completion_time,
                )
                logger.warning(
                    "job failed id=%s type=%s state=failed attempt=%s error_code=%s",
                    job.id,
                    job.job_type,
                    job.attempt_count,
                    error_code,
                )
            await session.commit()
            if cancellation is not None:
                raise cancellation
            return True

    async def _record_runtime_heartbeat(self, observed_at: datetime) -> None:
        async with self.session_factory() as session:
            await self.runtime_service_factory(session).record(
                component_id=self.worker_id,
                component_type="worker",
                capabilities=self.capabilities,
                observed_at=observed_at,
                metadata={},
            )
            await session.commit()

    async def _lease_heartbeat_loop(
        self,
        job_id,
        stop: asyncio.Event,
        started: asyncio.Event,
    ) -> None:
        try:
            while not stop.is_set():
                try:
                    async with self.session_factory() as session:
                        await self.repository_factory(session).heartbeat_job(
                            job_id=job_id,
                            worker_id=self.worker_id,
                            lease_seconds=self.lease_seconds,
                            now=self._now(),
                        )
                        await session.commit()
                except Exception:  # noqa: BLE001 - transient heartbeat failures are retried
                    logger.exception("job heartbeat failed id=%s", job_id)
                finally:
                    started.set()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_seconds)
                except TimeoutError:
                    pass
        finally:
            started.set()

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("worker clock must return a timezone-aware datetime")
        return value

    async def run_forever(self, *, stop: asyncio.Event | None = None) -> None:
        stop_event = stop or asyncio.Event()
        await self._record_runtime_heartbeat(self._now())
        while not stop_event.is_set():
            handled = await self.run_once(allowed_job_types=self.handler_registry.job_types())
            if handled:
                continue
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass


async def run_worker() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await WorkerRunner().run_forever(stop=stop)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
