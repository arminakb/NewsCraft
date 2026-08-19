from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.resources import count_automation_definitions_referencing
from app.automations.models import AutomationRoute
from app.core.config import Settings, settings
from app.core.outbound_proxy import build_outbound_http_client
from app.generation.models import AIProviderProfile, GenerationRun
from app.generation.provider_settings import merge_provider_settings
from app.generation.providers.base import GenerationProviderRequest, ProviderMessage
from app.generation.providers.openai_compatible import OpenAICompatibleProvider
from app.jobs.models import WorkflowJob
from app.llm_providers.models import LLMProvider
from app.llm_providers.readiness import (
    DEFAULT_PROVIDER_TEST_TTL_SECONDS,
    ProviderReadiness,
    provider_capability_ready,
    provider_readiness,
)
from app.llm_providers.schemas import (
    LLMProviderCreate,
    LLMProviderDependenciesOut,
    LLMProviderOut,
    LLMProviderPatch,
    LLMProviderSettings,
    effective_llm_provider_settings,
    generation_policy_for_provider,
)
from app.research.models import ResearchRun
from app.research.openrouter_loop import research_action_schema, research_system_policy
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.secret_store import (
    EncryptedSecretStore,
    MasterKeyRing,
    SecretDecryptionFailed,
    SecretRotationFailed,
    SecretStore,
    SecretStoreError,
    SecretStoreUnavailable,
)


@dataclass(frozen=True, slots=True)
class CapabilityProbeResult:
    requested_model: str
    resolved_model: str
    latency_ms: int


@dataclass(frozen=True, slots=True)
class ProviderProbeResult:
    generation: CapabilityProbeResult
    research: CapabilityProbeResult
    latency_ms: int


class ProviderProbeFailure(RuntimeError):
    def __init__(
        self,
        capability: Literal["generation", "research"],
        cause: Exception,
        *,
        generation: CapabilityProbeResult | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self.capability = capability
        self.cause = cause
        self.generation = generation
        self.latency_ms = latency_ms
        super().__init__(f"{capability} probe failed")


ProviderProbe = Callable[
    [LLMProvider, str, LLMProviderSettings],
    Awaitable[ProviderProbeResult | None],
]
_ACTIVE_JOB_STATES = frozenset({"queued", "running", "retry_scheduled", "paused"})
_PROVIDER_HTTP_ERROR = re.compile(r"(?:openrouter|openai_compatible)_http_(\d{3})\Z")
CREDENTIAL_REPLACEMENT_REQUIRED = "credential_replacement_required"
# Reasoning-capable models spend output tokens on hidden reasoning before the structured
# answer, so the probe budget must clear that floor or every response arrives truncated.
# Measured on openai/gpt-oss-20b: generation reasoning peaked near 180 output tokens and
# research action reasoning near 610, so budgets keep roughly a 3x margin over the peak.
GENERATION_PROBE_TOKENS = 1_024
RESEARCH_PROBE_TOKENS = 2_048


def connection_failure_code(exc: Exception) -> str:
    if isinstance(exc, ProviderProbeFailure):
        return connection_failure_code(exc.cause)
    code = str(getattr(exc, "code", exc))
    status_match = _PROVIDER_HTTP_ERROR.fullmatch(code)
    if status_match is not None:
        status = int(status_match.group(1))
        if status == 401:
            return "authentication_failed"
        if status == 403:
            # OpenRouter uses 401 for rejected credentials; 403 comes from the provider edge
            # (security policy / moderation), so it must not be reported as a bad API key.
            return "provider_blocked"
        if status == 404:
            return "model_unavailable"
        return "connection_failed"
    if code in {"openrouter_model_missing", "openai_compatible_model_missing"}:
        return "model_unavailable"
    if code in {"openrouter_transport_failed", "openai_compatible_transport_failed"}:
        return "connection_failed"
    if code in {"openrouter_output_truncated", "openai_compatible_output_truncated"}:
        return "output_truncated"
    if code.startswith(("openrouter_output_invalid_", "openai_compatible_output_invalid_")):
        return "invalid_configuration"
    if code == "credential_missing":
        return "credential_missing"
    if isinstance(exc, (ValidationError, ValueError)):
        return "invalid_configuration"
    return "connection_failed"


def _base_url(value: object) -> str:
    if any(getattr(value, field, None) is not None for field in ("username", "password", "query", "fragment")):
        raise ValueError("base_url must be a credential-free HTTPS URL")
    rendered = str(value).rstrip("/")
    if not rendered.startswith("https://"):
        raise ValueError("base_url must use HTTPS")
    return rendered


def _settings(value: LLMProviderSettings | Mapping[str, Any]) -> dict[str, Any]:
    parsed = value if isinstance(value, LLMProviderSettings) else LLMProviderSettings.model_validate(value)
    return parsed.model_dump(mode="json")


def _legacy_settings(provider: LLMProvider) -> dict[str, Any]:
    if provider.protocol == "fake":
        return {}
    configured = effective_llm_provider_settings(provider.settings)
    attribution = configured.attribution_headers
    legacy = {
        "base_url": provider.base_url,
        "timeout_seconds": configured.timeout_seconds,
        "http_referer": str(attribution.http_referer) if attribution.http_referer else None,
        "pricing": configured.pricing.model_dump(mode="json"),
        "research_budgets": configured.research_budgets.model_dump(mode="json"),
        "generation_policy": generation_policy_for_provider(configured).model_dump(mode="json"),
    }
    if attribution.app_title is not None:
        legacy["app_title"] = attribution.app_title
    return legacy


def _contains_provider_id(value: object, provider_id: str) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_provider_id(item, provider_id) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_provider_id(item, provider_id) for item in value)
    return str(value) == provider_id


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


