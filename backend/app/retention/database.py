from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaAsset, RawPayload, SourceItem
from app.exports.models import ExportArtifact
from app.generation.models import GenerationAttempt, GenerationRun
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.publishing.models import PublishAttempt
from app.research.models import ResearchAttempt
from app.retention.contracts import (
    RAW_PAYLOAD_SCRUBBED_URL,
    RETENTION_CATEGORIES,
    RetentionCandidate,
    RetentionCategory,
    RetentionCleanupIntent,
    RetentionConflict,
    RetentionExecutionPlan,
    RetentionNotFound,
    RetentionPolicyInput,
    _snapshot_candidates,
    _snapshot_intents,
    build_preview_token,
)
from app.retention.filesystem import (
    _export_relative_path,
    _media_claim_identity,
    _media_relative_path,
    _UnsafeStoragePath,
)
from app.retention.models import RETENTION_SCHEMA_REVISION, RetentionRun


class RetentionDatabaseExecutor:
    def __init__(
        self,
        session: AsyncSession,
        *,
        media_root: Path,
        now: Callable[[], datetime],
        collect_candidates: Callable[..., Awaitable[list[RetentionCandidate]]],
    ) -> None:
        self.session = session
        self.media_root = media_root
        self.now = now
        self.collect_candidates = collect_candidates

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
        if (
            not isinstance(scrubbed, Mapping)
            or not isinstance(expired, Mapping)
            or not isinstance(database_skipped, Mapping)
            or not isinstance(filesystem_deleted, Mapping)
        ):
            return False
        if any(
            int(values.get(category, 0)) > 0
            for values in (scrubbed, expired, filesystem_deleted)
            for category in RETENTION_CATEGORIES
        ):
            return False
        if sum(int(database_skipped.get(category, 0)) for category in RETENTION_CATEGORIES) != len(candidates):
            return False
        identities = {(candidate.category, candidate.record_type, candidate.record_id) for candidate in candidates}
        current_candidates = await self.collect_candidates(
            RetentionPolicyInput.model_validate(run.policy_snapshot),
            now=self.now(),
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
        observed_at = self.now()
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
            research_attempt = await self.session.get(ResearchAttempt, candidate.record_id)
            if research_attempt is None:
                return
            research_attempt.queries = []
            research_attempt.usage = {}
            research_attempt.error_class = None
            research_attempt.error_code = None
            research_attempt.error_message = None
            return
        if candidate.record_type == "generation_attempt":
            generation_attempt = await self.session.get(GenerationAttempt, candidate.record_id)
            if generation_attempt is None:
                return
            generation_attempt.prompt_snapshot = {}
            generation_attempt.response_payload = {}
            generation_attempt.usage = {}
            generation_attempt.validation_errors = []
            generation_attempt.error_class = None
            generation_attempt.error_code = None
            generation_attempt.error_message = None
            generation_run = await self.session.get(GenerationRun, generation_attempt.generation_run_id)
            if generation_run is not None:
                generation_run.request_payload = {}
                generation_run.output_payload = {}
                generation_run.error_class = None
                generation_run.error_code = None
                generation_run.error_message = None
            return
        if candidate.record_type == "publish_attempt":
            publish_attempt = await self.session.get(PublishAttempt, candidate.record_id)
            if publish_attempt is None:
                return
            publish_attempt.sanitized_payload = {}
            publish_attempt.remote_response = {}
            publish_attempt.error_class = None
            publish_attempt.error_code = None
            publish_attempt.error_message = None
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
        current_candidates = await self.collect_candidates(
            RetentionPolicyInput.model_validate(run.policy_snapshot),
            now=self.now(),
            only=identities,
            lock=True,
            media_root=media_root,
        )
        current = {
            (candidate.category, candidate.record_type, candidate.record_id): candidate
            for candidate in current_candidates
        }
        observed_at = self.now()
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
            generation_attempt = generation_attempt_rows[candidate.record_id]
            current_candidate = current.get((candidate.category, candidate.record_type, candidate.record_id))
            if generation_attempt is not None and (
                current_candidate is None or current_candidate.state_hash != candidate.state_hash
            ):
                invalid_generation_run_ids.add(generation_attempt.generation_run_id)

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
                canonical_path = canonical_media_paths.get(media.id)
                if canonical_path is None:
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
                if canonical_path in invalid_canonical_paths:
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
