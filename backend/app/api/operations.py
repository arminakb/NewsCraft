from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbound_proxy import ProxyDiagnostics
from app.core.redaction import redact_secrets
from app.db.session import get_session
from app.jobs.schemas import JobAcceptedOut
from app.operations.diagnostics import OperationsDiagnostics
from app.operations.health import (
    OperationalHealthService,
    OperationalHealthSnapshot,
    render_prometheus_metrics,
)
from app.operations.history import (
    HistoryCategory,
    HistoryService,
    HistorySubjectType,
    decode_history_cursor,
)
from app.retention.contracts import RetentionPreview
from app.retention.models import RetentionRun
from app.retention.service import (
    RetentionCategory,
    RetentionConfirmationError,
    RetentionConflict,
    RetentionNotFound,
    RetentionOperation,
    RetentionPolicyInput,
    RetentionRecordType,
    RetentionService,
)


class ComponentHealthOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["healthy", "degraded", "down", "unknown"]
    observed_at: datetime | None
    last_success_at: datetime | None
    message: str
    action_url: str | None


class AttentionItemOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Literal["warning", "error"]
    kind: Literal[
        "job",
        "route",
        "research",
        "generation",
        "publication",
        "destination",
        "source",
    ]
    title: str
    occurred_at: datetime
    action_url: str


class OperationsSnapshotOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    global_paused: bool
    dry_run: bool
    components: dict[str, ComponentHealthOut]
    queue_counts: dict[str, int]
    attention: list[AttentionItemOut]
    outbound_proxy: ProxyDiagnostics


class HistoryEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    occurred_at: datetime
    category: HistoryCategory
    status: str
    title: str
    summary: str
    job_id: UUID | None
    subject_url: str
    sanitized_metadata: dict[str, object]


class HistoryPageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[HistoryEntryOut]
    next_cursor: str | None


class RetentionPolicyOut(RetentionPolicyInput):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: Literal["global"]
    created_at: datetime
    updated_at: datetime


class RetentionPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetentionCandidateOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    category: RetentionCategory
    record_type: RetentionRecordType
    record_id: UUID
    operation: RetentionOperation
    occurred_at: datetime
    byte_length: int | None = Field(default=None, ge=0)


class RetentionCategorySummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    count: int = Field(ge=0)
    byte_length: int | None = Field(default=None, ge=0)
    oldest_at: datetime | None
    newest_at: datetime | None


class RetentionPreviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_revision: str
    policy: RetentionPolicyInput
    candidates: list[RetentionCandidateOut]
    counts: dict[RetentionCategory, RetentionCategorySummaryOut]
    previewed_at: datetime
    preview_expires_at: datetime


class RetentionRunCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmation: Literal["DELETE PREVIEWED DATA"]


class RetentionRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workflow_job_id: UUID | None
    status: Literal[
        "previewed",
        "queued",
        "running",
        "succeeded",
        "partial",
        "failed",
        "expired",
    ]
    schema_revision: str
    policy: RetentionPolicyInput
    counts: dict[str, object]
    errors: list[dict[str, object]]
    previewed_at: datetime
    preview_expires_at: datetime
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RetentionRunListOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RetentionRunOut]


router = APIRouter(prefix="/operations", tags=["operations"])
SessionDependency = Depends(get_session)
RetentionPreviewBody = Body(default_factory=RetentionPreviewRequest)


@router.get("/diagnostics", response_model=OperationsSnapshotOut)
async def operations_diagnostics(
    session: AsyncSession = SessionDependency,
) -> OperationsSnapshotOut:
    snapshot = await OperationsDiagnostics(session).snapshot()
    return OperationsSnapshotOut.model_validate(snapshot.model_dump())


@router.get("/health", response_model=OperationalHealthSnapshot)
async def operations_health(
    session: AsyncSession = SessionDependency,
) -> OperationalHealthSnapshot:
    return await OperationalHealthService(session).snapshot()


@router.get("/metrics", response_class=PlainTextResponse)
async def operations_metrics(
    session: AsyncSession = SessionDependency,
) -> str:
    snapshot = await OperationalHealthService(session).snapshot()
    return render_prometheus_metrics(snapshot)


@router.get("/history", response_model=HistoryPageOut)
async def operations_history(
    subject_type: HistorySubjectType | None = None,
    subject_id: UUID | None = None,
    category: HistoryCategory | None = None,
    status: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
    cursor: str | None = Query(default=None, min_length=1, max_length=1000),
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = SessionDependency,
) -> HistoryPageOut:
    if (subject_type is None) != (subject_id is None):
        raise HTTPException(
            status_code=422,
            detail="subject_type and subject_id must be supplied together",
        )
    _validate_history_cursor(cursor)
    page = await HistoryService(session).list(
        subject_type=subject_type,
        subject_id=subject_id,
        category=category,
        status=status,
        cursor=cursor,
        limit=limit,
    )
    return HistoryPageOut.model_validate(page.model_dump())


