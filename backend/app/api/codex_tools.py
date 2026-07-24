from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telegram_schemas import TelegramDestinationOut
from app.codex_gateway.credentials import GatewayCredentialHasher, GatewayKeyUnavailable
from app.codex_gateway.models import CodexConnection
from app.codex_gateway.service import CodexGatewayService, GatewayError
from app.codex_gateway.tools import (
    AutomationSummaryOut,
    CodexToolService,
    ContentSettingsSummaryOut,
    ToolResourceNotFound,
)
from app.core.config import settings
from app.db.session import get_session
from app.jobs.schemas import JobOut
from app.llm_providers.schemas import LLMProviderOut
from app.operations.health import ReadinessSnapshot
from app.security.auth import SecurityPrincipal

router = APIRouter(prefix="/codex-gateway/tools", tags=["codex-gateway-tools"])
SessionDependency = Depends(get_session)


@dataclass(slots=True)
class ToolContext:
    session: AsyncSession
    gateway: CodexGatewayService
    tools: CodexToolService
    connection: CodexConnection
    principal: SecurityPrincipal
    capability: str
    required_scope: str | None


def _gateway(session: AsyncSession) -> CodexGatewayService:
    try:
        hasher = GatewayCredentialHasher.from_settings(settings)
    except GatewayKeyUnavailable:
        raise HTTPException(503, detail={"code": "codex_gateway_unavailable"}) from None
    return CodexGatewayService(session, hasher=hasher, config=settings)


async def _raise_gateway_error(session: AsyncSession, exc: GatewayError) -> None:
    await session.commit()
    headers = (
        {"Retry-After": str(exc.retry_after_seconds)}
        if exc.retry_after_seconds is not None
        else None
    )
    raise HTTPException(
        exc.status_code,
        detail={"code": exc.code},
        headers=headers,
    ) from None


async def _authorize(
    request: Request,
    session: AsyncSession,
    *,
    capability: str,
    required_scope: str | None,
) -> ToolContext:
    gateway = _gateway(session)
    try:
        connection, principal = await gateway.authenticate(
            request.headers.get("authorization"),
            endpoint_class="tool_call",
            rate_limit=settings.codex_gateway_capability_limit,
        )
        if required_scope is not None:
            gateway.require_scope(
                connection,
                principal,
                required_scope,
                capability=capability,
            )
    except GatewayError as exc:
        await _raise_gateway_error(session, exc)
    return ToolContext(
        session=session,
        gateway=gateway,
        tools=CodexToolService(session, principal=principal, config=settings),
        connection=connection,
        principal=principal,
        capability=capability,
        required_scope=required_scope,
    )


async def _execute[T](
    context: ToolContext,
    operation: Callable[[], Awaitable[T]],
) -> T:
    try:
        result = await operation()
    except ToolResourceNotFound:
        context.gateway.record_tool_call(
            context.connection,
            context.principal,
            capability=context.capability,
            outcome="rejected",
            required_scope=context.required_scope,
            reason_code="capability_unavailable",
        )
        await context.session.commit()
        raise HTTPException(
            404,
            detail={"code": "capability_unavailable"},
        ) from None
    context.gateway.record_tool_call(
        context.connection,
        context.principal,
        capability=context.capability,
        outcome="succeeded",
        required_scope=context.required_scope,
    )
    await context.session.commit()
    return result


@router.get("/status", response_model=ReadinessSnapshot)
async def get_status(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_get_status",
        required_scope=None,
    )
    return await _execute(context, context.tools.get_status)


@router.get("/content-settings-summary", response_model=ContentSettingsSummaryOut)
async def get_content_settings_summary(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_get_content_settings_summary",
        required_scope="settings:read",
    )
    return await _execute(
        context,
        lambda: context.tools.get_content_settings_summary(context.connection),
    )


@router.get("/llm-providers", response_model=list[LLMProviderOut])
async def list_llm_providers(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_list_llm_providers",
        required_scope="providers:read",
    )
    return await _execute(context, context.tools.list_llm_providers)


@router.get("/llm-providers/{provider_id}", response_model=LLMProviderOut)
async def get_llm_provider_status(
    provider_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_get_llm_provider_status",
        required_scope="providers:read",
    )
    return await _execute(
        context,
        lambda: context.tools.get_llm_provider_status(provider_id),
    )


@router.get("/telegram-destinations", response_model=list[TelegramDestinationOut])
async def list_telegram_destinations(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_list_telegram_destinations",
        required_scope="destinations:read",
    )
    return await _execute(context, context.tools.list_telegram_destinations)


@router.get(
    "/telegram-destinations/{destination_id}",
    response_model=TelegramDestinationOut,
)
async def get_telegram_destination_status(
    destination_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_get_telegram_destination_status",
        required_scope="destinations:read",
    )
    return await _execute(
        context,
        lambda: context.tools.get_telegram_destination_status(destination_id),
    )


@router.get("/automations", response_model=list[AutomationSummaryOut])
async def list_automations(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_list_automations",
        required_scope="automations:read",
    )
    return await _execute(context, context.tools.list_automations)


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job_status(
    job_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    context = await _authorize(
        request,
        session,
        capability="newscraft_get_job_status",
        required_scope="jobs:read",
    )
    return await _execute(
        context,
        lambda: context.tools.get_job_status(job_id),
    )


__all__ = ["router"]
