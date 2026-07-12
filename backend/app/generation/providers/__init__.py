"""Generation provider extension contracts."""

from app.generation.providers.base import (
    GenerationProvider,
    GenerationProviderRequest,
    GenerationProviderResult,
    ProviderMessage,
)
from app.generation.providers.fake import DeterministicFakeProvider
from app.generation.providers.registry import (
    DuplicateProviderError,
    ProviderRegistry,
    UnknownProviderError,
    build_default_provider_registry,
)

__all__ = [
    "DeterministicFakeProvider",
    "DuplicateProviderError",
    "GenerationProvider",
    "GenerationProviderRequest",
    "GenerationProviderResult",
    "ProviderMessage",
    "ProviderRegistry",
    "UnknownProviderError",
    "build_default_provider_registry",
]
