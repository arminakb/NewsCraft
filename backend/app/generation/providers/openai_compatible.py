from __future__ import annotations

from app.generation.providers.openrouter import OpenRouterProvider


class OpenAICompatibleProvider(OpenRouterProvider):
    """Generic OpenAI-compatible transport using the proven structured-output adapter."""

    provider_name = "openai_compatible"

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(base_url={self.base_url!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, app_title={self.app_title!r})"
        )


__all__ = ["OpenAICompatibleProvider"]
