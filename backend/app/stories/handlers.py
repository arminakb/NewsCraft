from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select

from app.jobs.errors import NeedsReviewJobError, RetryableJobError
from app.jobs.models import WorkflowEvent
from app.jobs.registry import JobContext
from app.jobs.repository import JobRepository
from app.jobs.types import JobExecution, JobOrigin, job_payload_copy
from app.stories import manual_intake
from app.stories.evidence import EvidenceInput
from app.stories.grouping import GroupingInput, group_components
from app.stories.repository import StoryRepository
from app.stories.schemas import GroupPendingPayload, GroupPendingResult, ManualIntakeRequest


def _build_job_repository(session):
    return JobRepository(session)


async def handle_manual_intake(job: JobExecution, context: JobContext) -> dict[str, object]:
    request: ManualIntakeRequest = TypeAdapter(ManualIntakeRequest).validate_python(job_payload_copy(job))
    if request.kind == "url":
        await context.session.commit()
        try:
            async with manual_intake.ManualIntakeHttpClient(timeout=30) as client:
                extracted = await manual_intake.extract_article(
                    client,
                    manual_intake.manual_discovery_item(request),
                )
        except Exception as exc:
            raise NeedsReviewJobError(
                code="manual_extraction_failed",
                message="Manual URL extraction failed",
            ) from exc
        if extracted.extraction_status == "failed" or not extracted.content_text.strip():
            raise NeedsReviewJobError(
                code="manual_extraction_failed",
                message="Manual URL extraction failed",
            )
        evidence = EvidenceInput.from_extracted_article(
            extracted,
            title_override=request.title,
        )
    else:
        evidence = EvidenceInput.from_operator_text(request)

    try:
        async with context.session.begin_nested():
            story = await StoryRepository(context.session).create_from_manual_evidence(
                evidence,
                job.id,
            )
            completed_event_id = await context.session.scalar(
                select(WorkflowEvent.id)
                .where(
                    WorkflowEvent.workflow_job_id == job.id,
                    WorkflowEvent.event_type == "manual_intake.completed",
                )
                .limit(1)
            )
            if completed_event_id is None:
                context.session.add(
                    WorkflowEvent(
                        workflow_job_id=job.id,
                        event_type="manual_intake.completed",
                        actor="worker",
                        event_data={"story_id": str(story.id)},
                    )
                )
            await context.session.flush()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise RetryableJobError(
            code="manual_intake_persistence_failed",
            message="Manual intake persistence failed",
        ) from exc
    return {"story_id": str(story.id)}


def _group_components(items: list[Any]) -> list[list[Any]]:
    inputs = [
        GroupingInput(
            content_item_id=str(row.id),
            title=row.title or "",
            canonical_url=row.canonical_url,
            published_at=row.published_at or row.sort_at or datetime.min.replace(tzinfo=UTC),
        )
        for row in items
    ]
    return [[items[index] for index in component] for component in group_components(inputs)]


async def group_pending_content(job: JobExecution, context: JobContext) -> dict[str, Any]:
    payload = GroupPendingPayload.model_validate(job_payload_copy(job))
    repository = StoryRepository(context.session)
    items = await repository.list_pending_content_items(limit=payload.limit, cursor=payload.cursor)
    evidence_snapshot_count = 0
    story_count = 0
    disposition_counts = {
        "grouped": 0,
        "skipped": 0,
        "duplicate": 0,
        "conflicted": 0,
    }
    for component in _group_components(items):
        grouping = await repository.group_content_items([row.id for row in component])
        evidence_snapshot_count += grouping.created_evidence_snapshot_count
        for item_result in grouping.items:
            disposition_counts[item_result.disposition] += 1
        if grouping.story is None:
            continue
        story_count += 1

    result = GroupPendingResult(
        selected_count=len(items),
        grouped_story_count=story_count,
        evidence_snapshot_count=evidence_snapshot_count,
        grouped_item_count=disposition_counts["grouped"],
        skipped_item_count=disposition_counts["skipped"],
        duplicate_item_count=disposition_counts["duplicate"],
        conflicted_item_count=disposition_counts["conflicted"],
        next_cursor=items[-1].id if len(items) == payload.limit else None,
    )
    if result.next_cursor is not None:
        root_id = payload.root_ingest_job_id or job.id
        next_cursor = str(result.next_cursor)
        await _build_job_repository(context.session).enqueue_job(
            job_type="story.group_pending",
            payload={
                "limit": payload.limit,
                "cursor": next_cursor,
                "root_ingest_job_id": str(root_id),
            },
            idempotency_key=f"story-group-page:{root_id}:{next_cursor}",
            origin=JobOrigin.AUTOMATION,
        )
    return result.model_dump(mode="json")
