from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.jobs.models import WorkflowJob
from app.retention.models import (
    RetentionPolicy,
    RetentionRun,
)

type RetentionCategory = Literal[
    "raw_payload",
    "completed_job",
    "attempt_metadata",
    "export_artifact",
    "unreferenced_media",
]
type RetentionOperation = Literal["scrub", "expire"]
type RetentionRecordType = Literal[
    "raw_payload",
    "workflow_job",
    "research_attempt",
    "generation_attempt",
    "publish_attempt",
    "media_asset",
]

RETENTION_CATEGORIES: tuple[RetentionCategory, ...] = (
    "raw_payload",
    "completed_job",
    "attempt_metadata",
    "export_artifact",
    "unreferenced_media",
)
# A plain alias, not a `type` statement: pydantic gives PEP 695 aliases their own
# named OpenAPI component, and this one must stay an inline enum in the published
# contract. The annotation on the constant is what keeps the two in step.
RetentionConfirmationPhrase = Literal["DELETE PREVIEWED DATA"]
RETENTION_CONFIRMATION: RetentionConfirmationPhrase = "DELETE PREVIEWED DATA"
RETENTION_PREVIEW_TTL = timedelta(minutes=30)
RAW_PAYLOAD_SCRUBBED_URL = "retention:scrubbed"
GENERATION_SUCCESS_STATUSES = ("succeeded", "completed")


class RetentionConflict(ValueError):
    """Raised when a retention preview can no longer be executed safely."""


class RetentionConfirmationError(ValueError):
    """Raised when destructive confirmation is not the exact locked phrase."""


class RetentionNotFound(LookupError):
    """Raised when a requested retention audit record does not exist."""


class RetentionPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_payload_days: int = Field(default=30, ge=7, le=3650)
    completed_job_days: int = Field(default=90, ge=14, le=3650)
    attempt_metadata_days: int = Field(default=90, ge=14, le=3650)
    export_artifact_days: int = Field(default=14, ge=1, le=3650)
    unreferenced_media_days: int = Field(default=30, ge=7, le=3650)


class RetentionCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: RetentionCategory
    record_type: RetentionRecordType
    record_id: UUID
    operation: RetentionOperation
    occurred_at: AwareDatetime
    byte_length: int | None = Field(default=None, ge=0)
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_record_type(self) -> RetentionCandidate:
        expected: Mapping[RetentionCategory, frozenset[RetentionRecordType]] = {
            "raw_payload": frozenset({"raw_payload"}),
            "completed_job": frozenset({"workflow_job"}),
            "attempt_metadata": frozenset({"research_attempt", "generation_attempt", "publish_attempt"}),
            "export_artifact": frozenset({"workflow_job"}),
            "unreferenced_media": frozenset({"media_asset"}),
        }
        if self.record_type not in expected[self.category]:
            raise ValueError(f"record_type {self.record_type!r} is invalid for category {self.category!r}")
        return self


class RetentionCategorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    count: int = Field(ge=0)
    byte_length: int | None = Field(default=None, ge=0)
    oldest_at: AwareDatetime | None
    newest_at: AwareDatetime | None


class RetentionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_revision: str
    policy: RetentionPolicyInput
    candidates: list[RetentionCandidate]
    counts: dict[RetentionCategory, RetentionCategorySummary]
    previewed_at: AwareDatetime
    preview_expires_at: AwareDatetime


class RetentionCleanupIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    category: Literal["export_artifact", "unreferenced_media"]
    record_id: UUID
    operation: Literal["delete_tree", "delete_file"]
    relative_path: str


type RetentionExecutionPhase = Literal[
    "scrubbed",
    "expired",
    "skipped",
    "database_skipped",
    "filesystem_skipped",
    "filesystem_deleted",
]


def _zero_counts() -> dict[RetentionCategory, int]:
    return {category: 0 for category in RETENTION_CATEGORIES}


def _completed_counts(value: dict[RetentionCategory, int]) -> dict[RetentionCategory, int]:
    counts = _zero_counts()
    counts.update(value)
    return counts


class RetentionExecutionCounts(BaseModel):
    """Per-phase, per-category bookkeeping of one retention execution.

    Every category is always present, so callers index the phase dicts
    directly instead of defaulting a missing key at each read site.
    """

    model_config = ConfigDict(extra="forbid")

    scrubbed: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)
    expired: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)
    skipped: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)
    database_skipped: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)
    filesystem_skipped: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)
    filesystem_deleted: dict[RetentionCategory, int] = Field(default_factory=_zero_counts)

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_snapshots(cls, value: object) -> object:
        """Rows written before `database_skipped` existed carry only `skipped`."""
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        if data.get("database_skipped") is None and isinstance(data.get("skipped"), Mapping):
            data["database_skipped"] = dict(data["skipped"])
        return data

    @model_validator(mode="after")
    def _complete_every_category(self) -> RetentionExecutionCounts:
        for phase, counts in self.phases().items():
            if set(counts) != set(RETENTION_CATEGORIES):
                setattr(self, phase, _completed_counts(counts))
        return self

    def phases(self) -> dict[RetentionExecutionPhase, dict[RetentionCategory, int]]:
        """The live phase dicts, keyed by phase name (mutating a value counts)."""
        return {
            "scrubbed": self.scrubbed,
            "expired": self.expired,
            "skipped": self.skipped,
            "database_skipped": self.database_skipped,
            "filesystem_skipped": self.filesystem_skipped,
            "filesystem_deleted": self.filesystem_deleted,
        }

    def increment(self, phase: RetentionExecutionPhase, category: RetentionCategory) -> None:
        self.phases()[phase][category] += 1

    def reset(self, phase: RetentionExecutionPhase) -> None:
        self.phases()[phase].update(_zero_counts())


