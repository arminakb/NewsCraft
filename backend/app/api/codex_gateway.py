from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.codex_gateway.credentials import GatewayCredentialHasher, GatewayKeyUnavailable
from app.codex_gateway.schemas import (
    CapabilityOut,
    CodexConnectionOut,
    ConnectionScopesPatch,
    CredentialIssuedOut,
    GatewayActivityOut,
    HeartbeatIn,
    HeartbeatOut,
    PairingExchangeIn,
    PairingSessionCreate,
    PairingSessionCreatedOut,
    PairingSessionOut,
)
from app.codex_gateway.service import (
    CodexGatewayService,
    GatewayError,
    connection_out,
    pairing_out,
)
from app.core.config import settings
from app.db.session import get_session
from app.security.auth import (
    TEST_ADMIN,
    AuthenticationFailure,
    CredentialAuthenticator,
    SecurityPrincipal,
)

router = APIRouter(prefix="/codex-gateway", tags=["codex-gateway"])
SessionDependency = Depends(get_session)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _hasher() -> GatewayCredentialHasher:
    try:
        return GatewayCredentialHasher.from_settings(settings)
    except GatewayKeyUnavailable:
        raise HTTPException(503, detail={"code": "codex_gateway_unavailable"}) from None


def _service(session: AsyncSession) -> CodexGatewayService:
    return CodexGatewayService(session, hasher=_hasher(), config=settings)


def _admin_principal(request: Request) -> SecurityPrincipal:
    principal = getattr(request.state, "security_principal", None)
    if isinstance(principal, SecurityPrincipal):
        if principal.principal_type not in {"human_admin", "test_harness"}:
            raise HTTPException(403, detail={"code": "scope_denied"})
        return principal
    if settings.app_env == "test":
        return TEST_ADMIN
    try:
        principal = CredentialAuthenticator(settings).authenticate(
            request.headers.get("authorization"),
            request.headers.get("x-newscraft-principal-type"),
        )
    except AuthenticationFailure as exc:
        raise HTTPException(exc.status_code, detail={"code": exc.code}) from None
    if principal.principal_type != "human_admin":
        raise HTTPException(403, detail={"code": "scope_denied"})
    return principal


async def _commit_gateway_error(session: AsyncSession, exc: GatewayError) -> None:
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


