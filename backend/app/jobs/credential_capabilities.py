from __future__ import annotations

import re
import shutil
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.models import TelegramSourceConfig
from app.core.config import Settings, settings
from app.core.secrets import SecretResolver
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import CodexProviderSettings, OpenRouterProviderSettings
from app.jobs.errors import JobCapabilityUnavailable
from app.jobs.models import RuntimeHeartbeat
from app.llm_providers.models import LLMProvider
from app.llm_providers.readiness import provider_capability_ready
from app.publishing.models import Destination
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.scopes import parse_scopes
from app.security.secret_store import (
    EncryptedSecretStore,
    MasterKeyRing,
    SecretDecryptionFailed,
    SecretKeyUnavailable,
)

type ResourceType = Literal["provider", "source", "destination"]
type ResourceCapability = Literal["generation", "research", "source", "publishing"]
type ObservedCapabilityState = Literal["available", "unavailable"]
type ProjectedCapabilityState = Literal["available", "unavailable", "unknown", "stale"]

_SAFE_COMPONENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_FAILURE_CODES = frozenset(
    {
        "available",
        "credential_missing",
        "credential_invalid",
        "disabled",
        "executable_unavailable",
        "health_check_failed",
        "generation_profile_unqualified",
        "invalid_configuration",
        "observation_missing",
        "observation_stale",
        "ownership_mismatch",
        "research_configuration_missing",
    }
)
_OWNER_CAPABILITY = {
    "generation": "generation",
    "research": "generation",
    "source": "source",
    "publishing": "publishing",
}


class CapabilityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: ResourceType
    resource_id: UUID
    capability: ResourceCapability
    state: ObservedCapabilityState
    failure_code: str


class CapabilityStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ProjectedCapabilityState
    owner: str | None
    observed_at: datetime | None
    expires_at: datetime | None
    failure_code: str

    @property
    def available(self) -> bool:
        return self.status == "available"


def resolve_provider_profile_capabilities(
    profile: AIProviderProfile,
    generic: LLMProvider | None,
    *,
    config: Settings = settings,
) -> tuple[dict[str, bool], list[str]]:
    """Answer "is this provider usable?" for either storage generation.

    Profiles backed by an operator-managed ``llm_providers`` row qualify through
    that row's live connection-test readiness; legacy rows keep the historical
    static shape rules from :func:`provider_shape_capabilities`.
    """

    if generic is None:
        return provider_shape_capabilities(profile)
    if not generic.enabled or not profile.enabled:
        return {"generation": False, "research": False}, ["disabled"]
    if generic.protocol == "fake":
        valid = generic.base_url is None and generic.secret_id is None
        return (
            {"generation": valid, "research": valid},
            [] if valid else ["invalid_configuration"],
        )
    if generic.protocol != "openai_compatible":
        return {"generation": False, "research": False}, ["invalid_configuration"]
    ttl_seconds = config.llm_provider_test_ttl_seconds
    generation = provider_capability_ready(generic, "generation", ttl_seconds=ttl_seconds)
    research = provider_capability_ready(generic, "research", ttl_seconds=ttl_seconds)
    codes: list[str] = []
    missing_credential = generic.secret_id is None
    if missing_credential:
        codes.append("credential_missing")
    if not generation and not missing_credential:
        codes.append(generic.failure_code or "test_required")
    if not research and generation:
        codes.append("research_configuration_missing")
    return {"generation": generation, "research": research}, codes


async def provider_profile_capabilities(
    session: AsyncSession,
    profile: AIProviderProfile,
    *,
    generic: LLMProvider | None = None,
    config: Settings = settings,
) -> tuple[dict[str, bool], list[str]]:
    """Single-profile form of :func:`resolve_provider_profile_capabilities`.

    Pass ``generic`` when the caller already loaded ``llm_providers`` rows to
    avoid one redundant fetch per profile.
    """

    if generic is None:
        generic = await session.get(LLMProvider, profile.id)
    return resolve_provider_profile_capabilities(profile, generic, config=config)


