from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
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
from app.llm_providers.schemas import (
    LLMProviderCreate,
    LLMProviderDependenciesOut,
    LLMProviderOut,
    LLMProviderPatch,
    LLMProviderSettings,
    effective_llm_provider_settings,
)
from app.research.models import ResearchRun
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.secret_store import (
    EncryptedSecretStore,
    MasterKeyRing,
    SecretRotationFailed,
    SecretStore,
    SecretStoreError,
    SecretStoreUnavailable,
)

ProviderProbe = Callable[[LLMProvider, str, LLMProviderSettings], Awaitable[None]]
_ACTIVE_JOB_STATES = frozenset({"queued", "running", "retry_scheduled", "paused"})


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
    return {
        "base_url": provider.base_url,
        "timeout_seconds": configured.timeout_seconds,
        "http_referer": str(attribution.http_referer) if attribution.http_referer else None,
        "app_title": attribution.app_title,
        "pricing": configured.pricing.model_dump(mode="json"),
        "research_budgets": configured.research_budgets.model_dump(mode="json"),
    }


def _contains_provider_id(value: object, provider_id: str) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_provider_id(item, provider_id) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_contains_provider_id(item, provider_id) for item in value)
    return str(value) == provider_id


async def _default_probe(provider: LLMProvider, api_key: str, configured: LLMProviderSettings) -> None:
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
        await adapter.generate(
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
                metadata={"max_output_tokens": min(configured.max_output_tokens, 32)},
            )
        )
    finally:
        await client.aclose()


class ProviderDependencyConflict(RuntimeError):
    def __init__(self, dependencies: LLMProviderDependenciesOut) -> None:
        self.dependencies = dependencies
        super().__init__("provider_has_dependencies")


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
            provider.health_status = "unchecked"
            provider.generation_capability = "unknown"
            provider.research_capability = "unknown"
            provider.failure_code = None
            provider.last_checked_at = None
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
        provider.last_checked_at = None
        await self._shadow(provider)
        return provider

    async def test_connection(self, provider: LLMProvider) -> LLMProvider:
        provider.last_checked_at = self.clock()
        if provider.protocol == "fake":
            if self.config.app_env.casefold() not in {"development", "local", "test"}:
                raise ValueError("fake providers are unavailable")
            provider.health_status = "healthy"
            provider.generation_capability = "ready"
            provider.research_capability = "ready"
            provider.failure_code = None
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
            await self.probe(provider, api_key, configured)
        except SecretStoreError:
            raise
        except Exception as exc:
            code = str(getattr(exc, "code", exc))
            if "401" in code or "403" in code:
                failure = "authentication_failed"
            elif "model" in code or "404" in code:
                failure = "model_unavailable"
            elif "credential" in code:
                failure = "credential_missing"
            elif isinstance(exc, (ValidationError, ValueError)):
                failure = "invalid_configuration"
            else:
                failure = "connection_failed"
            provider.health_status = "unhealthy"
            provider.generation_capability = "unavailable"
            provider.research_capability = "unavailable"
            provider.failure_code = failure
            provider.enabled = False
            await self._shadow(provider)
            return provider
        provider.health_status = "healthy"
        provider.generation_capability = "ready"
        provider.research_capability = "ready"
        provider.failure_code = None
        return provider

    async def enable(self, provider: LLMProvider) -> LLMProvider:
        if provider.generation_capability != "ready" or provider.research_capability != "ready":
            raise ValueError("provider must pass connection test before enablement")
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


def provider_out(provider: LLMProvider) -> LLMProviderOut:
    configured = provider.protocol == "fake" or provider.secret_id is not None
    settings_value = effective_llm_provider_settings(provider.settings)
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
            "generation_ready": provider.enabled and provider.generation_capability == "ready",
            "research_ready": provider.enabled and provider.research_capability == "ready",
            "failure_code": provider.failure_code,
            "last_checked_at": provider.last_checked_at,
            "ownership": provider.ownership,
            "created_at": provider.created_at,
            "updated_at": provider.updated_at,
        }
    )


__all__ = [
    "LLMProviderService",
    "ProviderDependencyConflict",
    "provider_out",
]