async def _default_probe(
    provider: LLMProvider,
    api_key: str,
    configured: LLMProviderSettings,
) -> ProviderProbeResult:
    if provider.base_url is None:
        raise ValueError("provider base URL is unavailable")
    attribution = configured.attribution_headers
    client = build_outbound_http_client(
        base_url=provider.base_url,
        timeout=configured.timeout_seconds,
    )
    adapter: OpenAICompatibleProvider = OpenAICompatibleProvider(
        http_client=client,
        api_key=api_key,
        base_url=provider.base_url,
        timeout_seconds=configured.timeout_seconds,
        http_referer=str(attribution.http_referer) if attribution.http_referer else None,
        app_title=attribution.app_title,
    )
    try:
        generation_started = time.perf_counter()
        try:
            generation_result = await adapter.generate(
                GenerationProviderRequest(
                    run_id=uuid4(),
                    purpose="connection_test",
                    requested_model=provider.default_model,
                    messages=(ProviderMessage(role="user", content="Return JSON with ok=true."),),
                    response_schema={
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["ok"],
                        "properties": {"ok": {"type": "boolean"}},
                    },
                    metadata={"max_output_tokens": min(configured.max_output_tokens, GENERATION_PROBE_TOKENS)},
                )
            )
        except Exception as exc:
            raise ProviderProbeFailure("generation", exc, latency_ms=_elapsed_ms(generation_started)) from exc

        generation = CapabilityProbeResult(
            requested_model=provider.default_model,
            resolved_model=generation_result.resolved_model,
            latency_ms=_elapsed_ms(generation_started),
        )
        research_started = time.perf_counter()
        try:
            research_result = await adapter.generate(
                GenerationProviderRequest(
                    run_id=uuid4(),
                    purpose="research_action",
                    requested_model=provider.default_model,
                    messages=(
                        ProviderMessage(role="system", content=research_system_policy()),
                        ProviderMessage(
                            role="user",
                            content=(
                                "Return exactly one finish action with an empty research brief. "
                                "Do not search or fetch."
                            ),
                        ),
                    ),
                    response_schema=research_action_schema(),
                    metadata={"max_output_tokens": min(configured.max_output_tokens, RESEARCH_PROBE_TOKENS)},
                )
            )
        except Exception as exc:
            raise ProviderProbeFailure(
                "research",
                exc,
                generation=generation,
                latency_ms=_elapsed_ms(generation_started),
            ) from exc

        return ProviderProbeResult(
            generation=generation,
            research=CapabilityProbeResult(
                requested_model=provider.default_model,
                resolved_model=research_result.resolved_model,
                latency_ms=_elapsed_ms(research_started),
            ),
            latency_ms=_elapsed_ms(generation_started),
        )
    finally:
        await client.aclose()