def provider_shape_capabilities(profile: AIProviderProfile) -> tuple[dict[str, bool], list[str]]:
    generation = False
    research = False
    codes: list[str] = []
    if not profile.enabled:
        return {"generation": False, "research": False}, ["disabled"]
    if profile.provider_type == "fake":
        generation = research = profile.secret_ref is None and not dict(profile.settings or {})
        if not generation:
            codes.append("invalid_configuration")
    elif profile.provider_type == "codex":
        try:
            CodexProviderSettings.model_validate(dict(profile.settings or {}))
            valid_settings = True
        except ValueError:
            valid_settings = False
        generation = research = bool(profile.default_model and profile.secret_ref is None and valid_settings)
        if not generation:
            codes.append("invalid_configuration")
    elif profile.provider_type == "openrouter":
        try:
            configured = OpenRouterProviderSettings.model_validate(dict(profile.settings or {}))
            valid_settings = True
        except ValueError:
            configured = None
            valid_settings = False
        base_available = bool(profile.default_model and profile.secret_ref and valid_settings)
        generation = bool(
            base_available
            and configured is not None
            and configured.pricing is not None
            and configured.generation_policy is not None
            and configured.generation_policy.qualification_status == "qualified"
        )
        research = bool(
            base_available
            and configured is not None
            and configured.pricing is not None
            and configured.research_budgets is not None
        )
        if not base_available:
            codes.append("invalid_configuration")
        elif not generation:
            codes.append("generation_profile_unqualified")
        elif not research:
            codes.append("research_configuration_missing")
    else:
        codes.append("invalid_configuration")
    return {"generation": generation, "research": research}, codes


def _observation(
    resource_type: ResourceType,
    resource_id: UUID,
    capability: ResourceCapability,
    available: bool,
    failure_code: str,
) -> CapabilityObservation:
    return CapabilityObservation(
        resource_type=resource_type,
        resource_id=resource_id,
        capability=capability,
        state="available" if available else "unavailable",
        failure_code=_safe_failure_code(failure_code),
    )


def _secret_value(resolver: SecretResolver, reference: str | None) -> str | None:
    if not reference:
        return None
    try:
        value = resolver.resolve(reference)
    except Exception:
        return None
    return value if isinstance(value, str) and bool(value.strip()) else None


