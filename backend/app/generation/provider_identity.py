from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.config import Settings, settings
from app.generation.provider_settings import (
    CodexProviderSettings,
    OpenRouterProviderSettings,
    effective_codex_provider_settings,
)

PROMPT_COMPATIBILITY_REVISION = "newscraft-generation-contract-v1"


@dataclass(frozen=True, slots=True)
class ProviderConfigurationIdentity:
    revision: str
    checksum: str


def provider_configuration_identity(
    *,
    profile_id: UUID,
    provider_type: str,
    resolved_model: str,
    safe_settings: dict[str, Any],
) -> ProviderConfigurationIdentity:
    """Hash generation-affecting configuration without secret values or references."""

    canonical = json.dumps(
        {
            "profile_id": str(profile_id),
            "provider_type": provider_type,
            "resolved_model": resolved_model,
            "safe_settings": safe_settings,
            "prompt_compatibility": PROMPT_COMPATIBILITY_REVISION,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    checksum = hashlib.sha256(canonical).hexdigest()
    return ProviderConfigurationIdentity(revision=checksum[:16], checksum=checksum)


def provider_identity_for_profile(
    profile: Any,
    *,
    application_settings: Settings = settings,
) -> ProviderConfigurationIdentity:
    model = profile.default_model or ("fake-v1" if profile.provider_type == "fake" else "")
    if profile.provider_type == "openrouter":
        safe_settings = OpenRouterProviderSettings.model_validate(
            {"base_url": application_settings.openrouter_base_url, **dict(profile.settings or {})}
        ).model_dump(mode="json")
    elif profile.provider_type == "codex":
        safe_settings = effective_codex_provider_settings(
            CodexProviderSettings.model_validate(dict(profile.settings or {}))
        ).model_dump(mode="json")
    elif profile.provider_type == "fake":
        safe_settings = {}
    else:
        raise ValueError("unsupported generation provider type")
    return provider_configuration_identity(
        profile_id=profile.id,
        provider_type=profile.provider_type,
        resolved_model=model,
        safe_settings=safe_settings,
    )


def is_qualified_generation_profile(
    profile: Any,
    *,
    application_settings: Settings = settings,
) -> bool:
    if profile.provider_type != "openrouter":
        return True
    validated = OpenRouterProviderSettings.model_validate(
        {"base_url": application_settings.openrouter_base_url, **dict(profile.settings or {})}
    )
    return (
        validated.generation_policy is not None
        and validated.generation_policy.qualification_status == "qualified"
        and validated.pricing is not None
    )


__all__ = [
    "PROMPT_COMPATIBILITY_REVISION",
    "ProviderConfigurationIdentity",
    "provider_configuration_identity",
    "provider_identity_for_profile",
    "is_qualified_generation_profile",
]
