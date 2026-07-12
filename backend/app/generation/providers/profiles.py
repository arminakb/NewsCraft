from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.secrets import SecretResolver
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import OpenRouterProviderSettings
from app.generation.providers.base import GenerationProvider
from app.generation.providers.openrouter import OpenRouterProvider
from app.generation.providers.registry import ProviderRegistry


class ProviderProfileConfigurationError(ValueError):
    """Selected provider configuration cannot be executed safely."""


@dataclass(frozen=True, slots=True)
class ResolvedProviderProfile:
    profile_id: UUID
    provider_type: str
    model: str
    provider: GenerationProvider = field(repr=False)


def _default_http_client_factory(**kwargs) -> httpx.AsyncClient:
    return httpx.AsyncClient(
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
    ) -> None:
        self.secret_resolver = secret_resolver
        self.http_client_factory = http_client_factory
        self.provider_registry = provider_registry
        self.application_settings = application_settings

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
            raise ProviderProfileConfigurationError(
                "Selected provider profile settings are invalid"
            ) from None
        if (
            validated.base_url.scheme != "https"
            or validated.base_url.username is not None
            or validated.base_url.password is not None
            or validated.base_url.query is not None
            or validated.base_url.fragment is not None
        ):
            raise ProviderProfileConfigurationError(
                "Selected provider profile base URL is invalid"
            )
        try:
            if not self.secret_resolver.configured(profile.secret_ref):
                raise ProviderProfileConfigurationError(
                    "Selected provider profile secret is not configured"
                )
            api_key = self.secret_resolver.resolve(profile.secret_ref)
        except ProviderProfileConfigurationError:
            raise
        except Exception:
            raise ProviderProfileConfigurationError(
                "Selected provider profile secret is unavailable"
            ) from None
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
