from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Select, case, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.codex_gateway.credentials import GatewayCredentialHasher, IssuedCredential
from app.codex_gateway.models import (
    CodexConnection,
    CodexIdempotencyRecord,
    CodexPairingSession,
    CodexRateLimitBucket,
)
from app.codex_gateway.schemas import (
    CapabilityOut,
    CodexConnectionOut,
    CodexConnectionSummaryOut,
    GatewayActivityOut,
    PairingSessionCreatedOut,
    PairingSessionOut,
)
from app.core.config import Settings, settings
from app.security.audit import record_security_event
from app.security.auth import SecurityPrincipal
from app.security.models import SecurityAuditEvent

CAPABILITIES: tuple[tuple[str, str | None], ...] = (
    ("newscraft_get_status", None),
    ("newscraft_get_content_settings_summary", "settings:read"),
    ("newscraft_list_llm_providers", "providers:read"),
    ("newscraft_get_llm_provider_status", "providers:read"),
    ("newscraft_list_telegram_destinations", "destinations:read"),
    ("newscraft_get_telegram_destination_status", "destinations:read"),
    ("newscraft_list_automations", "automations:read"),
    ("newscraft_get_job_status", "jobs:read"),
)


class GatewayError(RuntimeError):
    def __init__(self, code: str, status_code: int, *, retry_after_seconds: int | None = None) -> None:
        self.code = code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


