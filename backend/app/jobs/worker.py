from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import signal
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.logging import configure_logging
from app.core.outbound_proxy import (
    OutboundProxyPolicy,
    build_outbound_http_client,
    safe_proxy_diagnostics,
    telethon_proxy_from_policy,
)
from app.core.secrets import SecretResolver, build_worker_secret_resolver
from app.db.session import async_session
from app.generation.providers.registry import ProviderRegistry, build_default_provider_registry
from app.jobs.credential_capabilities import WorkerCredentialCapabilityObserver
from app.jobs.errors import (
    NeedsReviewJobError,
    PermanentJobError,
    RetryableJobError,
    UnknownJobTypeError,
)
from app.jobs.registry import JobContext, JobHandlerRegistry, build_default_registry
from app.jobs.repository import JobRepository
from app.jobs.runtime import RuntimeHeartbeatService, build_component_id
from app.jobs.types import JobErrorClass, JobExecution

logger = logging.getLogger(__name__)

RepositoryFactory = Callable[[AsyncSession], JobRepository]
RuntimeServiceFactory = Callable[[AsyncSession], RuntimeHeartbeatService]
CAPABILITY_CHOICES = ("ingestion", "source", "generation", "publishing")


@dataclass(frozen=True, slots=True)
class _InvalidClaim:
    job_id: UUID
    job_type: str
    attempt_count: int


class HttpClientOwner:
    def __init__(
        self,
        *,
        client_factory: Callable[..., Any] | None = None,
        proxy_policy: OutboundProxyPolicy | None = None,
        max_clients: int = 16,
    ) -> None:
        if max_clients <= 0:
            raise ValueError("max_clients must be positive")
        self.client_factory = client_factory or build_outbound_http_client
        self.proxy_policy = (
            proxy_policy
            if proxy_policy is not None
            else (OutboundProxyPolicy.from_environment() if client_factory is None else None)
        )
        self._inject_proxy_policy = client_factory is None
        self.max_clients = max_clients
        self._clients: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}

    def get(self, purpose: str, **configuration: Any) -> Any:
        if self._inject_proxy_policy:
            configuration = {"policy": self.proxy_policy, **configuration}
        key = (purpose, tuple(sorted((name, repr(value)) for name, value in configuration.items())))
        existing = self._clients.get(key)
        if existing is not None:
            return existing
        if len(self._clients) >= self.max_clients:
            raise RuntimeError("HTTP client configuration limit exceeded")
        client = self.client_factory(**configuration)
        self._clients[key] = client
        return client

    async def aclose(self) -> None:
        clients = tuple(self._clients.values())
        self._clients.clear()
        failure: BaseException | None = None
        for client in clients:
            try:
                await client.aclose()
            except BaseException as exc:  # noqa: BLE001 - close every owned client before propagating
                failure = failure or exc
        if failure is not None:
            raise failure


class _TelegramMediaStager:
    def __init__(self) -> None:
        from app.automations.telegram.media import TelegramMediaStore

        self.staging_root = Path(settings.telegram_media_staging_root)
        self.media_store = TelegramMediaStore(
            Path(settings.media_root),
            max_photo_bytes=settings.telegram_max_photo_bytes,
            max_file_bytes=settings.telegram_max_file_bytes,
        )

    async def materialize(self, adapter: Any, envelope: Any) -> tuple[Any, ...]:
        self.staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(tempfile.mkdtemp(prefix="telegram-", dir=self.staging_root))
        try:
            materialized = tuple(await adapter.materialize_media(envelope, staging_dir))
        except BaseException:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        if not materialized:
            shutil.rmtree(staging_dir, ignore_errors=True)
        return materialized

    def capture_repository(self, session: AsyncSession) -> Any:
        from app.automations.telegram.repository import TelegramCaptureRepository

        return TelegramCaptureRepository(session, media_store=self.media_store)

    @staticmethod
    def cleanup(materialized: tuple[Any, ...]) -> None:
        from app.automations.telegram.repository import TelegramCaptureRepository

        staging_dirs = {item.path.parent for item in materialized}
        TelegramCaptureRepository.cleanup_staged_media(materialized)
        for staging_dir in staging_dirs:
            shutil.rmtree(staging_dir, ignore_errors=True)