class WorkerCredentialCapabilityObserver:
    """Observe only resource classes owned by the worker's registered capabilities."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        secret_resolver: SecretResolver,
        config: Settings = settings,
        executable_resolver: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.session = session
        self.secret_resolver = secret_resolver
        self.config = config
        self.executable_resolver = executable_resolver

    async def observe(self, capabilities: tuple[str, ...]) -> list[CapabilityObservation]:
        owned = set(capabilities)
        observations: list[CapabilityObservation] = []
        if "generation" in owned:
            generic_profiles = {profile.id: profile for profile in await self.session.scalars(select(LLMProvider))}
            profiles = list(await self.session.scalars(select(AIProviderProfile)))
            for profile in profiles:
                generic = generic_profiles.pop(profile.id, None)
                if generic is None:
                    observations.extend(self._provider(profile))
                else:
                    observations.extend(await self._generic_provider(generic))
            for generic in generic_profiles.values():
                observations.extend(await self._generic_provider(generic))
        if "source" in owned:
            sources = list(await self.session.scalars(select(TelegramSourceConfig)))
            observations.extend(self._source(source) for source in sources)
        if "publishing" in owned:
            destinations = list(
                await self.session.scalars(select(Destination).where(Destination.platform == "telegram"))
            )
            for destination in destinations:
                observations.append(await self._destination(destination))
        return observations

    async def _generic_provider(self, profile: LLMProvider) -> list[CapabilityObservation]:
        if not profile.enabled:
            generation_available = research_available = False
            generation_code = research_code = "disabled"
        elif profile.protocol == "fake":
            valid = profile.base_url is None and profile.secret_id is None
            generation_available = valid and provider_capability_ready(
                profile,
                "generation",
                ttl_seconds=self.config.llm_provider_test_ttl_seconds,
            )
            research_available = valid and provider_capability_ready(
                profile,
                "research",
                ttl_seconds=self.config.llm_provider_test_ttl_seconds,
            )
            generation_code = "available" if generation_available else "invalid_configuration"
            research_code = "available" if research_available else "research_configuration_missing"
        elif profile.protocol != "openai_compatible" or profile.secret_id is None:
            generation_available = research_available = False
            generation_code = research_code = "invalid_configuration"
        else:
            secret = await self.session.get(EncryptedSecret, profile.secret_id)
            credential_available = secret is not None
            credential_code = "credential_missing"
            if secret is not None:
                try:
                    EncryptedSecretStore(
                        self.session,
                        MasterKeyRing.from_settings(self.config),
                    ).decrypt(
                        secret,
                        principal=SecurityPrincipal(
                            "internal_service",
                            "generation-worker",
                            parse_scopes(self.config.security_internal_scopes),
                        ),
                        required_scope="providers:read",
                    )
                    credential_code = "available"
                except SecretKeyUnavailable:
                    credential_available = False
                    credential_code = "invalid_configuration"
                except SecretDecryptionFailed:
                    credential_available = False
                    credential_code = "credential_invalid"
                except Exception:
                    credential_available = False
                    credential_code = "invalid_configuration"
            generation_available = credential_available and provider_capability_ready(
                profile,
                "generation",
                ttl_seconds=self.config.llm_provider_test_ttl_seconds,
            )
            research_available = credential_available and provider_capability_ready(
                profile,
                "research",
                ttl_seconds=self.config.llm_provider_test_ttl_seconds,
            )
            generation_code = (
                "available"
                if generation_available
                else credential_code
                if not credential_available
                else profile.failure_code or "invalid_configuration"
            )
            research_code = (
                "available"
                if research_available
                else credential_code
                if not credential_available
                else profile.failure_code or "research_configuration_missing"
            )
        return [
            _observation("provider", profile.id, "generation", generation_available, generation_code),
            _observation("provider", profile.id, "research", research_available, research_code),
        ]

    def _provider(self, profile: AIProviderProfile) -> list[CapabilityObservation]:
        shaped, shape_codes = provider_shape_capabilities(profile)
        if not profile.enabled:
            code = "disabled"
            available = False
        elif profile.provider_type == "openrouter":
            if "invalid_configuration" in shape_codes:
                available = False
                code = "invalid_configuration"
            else:
                available = _secret_value(self.secret_resolver, profile.secret_ref) is not None
                code = "available" if available else "credential_missing"
        elif not any(shaped.values()):
            code = "invalid_configuration"
            available = False
        elif profile.provider_type == "codex":
            available = bool(
                self.config.codex_enabled and self.executable_resolver(self.config.codex_executable) is not None
            )
            code = "available" if available else "executable_unavailable"
        else:
            available = True
            code = "available"
        generation_available = available and shaped["generation"]
        generation_code = (
            "available"
            if generation_available
            else "generation_profile_unqualified"
            if available and "generation_profile_unqualified" in shape_codes
            else code
        )
        observations = [_observation("provider", profile.id, "generation", generation_available, generation_code)]
        research_available = available and shaped["research"]
        research_code = (
            "available"
            if research_available
            else "research_configuration_missing"
            if available and "research_configuration_missing" in shape_codes
            else code
        )
        observations.append(_observation("provider", profile.id, "research", research_available, research_code))
        return observations

    def _source(self, source: TelegramSourceConfig) -> CapabilityObservation:
        if source.access_mode == "public_html":
            return _observation("source", source.source_id, "source", True, "available")
        if source.access_mode != "mtproto_user":
            return _observation("source", source.source_id, "source", False, "invalid_configuration")
        api_id = _secret_value(self.secret_resolver, source.api_id_secret_ref)
        api_hash = _secret_value(self.secret_resolver, source.api_hash_secret_ref)
        session = _secret_value(self.secret_resolver, source.session_secret_ref)
        if None in (api_id, api_hash, session):
            return _observation("source", source.source_id, "source", False, "credential_missing")
        try:
            valid_api_id = int(api_id or "") > 0
        except ValueError:
            valid_api_id = False
        return _observation(
            "source",
            source.source_id,
            "source",
            valid_api_id,
            "available" if valid_api_id else "credential_invalid",
        )

    async def _destination(self, destination: Destination) -> CapabilityObservation:
        credential_available = False
        if destination.secret_id is not None:
            secret = await self.session.get(EncryptedSecret, destination.secret_id)
            if secret is not None:
                try:
                    EncryptedSecretStore(
                        self.session,
                        MasterKeyRing.from_settings(self.config),
                    ).decrypt(
                        secret,
                        principal=SecurityPrincipal(
                            "internal_service",
                            "publishing-worker",
                            parse_scopes(self.config.security_internal_scopes),
                        ),
                        required_scope="destinations:read",
                    )
                    credential_available = True
                except Exception:
                    credential_available = False
        else:
            credential_available = _secret_value(self.secret_resolver, destination.secret_ref) is not None
        available = credential_available and destination.enabled and destination.health_status == "healthy"
        if not credential_available:
            failure_code = "credential_missing"
        elif not destination.enabled:
            failure_code = "disabled"
        elif destination.health_status != "healthy":
            failure_code = "health_check_failed"
        else:
            failure_code = "available"
        return _observation(
            "destination",
            destination.id,
            "publishing",
            available,
            failure_code,
        )


class CapabilityStatusService:
    """Answers capability questions from one worker-heartbeat snapshot.

    An instance reads the heartbeat table at most once and projects every
    later question from that snapshot, so a caller asking about many
    resources (a scheduler tick, a resource summary, one API request) pays a
    single scan. The snapshot is therefore as old as the instance: construct
    a new service whenever newer heartbeats must be observed, and keep
    instances short-lived — request-, tick-, or call-scoped.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        config: Settings = settings,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.config = config
        self.clock = clock or (lambda: datetime.now(UTC))
        self._heartbeats: list[RuntimeHeartbeat] | None = None

    async def _worker_heartbeats(self) -> list[RuntimeHeartbeat]:
        if self._heartbeats is None:
            self._heartbeats = list(
                await self.session.scalars(
                    select(RuntimeHeartbeat)
                    .where(RuntimeHeartbeat.component_type == "worker")
                    .order_by(RuntimeHeartbeat.observed_at.desc())
                    .limit(10_000)
                )
            )
        return self._heartbeats

    async def get(
        self,
        resource_type: ResourceType,
        resource_id: UUID,
        capability: ResourceCapability,
    ) -> CapabilityStatus:
        return project_capability_status(
            await self._worker_heartbeats(),
            resource_type=resource_type,
            resource_id=resource_id,
            capability=capability,
            reference_time=self.clock(),
            ttl_seconds=self.config.capability_observation_ttl_seconds,
        )

    async def require_available(
        self,
        resource_type: ResourceType,
        resource_id: UUID,
        capability: ResourceCapability,
        *,
        job_type: str,
    ) -> CapabilityStatus:
        status = await self.get(resource_type, resource_id, capability)
        if not status.available:
            raise JobCapabilityUnavailable(
                code=(
                    "job_capability_unknown" if status.status in {"unknown", "stale"} else "job_capability_unavailable"
                ),
                job_type=job_type,
                retry_after_seconds=self.config.capability_retry_after_seconds,
            )
        return status