class CodexGatewayService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        hasher: GatewayCredentialHasher,
        config: Settings = settings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.hasher = hasher
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))

    def _audit(
        self,
        *,
        principal: SecurityPrincipal | None,
        action: str,
        outcome: str,
        resource_type: str,
        resource_id: UUID | str | None = None,
        required_scope: str | None = None,
        reason_code: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        record_security_event(
            self.session,
            principal=principal,
            required_scope=required_scope,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            outcome=outcome,
            reason_code=reason_code,
            metadata=metadata,
        )

    async def consume_rate_limit(
        self,
        *,
        category: str,
        subject: str,
        limit: int,
        window_seconds: int,
        principal: SecurityPrincipal | None = None,
    ) -> None:
        now = self.clock()
        key_hash = self.hasher.rate_limit_key(category, subject)
        reset_before = now - timedelta(seconds=window_seconds)
        new_bucket = insert(CodexRateLimitBucket).values(
            key_hash=key_hash,
            category=category,
            window_started_at=now,
            request_count=1,
            updated_at=now,
        )
        expired = CodexRateLimitBucket.window_started_at <= reset_before
        statement = new_bucket.on_conflict_do_update(
            index_elements=[CodexRateLimitBucket.key_hash],
            set_={
                "category": category,
                "window_started_at": case(
                    (expired, now),
                    else_=CodexRateLimitBucket.window_started_at,
                ),
                "request_count": case(
                    (expired, 1),
                    else_=CodexRateLimitBucket.request_count + 1,
                ),
                "updated_at": now,
            },
        ).returning(
            CodexRateLimitBucket.request_count,
            CodexRateLimitBucket.window_started_at,
        )
        request_count, window_started_at = (await self.session.execute(statement)).one()
        if request_count > limit:
            elapsed = (now - window_started_at).total_seconds()
            retry_after = max(1, int(window_seconds - elapsed))
            self._audit(
                principal=principal,
                action="codex_gateway.rate_limit",
                outcome="rejected",
                resource_type="codex_rate_limit",
                reason_code="rate_limited",
                metadata={"category": category, "retry_after_seconds": retry_after},
            )
            raise GatewayError("rate_limited", 429, retry_after_seconds=retry_after)

    async def create_pairing_session(
        self,
        *,
        principal: SecurityPrincipal,
        device_name: str,
        scopes: list[str],
        client_ip: str,
    ) -> PairingSessionCreatedOut:
        await self.consume_rate_limit(
            category="pairing_create_actor",
            subject=principal.principal_id,
            limit=self.config.codex_gateway_pairing_create_limit,
            window_seconds=self.config.codex_gateway_rate_window_seconds,
            principal=principal,
        )
        await self.consume_rate_limit(
            category="pairing_create_ip",
            subject=client_ip,
            limit=self.config.codex_gateway_pairing_create_limit,
            window_seconds=self.config.codex_gateway_rate_window_seconds,
            principal=principal,
        )
        now = self.clock()
        code, prefix, code_hash = self.hasher.issue_pairing_code()
        pairing = CodexPairingSession(
            id=uuid4(),
            code_prefix=prefix,
            code_hash=code_hash,
            device_name=device_name,
            requested_scopes=scopes,
            status="pending",
            expires_at=now + timedelta(seconds=self.config.codex_gateway_pairing_ttl_seconds),
            created_by_type=principal.principal_type,
            created_by_id=principal.principal_id,
            created_at=now,
        )
        self.session.add(pairing)
        await self.session.flush()
        self._audit(
            principal=principal,
            action="codex_pairing.create",
            outcome="succeeded",
            resource_type="codex_pairing",
            resource_id=pairing.id,
            required_scope="settings:write",
        )
        pairing_url = f"{self.config.codex_gateway_public_url.rstrip('/')}/codex-gateway/pair"
        pairing_payload = json.dumps(
            {"pairing_code": code},
            separators=(",", ":"),
        )
        return PairingSessionCreatedOut(
            **pairing_out(pairing).model_dump(),
            pairing_code=code,
            local_command=(
                f"curl --fail-with-body -X POST {shlex.quote(pairing_url)} "
                "-H 'Content-Type: application/json' "
                f"--data {shlex.quote(pairing_payload)}"
            ),
        )

    async def get_pairing_session(
        self,
        pairing_id: UUID,
        *,
        for_update: bool = False,
    ) -> CodexPairingSession | None:
        statement: Select[tuple[CodexPairingSession]] = select(CodexPairingSession).where(
            CodexPairingSession.id == pairing_id
        )
        if for_update:
            statement = statement.with_for_update()
        pairing = await self.session.scalar(statement)
        if pairing is not None and pairing.status == "pending" and pairing.expires_at <= self.clock():
            pairing.status = "expired"
        return pairing

    async def cancel_pairing_session(
        self,
        pairing: CodexPairingSession,
        *,
        principal: SecurityPrincipal,
    ) -> None:
        if pairing.status != "pending":
            raise GatewayError("pairing_session_not_pending", 409)
        now = self.clock()
        pairing.status = "cancelled"
        pairing.cancelled_at = now
        self._audit(
            principal=principal,
            action="codex_pairing.cancel",
            outcome="succeeded",
            resource_type="codex_pairing",
            resource_id=pairing.id,
            required_scope="settings:write",
        )

    async def exchange_pairing_code(
        self,
        *,
        code: str,
        client_ip: str,
    ) -> tuple[CodexConnection, IssuedCredential]:
        await self.consume_rate_limit(
            category="pairing_exchange_ip",
            subject=client_ip,
            limit=self.config.codex_gateway_pair_exchange_limit,
            window_seconds=self.config.codex_gateway_rate_window_seconds,
        )
        prefix = self.hasher.parse_pairing_prefix(code)
        await self.consume_rate_limit(
            category="pairing_exchange_session",
            subject=prefix or "malformed",
            limit=self.config.codex_gateway_pair_exchange_limit,
            window_seconds=self.config.codex_gateway_rate_window_seconds,
        )
        pairing = None
        if prefix is not None:
            pairing = await self.session.scalar(
                select(CodexPairingSession).where(CodexPairingSession.code_prefix == prefix).with_for_update()
            )
        now = self.clock()
        if (
            pairing is None
            or pairing.status != "pending"
            or pairing.expires_at <= now
            or not self.hasher.matches("pairing-code", code, pairing.code_hash)
        ):
            if pairing is not None and pairing.status == "pending" and pairing.expires_at <= now:
                pairing.status = "expired"
            self._audit(
                principal=None,
                action="codex_pairing.exchange",
                outcome="rejected",
                resource_type="codex_pairing",
                resource_id=pairing.id if pairing is not None else None,
                reason_code="pairing_code_invalid",
            )
            raise GatewayError("pairing_code_invalid", 401)

        issued = self.hasher.issue_credential()
        connection = CodexConnection(
            id=uuid4(),
            device_name=pairing.device_name,
            credential_prefix=issued.prefix,
            credential_hash=issued.digest,
            credential_fingerprint=issued.fingerprint,
            scopes=list(pairing.requested_scopes),
            status="active",
            expires_at=now + timedelta(seconds=self.config.codex_gateway_credential_ttl_seconds),
            pairing_session_id=pairing.id,
            created_at=now,
            updated_at=now,
        )
        pairing.status = "paired"
        pairing.used_at = now
        self.session.add(connection)
        await self.session.flush()
        principal = SecurityPrincipal(
            "codex_service",
            str(connection.id),
            frozenset(connection.scopes),
        )
        self._audit(
            principal=principal,
            action="codex_pairing.exchange",
            outcome="succeeded",
            resource_type="codex_connection",
            resource_id=connection.id,
        )
        return connection, issued

    async def authenticate(
        self,
        authorization: str | None,
        *,
        endpoint_class: str,
        rate_limit: int,
    ) -> tuple[CodexConnection, SecurityPrincipal]:
        try:
            credential = _bearer_value(authorization)
        except GatewayError as exc:
            await self.consume_rate_limit(
                category=endpoint_class,
                subject=authorization or "missing",
                limit=rate_limit,
                window_seconds=self.config.codex_gateway_rate_window_seconds,
            )
            self._audit(
                principal=None,
                action=f"codex_gateway.{endpoint_class}",
                outcome="rejected",
                resource_type="codex_connection",
                reason_code=exc.code,
            )
            raise
        prefix = self.hasher.parse_credential_prefix(credential)
        subject = prefix or "malformed"
        await self.consume_rate_limit(
            category=endpoint_class,
            subject=subject,
            limit=rate_limit,
            window_seconds=self.config.codex_gateway_rate_window_seconds,
        )
        connection = None
        if prefix is not None:
            connection = await self.session.scalar(
                select(CodexConnection).where(CodexConnection.credential_prefix == prefix).with_for_update()
            )
        now = self.clock()
        code = None
        status_code = 401
        if connection is None or not self.hasher.matches(
            "credential",
            credential,
            connection.credential_hash if connection is not None else b"",
        ):
            code = "credential_invalid"
        elif connection.status == "revoked":
            code = "credential_revoked"
        elif connection.expires_at <= now:
            code = "credential_expired"
        if code is not None:
            self._audit(
                principal=None,
                action=f"codex_gateway.{endpoint_class}",
                outcome="rejected",
                resource_type="codex_connection",
                resource_id=connection.id if connection is not None else None,
                reason_code=code,
            )
            raise GatewayError(code, status_code)
        assert connection is not None
        principal = SecurityPrincipal("codex_service", str(connection.id), frozenset(connection.scopes))
        return connection, principal

    async def heartbeat(
        self,
        connection: CodexConnection,
        *,
        principal: SecurityPrincipal,
        agent_version: str | None,
    ) -> datetime:
        now = self.clock()
        connection.last_heartbeat_at = now
        connection.updated_at = now
        self._audit(
            principal=principal,
            action="codex_gateway.heartbeat",
            outcome="succeeded",
            resource_type="codex_connection",
            resource_id=connection.id,
            metadata={"agent_version": agent_version} if agent_version else {},
        )
        return now

    def require_scope(
        self,
        connection: CodexConnection,
        principal: SecurityPrincipal,
        required_scope: str,
        *,
        capability: str,
    ) -> None:
        if principal.permits(required_scope):
            return
        connection.last_error_code = "scope_denied"
        connection.updated_at = self.clock()
        self._audit(
            principal=principal,
            action="codex_gateway.capability",
            outcome="rejected",
            resource_type="codex_connection",
            resource_id=connection.id,
            required_scope=required_scope,
            reason_code="scope_denied",
            metadata={"capability": capability},
        )
        raise GatewayError("scope_denied", 403)

    def record_tool_call(
        self,
        connection: CodexConnection,
        principal: SecurityPrincipal,
        *,
        capability: str,
        outcome: str,
        required_scope: str | None,
        reason_code: str | None = None,
    ) -> None:
        self._audit(
            principal=principal,
            action="codex_gateway.tool_call",
            outcome=outcome,
            resource_type="codex_connection",
            resource_id=connection.id,
            required_scope=required_scope,
            reason_code=reason_code,
            metadata={"capability": capability},
        )

    async def list_connections(self) -> list[CodexConnection]:
        return list(await self.session.scalars(select(CodexConnection).order_by(CodexConnection.created_at.desc())))

    async def get_connection(
        self,
        connection_id: UUID,
        *,
        for_update: bool = False,
    ) -> CodexConnection | None:
        statement: Select[tuple[CodexConnection]] = select(CodexConnection).where(CodexConnection.id == connection_id)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def update_scopes(
        self,
        connection: CodexConnection,
        *,
        scopes: list[str],
        principal: SecurityPrincipal,
    ) -> None:
        if connection.status != "active" or connection.expires_at <= self.clock():
            raise GatewayError("connection_inactive", 409)
        connection.scopes = scopes
        connection.last_error_code = None
        connection.updated_at = self.clock()
        self._audit(
            principal=principal,
            action="codex_connection.scopes",
            outcome="succeeded",
            resource_type="codex_connection",
            resource_id=connection.id,
            required_scope="settings:write",
            metadata={"scopes": scopes},
        )

    async def rotate(
        self,
        connection: CodexConnection,
        *,
        principal: SecurityPrincipal,
        idempotency_key: str,
    ) -> IssuedCredential:
        if connection.status != "active" or connection.expires_at <= self.clock():
            raise GatewayError("connection_inactive", 409)
        operation = "credential_rotate"
        key_hash = self.hasher.idempotency_key(operation, str(connection.id), idempotency_key)
        record = await self.session.get(
            CodexIdempotencyRecord,
            key_hash,
            with_for_update=True,
        )
        seed = f"{operation}:{connection.id}:{idempotency_key}"
        issued = self.hasher.issue_credential(seed=seed)
        if record is not None:
            if not self.hasher.matches("credential", issued.value, connection.credential_hash):
                raise GatewayError("idempotency_key_superseded", 409)
            return issued
        self.session.add(
            CodexIdempotencyRecord(
                key_hash=key_hash,
                operation=operation,
                resource_id=connection.id,
                created_at=self.clock(),
            )
        )
        now = self.clock()
        connection.credential_prefix = issued.prefix
        connection.credential_hash = issued.digest
        connection.credential_fingerprint = issued.fingerprint
        connection.expires_at = now + timedelta(seconds=self.config.codex_gateway_credential_ttl_seconds)
        connection.last_rotated_at = now
        connection.last_error_code = None
        connection.updated_at = now
        self._audit(
            principal=principal,
            action="codex_connection.rotate",
            outcome="succeeded",
            resource_type="codex_connection",
            resource_id=connection.id,
            required_scope="settings:write",
        )
        return issued

    async def revoke(
        self,
        connection: CodexConnection,
        *,
        principal: SecurityPrincipal,
    ) -> None:
        if connection.status == "revoked":
            return
        now = self.clock()
        connection.status = "revoked"
        connection.revoked_at = now
        connection.last_error_code = None
        connection.updated_at = now
        self._audit(
            principal=principal,
            action="codex_connection.revoke",
            outcome="succeeded",
            resource_type="codex_connection",
            resource_id=connection.id,
            required_scope="settings:write",
        )

    async def capabilities(self, principal: SecurityPrincipal) -> list[CapabilityOut]:
        return [
            CapabilityOut(
                name=name,
                required_scope=required_scope,
                granted=required_scope is None or principal.permits(required_scope),
                risk="read_only",
            )
            for name, required_scope in CAPABILITIES
        ]

    async def activity(
        self,
        *,
        connection_id: UUID | None,
        limit: int,
    ) -> list[GatewayActivityOut]:
        statement = (
            select(SecurityAuditEvent)
            .where(
                or_(
                    SecurityAuditEvent.resource_type.in_(("codex_connection", "codex_pairing", "codex_rate_limit")),
                    SecurityAuditEvent.action.like("codex_gateway.%"),
                )
            )
            .order_by(SecurityAuditEvent.created_at.desc())
            .limit(limit)
        )
        if connection_id is not None:
            statement = statement.where(
                or_(
                    SecurityAuditEvent.resource_id == str(connection_id),
                    SecurityAuditEvent.actor_id == str(connection_id),
                )
            )
        events = list(await self.session.scalars(statement))
        return [
            GatewayActivityOut(
                id=event.id,
                connection_id=(
                    event.resource_id
                    if event.resource_type == "codex_connection"
                    else event.actor_id
                    if event.actor_type == "codex_service"
                    else None
                ),
                action=event.action,
                outcome=event.outcome,
                reason_code=event.reason_code,
                created_at=event.created_at,
            )
            for event in events
        ]


def _bearer_value(authorization: str | None) -> str:
    if authorization is None:
        raise GatewayError("authentication_required", 401)
    scheme, separator, value = authorization.partition(" ")
    if separator != " " or scheme.casefold() != "bearer" or not value or value.strip() != value:
        raise GatewayError("credential_invalid", 401)
    return value


def pairing_out(pairing: CodexPairingSession) -> PairingSessionOut:
    return PairingSessionOut(
        id=pairing.id,
        device_name=pairing.device_name,
        scopes=list(pairing.requested_scopes),
        status=pairing.status,  # type: ignore[arg-type]
        expires_at=pairing.expires_at,
        created_at=pairing.created_at,
    )


def connection_status(
    connection: CodexConnection,
    *,
    now: datetime,
    fresh_seconds: int,
    stale_seconds: int,
) -> str:
    if connection.status != "active" or connection.expires_at <= now:
        return "gray"
    if connection.last_error_code is not None:
        return "red"
    if connection.last_heartbeat_at is None:
        return "gray"
    elapsed = (now - connection.last_heartbeat_at).total_seconds()
    if elapsed <= fresh_seconds:
        return "green"
    if elapsed <= stale_seconds:
        return "yellow"
    return "gray"


def connection_out(
    connection: CodexConnection,
    *,
    now: datetime,
    config: Settings,
) -> CodexConnectionOut:
    state = connection_status(
        connection,
        now=now,
        fresh_seconds=config.codex_gateway_heartbeat_fresh_seconds,
        stale_seconds=config.codex_gateway_heartbeat_stale_seconds,
    )
    return CodexConnectionOut(
        id=connection.id,
        device_name=connection.device_name,
        credential_fingerprint=connection.credential_fingerprint,
        scopes=list(connection.scopes),
        status=state,  # type: ignore[arg-type]
        connection_state=connection.status,  # type: ignore[arg-type]
        failure_code=connection.last_error_code if state == "red" else None,
        created_at=connection.created_at,
        expires_at=connection.expires_at,
        last_heartbeat_at=connection.last_heartbeat_at,
        last_rotated_at=connection.last_rotated_at,
        revoked_at=connection.revoked_at,
    )


def connection_summary_out(
    connection: CodexConnection,
    *,
    now: datetime,
    config: Settings,
) -> CodexConnectionSummaryOut:
    full = connection_out(connection, now=now, config=config)
    return CodexConnectionSummaryOut(
        id=full.id,
        device_name=full.device_name,
        scopes=full.scopes,
        status=full.status,
        connection_state=full.connection_state,
        failure_code=full.failure_code,
        expires_at=full.expires_at,
        last_heartbeat_at=full.last_heartbeat_at,
    )


__all__ = [
    "CAPABILITIES",
    "CodexGatewayService",
    "GatewayError",
    "connection_out",
    "connection_summary_out",
    "connection_status",
    "pairing_out",
]
