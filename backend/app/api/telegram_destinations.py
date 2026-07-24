from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telegram_schemas import (
    TelegramCheckOut,
    TelegramDestinationAcceptedOut,
    TelegramDestinationCreate,
    TelegramDestinationDependenciesOut,
    TelegramDestinationOut,
    TelegramDestinationPatch,
    TelegramProxyAcceptedOut,
    TelegramProxyCreate,
    TelegramProxyCredentialsIn,
    TelegramProxyDependenciesOut,
    TelegramProxyOut,
    TelegramProxyPatch,
)
from app.core.config import settings
from app.db.session import get_session
from app.generation.revision_fence import public_job_result
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobOrigin
from app.publishing.telegram.lifecycle import (
    TelegramDependencyConflict,
    TelegramLifecycleService,
    destination_out,
    proxy_out,
)
from app.publishing.telegram.routing import TelegramConfigurationError
from app.security.auth import TEST_ADMIN, SecurityPrincipal
from app.security.schemas import SecretWriteIn
from app.security.secret_store import MasterKeyRing, SecretStoreError

router = APIRouter(prefix="/telegram", tags=["telegram"])
SessionDependency = Depends(get_session)


def get_job_repository(session: AsyncSession = SessionDependency) -> JobRepository:
    return JobRepository(session)


def _principal(request: Request) -> SecurityPrincipal:
    principal = getattr(request.state, "security_principal", None)
    if isinstance(principal, SecurityPrincipal):
        return principal
    if settings.app_env == "test":
        return TEST_ADMIN
    if request.method == "GET":
        return SecurityPrincipal("internal_service", "unauthenticated-read", frozenset())
    raise HTTPException(401, detail={"code": "authentication_required"})


def _service(request: Request, session: AsyncSession, *, needs_key: bool) -> TelegramLifecycleService:
    key_ring = None
    if needs_key:
        try:
            key_ring = MasterKeyRing.from_settings(settings)
        except SecretStoreError:
            raise HTTPException(503, detail={"code": "secret_store_unavailable"}) from None
    return TelegramLifecycleService(session, principal=_principal(request), key_ring=key_ring)


def _http_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "telegram_configuration_invalid")
    status = 409 if code.endswith(("_conflict", "_not_ready", "_disabled")) else 422
    if code in {"secret_store_unavailable", "telegram_credential_unavailable"}:
        status = 503
    return HTTPException(status, detail={"code": code})


async def _destination_or_404(
    service: TelegramLifecycleService,
    destination_id: UUID,
    *,
    for_update: bool = False,
):
    destination = await service.get_destination(destination_id, for_update=for_update)
    if destination is None:
        raise HTTPException(404, detail={"code": "telegram_destination_not_found"})
    return destination


async def _proxy_or_404(service: TelegramLifecycleService, profile_id: UUID, *, for_update: bool = False):
    profile = await service.get_proxy(profile_id, for_update=for_update)
    if profile is None:
        raise HTTPException(404, detail={"code": "telegram_proxy_not_found"})
    return profile


async def _enqueue_check(
    session: AsyncSession,
    *,
    job_type: str,
    resource_key: str,
    resource_id: UUID,
) -> JobAcceptedOut:
    result = await JobRepository(session).enqueue_job(
        job_type=job_type,
        payload={resource_key: str(resource_id)},
        idempotency_key=f"{job_type}:{resource_id}:{uuid4()}",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
    )
    return JobAcceptedOut(
        job_id=result.job.id,
        status=result.job.status,
        deduplicated=not result.created,
    )


@router.get("/destinations", response_model=list[TelegramDestinationOut])
async def list_telegram_destinations(request: Request, session: AsyncSession = SessionDependency):
    service = _service(request, session, needs_key=False)
    return [await destination_out(session, item) for item in await service.list_destinations()]


@router.post("/destinations", response_model=TelegramDestinationAcceptedOut, status_code=202)
async def create_telegram_destination(
    body: TelegramDestinationCreate,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=True)
    try:
        destination = await service.create_destination(body)
        destination.telegram_health_status = "checking"
        destination.bot_health_status = "checking"
        destination.target_health_status = "checking"
        destination.administrator_status = "checking"
        if destination.proxy_profile_id is not None:
            destination.proxy_health_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.destination.check",
            resource_key="destination_id",
            resource_id=destination.id,
        )
        await session.commit()
        await session.refresh(destination)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "telegram_destination_conflict"}) from None
    except (TelegramConfigurationError, SecretStoreError, ValueError) as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramDestinationAcceptedOut(destination=await destination_out(session, destination), job=job)