def project_capability_status(
    heartbeats: Iterable[RuntimeHeartbeat],
    *,
    resource_type: ResourceType,
    resource_id: UUID,
    capability: ResourceCapability,
    reference_time: datetime,
    ttl_seconds: int,
) -> CapabilityStatus:
    now = _aware_utc(reference_time)
    ownership_mismatch: RuntimeHeartbeat | None = None
    expected_owner_capability = _OWNER_CAPABILITY[capability]
    for heartbeat in sorted(heartbeats, key=lambda row: row.observed_at, reverse=True):
        observations = _parse_observations(heartbeat.runtime_metadata)
        match = next(
            (
                item
                for item in observations
                if item.resource_type == resource_type
                and item.resource_id == resource_id
                and item.capability == capability
            ),
            None,
        )
        if match is None:
            continue
        if expected_owner_capability not in set(heartbeat.capabilities or []):
            ownership_mismatch = heartbeat
            continue
        observed_at = _aware_utc(heartbeat.observed_at)
        expires_at = observed_at + timedelta(seconds=ttl_seconds)
        owner = _safe_owner(heartbeat.component_id)
        if expires_at <= now:
            return CapabilityStatus(
                status="stale",
                owner=owner,
                observed_at=observed_at,
                expires_at=expires_at,
                failure_code="observation_stale",
            )
        return CapabilityStatus(
            status=match.state,
            owner=owner,
            observed_at=observed_at,
            expires_at=expires_at,
            failure_code=_safe_failure_code(match.failure_code),
        )
    if ownership_mismatch is not None:
        return CapabilityStatus(
            status="unknown",
            owner=_safe_owner(ownership_mismatch.component_id),
            observed_at=_aware_utc(ownership_mismatch.observed_at),
            expires_at=None,
            failure_code="ownership_mismatch",
        )
    return CapabilityStatus(
        status="unknown",
        owner=None,
        observed_at=None,
        expires_at=None,
        failure_code="observation_missing",
    )


def _parse_observations(metadata: object) -> list[CapabilityObservation]:
    if not isinstance(metadata, dict):
        return []
    values = metadata.get("external_capabilities")
    if not isinstance(values, list):
        return []
    observations: list[CapabilityObservation] = []
    for value in values:
        try:
            observations.append(CapabilityObservation.model_validate(value))
        except ValueError:
            continue
    return observations


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("capability timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _safe_owner(value: str) -> str | None:
    return value if _SAFE_COMPONENT_ID.fullmatch(value) else None


def _safe_failure_code(value: str) -> str:
    return value if value in _SAFE_FAILURE_CODES else "invalid_configuration"


__all__ = [
    "CapabilityObservation",
    "CapabilityStatus",
    "CapabilityStatusService",
    "WorkerCredentialCapabilityObserver",
    "project_capability_status",
    "provider_profile_capabilities",
    "provider_shape_capabilities",
    "resolve_provider_profile_capabilities",
]
