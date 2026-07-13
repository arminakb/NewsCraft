from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem, ItemMedia, MediaAsset, RawPayload, SourceItem
from app.exports.models import BuildExportPayload, ExportArtifact
from app.generation.models import GenerationAttempt, GenerationRun, PlatformVariantRevision
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.publishing.models import (
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.research.models import ResearchAttempt, ResearchRun
from app.retention.models import (
    RETENTION_POLICY_ID,
    RETENTION_SCHEMA_REVISION,
    RetentionPolicy,
    RetentionRun,
)
from app.stories.models import StoryEvidenceSnapshot

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
RETENTION_CONFIRMATION = "DELETE PREVIEWED DATA"
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


class _UnsafeStoragePath(ValueError):
    pass


def _owned_root(value: Path) -> tuple[Path, Path]:
    root = Path(value).absolute()
    current = Path(root.anchor)
    for part in root.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise _UnsafeStoragePath("storage root contains a symlink")
        if current.exists() and not current.is_dir():
            raise _UnsafeStoragePath("storage root contains a non-directory component")
    try:
        resolved = root.resolve(strict=False)
    except OSError as exc:
        raise _UnsafeStoragePath("storage root cannot be resolved safely") from exc
    return root, resolved


def _export_relative_path(export_root: Path, export_id: UUID) -> str:
    root, resolved_root = _owned_root(export_root)
    target = root / str(export_id)
    if target.is_symlink():
        raise _UnsafeStoragePath("export directory is a symlink")
    if target.exists():
        if not target.is_dir():
            raise _UnsafeStoragePath("export path is not a directory")
        try:
            resolved = target.resolve(strict=True)
        except OSError as exc:
            raise _UnsafeStoragePath("export directory cannot be resolved safely") from exc
        if not resolved.is_relative_to(resolved_root):
            raise _UnsafeStoragePath("export directory escapes the owned root")
    return str(export_id)


def _media_relative_path(media_root: Path, stored_path: str) -> str:
    root, resolved_root = _owned_root(media_root)
    stored = Path(stored_path)
    candidate = stored if stored.is_absolute() else root / stored
    candidate = candidate.absolute()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        raise _UnsafeStoragePath("media path escapes the owned root") from None
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise _UnsafeStoragePath("media path contains a symlink")
        if current.exists() and index < len(relative.parts) - 1 and not current.is_dir():
            raise _UnsafeStoragePath("media path contains a non-directory component")
    if candidate.exists():
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise _UnsafeStoragePath("media file cannot be resolved safely") from exc
        if not resolved.is_relative_to(resolved_root) or not stat.S_ISREG(resolved.stat().st_mode):
            raise _UnsafeStoragePath("media path is not a regular file under the owned root")
        return resolved.relative_to(resolved_root).as_posix()
    normalized = Path(os.path.normpath(str(candidate)))
    try:
        normalized_relative = normalized.relative_to(root)
    except ValueError:
        raise _UnsafeStoragePath("missing media path escapes the owned root") from None
    return normalized_relative.as_posix()


def _media_claim_identity(media_root: Path, stored_path: str) -> str:
    """Resolve a retained path for protection only; deletion uses stricter no-follow rules."""
    root, resolved_root = _owned_root(media_root)
    stored = Path(stored_path)
    candidate = stored if stored.is_absolute() else root / stored
    candidate = candidate.absolute()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise _UnsafeStoragePath("media claim cannot be resolved safely") from exc
    if not resolved.is_relative_to(resolved_root):
        raise _UnsafeStoragePath("media claim escapes the owned root")
    if resolved.exists() and not stat.S_ISREG(resolved.stat().st_mode):
        raise _UnsafeStoragePath("media claim does not resolve to a regular file")
    return resolved.relative_to(resolved_root).as_posix()


def _delete_relative_owned(root_value: Path, relative_path: str, *, directory: bool) -> None:
    relative = PurePosixPath(relative_path)
    if (
        not relative_path
        or relative.is_absolute()
        or ".." in relative.parts
        or "." in relative.parts
        or "\\" in relative_path
    ):
        raise _UnsafeStoragePath("cleanup path is not a safe relative identity")
    root = Path(root_value).absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptors: list[int] = []
    try:
        current_fd = os.open(root.anchor, flags)
        descriptors.append(current_fd)
        for part in root.parts[1:]:
            try:
                current_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                return
            descriptors.append(current_fd)
        for part in relative.parts[:-1]:
            try:
                current_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                return
            descriptors.append(current_fd)
        name = relative.parts[-1]
        try:
            metadata = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        if directory:
            if not stat.S_ISDIR(metadata.st_mode):
                raise _UnsafeStoragePath("cleanup target is not a directory")
            shutil.rmtree(name, dir_fd=current_fd)
        else:
            if not stat.S_ISREG(metadata.st_mode):
                raise _UnsafeStoragePath("cleanup target is not a regular file")
            os.unlink(name, dir_fd=current_fd)
    except OSError as exc:
        raise _UnsafeStoragePath("cleanup target could not be traversed without symlinks") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


class RetentionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
        media_root: Path | None = None,
    ) -> None:
        self.session = session
        self.clock = clock or (lambda: datetime.now(UTC))
        if media_root is None:
            from app.core.config import settings

            media_root = Path(settings.media_root)
        self.media_root = Path(media_root)

    def _now(self) -> datetime:
        observed_at = self.clock()
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("retention clock must return a timezone-aware timestamp")
        return observed_at

    async def get_policy(self) -> RetentionPolicy:
        policy = await self.session.get(RetentionPolicy, RETENTION_POLICY_ID)
        if policy is not None:
            return policy
        defaults = RetentionPolicyInput()
        await self.session.execute(
            insert(RetentionPolicy)
            .values(id=RETENTION_POLICY_ID, **defaults.model_dump())
            .on_conflict_do_nothing(index_elements=["id"])
        )
        policy = await self.session.get(RetentionPolicy, RETENTION_POLICY_ID)
        if policy is None:  # pragma: no cover - the singleton insert is authoritative
            raise RuntimeError("retention policy could not be initialized")
        return policy

    async def update_policy(self, value: RetentionPolicyInput) -> RetentionPolicy:
        policy = await self.session.scalar(
            select(RetentionPolicy).where(RetentionPolicy.id == RETENTION_POLICY_ID).with_for_update()
        )
        if policy is None:
            policy = RetentionPolicy(id=RETENTION_POLICY_ID)
            self.session.add(policy)
        for field, field_value in value.model_dump().items():
            setattr(policy, field, field_value)
        await self.session.flush()
        return policy

    save_policy = update_policy

    async def list_runs(self, limit: int = 50) -> list[RetentionRun]:
        if not 1 <= limit <= 250:
            raise ValueError("retention run limit must be between 1 and 250")
        return list(
            await self.session.scalars(
                select(RetentionRun).order_by(RetentionRun.created_at.desc(), RetentionRun.id.desc()).limit(limit)
            )
        )

    async def get_run(self, run_id: UUID) -> RetentionRun:
        run = await self.session.get(RetentionRun, run_id)
        if run is None:
            raise RetentionNotFound(f"retention run {run_id} was not found")
        return run

    @staticmethod
    def _only_ids(
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        category: RetentionCategory,
        record_type: RetentionRecordType,
    ) -> set[UUID] | None:
        if only is None:
            return None
        return {
            record_id
            for candidate_category, candidate_type, record_id in only
            if candidate_category == category and candidate_type == record_type
        }

    async def _protected_raw_payload_ids(self) -> set[UUID]:
        return set(
            await self.session.scalars(
                select(SourceItem.raw_payload_id)
                .join(
                    StoryEvidenceSnapshot,
                    StoryEvidenceSnapshot.content_item_id == SourceItem.content_item_id,
                )
                .where(SourceItem.raw_payload_id.is_not(None))
            )
        )

    async def _referenced_media_ids(self) -> set[UUID]:
        referenced = set(await self.session.scalars(select(ItemMedia.media_asset_id)))
        referenced.update(
            value
            for value in await self.session.scalars(
                select(ContentItem.primary_image_id).where(ContentItem.primary_image_id.is_not(None))
            )
            if value is not None
        )
        revisions = await self.session.execute(
            select(PlatformVariantRevision.content, PlatformVariantRevision.evidence_map)
        )
        for content, evidence_map in revisions:
            referenced.update(_uuid_values(content))
            referenced.update(_uuid_values(evidence_map))
        export_results = await self.session.scalars(
            select(WorkflowJob.result).where(
                WorkflowJob.job_type == "build_export",
                WorkflowJob.status == JobStatus.SUCCEEDED,
            )
        )
        for result in export_results:
            if isinstance(result, Mapping) and result.get("state") != "expired":
                referenced.update(_uuid_values(result))
        return referenced

    async def _raw_state(self, row: RawPayload) -> dict[str, object]:
        source_items = list(
            await self.session.scalars(
                select(SourceItem).where(SourceItem.raw_payload_id == row.id).order_by(SourceItem.id)
            )
        )
        return {
            "request_url": row.request_url,
            "final_url": row.final_url,
            "http_status": row.http_status,
            "headers": row.headers,
            "content_type": row.content_type,
            "body_sha256": row.body_sha256,
            "raw_text": row.raw_text,
            "parser_warnings": row.parser_warnings,
            "captured_at": row.captured_at,
            "source_items": [
                {
                    "id": item.id,
                    "external_id_raw": item.external_id_raw,
                    "source_url": item.source_url,
                    "canonical_url_candidate": item.canonical_url_candidate,
                    "title_raw": item.title_raw,
                    "summary_raw": item.summary_raw,
                    "content_html_raw": item.content_html_raw,
                    "content_text_raw": item.content_text_raw,
                    "author_raw": item.author_raw,
                    "published_raw": item.published_raw,
                    "parser_meta": item.parser_meta,
                }
                for item in source_items
            ],
        }

    async def _job_state(self, row: WorkflowJob) -> dict[str, object]:
        events = list(
            await self.session.scalars(
                select(WorkflowEvent).where(WorkflowEvent.workflow_job_id == row.id).order_by(WorkflowEvent.id)
            )
        )
        return {
            "status": str(row.status),
            "payload": row.payload,
            "result": row.result,
            "error_class": row.error_class,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "progress_message": row.progress_message,
            "finished_at": row.finished_at,
            "events": [
                {"id": event.id, "event_type": event.event_type, "event_data": event.event_data} for event in events
            ],
        }

    @staticmethod
    def _research_attempt_state(row: ResearchAttempt) -> dict[str, object]:
        return {
            "queries": row.queries,
            "usage": row.usage,
            "status": row.status,
            "error_class": row.error_class,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "finished_at": row.finished_at,
        }

    async def _generation_attempt_state(
        self,
        row: GenerationAttempt,
        *,
        lock: bool,
    ) -> dict[str, object]:
        run_statement = select(GenerationRun).where(GenerationRun.id == row.generation_run_id)
        if lock:
            run_statement = run_statement.with_for_update()
        generation_run = await self.session.scalar(run_statement)
        return {
            "prompt_snapshot": row.prompt_snapshot,
            "response_payload": row.response_payload,
            "usage": row.usage,
            "validation_errors": row.validation_errors,
            "status": row.status,
            "error_class": row.error_class,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "finished_at": row.finished_at,
            "generation_run": (
                None
                if generation_run is None
                else {
                    "status": generation_run.status,
                    "request_payload": generation_run.request_payload,
                    "output_payload": generation_run.output_payload,
                    "error_class": generation_run.error_class,
                    "error_code": generation_run.error_code,
                    "error_message": generation_run.error_message,
                    "finished_at": generation_run.finished_at,
                }
            ),
        }

    @staticmethod
    def _publish_attempt_state(row: PublishAttempt) -> dict[str, object]:
        return {
            "sanitized_payload": row.sanitized_payload,
            "remote_response": row.remote_response,
            "status": row.status,
            "http_status": row.http_status,
            "error_class": row.error_class,
            "error_code": row.error_code,
            "error_message": row.error_message,
            "finished_at": row.finished_at,
        }

    @staticmethod
    def _media_state(row: MediaAsset) -> dict[str, object]:
        return {
            "storage_path": row.storage_path,
            "fetch_status": row.fetch_status,
            "byte_length": row.byte_length,
            "checksum_sha256": row.checksum_sha256,
            "raw_metadata": row.raw_metadata,
            "updated_at": row.updated_at,
        }

    async def _collect_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None = None,
        lock: bool = False,
        media_root: Path | None = None,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []

        raw_statement = select(RawPayload).where(RawPayload.captured_at < now - timedelta(days=policy.raw_payload_days))
        raw_ids = self._only_ids(only, "raw_payload", "raw_payload")
        if raw_ids is not None:
            raw_statement = raw_statement.where(RawPayload.id.in_(raw_ids))
        if lock:
            raw_statement = raw_statement.with_for_update()
        raw_rows = list(await self.session.scalars(raw_statement))
        protected_raw_ids = await self._protected_raw_payload_ids()
        for row in raw_rows:
            state = await self._raw_state(row)
            source_items = state["source_items"]
            source_duplicates_scrubbed = isinstance(source_items, list) and all(
                isinstance(item, Mapping)
                and not any(
                    (
                        item.get("title_raw"),
                        item.get("external_id_raw"),
                        item.get("source_url"),
                        item.get("canonical_url_candidate"),
                        item.get("summary_raw"),
                        item.get("content_html_raw"),
                        item.get("content_text_raw"),
                        item.get("author_raw"),
                        item.get("published_raw"),
                        item.get("parser_meta"),
                    )
                )
                for item in source_items
            )
            if row.id in protected_raw_ids or (
                row.request_url == RAW_PAYLOAD_SCRUBBED_URL
                and row.final_url is None
                and row.headers == {}
                and row.content_type is None
                and row.raw_text is None
                and row.parser_warnings == []
                and source_duplicates_scrubbed
            ):
                continue
            candidates.append(
                RetentionCandidate(
                    category="raw_payload",
                    record_type="raw_payload",
                    record_id=row.id,
                    operation="scrub",
                    occurred_at=row.captured_at,
                    byte_length=_json_byte_length(state),
                    state_hash=_state_hash(state),
                )
            )

        protected_job_ids = set(
            value
            for value in await self.session.scalars(
                select(PublishJob.workflow_job_id).where(PublishJob.workflow_job_id.is_not(None))
            )
            if value is not None
        )
        protected_job_ids.update(
            value
            for value in await self.session.scalars(
                select(RetentionRun.workflow_job_id).where(RetentionRun.workflow_job_id.is_not(None))
            )
            if value is not None
        )
        published_revision_ids = set(await self.session.scalars(select(Publication.platform_variant_revision_id)))
        if published_revision_ids:
            event_rows = await self.session.execute(
                select(WorkflowEvent.workflow_job_id, WorkflowEvent.event_data).where(
                    WorkflowEvent.workflow_job_id.is_not(None)
                )
            )
            protected_job_ids.update(
                workflow_job_id
                for workflow_job_id, event_data in event_rows
                if workflow_job_id is not None and not _uuid_values(event_data).isdisjoint(published_revision_ids)
            )
        completed_statement = select(WorkflowJob).where(
            WorkflowJob.finished_at < now - timedelta(days=policy.completed_job_days),
            WorkflowJob.status.in_((JobStatus.SUCCEEDED, JobStatus.CANCELLED)),
            WorkflowJob.job_type.notin_(("build_export", "execute_retention")),
        )
        completed_ids = self._only_ids(only, "completed_job", "workflow_job")
        if completed_ids is not None:
            completed_statement = completed_statement.where(WorkflowJob.id.in_(completed_ids))
        if lock:
            completed_statement = completed_statement.with_for_update()
        for row in await self.session.scalars(completed_statement):
            if row.id in protected_job_ids:
                continue
            state = await self._job_state(row)
            if not any(
                (
                    row.payload,
                    row.result,
                    row.error_class,
                    row.error_code,
                    row.error_message,
                    row.progress_message,
                    any(event["event_data"] for event in state["events"]),
                )
            ):
                continue
            candidates.append(
                RetentionCandidate(
                    category="completed_job",
                    record_type="workflow_job",
                    record_id=row.id,
                    operation="scrub",
                    occurred_at=row.finished_at,
                    byte_length=_json_byte_length(state),
                    state_hash=_state_hash(state),
                )
            )

        attempt_cutoff = now - timedelta(days=policy.attempt_metadata_days)
        all_research_attempts = list(await self.session.scalars(select(ResearchAttempt)))
        protected_research_run_ids = {
            row.research_run_id
            for row in all_research_attempts
            if row.finished_at is None or row.finished_at >= attempt_cutoff or row.status != "succeeded"
        }
        research_statement = (
            select(ResearchAttempt)
            .join(ResearchRun, ResearchRun.id == ResearchAttempt.research_run_id)
            .where(
                ResearchAttempt.finished_at < attempt_cutoff,
                ResearchAttempt.status == "succeeded",
                ResearchRun.status == "succeeded",
                ResearchRun.result_story_revision_id.is_(None),
                ResearchAttempt.research_run_id.notin_(protected_research_run_ids),
            )
        )
        research_ids = self._only_ids(only, "attempt_metadata", "research_attempt")
        if research_ids is not None:
            research_statement = research_statement.where(ResearchAttempt.id.in_(research_ids))
        if lock:
            research_statement = research_statement.with_for_update(of=ResearchAttempt)
        for row in await self.session.scalars(research_statement):
            state = self._research_attempt_state(row)
            if not any((row.queries, row.usage, row.error_class, row.error_code, row.error_message)):
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="research_attempt",
                    record_id=row.id,
                    operation="scrub",
                    occurred_at=row.finished_at,
                    byte_length=_json_byte_length(state),
                    state_hash=_state_hash(state),
                )
            )

        referenced_generation_attempt_ids = set(
            value
            for value in await self.session.scalars(
                select(PlatformVariantRevision.generation_attempt_id).where(
                    PlatformVariantRevision.generation_attempt_id.is_not(None)
                )
            )
            if value is not None
        )
        all_generation_attempts = list(await self.session.scalars(select(GenerationAttempt)))
        protected_generation_run_ids = {
            row.generation_run_id
            for row in all_generation_attempts
            if row.id in referenced_generation_attempt_ids
            or row.finished_at is None
            or row.finished_at >= attempt_cutoff
            or row.status not in GENERATION_SUCCESS_STATUSES
        }
        protected_generation_run_ids.update(
            await self.session.scalars(
                select(GenerationRun.id).where(
                    (GenerationRun.status.notin_(GENERATION_SUCCESS_STATUSES))
                    | (GenerationRun.story_revision_id.is_not(None))
                    | (GenerationRun.finished_at.is_(None))
                    | (GenerationRun.finished_at >= attempt_cutoff)
                )
            )
        )
        generation_statement = select(GenerationAttempt).where(
            GenerationAttempt.finished_at < attempt_cutoff,
            GenerationAttempt.status.in_(GENERATION_SUCCESS_STATUSES),
            GenerationAttempt.generation_run_id.notin_(protected_generation_run_ids),
        )
        generation_ids = self._only_ids(only, "attempt_metadata", "generation_attempt")
        if generation_ids is not None:
            generation_statement = generation_statement.where(GenerationAttempt.id.in_(generation_ids))
        if lock:
            generation_statement = generation_statement.with_for_update()
        for row in await self.session.scalars(generation_statement):
            state = await self._generation_attempt_state(row, lock=lock)
            if not any(
                (
                    row.prompt_snapshot,
                    row.response_payload,
                    row.usage,
                    row.validation_errors,
                    row.error_class,
                    row.error_code,
                    row.error_message,
                )
            ):
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="generation_attempt",
                    record_id=row.id,
                    operation="scrub",
                    occurred_at=row.finished_at,
                    # The parent GenerationRun state is bound into every sibling's
                    # hash but scrubbed once, so a per-attempt byte total is unknown.
                    byte_length=None,
                    state_hash=_state_hash(state),
                )
            )

        protected_publish_job_ids = set(await self.session.scalars(select(Publication.publish_job_id)))
        protected_publish_job_ids.update(
            await self.session.scalars(
                select(PublishOperationReceipt.publish_job_id).where(
                    PublishOperationReceipt.status.in_(("pending", "ambiguous"))
                )
            )
        )
        all_publish_attempts = list(await self.session.scalars(select(PublishAttempt)))
        protected_publish_job_ids.update(
            row.publish_job_id
            for row in all_publish_attempts
            if row.finished_at is None or row.finished_at >= attempt_cutoff or row.status != "succeeded"
        )
        protected_publish_job_ids.update(
            await self.session.scalars(select(PublishJob.id).where(PublishJob.status != "succeeded"))
        )
        publish_statement = select(PublishAttempt).where(
            PublishAttempt.finished_at < attempt_cutoff,
            PublishAttempt.status == "succeeded",
            PublishAttempt.publish_job_id.notin_(protected_publish_job_ids),
        )
        publish_ids = self._only_ids(only, "attempt_metadata", "publish_attempt")
        if publish_ids is not None:
            publish_statement = publish_statement.where(PublishAttempt.id.in_(publish_ids))
        if lock:
            publish_statement = publish_statement.with_for_update()
        for row in await self.session.scalars(publish_statement):
            state = self._publish_attempt_state(row)
            if not any(
                (
                    row.sanitized_payload,
                    row.remote_response,
                    row.error_class,
                    row.error_code,
                    row.error_message,
                )
            ):
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="publish_attempt",
                    record_id=row.id,
                    operation="scrub",
                    occurred_at=row.finished_at,
                    byte_length=_json_byte_length(state),
                    state_hash=_state_hash(state),
                )
            )

        export_statement = select(WorkflowJob).where(
            WorkflowJob.job_type == "build_export",
            WorkflowJob.status == JobStatus.SUCCEEDED,
            WorkflowJob.finished_at < now - timedelta(days=policy.export_artifact_days),
        )
        export_ids = self._only_ids(only, "export_artifact", "workflow_job")
        if export_ids is not None:
            export_statement = export_statement.where(WorkflowJob.id.in_(export_ids))
        if lock:
            export_statement = export_statement.with_for_update()
        for row in await self.session.scalars(export_statement):
            try:
                artifact = ExportArtifact.model_validate(row.result)
                payload = BuildExportPayload.model_validate(row.payload)
            except ValueError:
                continue
            if artifact.export_id != row.id or artifact.content_pack_id != payload.content_pack_id:
                continue
            if (
                artifact.manifest.created_at != row.created_at
                or artifact.manifest_sha256
                != hashlib.sha256(_canonical_json(artifact.manifest.model_dump(mode="json"))).hexdigest()
            ):
                continue
            variants = artifact.manifest.variants
            if (
                [item.revision_id for item in variants] != payload.revision_ids
                or [item.content_hash for item in variants] != payload.revision_hashes
                or [item.platform for item in variants] != payload.platforms
                or [item.platform_variant_id for item in variants] != payload.platform_variant_ids
            ):
                continue
            state = {
                "status": str(row.status),
                "created_at": row.created_at,
                "finished_at": row.finished_at,
                "payload": row.payload,
                "result": row.result,
            }
            known_sizes = [item.byte_length for item in artifact.manifest.files]
            candidates.append(
                RetentionCandidate(
                    category="export_artifact",
                    record_type="workflow_job",
                    record_id=row.id,
                    operation="expire",
                    occurred_at=row.finished_at,
                    byte_length=sum(known_sizes),
                    state_hash=_state_hash(state),
                )
            )

        all_stored_media = list(
            await self.session.scalars(select(MediaAsset).where(MediaAsset.storage_path.is_not(None)))
        )
        referenced_media_ids = await self._referenced_media_ids()
        eligible_media_ids = {
            row.id
            for row in all_stored_media
            if row.created_at < now - timedelta(days=policy.unreferenced_media_days)
            and row.fetch_status != "expired"
            and row.id not in referenced_media_ids
        }
        owned_media_root = media_root or self.media_root
        canonical_media_paths: dict[UUID, str] = {}
        deletion_authorized_ids: set[UUID] = set()
        unclassifiable_media_claim = False
        for row in all_stored_media:
            try:
                canonical_media_paths[row.id] = _media_claim_identity(
                    owned_media_root,
                    str(row.storage_path),
                )
            except _UnsafeStoragePath:
                unclassifiable_media_claim = True
                continue
            try:
                strict_identity = _media_relative_path(
                    owned_media_root,
                    str(row.storage_path),
                )
            except _UnsafeStoragePath:
                continue
            if strict_identity == canonical_media_paths[row.id]:
                deletion_authorized_ids.add(row.id)
        if unclassifiable_media_claim:
            deletion_authorized_ids.clear()
        blocked_shared_paths = {
            canonical_path
            for row in all_stored_media
            if (row.id not in eligible_media_ids or row.id not in deletion_authorized_ids)
            and (canonical_path := canonical_media_paths.get(row.id)) is not None
        }
        media_statement = select(MediaAsset).where(
            MediaAsset.created_at < now - timedelta(days=policy.unreferenced_media_days),
            MediaAsset.storage_path.is_not(None),
            MediaAsset.fetch_status != "expired",
            MediaAsset.id.in_(eligible_media_ids),
        )
        media_ids = self._only_ids(only, "unreferenced_media", "media_asset")
        if media_ids is not None:
            media_statement = media_statement.where(MediaAsset.id.in_(media_ids))
        if lock:
            media_statement = media_statement.with_for_update()
        media_rows = list(await self.session.scalars(media_statement))
        for row in media_rows:
            canonical_path = canonical_media_paths.get(row.id)
            if (
                row.id in referenced_media_ids
                or row.id not in deletion_authorized_ids
                or canonical_path is None
                or canonical_path in blocked_shared_paths
            ):
                continue
            state = self._media_state(row)
            candidates.append(
                RetentionCandidate(
                    category="unreferenced_media",
                    record_type="media_asset",
                    record_id=row.id,
                    operation="expire",
                    occurred_at=row.created_at,
                    byte_length=int(row.byte_length) if row.byte_length is not None else None,
                    state_hash=_state_hash(state),
                )
            )

        return sorted(candidates, key=_candidate_sort_key)

    async def preview(self, policy: RetentionPolicyInput | None = None) -> RetentionPreview:
        observed_at = self._now()
        effective_policy = policy or _policy_input(await self.get_policy())
        candidates = await self._collect_candidates(effective_policy, now=observed_at)
        token = build_preview_token(
            effective_policy,
            candidates,
            schema_revision=RETENTION_SCHEMA_REVISION,
        )
        snapshot = [candidate.model_dump(mode="json") for candidate in candidates]
        counts = {
            category: summary.model_dump(mode="json") for category, summary in summarize_candidates(candidates).items()
        }
        run_id = uuid4()
        inserted_id = (
            await self.session.execute(
                insert(RetentionRun)
                .values(
                    id=run_id,
                    status="previewed",
                    preview_token=token,
                    schema_revision=RETENTION_SCHEMA_REVISION,
                    policy_snapshot=effective_policy.model_dump(mode="json"),
                    candidate_snapshot=snapshot,
                    cleanup_intent_snapshot=[],
                    count_snapshot=counts,
                    error_snapshot=[],
                    previewed_at=observed_at,
                    preview_expires_at=observed_at + RETENTION_PREVIEW_TTL,
                )
                .on_conflict_do_nothing(index_elements=["preview_token"])
                .returning(RetentionRun.id)
            )
        ).scalar_one_or_none()
        if inserted_id is not None:
            run = await self.session.get(RetentionRun, inserted_id)
            if run is None:  # pragma: no cover - RETURNING guarantees the row
                raise RuntimeError("retention preview could not be loaded")
            return _preview_from_run(run)
        existing = await self.session.scalar(
            select(RetentionRun).where(RetentionRun.preview_token == token).with_for_update()
        )
        if existing is None:  # pragma: no cover - conflict target guarantees a row
            raise RuntimeError("idempotent retention preview could not be loaded")
        if existing.status in {"previewed", "expired"} and existing.workflow_job_id is None:
            existing.status = "previewed"
            existing.policy_snapshot = effective_policy.model_dump(mode="json")
            existing.candidate_snapshot = snapshot
            existing.count_snapshot = counts
            existing.error_snapshot = []
            existing.previewed_at = observed_at
            existing.preview_expires_at = observed_at + RETENTION_PREVIEW_TTL
            await self.session.flush()
        return _preview_from_run(existing)

    async def enqueue(
        self,
        *,
        preview_token: str,
        confirmation: str,
    ) -> RetentionEnqueueResult:
        if confirmation != RETENTION_CONFIRMATION:
            raise RetentionConfirmationError(f"confirmation must exactly match {RETENTION_CONFIRMATION!r}")
        run = await self.session.scalar(
            select(RetentionRun).where(RetentionRun.preview_token == preview_token).with_for_update()
        )
        if run is None:
            raise RetentionConflict("preview token does not match a persisted preview")
        if run.schema_revision != RETENTION_SCHEMA_REVISION:
            raise RetentionConflict("preview schema revision is no longer executable")
        candidates = _snapshot_candidates(run)
        policy = RetentionPolicyInput.model_validate(run.policy_snapshot)
        expected_token = build_preview_token(
            policy,
            candidates,
            schema_revision=run.schema_revision,
        )
        if expected_token != preview_token:
            raise RetentionConflict("preview token does not match its server snapshot")
        if run.workflow_job_id is not None:
            job = await self.session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == run.workflow_job_id).with_for_update()
            )
            if job is None:  # pragma: no cover - protected by the retention FK
                raise RetentionConflict("retention workflow job is unavailable")
            if str(job.status) in {
                JobStatus.QUEUED,
                JobStatus.FAILED,
                JobStatus.NEEDS_REVIEW,
                JobStatus.CANCELLED,
                JobStatus.SUCCEEDED,
            } and await self._reset_all_skipped_database_run(run):
                observed_at = self._now()
                job.status = JobStatus.QUEUED
                job.scheduled_for = observed_at
                job.attempt_count = 0
                job.started_at = None
                job.finished_at = None
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.progress = 0
                job.progress_message = None
                job.error_class = None
                job.error_code = None
                job.error_message = None
                job.result = {}
                self.session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="job.requeued",
                        actor=JobOrigin.MANUAL,
                        event_data={"reason": "retention_all_database_candidates_reconfirmed"},
                    )
                )
                run.status = "queued"
                run.started_at = None
                run.finished_at = None
                run.queued_at = observed_at
                run.cleanup_intent_snapshot = []
                run.count_snapshot = {
                    category: summary.model_dump(mode="json")
                    for category, summary in summarize_candidates(candidates).items()
                }
                run.error_snapshot = []
                await self.session.flush()
                return RetentionEnqueueResult(run=run, job=job, created=False)
            revivable_before_database = run.started_at is None and run.status in {
                "queued",
                "failed",
            }
            revivable_cleanup = run.started_at is not None and run.status in {
                "running",
                "partial",
            }
            if str(job.status) == JobStatus.CANCELLED and (revivable_before_database or revivable_cleanup):
                observed_at = self._now()
                job.status = JobStatus.QUEUED
                job.scheduled_for = observed_at
                job.finished_at = None
                job.lease_owner = None
                job.lease_expires_at = None
                job.heartbeat_at = None
                job.progress = 0
                job.progress_message = None
                job.error_class = None
                job.error_code = None
                job.error_message = None
                self.session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="job.requeued",
                        actor=JobOrigin.MANUAL,
                        event_data={"reason": "retention_reconfirmed"},
                    )
                )
                if revivable_before_database:
                    run.status = "queued"
                    run.finished_at = None
                run.queued_at = observed_at
                run.error_snapshot = [
                    error
                    for error in run.error_snapshot
                    if error.get("phase") != "workflow" and error.get("code") != "retention_job_terminal"
                ]
                await self.session.flush()
                return RetentionEnqueueResult(run=run, job=job, created=False)
            if str(job.status) in {JobStatus.FAILED, JobStatus.CANCELLED} and run.status in {
                "queued",
                "running",
            }:
                observed_at = self._now()
                run.status = "failed"
                run.finished_at = observed_at
                run.error_snapshot = [
                    *run.error_snapshot,
                    {
                        "phase": "queue",
                        "code": "retention_job_terminal",
                        "message": "The linked retention workflow job became terminal before completion",
                    },
                ]
                await self.session.flush()
            return RetentionEnqueueResult(run=run, job=job, created=False)
        observed_at = self._now()
        if run.status != "previewed":
            raise RetentionConflict(f"retention preview cannot be queued from status {run.status!r}")
        if run.preview_expires_at <= observed_at:
            run.status = "expired"
            await self.session.flush()
            raise RetentionConflict("retention preview has expired; create a new preview")
        result = await JobRepository(self.session).enqueue_job(
            job_type="execute_retention",
            payload={"run_id": str(run.id), "preview_token": preview_token},
            idempotency_key=f"retention:{preview_token}",
            origin=JobOrigin.MANUAL,
            pause_sensitive=True,
        )
        run.workflow_job_id = result.job.id
        run.status = "queued"
        run.queued_at = observed_at
        await self.session.flush()
        return RetentionEnqueueResult(run=run, job=result.job, created=result.created)

    async def _reset_all_skipped_database_run(self, run: RetentionRun) -> bool:
        if run.status not in {"partial", "succeeded"} or run.cleanup_intent_snapshot:
            return False
        candidates = _snapshot_candidates(run)
        if not candidates:
            return False
        execution = run.count_snapshot.get("execution")
        if not isinstance(execution, Mapping):
            return False
        scrubbed = execution.get("scrubbed")
        expired = execution.get("expired")
        database_skipped = execution.get("database_skipped")
        filesystem_deleted = execution.get("filesystem_deleted")
        if not all(isinstance(values, Mapping) for values in (scrubbed, expired, database_skipped, filesystem_deleted)):
            return False
        if any(
            int(values.get(category, 0))
            for values in (scrubbed, expired, filesystem_deleted)
            for category in RETENTION_CATEGORIES
        ):
            return False
        if sum(int(database_skipped.get(category, 0)) for category in RETENTION_CATEGORIES) != len(candidates):
            return False
        identities = {(candidate.category, candidate.record_type, candidate.record_id) for candidate in candidates}
        current_candidates = await self._collect_candidates(
            RetentionPolicyInput.model_validate(run.policy_snapshot),
            now=self._now(),
            only=identities,
            media_root=self.media_root,
        )
        current = {
            (candidate.category, candidate.record_type, candidate.record_id): candidate.state_hash
            for candidate in current_candidates
        }
        return len(current) == len(candidates) and all(
            current.get((candidate.category, candidate.record_type, candidate.record_id)) == candidate.state_hash
            for candidate in candidates
        )

    @staticmethod
    def _execution_counts(run: RetentionRun) -> dict[str, object]:
        counts = json.loads(json.dumps(run.count_snapshot))
        counts.setdefault(
            "execution",
            {
                "scrubbed": {category: 0 for category in RETENTION_CATEGORIES},
                "expired": {category: 0 for category in RETENTION_CATEGORIES},
                "skipped": {category: 0 for category in RETENTION_CATEGORIES},
                "database_skipped": {category: 0 for category in RETENTION_CATEGORIES},
                "filesystem_skipped": {category: 0 for category in RETENTION_CATEGORIES},
                "filesystem_deleted": {category: 0 for category in RETENTION_CATEGORIES},
            },
        )
        return counts

    @staticmethod
    def _increment(
        counts: dict[str, object],
        phase: str,
        category: RetentionCategory,
    ) -> None:
        execution = counts["execution"]
        if not isinstance(execution, dict):  # pragma: no cover - persisted by this service
            raise RetentionConflict("retention execution count snapshot is invalid")
        values = execution[phase]
        if not isinstance(values, dict):  # pragma: no cover - persisted by this service
            raise RetentionConflict("retention execution phase count is invalid")
        values[category] = int(values.get(category, 0)) + 1

    @staticmethod
    def _execution_plan(run: RetentionRun) -> RetentionExecutionPlan:
        return RetentionExecutionPlan(
            run_id=run.id,
            preview_token=run.preview_token,
            cleanup_intents=_snapshot_intents(run),
            count_snapshot=run.count_snapshot,
        )

    async def _fail_run(self, run: RetentionRun, *, code: str, message: str) -> None:
        observed_at = self._now()
        run.status = "failed"
        run.finished_at = observed_at
        run.error_snapshot = [
            *run.error_snapshot,
            {"phase": "database", "code": code, "message": message},
        ]
        await self.session.flush()
        await self.session.commit()

    async def _scrub_raw_payload(self, record_id: UUID) -> None:
        row = await self.session.get(RawPayload, record_id)
        if row is None:  # pragma: no cover - revalidation loaded the locked row
            return
        row.request_url = RAW_PAYLOAD_SCRUBBED_URL
        row.final_url = None
        row.headers = {}
        row.content_type = None
        row.raw_text = None
        row.parser_warnings = []
        source_items = await self.session.scalars(select(SourceItem).where(SourceItem.raw_payload_id == record_id))
        for item in source_items:
            item.title_raw = None
            item.external_id_raw = None
            item.source_url = None
            item.canonical_url_candidate = None
            item.summary_raw = None
            item.content_html_raw = None
            item.content_text_raw = None
            item.author_raw = None
            item.published_raw = None
            item.parser_meta = {}

    async def _scrub_workflow_job(self, record_id: UUID) -> None:
        row = await self.session.get(WorkflowJob, record_id)
        if row is None:  # pragma: no cover - revalidation loaded the locked row
            return
        row.payload = {}
        row.result = {}
        row.error_class = None
        row.error_code = None
        row.error_message = None
        row.progress_message = None
        events = await self.session.scalars(select(WorkflowEvent).where(WorkflowEvent.workflow_job_id == record_id))
        for event in events:
            event.event_data = {}

    async def _scrub_attempt(self, candidate: RetentionCandidate) -> None:
        if candidate.record_type == "research_attempt":
            row = await self.session.get(ResearchAttempt, candidate.record_id)
            if row is None:
                return
            row.queries = []
            row.usage = {}
            row.error_class = None
            row.error_code = None
            row.error_message = None
            return
        if candidate.record_type == "generation_attempt":
            row = await self.session.get(GenerationAttempt, candidate.record_id)
            if row is None:
                return
            row.prompt_snapshot = {}
            row.response_payload = {}
            row.usage = {}
            row.validation_errors = []
            row.error_class = None
            row.error_code = None
            row.error_message = None
            generation_run = await self.session.get(GenerationRun, row.generation_run_id)
            if generation_run is not None:
                generation_run.request_payload = {}
                generation_run.output_payload = {}
                generation_run.error_class = None
                generation_run.error_code = None
                generation_run.error_message = None
            return
        if candidate.record_type == "publish_attempt":
            row = await self.session.get(PublishAttempt, candidate.record_id)
            if row is None:
                return
            row.sanitized_payload = {}
            row.remote_response = {}
            row.error_class = None
            row.error_code = None
            row.error_message = None
            return
        raise RetentionConflict(f"unsupported attempt record type {candidate.record_type!r}")

    async def execute_db_phase(
        self,
        run_id: UUID,
        preview_token: str,
        *,
        export_root: Path,
        media_root: Path,
    ) -> RetentionExecutionPlan:
        run = await self.session.scalar(select(RetentionRun).where(RetentionRun.id == run_id).with_for_update())
        if run is None:
            raise RetentionNotFound(f"retention run {run_id} was not found")
        if run.preview_token != preview_token:
            raise RetentionConflict("preview token does not match the retention run")
        if run.schema_revision != RETENTION_SCHEMA_REVISION:
            await self._fail_run(
                run,
                code="retention_schema_changed",
                message="The retention preview schema is no longer executable",
            )
            raise RetentionConflict("preview schema revision is no longer executable")
        if run.status in {"running", "succeeded", "partial"}:
            return self._execution_plan(run)
        if run.status != "queued":
            raise RetentionConflict(f"retention run cannot execute from status {run.status!r}")

        try:
            candidates = _snapshot_candidates(run)
        except RetentionConflict:
            await self._fail_run(
                run,
                code="retention_snapshot_invalid",
                message="The persisted retention candidate snapshot is invalid",
            )
            raise
        expected_token = build_preview_token(
            RetentionPolicyInput.model_validate(run.policy_snapshot),
            candidates,
            schema_revision=run.schema_revision,
        )
        if expected_token != preview_token:
            await self._fail_run(
                run,
                code="retention_snapshot_token_invalid",
                message="The persisted retention preview no longer matches its token",
            )
            raise RetentionConflict("preview token does not match its server snapshot")

        # These tables contain JSON/no-FK protection edges. SHARE prevents a new
        # reference from appearing between the protection query and the DB marker.
        await self.session.execute(
            text(
                "LOCK TABLE content_items, item_media, media_assets, workflow_jobs, "
                "publish_jobs, platform_variant_revisions, "
                "generation_attempts, generation_runs, research_attempts, research_runs, "
                "publish_attempts, publications, publish_operation_receipts, source_items, "
                "story_evidence_snapshots, "
                "workflow_events IN SHARE MODE"
            )
        )
        identities = {(candidate.category, candidate.record_type, candidate.record_id) for candidate in candidates}
        current_candidates = await self._collect_candidates(
            RetentionPolicyInput.model_validate(run.policy_snapshot),
            now=self._now(),
            only=identities,
            lock=True,
            media_root=media_root,
        )
        current = {
            (candidate.category, candidate.record_type, candidate.record_id): candidate
            for candidate in current_candidates
        }
        observed_at = self._now()
        counts = self._execution_counts(run)
        errors = list(run.error_snapshot)
        intents: list[RetentionCleanupIntent] = []

        media_rows = {
            candidate.record_id: await self.session.get(MediaAsset, candidate.record_id)
            for candidate in candidates
            if candidate.record_type == "media_asset"
        }
        canonical_media_paths: dict[UUID, str] = {}
        rows_by_canonical_path: dict[str, set[UUID]] = {}
        all_stored_media = list(
            await self.session.scalars(select(MediaAsset).where(MediaAsset.storage_path.is_not(None)))
        )
        unclassifiable_media_claim = False
        for row in all_stored_media:
            try:
                relative_path = _media_claim_identity(media_root, str(row.storage_path))
            except _UnsafeStoragePath:
                unclassifiable_media_claim = True
                continue
            canonical_media_paths[row.id] = relative_path
            rows_by_canonical_path.setdefault(relative_path, set()).add(row.id)
        unchanged_media_ids = {
            candidate.record_id
            for candidate in candidates
            if candidate.record_type == "media_asset"
            and (current_candidate := current.get((candidate.category, candidate.record_type, candidate.record_id)))
            is not None
            and current_candidate.state_hash == candidate.state_hash
        }
        invalid_canonical_paths = {
            relative_path
            for relative_path, record_ids in rows_by_canonical_path.items()
            if not record_ids.issubset(unchanged_media_ids)
        }
        if unclassifiable_media_claim:
            invalid_canonical_paths.update(rows_by_canonical_path)
        generation_attempt_rows = {
            candidate.record_id: await self.session.get(GenerationAttempt, candidate.record_id)
            for candidate in candidates
            if candidate.record_type == "generation_attempt"
        }
        invalid_generation_run_ids: set[UUID] = set()
        for candidate in candidates:
            if candidate.record_type != "generation_attempt":
                continue
            row = generation_attempt_rows[candidate.record_id]
            current_candidate = current.get((candidate.category, candidate.record_type, candidate.record_id))
            if row is not None and (current_candidate is None or current_candidate.state_hash != candidate.state_hash):
                invalid_generation_run_ids.add(row.generation_run_id)

        for candidate in candidates:
            identity = (candidate.category, candidate.record_type, candidate.record_id)
            current_candidate = current.get(identity)
            if current_candidate is None or current_candidate.state_hash != candidate.state_hash:
                if candidate.record_type == "media_asset" and current_candidate is None:
                    media = media_rows[candidate.record_id]
                    if media is not None and media.storage_path is not None:
                        try:
                            _media_relative_path(media_root, media.storage_path)
                        except _UnsafeStoragePath:
                            errors.append(
                                {
                                    "category": candidate.category,
                                    "record_type": candidate.record_type,
                                    "record_id": str(candidate.record_id),
                                    "code": "unsafe_media_path",
                                    "message": ("Media storage identity is outside the owned root or unsafe"),
                                }
                            )
                self._increment(counts, "skipped", candidate.category)
                continue
            if candidate.record_type == "generation_attempt":
                generation_attempt = generation_attempt_rows[candidate.record_id]
                if generation_attempt is None or generation_attempt.generation_run_id in invalid_generation_run_ids:
                    self._increment(counts, "skipped", candidate.category)
                    continue
            if candidate.record_type == "media_asset":
                media = media_rows[candidate.record_id]
                if media is None or media.storage_path is None:
                    self._increment(counts, "skipped", candidate.category)
                    continue
                relative_path = canonical_media_paths.get(media.id)
                if relative_path is None:
                    errors.append(
                        {
                            "category": candidate.category,
                            "record_type": candidate.record_type,
                            "record_id": str(candidate.record_id),
                            "code": "unsafe_media_path",
                            "message": "Media storage identity is outside the owned root or unsafe",
                        }
                    )
                    self._increment(counts, "skipped", candidate.category)
                    continue
                if relative_path in invalid_canonical_paths:
                    self._increment(counts, "skipped", candidate.category)
                    continue
                media.storage_path = None
                media.fetch_status = "expired"
                media.raw_metadata = {"retention": {"state": "expired", "expired_at": observed_at.isoformat()}}
                intents.append(
                    RetentionCleanupIntent(
                        category="unreferenced_media",
                        record_id=candidate.record_id,
                        operation="delete_file",
                        relative_path=relative_path,
                    )
                )
                self._increment(counts, "expired", candidate.category)
                continue
            if candidate.category == "export_artifact":
                export = await self.session.get(WorkflowJob, candidate.record_id)
                if export is None:
                    self._increment(counts, "skipped", candidate.category)
                    continue
                try:
                    relative_path = _export_relative_path(export_root, export.id)
                except _UnsafeStoragePath:
                    errors.append(
                        {
                            "category": candidate.category,
                            "record_type": candidate.record_type,
                            "record_id": str(candidate.record_id),
                            "code": "unsafe_export_path",
                            "message": "Export storage identity is outside the owned root or unsafe",
                        }
                    )
                    self._increment(counts, "skipped", candidate.category)
                    continue
                artifact = ExportArtifact.model_validate(export.result)
                export.result = {
                    "export_id": str(export.id),
                    "content_pack_id": str(artifact.content_pack_id),
                    "state": "expired",
                    "expired_at": observed_at.isoformat(),
                }
                intents.append(
                    RetentionCleanupIntent(
                        category="export_artifact",
                        record_id=export.id,
                        operation="delete_tree",
                        relative_path=relative_path,
                    )
                )
                self._increment(counts, "expired", candidate.category)
                continue
            if candidate.category == "raw_payload":
                await self._scrub_raw_payload(candidate.record_id)
            elif candidate.category == "completed_job":
                await self._scrub_workflow_job(candidate.record_id)
            elif candidate.category == "attempt_metadata":
                await self._scrub_attempt(candidate)
            else:  # pragma: no cover - strict category/record_type validation above
                raise RetentionConflict(f"unsupported retention category {candidate.category!r}")
            self._increment(counts, "scrubbed", candidate.category)

        run.status = "running"
        run.started_at = run.started_at or observed_at
        run.cleanup_intent_snapshot = [intent.model_dump(mode="json") for intent in intents]
        execution_counts = counts["execution"]
        if isinstance(execution_counts, dict):
            execution_counts["database_skipped"] = dict(execution_counts["skipped"])
        run.count_snapshot = counts
        run.error_snapshot = errors
        await self.session.flush()
        await self.session.commit()
        return self._execution_plan(run)

    async def finish_filesystem_phase(
        self,
        run_id: UUID,
        *,
        export_root: Path,
        media_root: Path,
    ) -> RetentionRun:
        run = await self.session.scalar(select(RetentionRun).where(RetentionRun.id == run_id).with_for_update())
        if run is None:
            raise RetentionNotFound(f"retention run {run_id} was not found")
        if run.status == "succeeded":
            return run
        if run.status not in {"running", "partial"}:
            raise RetentionConflict(f"retention filesystem cleanup cannot run from status {run.status!r}")
        counts = self._execution_counts(run)
        errors = [error for error in run.error_snapshot if error.get("phase") != "filesystem"]
        execution = counts["execution"]
        if not isinstance(execution, dict):
            raise RetentionConflict("retention execution count snapshot is invalid")
        deleted_counts = execution["filesystem_deleted"]
        if not isinstance(deleted_counts, dict):
            raise RetentionConflict("retention filesystem count snapshot is invalid")
        for category in RETENTION_CATEGORIES:
            deleted_counts[category] = 0
        database_skipped = execution.get("database_skipped", execution["skipped"])
        if not isinstance(database_skipped, dict):
            raise RetentionConflict("retention database skip snapshot is invalid")
        filesystem_skipped = execution.get("filesystem_skipped")
        if not isinstance(filesystem_skipped, dict):
            filesystem_skipped = {category: 0 for category in RETENTION_CATEGORIES}
            execution["filesystem_skipped"] = filesystem_skipped
        execution["skipped"] = dict(database_skipped)
        for category in RETENTION_CATEGORIES:
            filesystem_skipped[category] = 0
        intents = _snapshot_intents(run)
        reclaimed_media_paths: set[str] = set()
        reclaimed_media_ids: set[UUID] = set()
        unclassifiable_media_claim = False
        if any(intent.category == "unreferenced_media" for intent in intents):
            await self.session.execute(
                text(
                    "LOCK TABLE content_items, item_media, media_assets, "
                    "platform_variant_revisions, workflow_jobs IN SHARE MODE"
                )
            )
            reclaimed_media_ids = await self._referenced_media_ids()
            claimed_media = await self.session.scalars(select(MediaAsset).where(MediaAsset.storage_path.is_not(None)))
            for media in claimed_media:
                try:
                    reclaimed_media_paths.add(_media_claim_identity(media_root, str(media.storage_path)))
                except _UnsafeStoragePath:
                    unclassifiable_media_claim = True
        media_record_ids_by_path: dict[str, set[UUID]] = {}
        for intent in intents:
            if intent.category == "unreferenced_media":
                media_record_ids_by_path.setdefault(intent.relative_path, set()).add(intent.record_id)
        seen: set[tuple[str, str]] = set()
        for intent in intents:
            identity = (intent.category, intent.relative_path)
            if identity in seen:
                continue
            seen.add(identity)
            root = export_root if intent.category == "export_artifact" else media_root
            if intent.category == "unreferenced_media" and (
                unclassifiable_media_claim
                or not media_record_ids_by_path[intent.relative_path].isdisjoint(reclaimed_media_ids)
                or intent.relative_path in reclaimed_media_paths
            ):
                filesystem_skipped[intent.category] = int(filesystem_skipped.get(intent.category, 0)) + 1
                skipped = execution["skipped"]
                if isinstance(skipped, dict):
                    skipped[intent.category] = int(skipped.get(intent.category, 0)) + 1
                continue
            try:
                _delete_relative_owned(
                    root,
                    intent.relative_path,
                    directory=intent.operation == "delete_tree",
                )
                deleted_counts[intent.category] = int(deleted_counts.get(intent.category, 0)) + 1
            except OSError, _UnsafeStoragePath:
                errors.append(
                    {
                        "phase": "filesystem",
                        "category": intent.category,
                        "record_type": ("workflow_job" if intent.category == "export_artifact" else "media_asset"),
                        "record_id": str(intent.record_id),
                        "code": "unsafe_or_failed_cleanup",
                        "message": "Persisted cleanup identity could not be removed safely",
                    }
                )
        run.count_snapshot = counts
        run.error_snapshot = errors
        run.status = "partial" if errors else "succeeded"
        run.finished_at = self._now()
        await self.session.flush()
        await self.session.commit()
        return run
