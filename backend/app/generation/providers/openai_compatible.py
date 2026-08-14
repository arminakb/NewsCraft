from __future__ import annotations

from app.generation.providers.openrouter import OpenRouterProvider


class OpenAICompatibleProvider(OpenRouterProvider):
    """Generic OpenAI-compatible transport using the proven structured-output adapter."""

    provider_name = "openai_compatible"


__all__ = ["OpenAICompatibleProvider"]