@router.get("/destinations/{destination_id}", response_model=TelegramDestinationOut)
async def get_telegram_destination(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    return await destination_out(session, await _destination_or_404(service, destination_id))


@router.patch("/destinations/{destination_id}", response_model=TelegramDestinationAcceptedOut)
async def patch_telegram_destination(
    destination_id: UUID,
    body: TelegramDestinationPatch,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    try:
        await service.patch_destination(destination, body)
        destination.telegram_health_status = "checking"
        destination.bot_health_status = "checking"
        destination.target_health_status = "checking"
        destination.administrator_status = "checking"
        if destination.proxy_profile_id is not None:
            destination.proxy_health_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.destination.check",
            resource_key="destination_id",
            resource_id=destination.id,
        )
        await session.commit()
        await session.refresh(destination)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "telegram_destination_conflict"}) from None
    except TelegramConfigurationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramDestinationAcceptedOut(destination=await destination_out(session, destination), job=job)


@router.post("/destinations/{destination_id}/rotate-token", response_model=TelegramDestinationAcceptedOut)
async def rotate_telegram_destination_token(
    destination_id: UUID,
    body: SecretWriteIn,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=True)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    try:
        await service.rotate_destination_token(destination, body.secret.get_secret_value())
        destination.telegram_health_status = "checking"
        destination.bot_health_status = "checking"
        destination.target_health_status = "checking"
        destination.administrator_status = "checking"
        if destination.proxy_profile_id is not None:
            destination.proxy_health_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.destination.check",
            resource_key="destination_id",
            resource_id=destination.id,
        )
        await session.commit()
        await session.refresh(destination)
    except (TelegramConfigurationError, SecretStoreError, ValueError) as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramDestinationAcceptedOut(destination=await destination_out(session, destination), job=job)