@router.get("/retention-policy", response_model=RetentionPolicyOut)
async def get_retention_policy(
    session: AsyncSession = SessionDependency,
) -> RetentionPolicyOut:
    policy = await RetentionService(session).get_policy()
    return RetentionPolicyOut.model_validate(policy)


@router.put("/retention-policy", response_model=RetentionPolicyOut)
async def update_retention_policy(
    body: RetentionPolicyInput,
    session: AsyncSession = SessionDependency,
) -> RetentionPolicyOut:
    policy = await RetentionService(session).update_policy(body)
    result = RetentionPolicyOut.model_validate(policy)
    await session.commit()
    return result


@router.post("/retention-preview", response_model=RetentionPreviewOut)
async def preview_retention(
    _body: RetentionPreviewRequest = RetentionPreviewBody,
    session: AsyncSession = SessionDependency,
) -> RetentionPreviewOut:
    preview = await RetentionService(session).preview()
    result = _retention_preview_out(preview)
    await session.commit()
    return result


@router.post(
    "/retention-runs",
    response_model=JobAcceptedOut,
    status_code=202,
)
async def enqueue_retention_run(
    body: RetentionRunCreateIn,
    session: AsyncSession = SessionDependency,
) -> JobAcceptedOut:
    try:
        result = await RetentionService(session).enqueue(
            preview_token=body.preview_token,
            confirmation=body.confirmation,
        )
    except RetentionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RetentionConfirmationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    response = JobAcceptedOut.model_validate(
        {
            "job_id": result.job.id,
            "status": result.job.status,
            "deduplicated": not result.created,
        }
    )
    await session.commit()
    return response


@router.get("/retention-runs", response_model=RetentionRunListOut)
async def list_retention_runs(
    limit: int = Query(default=50, ge=1, le=100),
    session: AsyncSession = SessionDependency,
) -> RetentionRunListOut:
    runs = await RetentionService(session).list_runs(limit=limit)
    return RetentionRunListOut(items=[_retention_run_out(run) for run in runs])


@router.get("/retention-runs/{run_id}", response_model=RetentionRunOut)
async def get_retention_run(
    run_id: UUID,
    session: AsyncSession = SessionDependency,
) -> RetentionRunOut:
    try:
        run = await RetentionService(session).get_run(run_id)
    except RetentionNotFound:
        raise HTTPException(status_code=404, detail="Retention run not found") from None
    if run is None:
        raise HTTPException(status_code=404, detail="Retention run not found")
    return _retention_run_out(run)


def _validate_history_cursor(cursor: str | None) -> None:
    if cursor is None:
        return
    try:
        decode_history_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


def _retention_policy_input(value: RetentionPolicyInput) -> RetentionPolicyInput:
    return RetentionPolicyInput(
        raw_payload_days=value.raw_payload_days,
        completed_job_days=value.completed_job_days,
        attempt_metadata_days=value.attempt_metadata_days,
        export_artifact_days=value.export_artifact_days,
        unreferenced_media_days=value.unreferenced_media_days,
    )


def _retention_preview_out(preview: RetentionPreview) -> RetentionPreviewOut:
    return RetentionPreviewOut(
        run_id=preview.run_id,
        preview_token=preview.preview_token,
        schema_revision=preview.schema_revision,
        policy=_retention_policy_input(preview.policy),
        candidates=[RetentionCandidateOut.model_validate(candidate) for candidate in preview.candidates],
        counts={
            category: RetentionCategorySummaryOut.model_validate(summary)
            for category, summary in preview.counts.items()
        },
        previewed_at=preview.previewed_at,
        preview_expires_at=preview.preview_expires_at,
    )


def _retention_run_out(run: RetentionRun) -> RetentionRunOut:
    counts = redact_secrets(run.count_snapshot)
    errors = redact_secrets(run.error_snapshot)
    if not isinstance(counts, dict):  # pragma: no cover - persisted mapping contract
        counts = {}
    if not isinstance(errors, list):  # pragma: no cover - persisted list contract
        errors = []
    return RetentionRunOut.model_validate(
        {
            "id": run.id,
            "workflow_job_id": run.workflow_job_id,
            "status": run.status,
            "schema_revision": run.schema_revision,
            "policy": RetentionPolicyInput.model_validate(run.policy_snapshot),
            "counts": counts,
            "errors": errors,
            "previewed_at": run.previewed_at,
            "preview_expires_at": run.preview_expires_at,
            "queued_at": run.queued_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }
    )