def _failure_message(code: str, *, capability: Literal["generation", "research"] = "generation") -> str:
    if capability == "research":
        if code == "output_truncated":
            return (
                "Generation is healthy, but Research is unavailable because the model ran out of "
                "output tokens before completing a research action."
            )
        if code == "provider_blocked":
            return (
                "Generation is healthy, but Research is unavailable because the provider edge "
                "rejected the request. Retry in a few minutes."
            )
        return (
            "Generation is healthy, but Research is unavailable because the model failed "
            "the research action contract."
        )
    return {
        "authentication_failed": "The provider rejected the API credential.",
        "model_unavailable": "The configured model could not be used.",
        "connection_failed": "The provider could not be reached.",
        "provider_blocked": (
            "The provider edge rejected the request with HTTP 403 before the model was reached. "
            "This is not a credential problem. Retry in a few minutes."
        ),
        "output_truncated": (
            "The configured model ran out of output tokens before returning a valid response. "
            "Raise the output token allowance or choose a model with less reasoning overhead."
        ),
        "invalid_configuration": "Provider configuration is invalid.",
        "credential_missing": "Provider credential is missing.",
    }.get(code, "The provider connection test failed.")


class ProviderDependencyConflict(RuntimeError):
    def __init__(self, dependencies: LLMProviderDependenciesOut) -> None:
        self.dependencies = dependencies
        super().__init__("provider_has_dependencies")


class ProviderNotReady(RuntimeError):
    def __init__(self, readiness: ProviderReadiness) -> None:
        self.readiness = readiness
        super().__init__(readiness.message)


