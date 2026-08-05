from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.llm_providers.schemas import (
    LLMProviderCreate,
    LLMProviderDependenciesOut,
    LLMProviderOut,
    LLMProviderPatch,
)
from app.llm_providers.service import LLMProviderService, ProviderDependencyConflict, provider_out
from app.security.auth import TEST_ADMIN, SecurityPrincipal
from app.security.schemas import SecretWriteIn
from app.security.secret_store import (
    SecretStoreError,
    SecretStoreRuntime,
    SecretStoreUnavailable,
    classify_secret_store_error,
)

router = APIRouter(prefix="/llm-providers", tags=["llm-providers"])
SessionDependency = Depends(get_session)


def _principal(request: Request) -> SecurityPrincipal:
    principal = getattr(request.state, "security_principal", None)
    if isinstance(principal, SecurityPrincipal):
        return principal
    if settings.app_env == "test":
        return TEST_ADMIN
    if request.method == "GET":
        return SecurityPrincipal("internal_service", "unauthenticated-read", frozenset())
    raise HTTPException(401, detail={"code": "authentication_required"})


def _service(
    request: Request,
    session: AsyncSession,
    *,
    needs_key: bool,
) -> LLMProviderService:
    secret_store = None
    if needs_key:
        try:
            runtime = getattr(request.app.state, "secret_store_runtime", None)
            if settings.app_env == "test":
                runtime = SecretStoreRuntime.from_settings(settings)
            if not isinstance(runtime, SecretStoreRuntime):
                raise SecretStoreUnavailable
            secret_store = runtime.bind(session)
        except SecretStoreError as exc:
            raise HTTPException(503, detail={"code": exc.public_code}) from None
    return LLMProviderService(
        session,
        principal=_principal(request),
        secret_store=secret_store,
        config=settings,
    )


async def _provider_or_404(service: LLMProviderService, provider_id: UUID, *, for_update: bool = False):
    provider = await service.get(provider_id, for_update=for_update)
    if provider is None:
        raise HTTPException(404, detail={"code": "llm_provider_not_found"})
    return provider


@router.get("", response_model=list[LLMProviderOut])
async def list_llm_providers(request: Request, session: AsyncSession = SessionDependency):
    service = _service(request, session, needs_key=False)
    return [provider_out(provider) for provider in await service.list()]


@router.post("", response_model=LLMProviderOut, status_code=201)
async def create_llm_provider(
    body: LLMProviderCreate,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=body.protocol == "openai_compatible")
    try:
        provider = await service.create(body)
        await session.commit()
        await session.refresh(provider)
    except SecretStoreError as exc:
        await session.rollback()
        raise HTTPException(503, detail={"code": exc.public_code}) from None
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "llm_provider_name_conflict"}) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        failure = classify_secret_store_error(exc)
        raise HTTPException(503, detail={"code": failure.public_code}) from None
    except ValueError:
        await session.rollback()
        raise HTTPException(422, detail={"code": "llm_provider_invalid"}) from None
    return provider_out(provider)


@router.get("/{provider_id}", response_model=LLMProviderOut)
async def get_llm_provider(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    return provider_out(await _provider_or_404(service, provider_id))


@router.patch("/{provider_id}", response_model=LLMProviderOut)
async def patch_llm_provider(
    provider_id: UUID,
    body: LLMProviderPatch,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    provider = await _provider_or_404(service, provider_id, for_update=True)
    try:
        provider = await service.patch(provider, body)
        await session.commit()
        await session.refresh(provider)
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, detail={"code": "llm_provider_name_conflict"}) from None
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, detail={"code": "llm_provider_invalid"}) from exc
    return provider_out(provider)


@router.post("/{provider_id}/rotate-secret", response_model=LLMProviderOut)
async def rotate_llm_provider_secret(
    provider_id: UUID,
    body: SecretWriteIn,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=True)
    try:
        provider = await _provider_or_404(service, provider_id, for_update=True)
        await service.rotate_secret(provider, body.secret.get_secret_value())
        await session.flush()
        await session.commit()
        await session.refresh(provider)
    except SecretStoreError as exc:
        await session.rollback()
        raise HTTPException(503, detail={"code": exc.public_code}) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        failure = classify_secret_store_error(exc)
        raise HTTPException(503, detail={"code": failure.public_code}) from None
    except RuntimeError:
        await session.rollback()
        raise HTTPException(503, detail={"code": "secret_rotation_failed"}) from None
    except ValueError:
        await session.rollback()
        raise HTTPException(422, detail={"code": "llm_provider_secret_invalid"}) from None
    return provider_out(provider)


@router.post("/{provider_id}/test", response_model=LLMProviderOut)
async def test_llm_provider(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    try:
        provider = await _provider_or_404(service, provider_id, for_update=True)
        if provider.protocol == "openai_compatible":
            service = _service(request, session, needs_key=True)
        await service.test_connection(provider)
        await session.commit()
        await session.refresh(provider)
    except SecretStoreError as exc:
        await session.rollback()
        raise HTTPException(503, detail={"code": exc.public_code}) from None
    except SQLAlchemyError as exc:
        await session.rollback()
        failure = classify_secret_store_error(exc)
        raise HTTPException(503, detail={"code": failure.public_code}) from None
    return provider_out(provider)


@router.post("/{provider_id}/enable", response_model=LLMProviderOut)
async def enable_llm_provider(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    provider = await _provider_or_404(service, provider_id, for_update=True)
    try:
        await service.enable(provider)
    except ValueError:
        raise HTTPException(409, detail={"code": "llm_provider_not_ready"}) from None
    await session.commit()
    await session.refresh(provider)
    return provider_out(provider)


@router.post("/{provider_id}/disable", response_model=LLMProviderOut)
async def disable_llm_provider(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    provider = await _provider_or_404(service, provider_id, for_update=True)
    await service.disable(provider)
    await session.commit()
    await session.refresh(provider)
    return provider_out(provider)


@router.get("/{provider_id}/dependencies", response_model=LLMProviderDependenciesOut)
async def get_llm_provider_dependencies(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    await _provider_or_404(service, provider_id)
    return await service.dependencies(provider_id)


@router.delete("/{provider_id}", status_code=204)
async def delete_llm_provider(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(request, session, needs_key=False)
    provider = await _provider_or_404(service, provider_id, for_update=True)
    try:
        await service.delete(provider)
    except ProviderDependencyConflict as exc:
        raise HTTPException(
            409,
            detail={"code": "llm_provider_has_dependencies", "dependencies": exc.dependencies.model_dump()},
        ) from None
    await session.commit()
    return Response(status_code=204)


__all__ = ["router"]
