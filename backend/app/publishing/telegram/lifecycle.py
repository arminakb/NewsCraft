from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.telegram_schemas import (
    TelegramDestinationCreate,
    TelegramDestinationDependenciesOut,
    TelegramDestinationOut,
    TelegramDestinationPatch,
    TelegramProxyCreate,
    TelegramProxyCredentialsIn,
    TelegramProxyDependenciesOut,
    TelegramProxyOut,
    TelegramProxyPatch,
)
from app.automations.models import AutomationRoute
from app.jobs.models import WorkflowJob
from app.publishing.models import Destination, Publication, PublishJob, TelegramProxyProfile
from app.publishing.telegram.routing import (
    TelegramConfigurationError,
    allowed_proxy_ports,
    normalize_proxy_host,
    normalize_telegram_target,
)
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.secret_store import EncryptedSecretStore, MasterKeyRing

_ACTIVE_JOB_STATUSES = ("queued", "running")


class TelegramDependencyConflict(RuntimeError):
    def __init__(self, code: str, dependencies) -> None:
        self.code = code
        self.dependencies = dependencies
        super().__init__(code)


class TelegramLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        principal: SecurityPrincipal,
        key_ring: MasterKeyRing | None = None,
        clock=None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.key_ring = key_ring
        self.clock = clock or (lambda: datetime.now(UTC))

    def _store(self) -> EncryptedSecretStore:
        if self.key_ring is None:
            raise TelegramConfigurationError("secret_store_unavailable")
        return EncryptedSecretStore(self.session, self.key_ring)

    async def list_destinations(self) -> list[Destination]:
        return list(
            await self.session.scalars(
                select(Destination).where(Destination.platform == "telegram").order_by(Destination.name)
            )
        )

    async def get_destination(self, destination_id: UUID, *, for_update: bool = False) -> Destination | None:
        statement = select(Destination).where(
            Destination.id == destination_id,
            Destination.platform == "telegram",
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def _ensure_unique_target(self, canonical: str, *, exclude_id: UUID | None = None) -> None:
        statement = select(Destination).where(
            Destination.platform == "telegram",
            Destination.canonical_target == canonical,
        )
        if exclude_id is not None:
            statement = statement.where(Destination.id != exclude_id)
        if await self.session.scalar(statement) is not None:
            raise TelegramConfigurationError("telegram_destination_target_conflict")
        legacy = list(
            await self.session.scalars(
                select(Destination).where(
                    Destination.platform == "telegram",
                    Destination.canonical_target.is_(None),
                )
            )
        )
        for destination in legacy:
            if destination.id == exclude_id:
                continue
            try:
                existing = normalize_telegram_target(destination.target_ref).value
            except TelegramConfigurationError:
                continue
            if existing == canonical:
                raise TelegramConfigurationError("telegram_destination_target_conflict")

    async def _proxy_or_error(self, proxy_profile_id: UUID | None) -> TelegramProxyProfile | None:
        if proxy_profile_id is None:
            return None
        profile = await self.session.get(TelegramProxyProfile, proxy_profile_id)
        if profile is None:
            raise TelegramConfigurationError("telegram_proxy_not_found")
        if not profile.enabled or profile.reachability_status != "healthy":
            raise TelegramConfigurationError("telegram_proxy_not_ready")
        return profile

    @staticmethod
    def _reset_destination(destination: Destination) -> None:
        destination.enabled = False
        destination.health_status = "unknown"
        destination.proxy_health_status = "direct" if destination.proxy_profile_id is None else "unchecked"
        destination.telegram_health_status = "unchecked"
        destination.bot_health_status = "unchecked"
        destination.target_health_status = "unchecked"
        destination.administrator_status = "unchecked"
        destination.failure_code = None
        destination.last_health_check_at = None
        destination.verified_bot_id = None
        destination.verified_bot_username = None
        destination.verified_chat_id = None
        destination.verified_chat_title = None
        destination.verified_chat_type = None

    async def create_destination(self, body: TelegramDestinationCreate) -> Destination:
        target = normalize_telegram_target(body.target)
        await self._ensure_unique_target(target.value)
        await self._proxy_or_error(body.proxy_profile_id)
        destination = Destination(
            id=uuid4(),
            name=body.name,
            platform="telegram",
            target_ref=target.value,
            canonical_target=target.value,
            target_type=target.target_type,
            secret_ref="pending-encrypted-secret",
            proxy_profile_id=body.proxy_profile_id,
            enabled=False,
            health_status="unknown",
            proxy_health_status="direct" if body.proxy_profile_id is None else "unchecked",
            settings={},
            ownership="operator_managed",
        )
        secret = self._store().create(
            purpose="telegram_bot_token",
            owner_type="telegram_destination",
            owner_id=destination.id,
            value=body.bot_token,
            principal=self.principal,
            required_scope="destinations:write",
        )
        await self.session.flush([secret])
        destination.secret_id = secret.id
        destination.secret_ref = f"encrypted:{secret.id}"
        self.session.add(destination)
        await self.session.flush()
        return destination

    async def patch_destination(
        self,
        destination: Destination,
        body: TelegramDestinationPatch,
    ) -> Destination:
        patch = body.model_dump(exclude_unset=True)
        configuration_changed = False
        if "name" in patch:
            destination.name = patch["name"].strip()
        if "target" in patch:
            target = normalize_telegram_target(patch["target"])
            await self._ensure_unique_target(target.value, exclude_id=destination.id)
            destination.target_ref = target.value
            destination.canonical_target = target.value
            destination.target_type = target.target_type
            configuration_changed = True
        if "proxy_profile_id" in patch:
            await self._proxy_or_error(patch["proxy_profile_id"])
            if destination.proxy_profile_id != patch["proxy_profile_id"]:
                destination.proxy_profile_id = patch["proxy_profile_id"]
                configuration_changed = True
        if configuration_changed:
            self._reset_destination(destination)
        await self.session.flush()
        return destination

    async def rotate_destination_token(self, destination: Destination, value: str) -> Destination:
        if destination.secret_id is None:
            created_secret = self._store().create(
                purpose="telegram_bot_token",
                owner_type="telegram_destination",
                owner_id=destination.id,
                value=value,
                principal=self.principal,
                required_scope="destinations:write",
            )
            await self.session.flush([created_secret])
            destination.secret_id = created_secret.id
            destination.secret_ref = f"encrypted:{created_secret.id}"
        else:
            secret = await self.session.get(EncryptedSecret, destination.secret_id)
            if secret is None:
                raise TelegramConfigurationError("secret_store_unavailable")
            self._store().rotate(
                secret,
                value,
                principal=self.principal,
                required_scope="destinations:write",
            )
        self._reset_destination(destination)
        return destination

    async def enable_destination(self, destination: Destination) -> Destination:
        if (
            destination.secret_id is None
            or destination.health_status != "healthy"
            or destination.proxy_health_status not in {"direct", "healthy"}
            or destination.telegram_health_status != "healthy"
            or destination.bot_health_status != "healthy"
            or destination.target_health_status != "healthy"
            or destination.administrator_status != "administrator"
        ):
            raise TelegramConfigurationError("telegram_destination_not_ready")
        destination.enabled = True
        return destination

    async def disable_destination(self, destination: Destination) -> Destination:
        destination.enabled = False
        return destination

    async def destination_dependencies(self, destination_id: UUID) -> TelegramDestinationDependenciesOut:
        automations = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AutomationRoute)
                .where(AutomationRoute.destination_id == destination_id)
            )
            or 0
        )
        publish_jobs = int(
            await self.session.scalar(
                select(func.count()).select_from(PublishJob).where(PublishJob.destination_id == destination_id)
            )
            or 0
        )
        publications = int(
            await self.session.scalar(
                select(func.count()).select_from(Publication).where(Publication.destination_id == destination_id)
            )
            or 0
        )
        active_checks = int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkflowJob)
                .where(
                    WorkflowJob.job_type == "telegram.destination.check",
                    WorkflowJob.status.in_(_ACTIVE_JOB_STATUSES),
                    WorkflowJob.payload["destination_id"].as_string() == str(destination_id),
                )
            )
            or 0
        )
        active_publishes = int(
            await self.session.scalar(
                select(func.count())
                .select_from(WorkflowJob)
                .join(PublishJob, PublishJob.workflow_job_id == WorkflowJob.id)
                .where(
                    PublishJob.destination_id == destination_id,
                    WorkflowJob.status.in_(_ACTIVE_JOB_STATUSES),
                )
            )
            or 0
        )
        active_jobs = active_checks + active_publishes
        return TelegramDestinationDependenciesOut(
            automations=automations,
            publish_jobs=publish_jobs,
            publications=publications,
            active_jobs=active_jobs,
            blocked=any((automations, publish_jobs, publications, active_jobs)),
        )

    async def delete_destination(self, destination: Destination) -> None:
        dependencies = await self.destination_dependencies(destination.id)
        if dependencies.blocked:
            raise TelegramDependencyConflict("telegram_destination_has_dependencies", dependencies)
        secret = await self.session.get(EncryptedSecret, destination.secret_id) if destination.secret_id else None
        await self.session.delete(destination)
        await self.session.flush()
        if secret is not None:
            await self.session.delete(secret)

    async def list_proxies(self) -> list[TelegramProxyProfile]:
        return list(await self.session.scalars(select(TelegramProxyProfile).order_by(TelegramProxyProfile.name)))

    async def get_proxy(self, profile_id: UUID, *, for_update: bool = False) -> TelegramProxyProfile | None:
        statement = select(TelegramProxyProfile).where(TelegramProxyProfile.id == profile_id)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def _create_proxy_secret(
        self,
        profile: TelegramProxyProfile,
        *,
        purpose: str,
        value,
    ) -> EncryptedSecret:
        secret = self._store().create(
            purpose=purpose,
            owner_type="telegram_proxy_profile",
            owner_id=profile.id,
            value=value,
            principal=self.principal,
            required_scope="destinations:write",
        )
        await self.session.flush([secret])
        return secret

    async def create_proxy(self, body: TelegramProxyCreate) -> TelegramProxyProfile:
        if body.port not in allowed_proxy_ports():
            raise TelegramConfigurationError("telegram_proxy_port_blocked")
        profile = TelegramProxyProfile(
            id=uuid4(),
            name=body.name.strip(),
            proxy_type=body.proxy_type,
            host=normalize_proxy_host(body.host),
            port=body.port,
            enabled=False,
            reachability_status="unchecked",
        )
        if body.username is not None and body.password is not None:
            username = await self._create_proxy_secret(profile, purpose="proxy_username", value=body.username)
            password = await self._create_proxy_secret(profile, purpose="proxy_password", value=body.password)
            profile.username_secret_id = username.id
            profile.password_secret_id = password.id
        self.session.add(profile)
        await self.session.flush()
        return profile

    async def patch_proxy(self, profile: TelegramProxyProfile, body: TelegramProxyPatch) -> TelegramProxyProfile:
        patch = body.model_dump(exclude_unset=True)
        if "name" in patch:
            profile.name = patch["name"].strip()
        if "proxy_type" in patch:
            profile.proxy_type = patch["proxy_type"]
        if "host" in patch:
            profile.host = normalize_proxy_host(patch["host"])
        if "port" in patch:
            if patch["port"] not in allowed_proxy_ports():
                raise TelegramConfigurationError("telegram_proxy_port_blocked")
            profile.port = patch["port"]
        if any(key in patch for key in ("proxy_type", "host", "port")):
            profile.enabled = False
            profile.reachability_status = "unchecked"
            profile.failure_code = None
            profile.last_checked_at = None
            await self._invalidate_proxy_destinations(profile.id, "telegram_proxy_changed")
        await self.session.flush()
        return profile

    async def rotate_proxy_credentials(
        self,
        profile: TelegramProxyProfile,
        body: TelegramProxyCredentialsIn,
    ) -> TelegramProxyProfile:
        existing = [
            await self.session.get(EncryptedSecret, secret_id)
            for secret_id in (profile.username_secret_id, profile.password_secret_id)
            if secret_id is not None
        ]
        existing_by_purpose = {secret.purpose: secret for secret in existing if secret is not None}
        if body.username is None and body.password is None:
            profile.username_secret_id = None
            profile.password_secret_id = None
            await self.session.flush()
            for secret in existing:
                if secret is not None:
                    await self.session.delete(secret)
        else:
            assert body.username is not None and body.password is not None
            values = (("proxy_username", body.username), ("proxy_password", body.password))
            ids = []
            for purpose, value in values:
                current = existing_by_purpose.get(purpose)
                if current is None:
                    current = await self._create_proxy_secret(profile, purpose=purpose, value=value)
                else:
                    self._store().rotate(
                        current,
                        value,
                        principal=self.principal,
                        required_scope="destinations:write",
                    )
                ids.append(current.id)
            profile.username_secret_id, profile.password_secret_id = ids
        profile.enabled = False
        profile.reachability_status = "unchecked"
        profile.failure_code = None
        profile.last_checked_at = None
        await self._invalidate_proxy_destinations(profile.id, "telegram_proxy_credentials_rotated")
        return profile

    async def enable_proxy(self, profile: TelegramProxyProfile) -> TelegramProxyProfile:
        if profile.reachability_status != "healthy":
            raise TelegramConfigurationError("telegram_proxy_not_ready")
        profile.enabled = True
        return profile

    async def disable_proxy(self, profile: TelegramProxyProfile) -> TelegramProxyProfile:
        profile.enabled = False
        await self._invalidate_proxy_destinations(profile.id, "telegram_proxy_disabled")
        return profile

    async def _invalidate_proxy_destinations(self, profile_id: UUID, failure_code: str) -> None:
        destinations = list(
            await self.session.scalars(
                select(Destination).where(Destination.proxy_profile_id == profile_id).with_for_update()
            )
        )
        for destination in destinations:
            self._reset_destination(destination)
            destination.failure_code = failure_code

    async def proxy_dependencies(self, profile_id: UUID) -> TelegramProxyDependenciesOut:
        destinations = int(
            await self.session.scalar(
                select(func.count()).select_from(Destination).where(Destination.proxy_profile_id == profile_id)
            )
            or 0
        )
        return TelegramProxyDependenciesOut(destinations=destinations, blocked=destinations > 0)

    async def delete_proxy(self, profile: TelegramProxyProfile) -> None:
        dependencies = await self.proxy_dependencies(profile.id)
        if dependencies.blocked:
            raise TelegramDependencyConflict("telegram_proxy_has_dependencies", dependencies)
        secrets = [
            await self.session.get(EncryptedSecret, secret_id)
            for secret_id in (profile.username_secret_id, profile.password_secret_id)
            if secret_id is not None
        ]
        await self.session.delete(profile)
        await self.session.flush()
        for secret in secrets:
            if secret is not None:
                await self.session.delete(secret)