@router.post(
    "/pairing-sessions",
    response_model=PairingSessionCreatedOut,
    status_code=201,
)
async def create_pairing_session(
    body: PairingSessionCreate,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    principal = _admin_principal(request)
    service = _service(session)
    try:
        result = await service.create_pairing_session(
            principal=principal,
            device_name=body.device_name,
            scopes=body.scopes,
            client_ip=_client_ip(request),
        )
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    return result


@router.get(
    "/pairing-sessions/{pairing_id}",
    response_model=PairingSessionOut,
)
async def get_pairing_session(
    pairing_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    _admin_principal(request)
    service = _service(session)
    pairing = await service.get_pairing_session(pairing_id)
    if pairing is None:
        raise HTTPException(404, detail={"code": "pairing_session_not_found"})
    await session.commit()
    return pairing_out(pairing)


@router.delete("/pairing-sessions/{pairing_id}", status_code=204)
async def cancel_pairing_session(
    pairing_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    principal = _admin_principal(request)
    service = _service(session)
    pairing = await service.get_pairing_session(pairing_id, for_update=True)
    if pairing is None:
        raise HTTPException(404, detail={"code": "pairing_session_not_found"})
    try:
        await service.cancel_pairing_session(pairing, principal=principal)
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    return Response(status_code=204)


@router.post("/pair", response_model=CredentialIssuedOut, status_code=201)
async def exchange_pairing_code(
    body: PairingExchangeIn,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(session)
    try:
        connection, issued = await service.exchange_pairing_code(
            code=body.pairing_code.get_secret_value(),
            client_ip=_client_ip(request),
        )
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    await session.refresh(connection)
    return CredentialIssuedOut(
        connection=connection_out(connection, now=service.clock(), config=settings),
        credential=issued.value,
    )


@router.post("/heartbeat", response_model=HeartbeatOut)
async def heartbeat(
    body: HeartbeatIn,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(session)
    try:
        connection, principal = await service.authenticate(
            request.headers.get("authorization"),
            endpoint_class="heartbeat",
            rate_limit=settings.codex_gateway_heartbeat_limit,
        )
        server_time = await service.heartbeat(
            connection,
            principal=principal,
            agent_version=body.agent_version,
        )
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    status = connection_out(connection, now=server_time, config=settings).status
    return HeartbeatOut(
        connection_id=connection.id,
        status=status,
        server_time=server_time,
        next_heartbeat_seconds=settings.codex_gateway_heartbeat_interval_seconds,
    )


@router.get("/connections", response_model=list[CodexConnectionOut])
async def list_connections(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    _admin_principal(request)
    service = _service(session)
    now = service.clock()
    return [
        connection_out(connection, now=now, config=settings)
        for connection in await service.list_connections()
    ]


async def _connection_or_404(
    service: CodexGatewayService,
    connection_id: UUID,
    *,
    for_update: bool = False,
):
    connection = await service.get_connection(connection_id, for_update=for_update)
    if connection is None:
        raise HTTPException(404, detail={"code": "codex_connection_not_found"})
    return connection


@router.get("/connections/{connection_id}", response_model=CodexConnectionOut)
async def get_connection(
    connection_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    _admin_principal(request)
    service = _service(session)
    connection = await _connection_or_404(service, connection_id)
    return connection_out(connection, now=service.clock(), config=settings)


@router.patch(
    "/connections/{connection_id}/scopes",
    response_model=CodexConnectionOut,
)
async def update_connection_scopes(
    connection_id: UUID,
    body: ConnectionScopesPatch,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    principal = _admin_principal(request)
    service = _service(session)
    connection = await _connection_or_404(service, connection_id, for_update=True)
    try:
        await service.update_scopes(
            connection,
            scopes=body.scopes,
            principal=principal,
        )
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    await session.refresh(connection)
    return connection_out(connection, now=service.clock(), config=settings)


@router.post(
    "/connections/{connection_id}/rotate",
    response_model=CredentialIssuedOut,
)
async def rotate_connection(
    connection_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        min_length=8,
        max_length=128,
    ),
):
    if idempotency_key is None:
        raise HTTPException(400, detail={"code": "idempotency_key_required"})
    principal = _admin_principal(request)
    service = _service(session)
    connection = await _connection_or_404(service, connection_id, for_update=True)
    try:
        issued = await service.rotate(
            connection,
            principal=principal,
            idempotency_key=idempotency_key,
        )
    except GatewayError as exc:
        await _commit_gateway_error(session, exc)
    await session.commit()
    await session.refresh(connection)
    return CredentialIssuedOut(
        connection=connection_out(connection, now=service.clock(), config=settings),
        credential=issued.value,
    )


@router.delete("/connections/{connection_id}", status_code=204)
async def revoke_connection(
    connection_id: UUID,
    request: Request,
    session: AsyncSession = SessionDependency,
):
    principal = _admin_principal(request)
    service = _service(session)
    connection = await _connection_or_404(service, connection_id, for_update=True)
    await service.revoke(connection, principal=principal)
    await session.commit()
    return Response(status_code=204)


@router.get("/capabilities", response_model=list[CapabilityOut])
async def get_capabilities(
    request: Request,
    session: AsyncSession = SessionDependency,
):
    service = _service(session)
    authorization = request.headers.get("authorization")
    if authorization is None or not authorization.casefold().startswith("bearer ncg_"):
        principal = _admin_principal(request)
    else:
        try:
            _connection, principal = await service.authenticate(
                authorization,
                endpoint_class="capabilities",
                rate_limit=settings.codex_gateway_capability_limit,
            )
        except GatewayError as exc:
            await _commit_gateway_error(session, exc)
    await session.commit()
    return await service.capabilities(principal)


@router.get("/activity", response_model=list[GatewayActivityOut])
async def get_activity(
    request: Request,
    connection_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    session: AsyncSession = SessionDependency,
):
    _admin_principal(request)
    return await _service(session).activity(connection_id=connection_id, limit=limit)


__all__ = ["router"]