class LLMProviderService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        principal: SecurityPrincipal,
        key_ring: MasterKeyRing | None = None,
        secret_store: SecretStore | None = None,
        config: Settings = settings,
        probe: ProviderProbe = _default_probe,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session = session
        self.principal = principal
        self.key_ring = key_ring
        self.secret_store = secret_store
        self.config = config
        self.probe = probe
        self.clock = clock or (lambda: datetime.now(UTC))

    def _secret_store(self) -> SecretStore:
        if self.secret_store is not None:
            return self.secret_store
        if self.key_ring is None:
            raise SecretStoreUnavailable
        return EncryptedSecretStore(self.session, self.key_ring)

    async def _shadow(self, provider: LLMProvider) -> AIProviderProfile:
        shadow = await self.session.get(AIProviderProfile, provider.id)
        if shadow is None:
            shadow = AIProviderProfile(id=provider.id, name=provider.name, provider_type="fake")
            self.session.add(shadow)
        shadow.name = provider.name
        shadow.provider_type = "fake" if provider.protocol == "fake" else "openrouter"
        shadow.default_model = provider.default_model
        shadow.secret_ref = None
        shadow.settings = _legacy_settings(provider)
        shadow.enabled = provider.enabled
        return shadow

    async def list(self) -> list[LLMProvider]:
        statement = select(LLMProvider).order_by(LLMProvider.name)
        if self.config.app_env.casefold() not in {"development", "local", "test"}:
            statement = statement.where(LLMProvider.protocol != "fake")
        return list(await self.session.scalars(statement))

    async def get(self, provider_id: UUID, *, for_update: bool = False) -> LLMProvider | None:
        statement = select(LLMProvider).where(LLMProvider.id == provider_id)
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def create(self, body: LLMProviderCreate) -> LLMProvider:
        if body.protocol == "fake" and self.config.app_env.casefold() not in {"development", "local", "test"}:
            raise ValueError("fake providers are unavailable")
        if body.enabled and body.protocol != "fake":
            raise ValueError("provider must pass connection test before enablement")
        provider = LLMProvider(
            id=uuid4(),
            name=body.name,
            protocol=body.protocol,
            base_url=_base_url(body.base_url) if body.base_url is not None else None,
            default_model=body.default_model,
            enabled=body.enabled,
            settings=_settings(body.settings),
            health_status="healthy" if body.protocol == "fake" else "unchecked",
            generation_capability="ready" if body.protocol == "fake" else "unknown",
            research_capability="ready" if body.protocol == "fake" else "unknown",
            failure_code=None,
            ownership="operator_managed",
        )
        self.session.add(provider)
        if body.protocol == "openai_compatible":
            assert body.api_key is not None
            secret = self._secret_store().create(
                purpose="provider_api_key",
                owner_type="llm_provider",
                owner_id=provider.id,
                value=body.api_key,
                principal=self.principal,
                required_scope="providers:write",
            )
            await self.session.flush([secret])
            provider.secret_id = secret.id
        await self._shadow(provider)
        await self.session.flush()
        return provider

    async def patch(self, provider: LLMProvider, body: LLMProviderPatch) -> LLMProvider:
        patch = body.model_dump(exclude_unset=True)
        if "name" in patch:
            provider.name = patch["name"].strip()
        if "default_model" in patch:
            provider.default_model = patch["default_model"].strip()
        if "base_url" in patch:
            if provider.protocol == "fake":
                raise ValueError("fake provider forbids base_url")
            provider.base_url = _base_url(patch["base_url"])
        if "settings" in patch:
            current = effective_llm_provider_settings(provider.settings).model_dump(mode="json")
            provider.settings = _settings(merge_provider_settings(current, patch["settings"]))
        if patch:
            replacement_required = provider.failure_code == CREDENTIAL_REPLACEMENT_REQUIRED
            provider.health_status = "unhealthy" if replacement_required else "unchecked"
            provider.generation_capability = "unavailable" if replacement_required else "unknown"
            provider.research_capability = "unavailable" if replacement_required else "unknown"
            provider.failure_code = CREDENTIAL_REPLACEMENT_REQUIRED if replacement_required else None
            provider.failure_message = (
                "Replace the provider credential, then run a new connection test."
                if replacement_required
                else None
            )
            if replacement_required:
                provider.enabled = False
            provider.last_checked_at = None
            provider.last_successful_test_at = None
            provider.last_test_latency_ms = None
            provider.last_tested_model = None
        await self._shadow(provider)
        await self.session.flush()
        return provider

    async def rotate_secret(self, provider: LLMProvider, value: str) -> LLMProvider:
        if provider.protocol != "openai_compatible":
            raise ValueError("provider secret cannot be rotated")
        if provider.secret_id is None:
            created_secret = self._secret_store().create(
                purpose="provider_api_key",
                owner_type="llm_provider",
                owner_id=provider.id,
                value=value,
                principal=self.principal,
                required_scope="providers:write",
            )
            await self.session.flush([created_secret])
            provider.secret_id = created_secret.id
        else:
            secret = await self.session.get(EncryptedSecret, provider.secret_id)
            if secret is None:
                raise SecretRotationFailed
            self._secret_store().rotate(
                secret,
                value,
                principal=self.principal,
                required_scope="providers:write",
            )
        provider.enabled = False
        provider.health_status = "unchecked"
        provider.generation_capability = "unknown"
        provider.research_capability = "unknown"
        provider.failure_code = None
        provider.failure_message = None
        provider.last_checked_at = None
        provider.last_successful_test_at = None
        provider.last_test_latency_ms = None
        provider.last_tested_model = None
        await self._shadow(provider)
        return provider

    async def test_connection(self, provider: LLMProvider) -> LLMProvider:
        checked_at = self.clock()
        provider.last_checked_at = checked_at
        provider.last_tested_model = provider.default_model
        provider.last_test_latency_ms = None
        provider.failure_message = None
        if provider.protocol == "fake":
            if self.config.app_env.casefold() not in {"development", "local", "test"}:
                raise ValueError("fake providers are unavailable")
            provider.health_status = "healthy"
            provider.generation_capability = "ready"
            provider.research_capability = "ready"
            provider.failure_code = None
            provider.failure_message = None
            provider.last_successful_test_at = checked_at
            provider.last_test_latency_ms = 0
            return provider
        try:
            configured = effective_llm_provider_settings(provider.settings)
            if provider.secret_id is None:
                raise RuntimeError("credential_missing")
            secret = await self.session.get(EncryptedSecret, provider.secret_id)
            if secret is None:
                raise RuntimeError("credential_missing")
            api_key = self._secret_store().decrypt(
                secret,
                principal=self.principal,
                required_scope="providers:write",
            )
            probe_result = await self.probe(provider, api_key, configured)
        except SecretDecryptionFailed:
            await self.mark_credential_replacement_required(provider)
            raise
        except SecretStoreError:
            raise
        except ProviderProbeFailure as exc:
            failure = connection_failure_code(exc)
            provider.last_test_latency_ms = exc.latency_ms
            if exc.capability == "research" and exc.generation is not None:
                provider.health_status = "degraded"
                provider.generation_capability = "ready"
                provider.research_capability = "unavailable"
                provider.failure_code = f"research_{failure}"
                provider.failure_message = _failure_message(failure, capability="research")
                provider.last_successful_test_at = checked_at
                provider.last_tested_model = exc.generation.resolved_model
                await self._shadow(provider)
                return provider
            provider.health_status = "unhealthy"
            provider.generation_capability = "unavailable"
            provider.research_capability = "unavailable"
            provider.failure_code = failure
            provider.failure_message = _failure_message(failure)
            provider.enabled = False
            await self._shadow(provider)
            return provider
        except Exception as exc:
            failure = connection_failure_code(exc)
            provider.health_status = "unhealthy"
            provider.generation_capability = "unavailable"
            provider.research_capability = "unavailable"
            provider.failure_code = failure
            provider.failure_message = _failure_message(failure)
            provider.enabled = False
            await self._shadow(provider)
            return provider
        provider.health_status = "healthy"
        provider.generation_capability = "ready"
        provider.research_capability = "ready"
        provider.failure_code = None
        provider.failure_message = None
        provider.last_successful_test_at = checked_at
        if probe_result is None:
            provider.last_test_latency_ms = 0
        else:
            provider.last_test_latency_ms = probe_result.latency_ms
            provider.last_tested_model = probe_result.generation.resolved_model
        return provider

    async def mark_credential_replacement_required(self, provider: LLMProvider) -> None:
        provider.enabled = False
        provider.health_status = "unhealthy"
        provider.generation_capability = "unavailable"
        provider.research_capability = "unavailable"
        provider.failure_code = CREDENTIAL_REPLACEMENT_REQUIRED
        provider.failure_message = "Replace the provider credential, then run a new connection test."
        await self._shadow(provider)

    async def enable(self, provider: LLMProvider) -> LLMProvider:
        readiness = provider_readiness(
            provider,
            now=self.clock(),
            ttl_seconds=self.config.llm_provider_test_ttl_seconds,
        )
        if not readiness.ready:
            raise ProviderNotReady(readiness)
        provider.enabled = True
        await self._shadow(provider)
        return provider

    async def disable(self, provider: LLMProvider) -> LLMProvider:
        provider.enabled = False
        await self._shadow(provider)
        return provider

    async def dependencies(self, provider_id: UUID) -> LLMProviderDependenciesOut:
        automations = int(
            await self.session.scalar(
                select(func.count())
                .select_from(AutomationRoute)
                .where(
                    or_(
                        AutomationRoute.ai_provider_profile_id == provider_id,
                        AutomationRoute.content_filters["research_provider_profile_id"].as_string() == str(provider_id),
                    )
                )
            )
            or 0
        )
        automations += await count_automation_definitions_referencing(self.session, provider_id)
        generation_runs = int(
            await self.session.scalar(
                select(func.count()).select_from(GenerationRun).where(GenerationRun.provider_profile_id == provider_id)
            )
            or 0
        )
        research_runs = int(
            await self.session.scalar(
                select(func.count()).select_from(ResearchRun).where(ResearchRun.provider_profile_id == provider_id)
            )
            or 0
        )
        active = list(await self.session.scalars(select(WorkflowJob).where(WorkflowJob.status.in_(_ACTIVE_JOB_STATES))))
        active_jobs = sum(_contains_provider_id(job.payload, str(provider_id)) for job in active)
        return LLMProviderDependenciesOut(
            automations=automations,
            generation_runs=generation_runs,
            research_runs=research_runs,
            active_jobs=active_jobs,
            blocked=any((automations, generation_runs, research_runs, active_jobs)),
        )

    async def delete(self, provider: LLMProvider) -> None:
        dependencies = await self.dependencies(provider.id)
        if dependencies.blocked:
            raise ProviderDependencyConflict(dependencies)
        shadow = await self.session.get(AIProviderProfile, provider.id)
        secret = await self.session.get(EncryptedSecret, provider.secret_id) if provider.secret_id else None
        if shadow is not None:
            await self.session.delete(shadow)
        await self.session.delete(provider)
        await self.session.flush()
        if secret is not None:
            await self.session.delete(secret)