def _build_source_dependencies(owner: HttpClientOwner, secrets: SecretResolver) -> dict[str, Any]:
    from telethon import TelegramClient

    from app.automations.telegram.mtproto import MtprotoTelegramAdapter
    from app.automations.telegram.public_html import PublicHtmlTelegramAdapter
    from app.automations.telegram.registry import TelegramSourceRegistry

    proxy_policy = getattr(owner, "proxy_policy", None) or OutboundProxyPolicy.from_environment({})
    mtproto_proxy = telethon_proxy_from_policy(proxy_policy)

    def build_telegram_client(**configuration: Any) -> Any:
        if mtproto_proxy is not None:
            configuration["proxy"] = mtproto_proxy
        return TelegramClient(**configuration)

    if settings.telegram_acceptance_fixture_path:
        from app.automations.telegram.acceptance_fixture import (
            TelegramAcceptanceFixtureTransport,
        )

        public_html_client = owner.get(
            "telegram-public-html-acceptance",
            timeout=30.0,
            follow_redirects=True,
            transport=TelegramAcceptanceFixtureTransport(settings.telegram_acceptance_fixture_path),
        )
    else:
        public_html_client = owner.get(
            "telegram-public-html",
            timeout=30.0,
            follow_redirects=True,
        )

    source_registry = TelegramSourceRegistry()
    source_registry.register(
        "public_html",
        PublicHtmlTelegramAdapter(public_html_client),
    )
    source_registry.register(
        "mtproto_user",
        MtprotoTelegramAdapter(
            secret_resolver=secrets,
            client_factory=build_telegram_client,
        ),
    )
    return {"source_registry": source_registry, "media_stager": _TelegramMediaStager()}


def _build_generation_dependencies(owner: HttpClientOwner, secrets: SecretResolver) -> dict[str, Any]:
    from app.generation.providers.registry import build_provider_profile_resolver

    profile_resolver = build_provider_profile_resolver(
        secret_resolver=secrets,
        http_client_factory=lambda **kwargs: owner.get(
            "openrouter",
            base_url=kwargs["base_url"],
            timeout=kwargs["timeout_seconds"],
        ),
    )
    from app.research.handlers import DefaultResearchBackendResolver

    return {
        "profile_resolver": profile_resolver,
        "research_backend_resolver": DefaultResearchBackendResolver(profile_resolver),
        "export_root": Path(settings.export_root),
        "media_root": Path(settings.media_root),
    }


def _build_publishing_dependencies(owner: HttpClientOwner, secrets: SecretResolver) -> dict[str, Any]:
    from app.publishing.telegram.client import TelegramBotClient

    return {
        "telegram_client": TelegramBotClient(
            owner.get(
                "telegram-bot",
                timeout=30.0,
                follow_redirects=True,
            )
        ),
        "destination_secret_resolver": secrets,
    }


def parse_capabilities(argv: list[str] | None = None) -> tuple[str, ...]:
    parser = argparse.ArgumentParser(description="Run a capability-scoped NewsCraft worker")
    parser.add_argument(
        "--capability",
        action="append",
        choices=CAPABILITY_CHOICES,
        required=True,
    )
    arguments = parser.parse_args(argv)
    return tuple(dict.fromkeys(arguments.capability))


def build_worker_runner(
    capabilities: tuple[str, ...],
    resource_owner: HttpClientOwner | None = None,
) -> WorkerRunner:
    owner = resource_owner or HttpClientOwner()
    secrets = build_worker_secret_resolver(
        app_env=settings.app_env,
        secret_root=settings.worker_secret_root,
    )
    dependencies: dict[str, Any] = {}
    if "source" in capabilities:
        dependencies.update(_build_source_dependencies(owner, secrets))
    if "generation" in capabilities:
        dependencies.update(_build_generation_dependencies(owner, secrets))
    if "publishing" in capabilities:
        dependencies.update(_build_publishing_dependencies(owner, secrets))
    registry = build_default_registry(capabilities=capabilities, **dependencies)
    return WorkerRunner(
        handler_registry=registry,
        capabilities=capabilities,
        resource_owner=owner,
        secret_resolver=secrets,
    )