async def destination_out(session: AsyncSession, destination: Destination) -> TelegramDestinationOut:
    secret = await session.get(EncryptedSecret, destination.secret_id) if destination.secret_id else None
    canonical = destination.canonical_target or destination.target_ref
    target_type: Literal["username", "numeric_id", "legacy"]
    if destination.target_type == "username":
        target_type = "username"
    elif destination.target_type == "numeric_id":
        target_type = "numeric_id"
    else:
        target_type = "legacy"
    return TelegramDestinationOut(
        id=destination.id,
        name=destination.name,
        target_ref=canonical,
        canonical_target=canonical,
        target_type=target_type,
        enabled=destination.enabled,
        health_status=destination.health_status,
        configured=secret is not None,
        proxy_profile_id=destination.proxy_profile_id,
        connection_route="direct" if destination.proxy_profile_id is None else "proxy",
        proxy_health_status=destination.proxy_health_status,
        telegram_health_status=destination.telegram_health_status,
        bot_health_status=destination.bot_health_status,
        target_health_status=destination.target_health_status,
        administrator_status=destination.administrator_status,
        failure_code=destination.failure_code,
        verified_bot_id=destination.verified_bot_id,
        verified_bot_username=destination.verified_bot_username,
        verified_chat_id=destination.verified_chat_id,
        verified_chat_title=destination.verified_chat_title,
        verified_chat_type=destination.verified_chat_type,
        last_checked_at=destination.last_health_check_at,
        last_rotated_at=secret.last_rotated_at if secret else None,
        created_at=destination.created_at,
        updated_at=destination.updated_at,
    )


async def proxy_out(session: AsyncSession, profile: TelegramProxyProfile) -> TelegramProxyOut:
    secret_ids = [item for item in (profile.username_secret_id, profile.password_secret_id) if item is not None]
    secrets = [await session.get(EncryptedSecret, item) for item in secret_ids]
    rotated = max((item.last_rotated_at for item in secrets if item is not None), default=None)
    proxy_type: Literal["http_connect", "socks5"]
    if profile.proxy_type == "http_connect":
        proxy_type = "http_connect"
    elif profile.proxy_type == "socks5":
        proxy_type = "socks5"
    else:
        raise TelegramConfigurationError("telegram_proxy_type_invalid")
    return TelegramProxyOut(
        id=profile.id,
        name=profile.name,
        proxy_type=proxy_type,
        host=profile.host,
        port=profile.port,
        enabled=profile.enabled,
        credentials_configured=len(secret_ids) == 2 and len(secrets) == 2 and all(secrets),
        reachability_status=profile.reachability_status,
        failure_code=profile.failure_code,
        last_checked_at=profile.last_checked_at,
        last_rotated_at=rotated,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


__all__ = [
    "TelegramDependencyConflict",
    "TelegramLifecycleService",
    "destination_out",
    "proxy_out",
]
