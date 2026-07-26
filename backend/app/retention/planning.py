from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ContentItem, ItemMedia, MediaAsset, RawPayload, SourceItem
from app.exports.models import BuildExportPayload, ExportArtifact
from app.generation.models import GenerationAttempt, GenerationRun, PlatformVariantRevision
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.types import JobStatus
from app.publishing.models import (
    Publication,
    PublishAttempt,
    PublishJob,
    PublishOperationReceipt,
)
from app.research.models import ResearchAttempt, ResearchRun
from app.retention.contracts import (
    GENERATION_SUCCESS_STATUSES,
    RAW_PAYLOAD_SCRUBBED_URL,
    RetentionCandidate,
    RetentionCategory,
    RetentionPolicyInput,
    RetentionRecordType,
    _candidate_sort_key,
    _canonical_json,
    _json_byte_length,
    _state_hash,
    _uuid_values,
)
from app.retention.filesystem import (
    _media_claim_identity,
    _media_relative_path,
    _UnsafeStoragePath,
)
from app.retention.models import RetentionRun
from app.stories.models import StoryEvidenceSnapshot


class RetentionPlanner:
    def __init__(self, session: AsyncSession, media_root: Path) -> None:
        self.session = session
        self.media_root = media_root

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
        # Existing broad protection covers every primary image, including those
        # referenced by ContentItems saved in one or more collections.
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
