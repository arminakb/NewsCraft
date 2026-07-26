from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

from app.jobs.credential_capabilities import CapabilityStatus
from app.jobs.errors import JobCapabilityUnavailable


class StaticCapabilityStatusService:
    """Small endpoint-test double for worker-observed capability state."""

    def __init__(
        self,
        status: str = "available",
        *,
        failure_code: str | None = None,
        overrides: dict[tuple[str, UUID, str], CapabilityStatus] | None = None,
    ) -> None:
        self.status = status
        self.failure_code = failure_code
        self.overrides = overrides or {}
        self.config = SimpleNamespace(capability_retry_after_seconds=30)

    async def get(self, resource_type: str, resource_id: UUID, capability: str) -> CapabilityStatus:
        override = self.overrides.get((resource_type, resource_id, capability))
        if override is not None:
            return override
        observed_at = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
        fresh = self.status in {"available", "unavailable"}
        return CapabilityStatus(
            status=self.status,
            owner="worker-test" if self.status != "unknown" else None,
            observed_at=observed_at if self.status != "unknown" else None,
            expires_at=observed_at + timedelta(seconds=120) if fresh else None,
            failure_code=self.failure_code
            or {
                "available": "available",
                "unavailable": "credential_missing",
                "unknown": "observation_missing",
                "stale": "observation_stale",
            }[self.status],
        )

    async def require_available(
        self,
        resource_type: str,
        resource_id: UUID,
        capability: str,
        *,
        job_type: str,
    ) -> CapabilityStatus:
        status = await self.get(resource_type, resource_id, capability)
        if not status.available:
            raise JobCapabilityUnavailable(
                code=(
                    "job_capability_unknown" if status.status in {"unknown", "stale"} else "job_capability_unavailable"
                ),
                job_type=job_type,
                retry_after_seconds=self.config.capability_retry_after_seconds,
            )
        return status


AVAILABLE_CAPABILITIES = StaticCapabilityStatusService()
