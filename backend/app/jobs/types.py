from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, cast
from uuid import UUID

from app.core.redaction import redact_secrets
from app.jobs.secret_policy import restore_exempt_secrets


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    CANCELLED = "cancelled"


class JobErrorClass(StrEnum):
    RETRYABLE = "retryable"
    NEEDS_REVIEW = "needs_review"
    PERMANENT = "permanent"


class JobOrigin(StrEnum):
    MANUAL = "manual"
    SCHEDULER = "scheduler"
    AUTOMATION = "automation"
    RETRY = "retry"


class JobType(StrEnum):
    """Every job type the default registry can route.

    This enum is the inventory of routable work, not documentation: a job type
    the worker can claim but cannot route is a queued row that dies at claim
    time with ``UnknownJobTypeError``. ``build_default_registry`` registers
    through these members and
    ``tests/test_job_handler_registry.py::test_job_type_enum_matches_the_fully_capable_registry``
    fails the moment a registration and this enum disagree in either direction.
    """

    # ingestion capability
    CANARY_SOURCE_GENERATION = "operations.canary.source_generation"
    INGEST_COLLECT = "ingest.collect"
    INGEST_COLLECTION_CONTINUOUS_CYCLE = "ingest.collection.continuous_cycle"
    MANUAL_INTAKE = "manual_intake"
    STORY_GROUP_PENDING = "story.group_pending"

    # source capability
    SOURCE_ICON_DISCOVERY = "source.icon.discover"
    TELEGRAM_ROUTE_BACKFILL = "telegram.route.backfill"
    TELEGRAM_ROUTE_DRY_RUN = "telegram.route.dry_run"
    TELEGRAM_ROUTE_INITIALIZE = "telegram.route.initialize"
    TELEGRAM_ROUTE_POLL = "telegram.route.poll"

    # generation capability
    AUTOMATION_RUN_START = "automation.run.start"
    BUILD_EXPORT = "build_export"
    CONTENT_PACK_GENERATE = "content_pack.generate"
    CONTENT_PACK_GENERATE_TELEGRAM = "content_pack.generate_telegram"
    CONTENT_PACK_REGENERATE = "content_pack.regenerate"
    EXECUTE_RETENTION = "execute_retention"
    TELEGRAM_ROUTE_PROCESS = "telegram.route.process"

    # research backend
    RESEARCH_STORY = "research_story"

    # publishing capability
    CANARY_PUBLISHING = "operations.canary.publishing"
    TELEGRAM_DESTINATION_CHECK = "telegram.destination.check"
    TELEGRAM_PROXY_CHECK = "telegram.proxy.check"
    TELEGRAM_PUBLISH = "telegram.publish"


def _freeze_json(value: object) -> object:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("job execution payload contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise TypeError("job execution payload keys must be strings")
            frozen[key] = _freeze_json(nested)
        return MappingProxyType(frozen)
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError(f"job execution payload contains unsupported {type(value).__name__}")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _reject_secret_payload(job_type: str, payload: dict[str, Any]) -> None:
    sanitized = redact_secrets(payload)
    if isinstance(sanitized, dict):
        sanitized = restore_exempt_secrets(job_type, payload, sanitized)
    if sanitized != payload:
        raise ValueError("job execution payload contains a secret value")


def _require_aware(value: datetime | None, *, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"job execution {field_name} must be timezone-aware")


class _JobSnapshot(Protocol):
    id: UUID
    job_type: str
    payload: Mapping[str, object]
    attempt_count: int
    max_attempts: int
    origin: JobOrigin | str
    lease_owner: str
    created_at: datetime
    scheduled_for: datetime | None
    priority: int
    pause_sensitive: bool
    automation_run_id: UUID | None
    automation_node_run_id: UUID | None


class _PayloadCarrier(Protocol):
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class JobExecution:
    """Immutable, session-independent snapshot passed to a job handler."""

    id: UUID
    job_type: str
    payload: Mapping[str, object] = field(hash=False, repr=False)
    attempt_count: int
    max_attempts: int
    origin: JobOrigin
    lease_owner: str
    created_at: datetime
    scheduled_for: datetime | None
    priority: int
    pause_sensitive: bool
    automation_run_id: UUID | None = None
    automation_node_run_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("job execution id must be a UUID")
        if not isinstance(self.job_type, str) or not self.job_type.strip():
            raise ValueError("job execution type must be non-empty")
        if isinstance(self.attempt_count, bool) or not isinstance(self.attempt_count, int) or self.attempt_count <= 0:
            raise ValueError("job execution attempt count must be positive")
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int) or self.max_attempts <= 0:
            raise ValueError("job execution max attempts must be positive")
        if self.attempt_count > self.max_attempts:
            raise ValueError("job execution attempt count exceeds max attempts")
        if not isinstance(self.lease_owner, str) or not self.lease_owner.strip():
            raise ValueError("job execution lease owner must be non-empty")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("job execution priority must be an integer")
        if not isinstance(self.pause_sensitive, bool):
            raise TypeError("job execution pause sensitivity must be boolean")
        _require_aware(self.created_at, field_name="created_at")
        _require_aware(self.scheduled_for, field_name="scheduled_for")
        try:
            origin = self.origin if isinstance(self.origin, JobOrigin) else JobOrigin(str(self.origin))
        except ValueError:
            raise ValueError("job execution origin is invalid") from None
        frozen_payload = _freeze_json(self.payload)
        if not isinstance(frozen_payload, Mapping):  # pragma: no cover - field type contract
            raise TypeError("job execution payload must be a mapping")
        mutable_payload = _thaw_json(frozen_payload)
        if not isinstance(mutable_payload, dict):  # pragma: no cover - mapping contract
            raise TypeError("job execution payload must be a mapping")
        _reject_secret_payload(self.job_type, mutable_payload)
        object.__setattr__(self, "origin", origin)
        object.__setattr__(self, "payload", frozen_payload)

    @classmethod
    def from_job(cls, job: _JobSnapshot) -> JobExecution:
        return cls(
            id=job.id,
            job_type=job.job_type,
            payload=job.payload,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            # __post_init__ validates and normalizes string-backed ORM enum values.
            origin=cast(JobOrigin, job.origin),
            lease_owner=job.lease_owner,
            created_at=job.created_at,
            scheduled_for=job.scheduled_for,
            priority=job.priority,
            pause_sensitive=job.pause_sensitive,
            automation_run_id=getattr(job, "automation_run_id", None),
            automation_node_run_id=getattr(job, "automation_node_run_id", None),
        )

    def payload_copy(self) -> dict[str, Any]:
        payload = _thaw_json(self.payload)
        if not isinstance(payload, dict):  # pragma: no cover - constructor invariant
            raise TypeError("job execution payload must be a mapping")
        return payload

    def with_payload(self, payload: Mapping[str, object]) -> JobExecution:
        return JobExecution(
            id=self.id,
            job_type=self.job_type,
            payload=payload,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            origin=self.origin,
            lease_owner=self.lease_owner,
            created_at=self.created_at,
            scheduled_for=self.scheduled_for,
            priority=self.priority,
            pause_sensitive=self.pause_sensitive,
            automation_run_id=self.automation_run_id,
            automation_node_run_id=self.automation_node_run_id,
        )


def job_payload_copy(job: JobExecution | _PayloadCarrier) -> dict[str, Any]:
    if isinstance(job, JobExecution):
        return job.payload_copy()
    payload = _thaw_json(job.payload)
    if not isinstance(payload, dict):
        raise TypeError("job payload must be a mapping")
    return payload
