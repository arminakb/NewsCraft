from typing import Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.schemas import (
    ApproveContentItemIn,
    ApproveContentItemOut,
    CandidateShortlistOut,
    ContentItemOut,
    ContentProductionRequestCreateIn,
    ContentProductionRequestDetailOut,
    ContentProductionRequestOut,
    ContentProductionRunOut,
    DashboardSummaryOut,
    DiagnosticsOut,
    DraftQualityReportOut,
    EditorialBriefOut,
    IngestRunOut,
    IngestRunRequest,
    IngestRunSummaryOut,
    MediaAssetListOut,
    ShortlistDecisionIn,
    SourceDetailOut,
    SourceOut,
    TelegramDraftOut,
    TelegramPostPackageOut,
    VisualBriefOut,
    WorkflowEventOut,
)
from app.content_production.candidates import ShortlistApprovalService
from app.content_production.events import WorkflowEventType
from app.content_production.packages import TelegramPackageService
from app.content_production.repository import ContentProductionRepository
from app.content_production.tracing import HumanDecisionTraceService
from app.db.models import (
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    DraftQualityReport,
    EditorialBrief,
    IngestRun,
    MediaAsset,
    Source,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WorkflowEvent,
)
from app.db.session import get_session
from app.diagnostics.service import DiagnosticsService
from app.ingestion.seed_sources import seed_sources
from app.ingestion.service import IngestionService
from app.workflows.approval import ApprovalService

router = APIRouter()
SessionDependency = Depends(get_session)


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(Source).order_by(Source.source_group, Source.name))
    return list(rows)


@router.post("/sources/seed")
async def seed(session: AsyncSession = SessionDependency):
    count = await seed_sources(session)
    await session.commit()
    return {"upserted": count}


@router.get("/sources/{source_id}", response_model=SourceDetailOut)
async def get_source(source_id: UUID, session: AsyncSession = SessionDependency):
    source = await session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    return source


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
async def dashboard_summary(session: AsyncSession = SessionDependency):
    rss_feeds = await _count(session, Source, Source.platform == "rss")
    telegram_channels = await _count(session, Source, Source.platform == "telegram_public")
    content_items = await _count(session, ContentItem)
    media_assets = await _count(session, MediaAsset)
    warnings = await _count(
        session,
        Source,
        or_(Source.health_status != "healthy", Source.failure_count > 0, Source.active.is_(False)),
    )
    return DashboardSummaryOut(
        rss_feeds=rss_feeds,
        telegram_channels=telegram_channels,
        content_items=content_items,
        media_assets=media_assets,
        warnings=warnings,
    )


@router.get("/ingest/runs", response_model=list[IngestRunSummaryOut])
async def list_ingest_runs(limit: int = Query(100, ge=1, le=250), session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(limit))
    return list(rows)


@router.post("/ingest/run", response_model=IngestRunOut)
async def run_ingest(request: IngestRunRequest, session: AsyncSession = SessionDependency):
    service = IngestionService(session)
    stats = await service.run_once(platforms=request.platforms, source_ids=request.source_ids, trigger="api")
    await session.commit()
    if "status" not in stats:
        stats["status"] = "partial" if stats.get("failed") else "succeeded"
    return stats


@router.get("/media-assets", response_model=list[MediaAssetListOut])
async def list_media_assets(limit: int = Query(100, ge=1, le=250), session: AsyncSession = SessionDependency):
    rows = await session.scalars(select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(limit))
    return list(rows)