class WorkerRunner:
    """Run jobs across isolated claim, handler, heartbeat, and terminal sessions."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] = async_session,
        handler_registry: JobHandlerRegistry | None = None,
        provider_registry: ProviderRegistry | None = None,
        repository_factory: RepositoryFactory = JobRepository,
        runtime_service_factory: RuntimeServiceFactory = RuntimeHeartbeatService,
        resource_owner: HttpClientOwner | None = None,
        secret_resolver: SecretResolver | None = None,
        worker_id: str | None = None,
        capabilities: tuple[str, ...] = ("generation", "ingestion", "source"),
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = settings.worker_lease_seconds,
        heartbeat_seconds: float = settings.worker_heartbeat_seconds,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.handler_registry = handler_registry or build_default_registry()
        self.provider_registry = provider_registry or build_default_provider_registry()
        self.repository_factory = repository_factory
        self.runtime_service_factory = runtime_service_factory
        self.resource_owner = resource_owner
        self.secret_resolver = secret_resolver
        self.worker_id = worker_id or build_component_id("worker")
        self.capabilities = tuple(sorted(set(capabilities)))
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.fault_injector = fault_injector if fault_injector is not None else NoopFaultInjector()
        self._process_instance_id = uuid4().hex
        self._process_started_at = self._now()
        self._runtime_heartbeat_managed = False
        self._active_work_type: str | None = None
        self._active_work_started_at: datetime | None = None
        self._last_loop_success_at: datetime | None = None

    async def run_once(self) -> bool:
        observed_at = self._now()
        if not self._runtime_heartbeat_managed:
            await self._record_runtime_heartbeat(observed_at)
        execution, invalid_claim = await self._claim_execution(observed_at)
        if execution is None:
            if invalid_claim is None:
                await self._record_loop_success()
                return False
            await self._fail_invalid_claim(invalid_claim)
            await self._record_loop_success()
            return True

        self._active_work_type = execution.job_type
        self._active_work_started_at = observed_at

        await self.fault_injector.hit(
            "worker.after_claim",
            {
                "job_id": execution.id,
                "job_type": execution.job_type,
                "worker_id": execution.lease_owner,
                "attempt_count": execution.attempt_count,
            },
        )

        stop_heartbeat = asyncio.Event()
        heartbeat_started = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._lease_heartbeat_loop(execution.id, stop_heartbeat, heartbeat_started),
            name=f"job-heartbeat:{execution.id}",
        )
        await heartbeat_started.wait()
        if heartbeat_task.done():
            await heartbeat_task

        try:
            result, failure, cancellation = await self._execute_handler(execution)
        finally:
            stop_heartbeat.set()
            await heartbeat_task

        completion_time = self._now()
        await self.fault_injector.hit(
            "worker.after_handler_before_terminal",
            {
                "job_id": execution.id,
                "job_type": execution.job_type,
                "worker_id": execution.lease_owner,
                "attempt_count": execution.attempt_count,
                "handler_outcome": "succeeded" if failure is None else "failed",
            },
        )
        if failure is None:
            await self._finish_execution(execution, result or {}, completion_time)
            await self._hit_after_terminal(execution, terminal_state="succeeded")
            logger.info(
                "job completed id=%s type=%s state=succeeded attempt=%s",
                execution.id,
                execution.job_type,
                execution.attempt_count,
            )
        else:
            error_class, error_code, error_message, requested_retry_at = failure
            retry_at = (
                requested_retry_at or completion_time + timedelta(seconds=30)
                if error_class == JobErrorClass.RETRYABLE
                else None
            )
            await self._fail_execution(
                execution,
                error_class=error_class,
                error_code=error_code,
                error_message=error_message,
                retry_at=retry_at,
                now=completion_time,
            )
            await self._hit_after_terminal(execution, terminal_state="failed")
            logger.warning(
                "job failed id=%s type=%s state=failed attempt=%s error_code=%s",
                execution.id,
                execution.job_type,
                execution.attempt_count,
                error_code,
            )
        if cancellation is not None:
            raise cancellation
        await self._record_loop_success()
        return True

    async def _hit_after_terminal(self, execution: JobExecution, *, terminal_state: str) -> None:
        await self.fault_injector.hit(
            "worker.after_terminal_commit",
            {
                "job_id": execution.id,
                "job_type": execution.job_type,
                "worker_id": execution.lease_owner,
                "attempt_count": execution.attempt_count,
                "terminal_state": terminal_state,
            },
        )

    async def _claim_execution(self, observed_at: datetime) -> tuple[JobExecution | None, _InvalidClaim | None]:
        async with self.session_factory() as session:
            repository = self.repository_factory(session)
            job = await repository.claim_next_job(
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
                allowed_job_types=self.handler_registry.job_types(),
                now=observed_at,
            )
            if job is None:
                await session.commit()
                return None, None
            try:
                execution = JobExecution.from_job(job)
            except TypeError, ValueError:
                invalid_claim = _InvalidClaim(
                    job_id=job.id,
                    job_type=str(job.job_type),
                    attempt_count=int(job.attempt_count),
                )
                await session.commit()
                return None, invalid_claim
            if execution.lease_owner != self.worker_id:
                invalid_claim = _InvalidClaim(
                    job_id=execution.id,
                    job_type=execution.job_type,
                    attempt_count=execution.attempt_count,
                )
                await session.commit()
                return None, invalid_claim
            await session.commit()
            return execution, None

    async def _execute_handler(
        self,
        execution: JobExecution,
    ) -> tuple[
        dict[str, Any] | None,
        tuple[JobErrorClass, str, str, datetime | None] | None,
        asyncio.CancelledError | None,
    ]:
        cancellation: asyncio.CancelledError | None = None
        result: dict[str, Any] | None = None
        failure: tuple[JobErrorClass, str, str, datetime | None] | None = None
        async with self.session_factory() as session:
            try:
                try:
                    handler = self.handler_registry.get(execution.job_type)
                except UnknownJobTypeError:
                    raise PermanentJobError(
                        code="unknown_job_type", message="No handler is registered for this job type"
                    ) from None
                handler_task = asyncio.create_task(
                    handler(execution, JobContext(session=session, providers=self.provider_registry)),
                    name=f"job-handler:{execution.id}",
                )
                try:
                    result = await asyncio.shield(handler_task)
                except asyncio.CancelledError as exc:
                    cancellation = exc
                    result = await handler_task
                await session.commit()
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
            if failure is not None:
                await session.rollback()
        return result, failure, cancellation

    async def _finish_execution(
        self,
        execution: JobExecution,
        result: dict[str, Any],
        now: datetime,
    ) -> None:
        async with self.session_factory() as session:
            await self.repository_factory(session).finish_job(
                job_id=execution.id,
                worker_id=execution.lease_owner,
                result=result,
                now=now,
            )
            await session.commit()

    async def _fail_execution(
        self,
        execution: JobExecution,
        *,
        error_class: JobErrorClass,
        error_code: str,
        error_message: str,
        retry_at: datetime | None,
        now: datetime,
    ) -> None:
        async with self.session_factory() as session:
            await self.repository_factory(session).fail_job(
                job_id=execution.id,
                worker_id=execution.lease_owner,
                error_class=error_class,
                error_code=error_code,
                error_message=error_message,
                retry_at=retry_at,
                now=now,
            )
            await session.commit()

    async def _fail_invalid_claim(self, claim: _InvalidClaim) -> None:
        completion_time = self._now()
        async with self.session_factory() as session:
            await self.repository_factory(session).fail_job(
                job_id=claim.job_id,
                worker_id=self.worker_id,
                error_class=JobErrorClass.PERMANENT,
                error_code="job_execution_invalid",
                error_message="Claimed job could not be materialized safely",
                retry_at=None,
                now=completion_time,
            )
            await session.commit()
        logger.warning(
            "job failed id=%s type=%s state=failed attempt=%s error_code=job_execution_invalid",
            claim.job_id,
            claim.job_type,
            claim.attempt_count,
        )

    async def _record_runtime_heartbeat(self, observed_at: datetime) -> None:
        async with self.session_factory() as session:
            metadata = self._runtime_metadata()
            if self.secret_resolver is not None:
                observations = await WorkerCredentialCapabilityObserver(
                    session,
                    secret_resolver=self.secret_resolver,
                ).observe(self.capabilities)
                metadata["external_capabilities"] = [
                    observation.model_dump(mode="json") for observation in observations
                ]
            await self.runtime_service_factory(session).record(
                component_id=self.worker_id,
                component_type="worker",
                capabilities=self.capabilities,
                observed_at=observed_at,
                metadata=metadata,
            )
            await session.commit()

    def _runtime_metadata(self) -> dict[str, object]:
        return {
            "job_types": list(self.handler_registry.job_types()),
            "state": "working" if self._active_work_type is not None else "idle",
            "active_work_type": self._active_work_type,
            "active_work_started_at": (
                self._active_work_started_at.isoformat() if self._active_work_started_at is not None else None
            ),
            "last_success_at": (
                self._last_loop_success_at.isoformat() if self._last_loop_success_at is not None else None
            ),
            "process_instance_id": self._process_instance_id,
            "process_started_at": self._process_started_at.isoformat(),
            "outbound_proxy": safe_proxy_diagnostics().model_dump(mode="json"),
        }

    async def _record_loop_success(self) -> None:
        self._last_loop_success_at = self._now()
        self._active_work_type = None
        self._active_work_started_at = None
        if not self._runtime_heartbeat_managed:
            await self._record_runtime_heartbeat(self._last_loop_success_at)

    async def _runtime_heartbeat_loop(
        self,
        stop: asyncio.Event,
        started: asyncio.Event,
    ) -> None:
        try:
            while not stop.is_set():
                try:
                    await self._record_runtime_heartbeat(self._now())
                except Exception:  # noqa: BLE001 - a later heartbeat retries independently
                    logger.exception("runtime heartbeat failed component=%s", self.worker_id)
                finally:
                    started.set()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_seconds)
                except TimeoutError:
                    pass
        finally:
            started.set()

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
                        observed_at = self._now()
                        await self.fault_injector.hit(
                            "worker.before_heartbeat",
                            {
                                "job_id": job_id,
                                "worker_id": self.worker_id,
                                "lease_seconds": self.lease_seconds,
                                "observed_at": observed_at,
                            },
                        )
                        await self.repository_factory(session).heartbeat_job(
                            job_id=job_id,
                            worker_id=self.worker_id,
                            lease_seconds=self.lease_seconds,
                            now=observed_at,
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
        runtime_stop = asyncio.Event()
        runtime_started = asyncio.Event()
        self._runtime_heartbeat_managed = True
        runtime_task = asyncio.create_task(
            self._runtime_heartbeat_loop(runtime_stop, runtime_started),
            name=f"runtime-heartbeat:{self.worker_id}",
        )
        await runtime_started.wait()
        if runtime_task.done():
            await runtime_task
        try:
            while not stop_event.is_set():
                handled = await self.run_once()
                if handled:
                    continue
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=settings.worker_poll_seconds)
                except TimeoutError:
                    pass
        finally:
            runtime_stop.set()
            await runtime_task
            self._runtime_heartbeat_managed = False

    async def close(self) -> None:
        if self.resource_owner is not None:
            await self.resource_owner.aclose()


async def run_worker(capabilities: tuple[str, ...]) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    owner = HttpClientOwner()
    runner: WorkerRunner | None = None
    try:
        runner = build_worker_runner(capabilities, owner)
        await runner.run_forever(stop=stop)
    finally:
        if runner is None:
            await owner.aclose()
        else:
            await runner.close()


def main() -> None:
    configure_logging()
    asyncio.run(run_worker(parse_capabilities()))


if __name__ == "__main__":
    main()
