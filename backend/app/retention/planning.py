from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
    canonical_json,
    json_byte_length,
    state_hash,
    uuid_values,
)
from app.retention.filesystem import (
    _classified_media_claims,
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

    async def referenced_media_ids(self) -> set[UUID]:
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
            referenced.update(uuid_values(content))
            referenced.update(uuid_values(evidence_map))
        export_results = await self.session.scalars(
            select(WorkflowJob.result).where(
                WorkflowJob.job_type == "build_export",
                WorkflowJob.status == JobStatus.SUCCEEDED,
            )
        )
        for result in export_results:
            if isinstance(result, Mapping) and result.get("state") != "expired":
                referenced.update(uuid_values(result))
        return referenced

    async def _publication_referencing_job_ids(self, candidate_job_ids: Select[tuple[UUID]]) -> set[UUID]:
        """Jobs whose events mention a published revision, scanned in Python.

        The revision reference can sit anywhere inside the event JSON, so the
        disjointness test stays in Python — but the scan is restricted to the
        events of jobs that are already candidates instead of walking the whole
        workflow_events table.
        """
        published_revision_ids = set(await self.session.scalars(select(Publication.platform_variant_revision_id)))
        if not published_revision_ids:
            return set()
        event_rows = await self.session.execute(
            select(WorkflowEvent.workflow_job_id, WorkflowEvent.event_data).where(
                WorkflowEvent.workflow_job_id.in_(candidate_job_ids)
            )
        )
        return {
            workflow_job_id
            for workflow_job_id, event_data in event_rows
            if workflow_job_id is not None and not uuid_values(event_data).isdisjoint(published_revision_ids)
        }

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

    async def collect_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None = None,
        lock: bool = False,
        media_root: Path | None = None,
    ) -> list[RetentionCandidate]:
        """Concatenate the per-category collectors into one sorted plan.

        Each collector owns exactly one (category, record_type) pair and applies
        the same filters in the same order it always did; they run sequentially so
        the statement — and therefore the row-lock — order is unchanged.
        """
        candidates: list[RetentionCandidate] = []
        candidates.extend(await self._raw_payload_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(await self._completed_job_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(await self._research_attempt_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(await self._generation_attempt_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(await self._publish_attempt_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(await self._export_artifact_candidates(policy, now=now, only=only, lock=lock))
        candidates.extend(
            await self._unreferenced_media_candidates(
                policy,
                now=now,
                only=only,
                lock=lock,
                media_root=media_root,
            )
        )
        return sorted(candidates, key=_candidate_sort_key)

    async def _raw_payload_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
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
        for raw_payload in raw_rows:
            state = await self._raw_state(raw_payload)
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
            if raw_payload.id in protected_raw_ids or (
                raw_payload.request_url == RAW_PAYLOAD_SCRUBBED_URL
                and raw_payload.final_url is None
                and raw_payload.headers == {}
                and raw_payload.content_type is None
                and raw_payload.raw_text is None
                and raw_payload.parser_warnings == []
                and source_duplicates_scrubbed
            ):
                continue
            candidates.append(
                RetentionCandidate(
                    category="raw_payload",
                    record_type="raw_payload",
                    record_id=raw_payload.id,
                    operation="scrub",
                    occurred_at=raw_payload.captured_at,
                    byte_length=json_byte_length(state),
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _completed_job_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
        # Jobs owned by a publish or retention record are protected in SQL: the
        # ownership tables are joined by correlated EXISTS instead of being
        # materialised into Python sets that then grow the bind-parameter list.
        completed_conditions = [
            WorkflowJob.finished_at < now - timedelta(days=policy.completed_job_days),
            WorkflowJob.status.in_((JobStatus.SUCCEEDED, JobStatus.CANCELLED)),
            WorkflowJob.job_type.notin_(("build_export", "execute_retention")),
            ~select(1)
            .select_from(PublishJob)
            .where(PublishJob.workflow_job_id == WorkflowJob.id)
            .exists(),
            ~select(1)
            .select_from(RetentionRun)
            .where(RetentionRun.workflow_job_id == WorkflowJob.id)
            .exists(),
        ]
        completed_ids = self._only_ids(only, "completed_job", "workflow_job")
        if completed_ids is not None:
            completed_conditions.append(WorkflowJob.id.in_(completed_ids))
        protected_job_ids = await self._publication_referencing_job_ids(
            select(WorkflowJob.id).where(*completed_conditions)
        )
        completed_statement = select(WorkflowJob).where(*completed_conditions)
        if lock:
            completed_statement = completed_statement.with_for_update()
        for completed_job in await self.session.scalars(completed_statement):
            if completed_job.id in protected_job_ids:
                continue
            state = await self._job_state(completed_job)
            events = state.get("events")
            events_have_data = isinstance(events, list) and any(
                isinstance(event, Mapping) and bool(event.get("event_data")) for event in events
            )
            if not any(
                (
                    completed_job.payload,
                    completed_job.result,
                    completed_job.error_class,
                    completed_job.error_code,
                    completed_job.error_message,
                    completed_job.progress_message,
                    events_have_data,
                )
            ):
                continue
            if completed_job.finished_at is None:  # pragma: no cover - excluded by the query
                continue
            candidates.append(
                RetentionCandidate(
                    category="completed_job",
                    record_type="workflow_job",
                    record_id=completed_job.id,
                    operation="scrub",
                    occurred_at=completed_job.finished_at,
                    byte_length=json_byte_length(state),
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _research_attempt_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
        attempt_cutoff = now - timedelta(days=policy.attempt_metadata_days)
        # A run is protected when ANY of its attempts is unfinished, recent, or
        # unsuccessful. Expressed as a correlated EXISTS over a self-alias so the
        # protection set never becomes a bind-parameter list.
        sibling_research_attempt = aliased(ResearchAttempt)
        research_run_protected = (
            select(1)
            .select_from(sibling_research_attempt)
            .where(
                sibling_research_attempt.research_run_id == ResearchAttempt.research_run_id,
                or_(
                    sibling_research_attempt.finished_at.is_(None),
                    sibling_research_attempt.finished_at >= attempt_cutoff,
                    sibling_research_attempt.status != "succeeded",
                ),
            )
            .exists()
        )
        research_statement = (
            select(ResearchAttempt)
            .join(ResearchRun, ResearchRun.id == ResearchAttempt.research_run_id)
            .where(
                ResearchAttempt.finished_at < attempt_cutoff,
                ResearchAttempt.status == "succeeded",
                ResearchRun.status == "succeeded",
                ResearchRun.result_story_revision_id.is_(None),
                ~research_run_protected,
            )
        )
        research_ids = self._only_ids(only, "attempt_metadata", "research_attempt")
        if research_ids is not None:
            research_statement = research_statement.where(ResearchAttempt.id.in_(research_ids))
        if lock:
            research_statement = research_statement.with_for_update(of=ResearchAttempt)
        for research_attempt in await self.session.scalars(research_statement):
            state = self._research_attempt_state(research_attempt)
            if not any(
                (
                    research_attempt.queries,
                    research_attempt.usage,
                    research_attempt.error_class,
                    research_attempt.error_code,
                    research_attempt.error_message,
                )
            ):
                continue
            if research_attempt.finished_at is None:  # pragma: no cover - excluded by the query
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="research_attempt",
                    record_id=research_attempt.id,
                    operation="scrub",
                    occurred_at=research_attempt.finished_at,
                    byte_length=json_byte_length(state),
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _generation_attempt_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
        attempt_cutoff = now - timedelta(days=policy.attempt_metadata_days)
        sibling_generation_attempt = aliased(GenerationAttempt)
        sibling_attempt_referenced = (
            select(1)
            .select_from(PlatformVariantRevision)
            .where(PlatformVariantRevision.generation_attempt_id == sibling_generation_attempt.id)
            .exists()
        )
        generation_run_protected = or_(
            select(1)
            .select_from(sibling_generation_attempt)
            .where(
                sibling_generation_attempt.generation_run_id == GenerationAttempt.generation_run_id,
                or_(
                    sibling_attempt_referenced,
                    sibling_generation_attempt.finished_at.is_(None),
                    sibling_generation_attempt.finished_at >= attempt_cutoff,
                    sibling_generation_attempt.status.notin_(GENERATION_SUCCESS_STATUSES),
                ),
            )
            .exists(),
            select(1)
            .select_from(GenerationRun)
            .where(
                GenerationRun.id == GenerationAttempt.generation_run_id,
                or_(
                    GenerationRun.status.notin_(GENERATION_SUCCESS_STATUSES),
                    GenerationRun.story_revision_id.is_not(None),
                    GenerationRun.finished_at.is_(None),
                    GenerationRun.finished_at >= attempt_cutoff,
                ),
            )
            .exists(),
        )
        generation_statement = select(GenerationAttempt).where(
            GenerationAttempt.finished_at < attempt_cutoff,
            GenerationAttempt.status.in_(GENERATION_SUCCESS_STATUSES),
            ~generation_run_protected,
        )
        generation_ids = self._only_ids(only, "attempt_metadata", "generation_attempt")
        if generation_ids is not None:
            generation_statement = generation_statement.where(GenerationAttempt.id.in_(generation_ids))
        if lock:
            generation_statement = generation_statement.with_for_update()
        for generation_attempt in await self.session.scalars(generation_statement):
            state = await self._generation_attempt_state(generation_attempt, lock=lock)
            if not any(
                (
                    generation_attempt.prompt_snapshot,
                    generation_attempt.response_payload,
                    generation_attempt.usage,
                    generation_attempt.validation_errors,
                    generation_attempt.error_class,
                    generation_attempt.error_code,
                    generation_attempt.error_message,
                )
            ):
                continue
            if generation_attempt.finished_at is None:  # pragma: no cover - excluded by the query
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="generation_attempt",
                    record_id=generation_attempt.id,
                    operation="scrub",
                    occurred_at=generation_attempt.finished_at,
                    # The parent GenerationRun state is bound into every sibling's
                    # hash but scrubbed once, so a per-attempt byte total is unknown.
                    byte_length=None,
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _publish_attempt_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
        attempt_cutoff = now - timedelta(days=policy.attempt_metadata_days)
        sibling_publish_attempt = aliased(PublishAttempt)
        publish_job_protected = or_(
            select(1)
            .select_from(Publication)
            .where(Publication.publish_job_id == PublishAttempt.publish_job_id)
            .exists(),
            select(1)
            .select_from(PublishOperationReceipt)
            .where(
                PublishOperationReceipt.publish_job_id == PublishAttempt.publish_job_id,
                PublishOperationReceipt.status.in_(("pending", "ambiguous")),
            )
            .exists(),
            select(1)
            .select_from(sibling_publish_attempt)
            .where(
                sibling_publish_attempt.publish_job_id == PublishAttempt.publish_job_id,
                or_(
                    sibling_publish_attempt.finished_at.is_(None),
                    sibling_publish_attempt.finished_at >= attempt_cutoff,
                    sibling_publish_attempt.status != "succeeded",
                ),
            )
            .exists(),
            select(1)
            .select_from(PublishJob)
            .where(PublishJob.id == PublishAttempt.publish_job_id, PublishJob.status != "succeeded")
            .exists(),
        )
        publish_statement = select(PublishAttempt).where(
            PublishAttempt.finished_at < attempt_cutoff,
            PublishAttempt.status == "succeeded",
            ~publish_job_protected,
        )
        publish_ids = self._only_ids(only, "attempt_metadata", "publish_attempt")
        if publish_ids is not None:
            publish_statement = publish_statement.where(PublishAttempt.id.in_(publish_ids))
        if lock:
            publish_statement = publish_statement.with_for_update()
        for publish_attempt in await self.session.scalars(publish_statement):
            state = self._publish_attempt_state(publish_attempt)
            if not any(
                (
                    publish_attempt.sanitized_payload,
                    publish_attempt.remote_response,
                    publish_attempt.error_class,
                    publish_attempt.error_code,
                    publish_attempt.error_message,
                )
            ):
                continue
            if publish_attempt.finished_at is None:  # pragma: no cover - excluded by the query
                continue
            candidates.append(
                RetentionCandidate(
                    category="attempt_metadata",
                    record_type="publish_attempt",
                    record_id=publish_attempt.id,
                    operation="scrub",
                    occurred_at=publish_attempt.finished_at,
                    byte_length=json_byte_length(state),
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _export_artifact_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
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
        for export_job in await self.session.scalars(export_statement):
            try:
                artifact = ExportArtifact.model_validate(export_job.result)
                payload = BuildExportPayload.model_validate(export_job.payload)
            except ValueError:
                continue
            if artifact.export_id != export_job.id or artifact.content_pack_id != payload.content_pack_id:
                continue
            if (
                artifact.manifest.created_at != export_job.created_at
                or artifact.manifest_sha256
                != hashlib.sha256(canonical_json(artifact.manifest.model_dump(mode="json"))).hexdigest()
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
            if export_job.finished_at is None:  # pragma: no cover - excluded by the query
                continue
            state = {
                "status": str(export_job.status),
                "created_at": export_job.created_at,
                "finished_at": export_job.finished_at,
                "payload": export_job.payload,
                "result": export_job.result,
            }
            known_sizes = [item.byte_length for item in artifact.manifest.files]
            candidates.append(
                RetentionCandidate(
                    category="export_artifact",
                    record_type="workflow_job",
                    record_id=export_job.id,
                    operation="expire",
                    occurred_at=export_job.finished_at,
                    byte_length=sum(known_sizes),
                    state_hash=state_hash(state),
                )
            )
        return candidates

    async def _unreferenced_media_candidates(
        self,
        policy: RetentionPolicyInput,
        *,
        now: datetime,
        only: set[tuple[RetentionCategory, RetentionRecordType, UUID]] | None,
        lock: bool,
        media_root: Path | None,
    ) -> list[RetentionCandidate]:
        candidates: list[RetentionCandidate] = []
        # Only the four columns the path classification needs; loading whole
        # entities here also parked stale MediaAsset rows in the identity map
        # that the locked re-read below would then return unrefreshed.
        all_stored_media = list(
            await self.session.execute(
                select(
                    MediaAsset.id,
                    MediaAsset.storage_path,
                    MediaAsset.created_at,
                    MediaAsset.fetch_status,
                ).where(MediaAsset.storage_path.is_not(None))
            )
        )
        referenced_media_ids = await self.referenced_media_ids()
        eligible_media_ids = {
            row.id
            for row in all_stored_media
            if row.created_at < now - timedelta(days=policy.unreferenced_media_days)
            and row.fetch_status != "expired"
            and row.id not in referenced_media_ids
        }
        owned_media_root = media_root or self.media_root
        # Classifying one media row costs O(path depth) blocking syscalls; the
        # whole batch goes to a worker thread so an interactive preview request
        # never stalls the event loop for the API process.
        classification = await asyncio.to_thread(
            _classified_media_claims,
            owned_media_root,
            [(row.id, str(row.storage_path)) for row in all_stored_media],
        )
        canonical_media_paths = classification.canonical_paths
        deletion_authorized_ids = set(classification.deletion_authorized)
        if classification.unclassifiable:
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
        for media_asset in media_rows:
            canonical_path = canonical_media_paths.get(media_asset.id)
            if (
                media_asset.id in referenced_media_ids
                or media_asset.id not in deletion_authorized_ids
                or canonical_path is None
                or canonical_path in blocked_shared_paths
            ):
                continue
            state = self._media_state(media_asset)
            candidates.append(
                RetentionCandidate(
                    category="unreferenced_media",
                    record_type="media_asset",
                    record_id=media_asset.id,
                    operation="expire",
                    occurred_at=media_asset.created_at,
                    byte_length=int(media_asset.byte_length) if media_asset.byte_length is not None else None,
                    state_hash=state_hash(state),
                )
            )
        return candidates