@router.post("/destinations/{destination_id}/recheck", response_model=TelegramDestinationAcceptedOut)
async def recheck_telegram_destination(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    destination.health_status = "unknown"
    destination.failure_code = None
    destination.telegram_health_status = "checking"
    destination.bot_health_status = "checking"
    destination.target_health_status = "checking"
    destination.administrator_status = "checking"
    destination.proxy_health_status = "direct" if destination.proxy_profile_id is None else "checking"
    job = await _enqueue_check(
        session,
        job_type="telegram.destination.check",
        resource_key="destination_id",
        resource_id=destination.id,
    )
    await session.commit()
    await session.refresh(destination)
    return TelegramDestinationAcceptedOut(destination=await destination_out(session, destination), job=job)


@router.post("/destinations/{destination_id}/enable", response_model=TelegramDestinationOut)
async def enable_telegram_destination(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    try:
        await service.enable_destination(destination)
    except TelegramConfigurationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await session.refresh(destination)
    return await destination_out(session, destination)


@router.post("/destinations/{destination_id}/disable", response_model=TelegramDestinationOut)
async def disable_telegram_destination(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    await service.disable_destination(destination)
    await session.commit()
    await session.refresh(destination)
    return await destination_out(session, destination)


@router.get("/destinations/{destination_id}/dependencies", response_model=TelegramDestinationDependenciesOut)
async def get_telegram_destination_dependencies(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    await _destination_or_404(service, destination_id)
    return await service.destination_dependencies(destination_id)


@router.delete("/destinations/{destination_id}", status_code=204)
async def delete_telegram_destination(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    destination = await _destination_or_404(service, destination_id, for_update=True)
    try:
        await service.delete_destination(destination)
    except TelegramDependencyConflict as exc:
        raise HTTPException(
            409,
            detail={"code": exc.code, "dependencies": exc.dependencies.model_dump()},
        ) from None
    await session.commit()
    return Response(status_code=204)


@router.get("/destination-checks/{job_id}", response_model=TelegramCheckOut)
async def get_telegram_check(job_id: UUID, session: AsyncSession = SessionDependency):
    job = await session.get(WorkflowJob, job_id)
    if job is None or job.job_type not in {"telegram.destination.check", "telegram.proxy.check"}:
        raise HTTPException(404, detail={"code": "telegram_check_not_found"})
    resource_type = "destination" if job.job_type == "telegram.destination.check" else "proxy"
    key = f"{resource_type}_id"
    try:
        resource_id = UUID(str(job.payload[key]))
    except (KeyError, TypeError, ValueError):
        raise HTTPException(409, detail={"code": "telegram_check_payload_invalid"}) from None
    return TelegramCheckOut(
        job_id=job.id,
        resource_type=resource_type,
        resource_id=resource_id,
        status=str(job.status.value if hasattr(job.status, "value") else job.status),
        progress=job.progress,
        progress_message=job.progress_message,
        error_code=job.error_code,
        result=public_job_result(job.result),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/proxies", response_model=list[TelegramProxyOut])
async def list_telegram_proxies(request: Request, session: AsyncSession = SessionDependency):
    service = _service(request, session, needs_key=False)
    return [await proxy_out(session, item) for item in await service.list_proxies()]


@router.post("/proxies", response_model=TelegramProxyAcceptedOut, status_code=202)
async def create_telegram_proxy(
    body: TelegramProxyCreate,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=body.username is not None)
    try:
        profile = await service.create_proxy(body)
        profile.reachability_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.proxy.check",
            resource_key="proxy_id",
            resource_id=profile.id,
        )
        await session.commit()
        await session.refresh(profile)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "telegram_proxy_name_conflict"}) from None
    except (TelegramConfigurationError, SecretStoreError, ValueError) as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramProxyAcceptedOut(proxy=await proxy_out(session, profile), job=job)


@router.get("/proxies/{profile_id}", response_model=TelegramProxyOut)
async def get_telegram_proxy(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    return await proxy_out(session, await _proxy_or_404(service, profile_id))


@router.patch("/proxies/{profile_id}", response_model=TelegramProxyAcceptedOut)
async def patch_telegram_proxy(
    profile_id: UUID,
    body: TelegramProxyPatch,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    try:
        await service.patch_proxy(profile, body)
        profile.reachability_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.proxy.check",
            resource_key="proxy_id",
            resource_id=profile.id,
        )
        await session.commit()
        await session.refresh(profile)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "telegram_proxy_name_conflict"}) from None
    except TelegramConfigurationError as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramProxyAcceptedOut(proxy=await proxy_out(session, profile), job=job)


@router.post("/proxies/{profile_id}/rotate-credentials", response_model=TelegramProxyAcceptedOut)
async def rotate_telegram_proxy_credentials(
    profile_id: UUID,
    body: TelegramProxyCredentialsIn,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=body.username is not None)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    try:
        await service.rotate_proxy_credentials(profile, body)
        profile.reachability_status = "checking"
        job = await _enqueue_check(
            session,
            job_type="telegram.proxy.check",
            resource_key="proxy_id",
            resource_id=profile.id,
        )
        await session.commit()
        await session.refresh(profile)
    except (TelegramConfigurationError, SecretStoreError, ValueError) as exc:
        await session.rollback()
        raise _http_error(exc) from None
    return TelegramProxyAcceptedOut(proxy=await proxy_out(session, profile), job=job)


@router.post("/proxies/{profile_id}/recheck", response_model=TelegramProxyAcceptedOut)
async def recheck_telegram_proxy(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    profile.reachability_status = "checking"
    profile.failure_code = None
    job = await _enqueue_check(
        session,
        job_type="telegram.proxy.check",
        resource_key="proxy_id",
        resource_id=profile.id,
    )
    await session.commit()
    await session.refresh(profile)
    return TelegramProxyAcceptedOut(proxy=await proxy_out(session, profile), job=job)


@router.post("/proxies/{profile_id}/enable", response_model=TelegramProxyOut)
async def enable_telegram_proxy(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    try:
        await service.enable_proxy(profile)
    except TelegramConfigurationError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await session.refresh(profile)
    return await proxy_out(session, profile)


@router.post("/proxies/{profile_id}/disable", response_model=TelegramProxyOut)
async def disable_telegram_proxy(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    await service.disable_proxy(profile)
    await session.commit()
    await session.refresh(profile)
    return await proxy_out(session, profile)


@router.get("/proxies/{profile_id}/dependencies", response_model=TelegramProxyDependenciesOut)
async def get_telegram_proxy_dependencies(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    await _proxy_or_404(service, profile_id)
    return await service.proxy_dependencies(profile_id)


@router.delete("/proxies/{profile_id}", status_code=204)
async def delete_telegram_proxy(
    profile_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    profile = await _proxy_or_404(service, profile_id, for_update=True)
    try:
        await service.delete_proxy(profile)
    except TelegramDependencyConflict as exc:
        raise HTTPException(
            409,
            detail={"code": exc.code, "dependencies": exc.dependencies.model_dump()},
        ) from None
    await session.commit()
    return Response(status_code=204)


__all__ = ["get_job_repository", "router"]
