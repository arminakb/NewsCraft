from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.codex_exec import CodexExecutor
from app.core.config import Settings, settings
from app.core.outbound_proxy import build_outbound_http_client
from app.core.secrets import SecretResolver
from app.generation.invalid_output_quarantine import AgeInvalidOutputQuarantine
from app.generation.models import AIProviderProfile
from app.generation.provider_identity import provider_configuration_identity
from app.generation.provider_settings import (
    CodexProviderSettings,
    OpenRouterProviderSettings,
    effective_codex_provider_settings,
)
from app.generation.providers.base import GenerationProvider
from app.generation.providers.openai_compatible import OpenAICompatibleProvider
from app.generation.providers.openrouter import OpenRouterProvider
from app.generation.providers.registry import ProviderRegistry
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import effective_llm_provider_settings
from app.security.auth import SecurityPrincipal
from app.security.models import EncryptedSecret
from app.security.scopes import parse_scopes
from app.security.secret_store import EncryptedSecretStore, MasterKeyRing


class ProviderProfileConfigurationError(ValueError):
    """Selected provider configuration cannot be executed safely."""


@dataclass(frozen=True, slots=True)
class ResolvedProviderProfile:
    profile_id: UUID
    provider_type: str
    model: str
    provider: GenerationProvider = field(repr=False)
    configuration_revision: str = ""
    configuration_checksum: str = ""
    max_output_tokens: int | None = None
    max_attempts: int | None = None
    max_pack_cost_usd: Decimal | None = None
    max_elapsed_seconds: int | None = None
    pricing_input_usd_per_million: Decimal | None = None
    pricing_output_usd_per_million: Decimal | None = None


def _default_http_client_factory(**kwargs) -> httpx.AsyncClient:
    return build_outbound_http_client(
        base_url=kwargs["base_url"],
        timeout=kwargs["timeout_seconds"],
    )


