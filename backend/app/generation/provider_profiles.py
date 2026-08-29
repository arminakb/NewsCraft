from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.generation.errors import InvalidGenerationRequest
from app.generation.models import AIProviderProfile
from app.generation.provider_identity import (
    ProviderConfigurationIdentity,
    is_qualified_generation_profile,
    provider_identity_for_profile,
)
from app.jobs.credential_capabilities import provider_shape_capabilities
from app.llm_providers.models import LLMProvider
from app.llm_providers.readiness import provider_capability_ready


async def require_generation_profile(
    session: Any,
    profile_resolver: Any,
    profile_id: UUID,
) -> tuple[AIProviderProfile, ProviderConfigurationIdentity]:
    profile = await session.scalar(
        select(AIProviderProfile).where(AIProviderProfile.id == profile_id).with_for_update()
    )
    if profile is None or not profile.enabled or not profile.default_model:
        raise InvalidGenerationRequest("generation provider profile is unavailable")
    await _require_capability(session, profile)
    resolved = await _resolve_availability(session, profile_resolver, profile)
    try:
        if not is_qualified_generation_profile(profile):
            raise InvalidGenerationRequest("generation provider profile is not qualified")
    except ValueError:
        raise InvalidGenerationRequest("generation provider profile is unavailable") from None
    if getattr(resolved, "configuration_checksum", None):
        return profile, ProviderConfigurationIdentity(
            revision=resolved.configuration_revision,
            checksum=resolved.configuration_checksum,
        )
    try:
        return profile, provider_identity_for_profile(profile)
    except ValueError:
        raise InvalidGenerationRequest("generation provider profile is unavailable") from None


async def _require_capability(session: Any, profile: AIProviderProfile) -> None:
    generic = await session.get(LLMProvider, profile.id) if isinstance(session, AsyncSession) else None
    if generic is None:
        shaped, _codes = provider_shape_capabilities(profile)
        available = shaped["generation"]
    else:
        available = provider_capability_ready(
            generic,
            "generation",
            ttl_seconds=settings.llm_provider_test_ttl_seconds,
        )
    if not available:
        raise InvalidGenerationRequest("generation provider profile is unavailable")


async def _resolve_availability(
    session: Any,
    profile_resolver: Any,
    profile: AIProviderProfile,
) -> Any:
    if profile_resolver is None:
        return None
    try:
        validate_with_session = getattr(profile_resolver, "validate_availability_with_session", None)
        if validate_with_session is not None:
            return await validate_with_session(profile, None, session=session)
        validate = getattr(profile_resolver, "validate_availability", None) or profile_resolver.resolve
        return await validate(profile, None)
    except Exception:
        raise InvalidGenerationRequest("generation provider profile is unavailable") from None