class RetentionCountSnapshot(BaseModel):
    """The `retention_runs.count_snapshot` JSONB blob, parsed once per read.

    The persisted shape is the preview summary per category plus an
    `execution` object; `from_snapshot`/`to_snapshot` are the only places that
    know it.
    """

    model_config = ConfigDict(extra="forbid")

    categories: dict[RetentionCategory, RetentionCategorySummary] = Field(default_factory=dict)
    execution: RetentionExecutionCounts = Field(default_factory=RetentionExecutionCounts)

    @classmethod
    def from_snapshot(cls, value: Mapping[str, object]) -> RetentionCountSnapshot:
        """Parse a persisted snapshot, refusing an unusable one outright.

        This is the bookkeeping of an irreversible deletion: a shape violation
        must stop the run rather than degrade into a silently skipped write.
        """
        payload = dict(value)
        execution = payload.pop("execution", None)
        try:
            return cls.model_validate({"categories": payload, "execution": execution or {}})
        except ValidationError as exc:
            raise RetentionConflict(f"retention count snapshot is invalid: {exc.error_count()} problem(s)") from exc

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            category: summary.model_dump(mode="json") for category, summary in self.categories.items()
        }
        snapshot["execution"] = self.execution.model_dump(mode="json")
        return snapshot


class RetentionExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    cleanup_intents: list[RetentionCleanupIntent]
    count_snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class RetentionEnqueueResult:
    run: RetentionRun
    job: WorkflowJob
    created: bool


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retention timestamps must be timezone-aware")
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"unsupported retention identity value: {type(value).__name__}")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _candidate_sort_key(candidate: RetentionCandidate) -> tuple[str, str, str, str]:
    return (
        candidate.category,
        candidate.record_type,
        str(candidate.record_id),
        candidate.operation,
    )


def build_preview_token(
    policy: RetentionPolicyInput,
    candidates: Iterable[RetentionCandidate],
    *,
    schema_revision: str,
) -> str:
    identities = [
        {
            "category": candidate.category,
            "operation": candidate.operation,
            "record_id": str(candidate.record_id),
            "record_type": candidate.record_type,
            "state_hash": candidate.state_hash,
        }
        for candidate in sorted(candidates, key=_candidate_sort_key)
    ]
    value = {
        "candidates": identities,
        "policy": policy.model_dump(mode="json"),
        "schema_revision": schema_revision,
    }
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def summarize_candidates(
    candidates: Iterable[RetentionCandidate],
) -> dict[RetentionCategory, RetentionCategorySummary]:
    grouped: dict[RetentionCategory, list[RetentionCandidate]] = {category: [] for category in RETENTION_CATEGORIES}
    for candidate in candidates:
        grouped[candidate.category].append(candidate)
    result: dict[RetentionCategory, RetentionCategorySummary] = {}
    for category in RETENTION_CATEGORIES:
        rows = grouped[category]
        observed = [candidate.occurred_at for candidate in rows]
        sizes = [candidate.byte_length for candidate in rows]
        byte_length = (
            None if any(value is None for value in sizes) else sum(value for value in sizes if value is not None)
        )
        result[category] = RetentionCategorySummary(
            count=len(rows),
            byte_length=byte_length,
            oldest_at=min(observed) if observed else None,
            newest_at=max(observed) if observed else None,
        )
    return result


def _state_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _json_byte_length(*values: object) -> int:
    return sum(len(_canonical_json(value)) for value in values)


def _policy_input(policy: RetentionPolicy | RetentionPolicyInput) -> RetentionPolicyInput:
    if isinstance(policy, RetentionPolicyInput):
        return policy
    return RetentionPolicyInput(
        raw_payload_days=policy.raw_payload_days,
        completed_job_days=policy.completed_job_days,
        attempt_metadata_days=policy.attempt_metadata_days,
        export_artifact_days=policy.export_artifact_days,
        unreferenced_media_days=policy.unreferenced_media_days,
    )


def _uuid_values(value: object) -> set[UUID]:
    found: set[UUID] = set()

    def visit(candidate: object) -> None:
        if isinstance(candidate, Mapping):
            for nested in candidate.values():
                visit(nested)
            return
        if isinstance(candidate, list | tuple | set):
            for nested in candidate:
                visit(nested)
            return
        if isinstance(candidate, UUID):
            found.add(candidate)
            return
        if isinstance(candidate, str):
            try:
                found.add(UUID(candidate))
            except ValueError:
                pass

    visit(value)
    return found


def _snapshot_candidates(run: RetentionRun) -> list[RetentionCandidate]:
    try:
        candidates = [RetentionCandidate.model_validate(value) for value in run.candidate_snapshot]
    except ValueError as exc:
        raise RetentionConflict("persisted retention candidate snapshot is invalid") from exc
    return sorted(candidates, key=_candidate_sort_key)


def _snapshot_intents(run: RetentionRun) -> list[RetentionCleanupIntent]:
    try:
        return [RetentionCleanupIntent.model_validate(value) for value in run.cleanup_intent_snapshot]
    except ValueError as exc:
        raise RetentionConflict("persisted retention cleanup snapshot is invalid") from exc


def _preview_from_run(run: RetentionRun) -> RetentionPreview:
    policy = RetentionPolicyInput.model_validate(run.policy_snapshot)
    candidates = _snapshot_candidates(run)
    counts = summarize_candidates(candidates)
    return RetentionPreview(
        run_id=run.id,
        preview_token=run.preview_token,
        schema_revision=run.schema_revision,
        policy=policy,
        candidates=candidates,
        counts=counts,
        previewed_at=run.previewed_at,
        preview_expires_at=run.preview_expires_at,
    )
