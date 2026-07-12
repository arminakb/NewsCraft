from __future__ import annotations

from typing import Any

from app.core.config import Settings, settings
from app.core.secrets import SecretResolver
from app.generation.providers.base import GenerationProvider
from app.generation.providers.fake import DeterministicFakeProvider


class DuplicateProviderError(ValueError):
    """Raised when a provider name is registered more than once."""


class UnknownProviderError(LookupError):
    """Raised when a provider name has not been registered."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, GenerationProvider] = {}

    def register(self, provider: GenerationProvider) -> None:
        name = provider.provider_name
        if name in self._providers:
            raise DuplicateProviderError(name)
        self._providers[name] = provider

    def get(self, name: str) -> GenerationProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise UnknownProviderError(name) from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(DeterministicFakeProvider())
    return registry


def build_provider_profile_resolver(
    *,
    secret_resolver: SecretResolver,
    http_client_factory: Any,
    application_settings: Settings = settings,
):
    from app.generation.providers.profiles import ProviderProfileResolver

    return ProviderProfileResolver(
        secret_resolver=secret_resolver,
        http_client_factory=http_client_factory,
        provider_registry=build_default_provider_registry(),
        application_settings=application_settings,
    )