def provider_out(
    provider: LLMProvider,
    *,
    now: datetime | None = None,
    test_ttl_seconds: int = DEFAULT_PROVIDER_TEST_TTL_SECONDS,
) -> LLMProviderOut:
    configured = provider.protocol == "fake" or provider.secret_id is not None
    settings_value = effective_llm_provider_settings(provider.settings)
    readiness = provider_readiness(provider, now=now, ttl_seconds=test_ttl_seconds)
    return LLMProviderOut.model_validate(
        {
            "id": provider.id,
            "name": provider.name,
            "protocol": provider.protocol,
            "base_url": provider.base_url,
            "default_model": provider.default_model,
            "enabled": provider.enabled,
            "configured": configured,
            "settings": settings_value,
            "health_status": provider.health_status,
            "generation_capability": provider.generation_capability,
            "research_capability": provider.research_capability,
            "generation_ready": provider_capability_ready(
                provider,
                "generation",
                now=now,
                ttl_seconds=test_ttl_seconds,
            ),
            "research_ready": provider_capability_ready(
                provider,
                "research",
                now=now,
                ttl_seconds=test_ttl_seconds,
            ),
            "failure_code": provider.failure_code,
            "failure_message": provider.failure_message,
            "last_checked_at": provider.last_checked_at,
            "last_successful_test_at": provider.last_successful_test_at,
            "last_test_latency_ms": provider.last_test_latency_ms,
            "last_tested_model": provider.last_tested_model,
            "ready_for_enablement": readiness.ready,
            "readiness_code": readiness.code,
            "readiness_message": readiness.message,
            "ownership": provider.ownership,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
        }
    )


__all__ = [
    "CREDENTIAL_REPLACEMENT_REQUIRED",
    "LLMProviderService",
    "ProviderProbeFailure",
    "ProviderProbeResult",
    "ProviderDependencyConflict",
    "ProviderNotReady",
    "provider_out",
]
