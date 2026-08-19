from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.llm_providers.models import LLMProvider

CapabilityName = Literal["generation", "research"]
DEFAULT_PROVIDER_TEST_TTL_SECONDS = 3_600


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    ready: bool
    code: str
    message: str


def provider_test_is_fresh(
    provider: LLMProvider,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_PROVIDER_TEST_TTL_SECONDS,
) -> bool:
    if provider.protocol == "fake":
        return provider.health_status in {"healthy", "degraded"}
    tested_at = getattr(provider, "last_successful_test_at", None)
    if tested_at is None and getattr(provider, "health_status", None) in {"healthy", "degraded"}:
        # Compatibility for rows written before last_successful_test_at existed.
        tested_at = getattr(provider, "last_checked_at", None)
    if tested_at is None:
        return False

    tested_model = getattr(provider, "last_tested_model", None)
    if tested_model and tested_model != provider.default_model:
        return False

    observed_at = _utc(now or datetime.now(UTC))
    checked_at = _utc(tested_at)
    return checked_at <= observed_at + timedelta(seconds=5) and checked_at >= observed_at - timedelta(
        seconds=ttl_seconds
    )


def provider_capability_ready(
    provider: LLMProvider,
    capability: CapabilityName,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_PROVIDER_TEST_TTL_SECONDS,
) -> bool:
    value = getattr(provider, f"{capability}_capability", "unknown")
    return bool(
        provider.enabled
        and value == "ready"
        and provider_test_is_fresh(provider, now=now, ttl_seconds=ttl_seconds)
    )


def provider_readiness(
    provider: LLMProvider,
    *,
    now: datetime | None = None,
    ttl_seconds: int = DEFAULT_PROVIDER_TEST_TTL_SECONDS,
) -> ProviderReadiness:
    generation = provider.generation_capability
    if generation != "ready":
        if generation == "unknown" or provider.health_status == "unchecked":
            return ProviderReadiness(
                ready=False,
                code="test_required",
                message="Run a successful connection test before enabling this provider.",
            )
        if provider.failure_code == "credential_replacement_required":
            return ProviderReadiness(
                ready=False,
                code="credential_replacement_required",
                message="Replace the provider credential, then run a new connection test.",
            )
        return ProviderReadiness(
            ready=False,
            code="generation_unavailable",
            message=provider.failure_message or "The configured Generation model is unavailable.",
        )

    if not provider_test_is_fresh(provider, now=now, ttl_seconds=ttl_seconds):
        return ProviderReadiness(
            ready=False,
            code="test_stale",
            message="The connection test is stale. Run Test again before enabling this provider.",
        )

    research = _capability_label(provider.research_capability)
    return ProviderReadiness(
        ready=True,
        code="ready_for_generation",
        message=f"Ready for Generation. Research is {research}.",
    )


def _capability_label(value: str) -> str:
    return {
        "ready": "Healthy",
        "unavailable": "Unavailable",
        "unknown": "Not tested",
    }.get(value, "Unavailable")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_PROVIDER_TEST_TTL_SECONDS",
    "ProviderReadiness",
    "provider_capability_ready",
    "provider_readiness",
    "provider_test_is_fresh",
]