@router.get("/content-items", response_model=list[ContentItemOut])
async def list_content_items(
    status: str | None = None,
    content_type: str | None = None,
    rewrite_bucket: str | None = None,
    is_rewrite_ready: bool | None = None,
    source_tier: str | None = None,
    quality_status: str | None = None,
    sort: Literal["latest", "score"] = "latest",
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    stmt = select(ContentItem).options(selectinload(ContentItem.primary_media))
    if status:
        stmt = stmt.where(ContentItem.status == status)
    if content_type:
        stmt = stmt.where(ContentItem.content_type == content_type)
    if rewrite_bucket:
        stmt = stmt.where(ContentItem.rewrite_bucket == rewrite_bucket)
    if is_rewrite_ready is not None:
        stmt = stmt.where(ContentItem.is_rewrite_ready.is_(is_rewrite_ready))
    if source_tier:
        stmt = stmt.where(ContentItem.source_tier == source_tier)
    if quality_status:
        stmt = stmt.where(ContentItem.quality_status == quality_status)
    if sort == "score":
        stmt = stmt.order_by(ContentItem.score.desc(), ContentItem.sort_at.desc())
    else:
        stmt = stmt.order_by(ContentItem.sort_at.desc())
    rows = await session.scalars(stmt.limit(limit))
    return list(rows)


@router.get("/content-items/{content_item_id}", response_model=ContentItemOut)
async def get_content_item(content_item_id: UUID, session: AsyncSession = SessionDependency):
    item = await session.scalar(
        select(ContentItem)
        .options(selectinload(ContentItem.primary_media))
        .where(ContentItem.id == content_item_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="content item not found")
    return item


@router.post("/content-items/{content_item_id}/approve", response_model=ApproveContentItemOut)
async def approve_content_item(
    content_item_id: UUID,
    payload: ApproveContentItemIn,
    session: AsyncSession = SessionDependency,
):
    try:
        item = await ApprovalService(session).approve(content_item_id, notes=payload.notes)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return item


@router.post("/content-production/requests", response_model=ContentProductionRequestDetailOut)
async def create_content_production_request(
    payload: ContentProductionRequestCreateIn,
    session: AsyncSession = SessionDependency,
):
    if payload.platform != "telegram":
        raise HTTPException(status_code=422, detail="platform must be telegram")

    repository = ContentProductionRepository(session)
    request = await repository.create_request(
        topic=payload.topic,
        platform=payload.platform,
        language=payload.language,
        tone=payload.tone,
        audience=payload.audience,
        max_candidates=payload.max_candidates,
        require_rewrite_ready=payload.require_rewrite_ready,
        require_media=payload.require_media,
        constraints_json=payload.constraints_json,
        created_by=payload.created_by,
    )
    await _enqueue_content_production_event(
        repository,
        event_type=WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={"request_id": str(request.id), "topic": request.topic, "platform": request.platform},
    )
    await session.commit()
    return ContentProductionRequestDetailOut.model_validate(request, from_attributes=True).model_copy(
        update={"shortlist": []}
    )


@router.get("/content-production/requests", response_model=list[ContentProductionRequestOut])
async def list_content_production_requests(
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    return await ContentProductionRepository(session).list_requests(limit=limit)


@router.get("/content-production/requests/{request_id}", response_model=ContentProductionRequestDetailOut)
async def get_content_production_request(request_id: UUID, session: AsyncSession = SessionDependency):
    request = await session.get(ContentProductionRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="content production request not found")
    shortlist = await ContentProductionRepository(session).list_shortlist(request_id)
    return ContentProductionRequestDetailOut.model_validate(request, from_attributes=True).model_copy(
        update={"shortlist": shortlist}
    )


@router.get("/content-production/requests/{request_id}/shortlist", response_model=list[CandidateShortlistOut])
async def get_content_production_shortlist(request_id: UUID, session: AsyncSession = SessionDependency):
    request = await session.get(ContentProductionRequest, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail="content production request not found")
    return await ContentProductionRepository(session).list_shortlist(request_id)


@router.post("/content-production/requests/{request_id}/shortlist/approve", response_model=list[CandidateShortlistOut])
async def approve_content_production_shortlist(
    request_id: UUID,
    payload: ShortlistDecisionIn,
    session: AsyncSession = SessionDependency,
):
    repository = ContentProductionRepository(session)
    previous: dict[str, str] = {}

    async def approve_and_emit():
        candidates = await ShortlistApprovalService(session).approve(
            request_id,
            payload.selection_execution_id,
            payload.content_item_ids,
            previous_state=previous,
        )
        event = await _enqueue_content_production_event(
            repository,
            event_type=WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
            aggregate_type="content_production_request",
            aggregate_id=request_id,
            correlation_id=request_id,
            payload={
                "request_id": str(request_id),
                "selection_execution_id": str(payload.selection_execution_id),
                "content_item_ids": [str(value) for value in payload.content_item_ids],
            },
            discriminator=(
                f"{payload.selection_execution_id}:"
                + ",".join(sorted(str(value) for value in payload.content_item_ids))
            ),
        )
        return candidates, event

    try:
        candidates, _ = await HumanDecisionTraceService(session).execute(
            approve_and_emit,
            step_name="shortlist_approval_decision",
            service_name="ShortlistApprovalService",
            production_run_id=None,
            request_id=request_id,
            aggregate_type="content_production_request",
            aggregate_id=request_id,
            decision="approve",
            input_snapshot={
                "candidate_ids": [str(value) for value in payload.content_item_ids],
                "selection_execution_id": str(payload.selection_execution_id),
                "previous_state": previous,
            },
            output_snapshot=lambda result: {
                "candidate_ids": [str(candidate.content_item_id) for candidate in result[0]],
                "new_state": "approved",
                "resulting_event_id": str(result[1].event_id),
            },
        )
    except LookupError as exc:
        await session.commit()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return candidates


@router.post("/content-production/requests/{request_id}/shortlist/reject", response_model=list[CandidateShortlistOut])
async def reject_content_production_shortlist(
    request_id: UUID,
    payload: ShortlistDecisionIn,
    session: AsyncSession = SessionDependency,
):
    repository = ContentProductionRepository(session)
    previous: dict[str, str] = {}

    async def reject_and_emit():
        candidates = await ShortlistApprovalService(session).reject(
            request_id,
            payload.selection_execution_id,
            payload.content_item_ids,
            previous_state=previous,
        )
        event = await _enqueue_content_production_event(
            repository,
            event_type=WorkflowEventType.CANDIDATE_SHORTLIST_REJECTED,
            aggregate_type="content_production_request",
            aggregate_id=request_id,
            correlation_id=request_id,
            payload={
                "request_id": str(request_id),
                "selection_execution_id": str(payload.selection_execution_id),
                "content_item_ids": [str(value) for value in payload.content_item_ids],
            },
            discriminator=(
                f"{payload.selection_execution_id}:"
                + ",".join(sorted(str(value) for value in payload.content_item_ids))
            ),
        )
        return candidates, event

    try:
        candidates, _ = await HumanDecisionTraceService(session).execute(
            reject_and_emit,
            step_name="shortlist_rejection_decision",
            service_name="ShortlistApprovalService",
            production_run_id=None,
            request_id=request_id,
            aggregate_type="content_production_request",
            aggregate_id=request_id,
            decision="reject",
            input_snapshot={
                "candidate_ids": [str(value) for value in payload.content_item_ids],
                "selection_execution_id": str(payload.selection_execution_id),
                "previous_state": previous,
            },
            output_snapshot=lambda result: {
                "candidate_ids": [str(candidate.content_item_id) for candidate in result[0]],
                "new_state": "rejected",
                "resulting_event_id": str(result[1].event_id),
            },
        )
    except LookupError as exc:
        await session.commit()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return candidates


@router.get("/content-production/runs/{run_id}", response_model=ContentProductionRunOut)
async def get_content_production_run(run_id: UUID, session: AsyncSession = SessionDependency):
    run = await session.get(ContentProductionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="content production run not found")
    return run


@router.get("/content-production/runs/{run_id}/brief", response_model=EditorialBriefOut)
async def get_content_production_brief(run_id: UUID, session: AsyncSession = SessionDependency):
    return await _latest_run_artifact(session, EditorialBrief, run_id, "editorial brief not found")


@router.get("/content-production/runs/{run_id}/draft", response_model=TelegramDraftOut)
async def get_content_production_draft(run_id: UUID, session: AsyncSession = SessionDependency):
    return await _latest_run_artifact(session, TelegramDraft, run_id, "telegram draft not found")


@router.get("/content-production/runs/{run_id}/quality-report", response_model=DraftQualityReportOut)
async def get_content_production_quality_report(run_id: UUID, session: AsyncSession = SessionDependency):
    return await _latest_run_artifact(session, DraftQualityReport, run_id, "draft quality report not found")


@router.get("/content-production/runs/{run_id}/media", response_model=VisualBriefOut)
async def get_content_production_media(run_id: UUID, session: AsyncSession = SessionDependency):
    return await _latest_run_artifact(session, VisualBrief, run_id, "visual brief not found")


@router.get("/content-production/runs/{run_id}/package", response_model=TelegramPostPackageOut)
async def get_content_production_package(run_id: UUID, session: AsyncSession = SessionDependency):
    return await _latest_run_artifact(session, TelegramPostPackage, run_id, "telegram package not found")


@router.post("/content-production/runs/{run_id}/request-revision", response_model=TelegramPostPackageOut)
async def request_content_production_revision(run_id: UUID, session: AsyncSession = SessionDependency):
    run = await _get_run_or_404(session, run_id)
    package = await _latest_run_artifact(session, TelegramPostPackage, run_id, "telegram package not found")
    previous_state = {"run": run.state, "package": package.approval_status}

    async def request_revision():
        return await TelegramPackageService(session).request_revision(run=run, package=package)

    try:
        package = await HumanDecisionTraceService(session).execute(
            request_revision,
            step_name="final_package_revision_request",
            service_name="TelegramPackageService",
            production_run_id=run.id,
            request_id=run.request_id,
            aggregate_type="telegram_post_package",
            aggregate_id=package.id,
            decision="request_revision",
            input_snapshot={"package_id": str(package.id), "previous_state": previous_state, "revision_reason": None},
            output_snapshot=lambda result: {
                "package_id": str(result.id),
                "new_state": {"run": run.state, "package": result.approval_status},
                "revision_reason": None,
                "resulting_event_id": None,
            },
        )
    except ValueError as exc:
        await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return package


@router.post("/content-production/packages/{package_id}/approve", response_model=TelegramPostPackageOut)
async def approve_content_production_package(package_id: UUID, session: AsyncSession = SessionDependency):
    package = await _get_package_or_404(session, package_id)
    run = await _get_run_or_404(session, package.production_run_id)
    previous_state = {"run": run.state, "package": package.approval_status}

    async def approve_and_emit():
        approved = await TelegramPackageService(session).approve(run=run, package=package)
        event = await _enqueue_content_production_event(
            ContentProductionRepository(session),
            event_type=WorkflowEventType.POST_PACKAGE_APPROVED,
            aggregate_type="content_production_run",
            aggregate_id=run.id,
            correlation_id=run.request_id,
            payload={
                "production_run_id": str(run.id),
                "package_id": str(approved.id),
                "approval_status": approved.approval_status,
            },
            discriminator=str(approved.id),
        )
        return approved, event

    try:
        package, _ = await HumanDecisionTraceService(session).execute(
            approve_and_emit,
            step_name="final_package_approval_decision",
            service_name="TelegramPackageService",
            production_run_id=run.id,
            request_id=run.request_id,
            aggregate_type="telegram_post_package",
            aggregate_id=package.id,
            decision="approve",
            input_snapshot={"package_id": str(package.id), "previous_state": previous_state},
            output_snapshot=lambda result: {
                "package_id": str(result[0].id),
                "new_state": {"run": run.state, "package": result[0].approval_status},
                "resulting_event_id": str(result[1].event_id),
            },
        )
    except ValueError as exc:
        await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return package


@router.post("/content-production/packages/{package_id}/reject", response_model=TelegramPostPackageOut)
async def reject_content_production_package(package_id: UUID, session: AsyncSession = SessionDependency):
    package = await _get_package_or_404(session, package_id)
    run = await _get_run_or_404(session, package.production_run_id)
    previous_state = {"run": run.state, "package": package.approval_status}

    async def reject_and_emit():
        rejected = await TelegramPackageService(session).reject(run=run, package=package)
        event = await _enqueue_content_production_event(
            ContentProductionRepository(session),
            event_type=WorkflowEventType.POST_PACKAGE_REJECTED,
            aggregate_type="content_production_run",
            aggregate_id=run.id,
            correlation_id=run.request_id,
            payload={
                "production_run_id": str(run.id),
                "package_id": str(rejected.id),
                "approval_status": rejected.approval_status,
            },
            discriminator=str(rejected.id),
        )
        return rejected, event

    try:
        package, _ = await HumanDecisionTraceService(session).execute(
            reject_and_emit,
            step_name="final_package_rejection_decision",
            service_name="TelegramPackageService",
            production_run_id=run.id,
            request_id=run.request_id,
            aggregate_type="telegram_post_package",
            aggregate_id=package.id,
            decision="reject",
            input_snapshot={"package_id": str(package.id), "previous_state": previous_state},
            output_snapshot=lambda result: {
                "package_id": str(result[0].id),
                "new_state": {"run": run.state, "package": result[0].approval_status},
                "resulting_event_id": str(result[1].event_id),
            },
        )
    except ValueError as exc:
        await session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return package


@router.get("/content-production/events", response_model=list[WorkflowEventOut])
async def list_content_production_events(
    correlation_id: UUID | None = None,
    limit: int = Query(100, ge=1, le=250),
    session: AsyncSession = SessionDependency,
):
    stmt = select(WorkflowEvent)
    if correlation_id:
        stmt = stmt.where(WorkflowEvent.correlation_id == correlation_id)
    rows = await session.scalars(stmt.order_by(WorkflowEvent.occurred_at.desc()).limit(limit))
    return list(rows)


@router.get("/diagnostics", response_model=DiagnosticsOut)
async def diagnostics(session: AsyncSession = SessionDependency):
    return await DiagnosticsService(session).check()


async def _count(session: AsyncSession, model, *criteria) -> int:
    stmt = select(func.count()).select_from(model)
    for condition in criteria:
        stmt = stmt.where(condition)
    return int(await session.scalar(stmt) or 0)


async def _get_run_or_404(session: AsyncSession, run_id: UUID) -> ContentProductionRun:
    run = await session.get(ContentProductionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="content production run not found")
    return run


async def _get_package_or_404(session: AsyncSession, package_id: UUID) -> TelegramPostPackage:
    package = await session.get(TelegramPostPackage, package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="telegram package not found")
    return package


async def _latest_run_artifact(session: AsyncSession, model, run_id: UUID, not_found: str):
    row = await session.scalar(
        select(model).where(model.production_run_id == run_id).order_by(model.created_at.desc()).limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail=not_found)
    return row


async def _enqueue_content_production_event(
    repository: ContentProductionRepository,
    *,
    event_type: WorkflowEventType,
    aggregate_type: str,
    aggregate_id: UUID,
    correlation_id: UUID,
    payload: dict,
    discriminator: str = "",
) -> WorkflowEvent:
    event, _ = await repository.enqueue_event_once(
        event_id=uuid5(aggregate_id, f"api:{event_type.value}:{discriminator}"),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        payload=payload,
    )
    return event
