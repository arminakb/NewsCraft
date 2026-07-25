from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.config import Settings, settings
from app.core.secrets import SecretResolver
from app.generation.providers.base import GenerationProvider
from app.generation.providers.codex import CodexGenerationProvider
from app.generation.providers.fake import DeterministicFakeProvider


class DuplicateProviderError(ValueError):
    """Raised when a provider name is registered more than once."""


class UnknownProviderError(LookupError):
    """Raised when a provider name has not been registered."""


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, GenerationProvider] = {}
        self._factories: dict[str, Callable[..., GenerationProvider]] = {}

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

    def register_factory(self, name: str, factory: Callable[..., GenerationProvider]) -> None:
        if name in self._factories:
            raise DuplicateProviderError(name)
        self._factories[name] = factory

    def create(self, name: str, **kwargs: Any) -> GenerationProvider:
        try:
            factory = self._factories[name]
        except KeyError:
            raise UnknownProviderError(name) from None
        return factory(**kwargs)

    def factory_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def build_default_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(DeterministicFakeProvider())
    registry.register_factory("codex", CodexGenerationProvider)
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
