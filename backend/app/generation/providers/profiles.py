from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.codex_exec import CodexExecutor
from app.core.config import Settings, settings
from app.core.outbound_proxy import build_outbound_http_client
from app.core.secrets import SecretResolver
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import OpenRouterProviderSettings
from app.generation.providers.base import GenerationProvider
from app.generation.providers.openai_compatible import OpenAICompatibleProvider
from app.generation.providers.openrouter import OpenRouterProvider
from app.generation.providers.registry import ProviderRegistry
from app.llm_providers.models import LLMProvider
from app.llm_providers.schemas import LLMProviderSettings
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
            if profile.secret_ref is not None or dict(profile.settings or {}):
                raise ProviderProfileConfigurationError("Fake provider profile has invalid settings")
            return ResolvedProviderProfile(
                profile_id=profile.id,
                provider_type="fake",
                model=model_override or profile.default_model or "fake-v1",
                provider=self.provider_registry.get("fake"),
            )
        if profile.provider_type == "codex":
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
                provider = self.provider_registry.create(
                    "codex",
                    executor=self.codex_executor_factory(executable),
                    profile=profile,
                )
            except TypeError, ValueError:
                raise ProviderProfileConfigurationError("Selected provider profile settings are invalid") from None
            return ResolvedProviderProfile(
                profile_id=profile.id,
                provider_type="codex",
                model=profile.default_model,
                provider=provider,
            )
        if profile.provider_type != "openrouter":
            raise ProviderProfileConfigurationError("Selected provider type is unsupported")
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
        try:
            if not self.secret_resolver.configured(profile.secret_ref):
                raise ProviderProfileConfigurationError("Selected provider profile secret is not configured")
            api_key = self.secret_resolver.resolve(profile.secret_ref)
        except ProviderProfileConfigurationError:
            raise
        except Exception:
            raise ProviderProfileConfigurationError("Selected provider profile secret is unavailable") from None
        http_kwargs = {
            "base_url": str(validated.base_url).rstrip("/"),
            "timeout_seconds": validated.timeout_seconds,
            "http_referer": str(validated.http_referer) if validated.http_referer else None,
            "app_title": validated.app_title,
        }
        client = self.http_client_factory(**http_kwargs)
        provider = OpenRouterProvider(
            http_client=client,
            api_key=api_key,
            **http_kwargs,
        )
        return ResolvedProviderProfile(
            profile_id=profile.id,
            provider_type="openrouter",
            model=model,
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
            configured = LLMProviderSettings.model_validate(generic.settings)
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