class ProviderProfileResolver:
    def __init__(
        self,
        *,
        secret_resolver: SecretResolver,
        http_client_factory: Callable[..., httpx.AsyncClient] = _default_http_client_factory,
        provider_registry: ProviderRegistry,
        application_settings: Settings = settings,
        executable_resolver: Callable[[str], str | None] = shutil.which,
        codex_executor_factory: Callable[[str], CodexExecutor] | None = None,
    ) -> None:
        self.secret_resolver = secret_resolver
        self.http_client_factory = http_client_factory
        self.provider_registry = provider_registry
        self.application_settings = application_settings
        self.executable_resolver = executable_resolver
        self.codex_executor_factory = codex_executor_factory or (
            lambda executable: CodexExecutor(executable=executable)
        )

    async def resolve(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
    ) -> ResolvedProviderProfile:
        if not profile.enabled:
            raise ProviderProfileConfigurationError("Selected provider profile is disabled")
        if profile.provider_type == "fake":
            return self._resolve_fake(profile, model_override)
        if profile.provider_type == "codex":
            return self._resolve_codex(profile)
        if profile.provider_type == "openrouter":
            return await self._resolve_openrouter(profile, model_override)
        raise ProviderProfileConfigurationError("Selected provider type is unsupported")

    def _resolve_fake(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
    ) -> ResolvedProviderProfile:
        if profile.secret_ref is not None or dict(profile.settings or {}):
            raise ProviderProfileConfigurationError("Fake provider profile has invalid settings")
        model = model_override or profile.default_model or "fake-v1"
        identity = provider_configuration_identity(
            profile_id=profile.id,
            provider_type="fake",
            resolved_model=model,
            safe_settings={},
        )
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="fake",
            model=model,
            configuration_revision=identity.revision,
            configuration_checksum=identity.checksum,
            provider=self.provider_registry.get("fake"),
        )

    def _resolve_codex(self, profile: AIProviderProfile) -> ResolvedProviderProfile:
        if not self.application_settings.codex_enabled:
            raise ProviderProfileConfigurationError("Codex provider is disabled")
        if profile.secret_ref is not None:
            raise ProviderProfileConfigurationError("Codex provider profile cannot have a secret reference")
        if not profile.default_model:
            raise ProviderProfileConfigurationError("Selected provider profile has no model")
        executable = self.executable_resolver(self.application_settings.codex_executable)
        if executable is None:
            raise ProviderProfileConfigurationError("Codex executable is unavailable")
        try:
            validated = effective_codex_provider_settings(
                CodexProviderSettings.model_validate(dict(profile.settings or {}))
            )
            provider = self.provider_registry.create(
                "codex",
                executor=self.codex_executor_factory(executable),
                profile=profile,
            )
        except TypeError, ValueError:
            raise ProviderProfileConfigurationError("Selected provider profile settings are invalid") from None
        identity = provider_configuration_identity(
            profile_id=profile.id,
            provider_type="codex",
            resolved_model=profile.default_model,
            safe_settings=validated.model_dump(mode="json"),
        )
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="codex",
            model=profile.default_model,
            configuration_revision=identity.revision,
            configuration_checksum=identity.checksum,
            provider=provider,
        )

    def _openrouter_settings(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
    ) -> tuple[str, OpenRouterProviderSettings]:
        model = model_override or profile.default_model
        if not model:
            raise ProviderProfileConfigurationError("Selected provider profile has no model")
        if not profile.secret_ref:
            raise ProviderProfileConfigurationError("Selected provider profile has no secret reference")
        raw_settings: dict[str, Any] = {
            "base_url": self.application_settings.openrouter_base_url,
            **dict(profile.settings or {}),
        }
        try:
            validated = OpenRouterProviderSettings.model_validate(raw_settings)
        except ValidationError:
            raise ProviderProfileConfigurationError("Selected provider profile settings are invalid") from None
        if (
            validated.base_url.scheme != "https"
            or validated.base_url.username is not None
            or validated.base_url.password is not None
            or validated.base_url.query is not None
            or validated.base_url.fragment is not None
        ):
            raise ProviderProfileConfigurationError("Selected provider profile base URL is invalid")
        return model, validated

    def _openrouter_api_key(self, profile: AIProviderProfile) -> str:
        assert profile.secret_ref is not None
        try:
            if not self.secret_resolver.configured(profile.secret_ref):
                raise ProviderProfileConfigurationError("Selected provider profile secret is not configured")
            return self.secret_resolver.resolve(profile.secret_ref)
        except ProviderProfileConfigurationError:
            raise
        except Exception:
            raise ProviderProfileConfigurationError("Selected provider profile secret is unavailable") from None

    def _openrouter_http_kwargs(
        self,
        validated: OpenRouterProviderSettings,
    ) -> dict[str, Any]:
        return {
            "base_url": str(validated.base_url).rstrip("/"),
            "timeout_seconds": validated.timeout_seconds,
            "http_referer": str(validated.http_referer) if validated.http_referer else None,
            "app_title": validated.app_title,
        }

    async def _openrouter_quarantine(
        self,
        client: httpx.AsyncClient,
    ) -> AgeInvalidOutputQuarantine | None:
        if not self.application_settings.generation_invalid_output_quarantine_enabled:
            return None
        try:
            return AgeInvalidOutputQuarantine(
                root=self.application_settings.generation_invalid_output_quarantine_root,
                recipient_file=self.application_settings.generation_invalid_output_quarantine_recipient_file,
                max_bytes=self.application_settings.generation_invalid_output_quarantine_max_bytes,
                ttl_days=self.application_settings.generation_invalid_output_quarantine_ttl_days,
                age_executable=self.application_settings.generation_invalid_output_quarantine_age_executable,
            )
        except OSError, ValueError, RuntimeError:
            await client.aclose()
            raise ProviderProfileConfigurationError("Invalid output quarantine is unavailable") from None

    async def _resolve_openrouter(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
    ) -> ResolvedProviderProfile:
        model, validated = self._openrouter_settings(profile, model_override)
        api_key = self._openrouter_api_key(profile)
        http_kwargs = self._openrouter_http_kwargs(validated)
        client = self.http_client_factory(**http_kwargs)
        quarantine = await self._openrouter_quarantine(client)
        provider = OpenRouterProvider(
            http_client=client,
            api_key=api_key,
            invalid_output_quarantine=quarantine,
            **http_kwargs,
        )
        identity = provider_configuration_identity(
            profile_id=profile.id,
            provider_type="openrouter",
            resolved_model=model,
            safe_settings=validated.model_dump(mode="json"),
        )
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="openrouter",
            model=model,
            configuration_revision=identity.revision,
            configuration_checksum=identity.checksum,
            max_output_tokens=(
                validated.generation_policy.max_output_tokens if validated.generation_policy is not None else None
            ),
            max_attempts=(
                validated.generation_policy.max_attempts if validated.generation_policy is not None else None
            ),
            max_pack_cost_usd=(
                validated.generation_policy.max_pack_cost_usd if validated.generation_policy is not None else None
            ),
            max_elapsed_seconds=(
                validated.generation_policy.max_elapsed_seconds if validated.generation_policy is not None else None
            ),
            pricing_input_usd_per_million=(validated.pricing.input_usd_per_million if validated.pricing else None),
            pricing_output_usd_per_million=(validated.pricing.output_usd_per_million if validated.pricing else None),
            provider=provider,
        )

    async def validate_availability(
        self,
        profile: AIProviderProfile,
        model_override: str | None = None,
    ) -> ResolvedProviderProfile:
        """Resolve the canonical profile contract without retaining request resources."""
        resolved = await self.resolve(profile, model_override)
        client = getattr(resolved.provider, "http_client", None)
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()
        return resolved

    async def resolve_with_session(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
        *,
        session: Any,
    ) -> ResolvedProviderProfile:
        generic = await session.get(LLMProvider, profile.id)
        if generic is None:
            return await self.resolve(profile, model_override)
        if not generic.enabled or generic.generation_capability != "ready":
            raise ProviderProfileConfigurationError("Selected provider profile is unavailable")
        if generic.protocol == "fake":
            if generic.secret_id is not None or generic.base_url is not None:
                raise ProviderProfileConfigurationError("Fake provider profile has invalid settings")
            return ResolvedProviderProfile(
                profile_id=generic.id,
                provider_type="fake",
                model=model_override or generic.default_model,
                provider=self.provider_registry.get("fake"),
            )
        if generic.protocol != "openai_compatible" or generic.secret_id is None or generic.base_url is None:
            raise ProviderProfileConfigurationError("Selected provider type is unsupported")
        try:
            configured = effective_llm_provider_settings(generic.settings)
            secret = await session.get(EncryptedSecret, generic.secret_id)
            if secret is None:
                raise ProviderProfileConfigurationError("Selected provider profile secret is unavailable")
            principal = SecurityPrincipal(
                "internal_service",
                "generation-worker",
                parse_scopes(self.application_settings.security_internal_scopes),
            )
            api_key = EncryptedSecretStore(
                session,
                MasterKeyRing.from_settings(self.application_settings),
            ).decrypt(
                secret,
                principal=principal,
                required_scope="providers:read",
            )
        except ProviderProfileConfigurationError:
            raise
        except Exception:
            raise ProviderProfileConfigurationError("Selected provider profile is unavailable") from None
        attribution = configured.attribution_headers
        http_kwargs = {
            "base_url": generic.base_url,
            "timeout_seconds": configured.timeout_seconds,
            "http_referer": str(attribution.http_referer) if attribution.http_referer else None,
            "app_title": attribution.app_title,
        }
        client = self.http_client_factory(**http_kwargs)
        return ResolvedProviderProfile(
            profile_id=generic.id,
            provider_type="openai_compatible",
            model=model_override or generic.default_model,
            provider=OpenAICompatibleProvider(http_client=client, api_key=api_key, **http_kwargs),
        )

    async def validate_availability_with_session(
        self,
        profile: AIProviderProfile,
        model_override: str | None,
        *,
        session: Any,
    ) -> ResolvedProviderProfile:
        resolved = await self.resolve_with_session(profile, model_override, session=session)
        client = getattr(resolved.provider, "http_client", None)
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()
        return resolved
