from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from app.content_production.events import WorkflowEventType
from app.content_production.handlers import build_core_event_dispatcher
from app.content_production.llm import LLMProviderError, LLMResponse
from app.content_production.orchestration import WorkflowEventWorker
from app.content_production.packages import TelegramPackageService
from app.content_production.providers import SafeArticleExtractionProvider
from app.content_production.states import InvalidWorkflowTransition
from app.db.models import (
    AgentStepRun,
    ArticleExtractionResult,
    CandidateShortlist,
    ContentItem,
    ContentProductionRequest,
    ContentProductionRun,
    ContentSufficiencyReport,
    DraftQualityReport,
    EditorialBrief,
    MediaAsset,
    TelegramDispatchRequest,
    TelegramDraft,
    TelegramPostPackage,
    VisualBrief,
    WebEnrichmentResult,
    WorkflowEvent,
)


def test_core_registry_registers_requested_and_explicit_pause_events():
    dispatcher = build_core_event_dispatcher(MemorySession())

    assert dispatcher.registered_event_types == set(WorkflowEventType)


async def test_request_created_emits_one_causally_linked_candidate_selection_request():
    request = _request()
    session = MemorySession(request)
    dispatcher = build_core_event_dispatcher(session)
    created = _event(
        WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={"request_id": str(request.id)},
    )

    await dispatcher.dispatch(created)
    await dispatcher.dispatch(created)

    selections = session.events(WorkflowEventType.CANDIDATE_SELECTION_REQUESTED)
    assert len(selections) == 1
    assert selections[0].aggregate_type == "content_production_request"
    assert selections[0].aggregate_id == request.id
    assert selections[0].correlation_id == created.correlation_id
    assert selections[0].causation_id == created.event_id
    assert selections[0].payload == {"request_id": str(request.id), "max_candidates": request.max_candidates}


async def test_candidate_selection_and_explicit_approval_create_run_and_preserve_event_context():
    request = _request()
    item = _content_item(full=True)
    session = MemorySession(request, item)
    dispatcher = build_core_event_dispatcher(session)
    selection = _event(
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
    )

    await dispatcher.dispatch(selection)

    candidates = session.rows(CandidateShortlist)
    assert len(candidates) == 1
    prepared = session.event(WorkflowEventType.CANDIDATE_SHORTLIST_PREPARED)
    assert prepared.correlation_id == selection.correlation_id
    assert prepared.causation_id == selection.event_id

    await dispatcher.dispatch(prepared)
    approval_gate = session.event(WorkflowEventType.CANDIDATE_SHORTLIST_APPROVAL_REQUESTED)
    await dispatcher.dispatch(approval_gate)
    assert session.rows(ContentProductionRun) == []

    candidates[0].approval_status = "approved"
    approval = _event(
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=selection.correlation_id,
        payload={
            "selection_execution_id": str(selection.event_id),
            "content_item_ids": [str(item.id)],
        },
    )
    await dispatcher.dispatch(approval)

    runs = session.rows(ContentProductionRun)
    assert len(runs) == 1
    assert runs[0].state == "shortlist_approved"
    sufficiency = session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)
    assert sufficiency.aggregate_id == runs[0].id
    assert sufficiency.correlation_id == approval.correlation_id
    assert sufficiency.causation_id == approval.event_id


@pytest.mark.parametrize(
    ("full", "expected_status", "expected_event"),
    [
        (True, "sufficient", WorkflowEventType.EDITORIAL_BRIEF_REQUESTED),
        (False, "partial", WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED),
    ],
)
async def test_sufficiency_handler_invokes_service_and_branches(full, expected_status, expected_event):
    item = _content_item(full=full)
    run = _run(item, state="shortlist_approved")
    session = MemorySession(item, run)
    dispatcher = build_core_event_dispatcher(session)
    requested = _run_event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
        run,
        payload={"stage": "original"},
    )

    await dispatcher.dispatch(requested)

    reports = session.rows(ContentSufficiencyReport)
    assert len(reports) == 1
    assert reports[0].status == expected_status
    checked = session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED)
    assert checked.payload["status"] == expected_status

    await dispatcher.dispatch(checked)

    next_event = session.event(expected_event)
    assert next_event.correlation_id == requested.correlation_id
    assert next_event.causation_id == checked.event_id
    if full:
        assert not session.events(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED)
        assert not session.events(WorkflowEventType.WEB_ENRICHMENT_REQUESTED)
        assert len(session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)) == 1


async def test_routing_extraction_can_make_content_sufficient():
    item = _content_item(full=False)
    run = _run(item, state="shortlist_approved")
    session = MemorySession(item, run)
    dispatcher = build_core_event_dispatcher(session)
    original = _run_event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED, run, payload={"stage": "original"}
    )
    await _dispatch_sufficiency_stage(dispatcher, session, original)
    extraction = ArticleExtractionResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        status="ok",
        content_text="Extracted article facts and source detail. " * 80,
        warnings_json=[],
        metadata_json={},
    )
    session.add(extraction)
    run.state = "article_extracted"
    await dispatcher.dispatch(
        _run_event(
            WorkflowEventType.ARTICLE_EXTRACTED,
            run,
            payload={"extraction_result_id": str(extraction.id), "status": "ok"},
        )
    )
    post_extraction = session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)
    await _dispatch_sufficiency_stage(dispatcher, session, post_extraction)

    reports = session.rows(ContentSufficiencyReport)
    assert [report.input_snapshot_json["stage"] for report in reports] == ["original", "post_extraction"]
    assert reports[-1].status == "sufficient"
    assert len(session.events(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED)) == 1
    assert not session.events(WorkflowEventType.WEB_ENRICHMENT_REQUESTED)
    assert len(session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)) == 1
    trace = _event_trace(session, "content_sufficiency", post_extraction)
    assert trace.output_snapshot_json["sufficiency"] == {
        "stage": "post_extraction",
        "decision": "sufficient",
        "extraction_result_id": str(extraction.id),
        "enrichment_result_id": None,
        "reasons": reports[-1].reasons_json,
    }
    assert trace.output_snapshot_json["emitted_events"][0]["event_type"] == "ContentSufficiencyChecked"


async def test_routing_enrichment_can_make_content_sufficient():
    item = _content_item(full=False)
    run = _run(item, state="shortlist_approved")
    session = MemorySession(item, run)
    dispatcher = build_core_event_dispatcher(session)
    original = _run_event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED, run, payload={"stage": "original"}
    )
    await _dispatch_sufficiency_stage(dispatcher, session, original)
    extraction = ArticleExtractionResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        status="fallback",
        content_text="weak extraction",
        warnings_json=["weak_content"],
        metadata_json={},
    )
    session.add(extraction)
    run.state = "article_extracted"
    await dispatcher.dispatch(
        _run_event(
            WorkflowEventType.ARTICLE_EXTRACTED,
            run,
            payload={"extraction_result_id": str(extraction.id), "status": "fallback"},
        )
    )
    await _dispatch_sufficiency_stage(
        dispatcher, session, session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)
    )
    enrichment = WebEnrichmentResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        provider_name="mock-search",
        status="ok",
        query_json={},
        findings_json=[
            {
                "title": "Confirmed context",
                "snippet": "Verified supporting facts. " * 80,
                "relevance_status": "relevant",
                "relevance_score": 0.8,
                "matched_signals": ["title_term_overlap"],
                "rejection_reason": None,
                "accepted_for_evidence": True,
            }
        ],
        source_attribution_json=[],
        warnings_json=[],
    )
    session.add(enrichment)
    run.state = "enriched"
    await dispatcher.dispatch(
        _run_event(
            WorkflowEventType.WEB_ENRICHED,
            run,
            payload={
                "extraction_result_id": str(extraction.id),
                "enrichment_result_id": str(enrichment.id),
                "status": "ok",
            },
        )
    )
    await _dispatch_sufficiency_stage(
        dispatcher, session, session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)
    )

    reports = session.rows(ContentSufficiencyReport)
    assert [report.input_snapshot_json["stage"] for report in reports] == [
        "original",
        "post_extraction",
        "post_enrichment",
    ]
    assert reports[-1].status == "sufficient"
    assert len(session.events(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED)) == 1
    assert len(session.events(WorkflowEventType.WEB_ENRICHMENT_REQUESTED)) == 1
    assert len(session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)) == 1


async def test_routing_still_insufficient_after_enrichment_is_terminal_and_replay_safe():
    item = _content_item(full=False)
    run = _run(item, state="enriched")
    extraction = ArticleExtractionResult(
        id=uuid4(), production_run_id=run.id, content_item_id=item.id, status="fallback", content_text="weak"
    )
    enrichment = WebEnrichmentResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        provider_name="mock-search",
        status="ok",
        query_json={},
        findings_json=[],
        source_attribution_json=[],
        warnings_json=["no_findings"],
    )
    final_check = _run_event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
        run,
        payload={
            "stage": "post_enrichment",
            "extraction_result_id": str(extraction.id),
            "enrichment_result_id": str(enrichment.id),
        },
    )
    session = MemorySession(item, run, extraction, enrichment)
    dispatcher = build_core_event_dispatcher(session)

    await _dispatch_sufficiency_stage(dispatcher, session, final_check)
    await _dispatch_sufficiency_stage(dispatcher, session, final_check)

    failures = session.events(WorkflowEventType.PRODUCTION_RUN_FAILED)
    assert len(session.rows(ContentSufficiencyReport)) == 1
    assert len(failures) == 1
    assert failures[0].payload["failure_type"] == "terminal_content_insufficient"
    assert failures[0].payload["no_more_automatic_stages"] is True
    assert not session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)
    assert not session.events(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED)
    assert not session.events(WorkflowEventType.WEB_ENRICHMENT_REQUESTED)
    await dispatcher.dispatch(failures[0])
    assert run.state == "failed"


async def test_ambiguous_enrichment_stops_with_explicit_human_review_classification():
    item = _content_item(full=False)
    run = _run(item, state="enriched")
    extraction = ArticleExtractionResult(
        id=uuid4(), production_run_id=run.id, content_item_id=item.id, status="fallback", content_text="weak"
    )
    enrichment = WebEnrichmentResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        provider_name="mock-search",
        status="ok",
        query_json={},
        findings_json=[
            {
                "title": "Possibly related context",
                "snippet": "One moderate source",
                "relevance_status": "ambiguous",
                "relevance_score": 0.5,
                "matched_signals": ["partial_title_overlap"],
                "rejection_reason": "requires_multiple_independent_moderate_results",
                "accepted_for_evidence": False,
            }
        ],
        source_attribution_json=[],
        warnings_json=["no_relevant_findings"],
    )
    final_check = _run_event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
        run,
        payload={
            "stage": "post_enrichment",
            "extraction_result_id": str(extraction.id),
            "enrichment_result_id": str(enrichment.id),
        },
    )
    session = MemorySession(item, run, extraction, enrichment)

    await _dispatch_sufficiency_stage(build_core_event_dispatcher(session), session, final_check)

    failure = session.event(WorkflowEventType.PRODUCTION_RUN_FAILED)
    assert failure.payload["failure_type"] == "enrichment_relevance_human_review_required"
    assert failure.payload["human_review_required"] is True
    assert not session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)


async def test_extraction_technical_failure_routes_once_to_enrichment():
    item = _content_item(full=False)
    run = _run(item, state="article_extracting")
    extraction = ArticleExtractionResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        status="failed",
        warnings_json=["technical_extraction_failure:TimeoutError"],
        metadata_json={},
        error_message="technical_extraction_failure:TimeoutError",
    )
    event = _run_event(
        WorkflowEventType.ARTICLE_EXTRACTION_FAILED,
        run,
        payload={"extraction_result_id": str(extraction.id), "status": "failed"},
    )
    session = MemorySession(item, run, extraction)
    dispatcher = build_core_event_dispatcher(session)

    await dispatcher.dispatch(event)
    await dispatcher.dispatch(event)

    enrichment = session.events(WorkflowEventType.WEB_ENRICHMENT_REQUESTED)
    assert len(enrichment) == 1
    assert enrichment[0].payload["extraction_failure_type"] == "technical"
    assert not session.events(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED)


async def test_enrichment_technical_failure_is_explicit_terminal_outcome():
    item = _content_item(full=False)
    run = _run(item, state="enriching")
    enrichment = WebEnrichmentResult(
        id=uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        provider_name="mock-search",
        status="failed",
        query_json={},
        findings_json=[],
        source_attribution_json=[],
        warnings_json=["technical_enrichment_failure"],
        error_message="TimeoutError: provider unavailable",
    )
    event = _run_event(
        WorkflowEventType.WEB_ENRICHMENT_FAILED,
        run,
        payload={"enrichment_result_id": str(enrichment.id), "status": "failed"},
    )
    session = MemorySession(item, run, enrichment)
    dispatcher = build_core_event_dispatcher(session)

    await dispatcher.dispatch(event)
    await dispatcher.dispatch(event)

    failures = session.events(WorkflowEventType.PRODUCTION_RUN_FAILED)
    assert len(failures) == 1
    assert failures[0].payload["failure_type"] == "enrichment_technical_failure"
    assert failures[0].payload["provider_name"] == "mock-search"
    assert not session.events(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED)
    await dispatcher.dispatch(failures[0])
    assert run.state == "failed"


@pytest.mark.parametrize(
    ("completion_type", "artifact_factory", "state", "payload_key"),
    [
        (
            WorkflowEventType.ARTICLE_EXTRACTED,
            lambda run: ArticleExtractionResult(
                id=uuid4(),
                production_run_id=run.id,
                content_item_id=run.content_item_id,
                status="ok",
                warnings_json=[],
                metadata_json={},
            ),
            "article_extracted",
            "extraction_result_id",
        ),
        (
            WorkflowEventType.WEB_ENRICHED,
            lambda run: WebEnrichmentResult(
                id=uuid4(),
                production_run_id=run.id,
                content_item_id=run.content_item_id,
                provider_name="test",
                status="ok",
                query_json={},
                findings_json=[],
                source_attribution_json=[],
                warnings_json=[],
            ),
            "enriched",
            "enrichment_result_id",
        ),
    ],
)
async def test_extraction_and_enrichment_completion_request_sufficiency_recheck(
    completion_type,
    artifact_factory,
    state,
    payload_key,
):
    item = _content_item(full=False)
    run = _run(item, state=state)
    artifact = artifact_factory(run)
    session = MemorySession(item, run, artifact)
    dispatcher = build_core_event_dispatcher(session)
    completion = _run_event(completion_type, run, payload={payload_key: str(artifact.id)})

    await dispatcher.dispatch(completion)

    recheck = session.event(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)
    assert recheck.causation_id == completion.event_id
    assert recheck.correlation_id == completion.correlation_id


async def test_service_backed_handlers_advance_to_final_approval_and_stop_at_human_gate():
    request = _request()
    image = _media_asset()
    item = _content_item(full=True, primary_image_id=image.id)
    run = _run(item, state="sufficiency_sufficient", request_id=request.id)
    session = MemorySession(request, item, image, run)
    dispatcher = build_core_event_dispatcher(session)

    brief_requested = _run_event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, run)
    await dispatcher.dispatch(brief_requested)
    assert len(session.rows(EditorialBrief)) == 1

    brief_created = session.event(WorkflowEventType.EDITORIAL_BRIEF_CREATED)
    await dispatcher.dispatch(brief_created)
    await dispatcher.dispatch(session.event(WorkflowEventType.DRAFT_GENERATION_REQUESTED))
    assert len(session.rows(TelegramDraft)) == 1

    await dispatcher.dispatch(session.event(WorkflowEventType.DRAFT_GENERATED))
    await dispatcher.dispatch(session.event(WorkflowEventType.DRAFT_QUALITY_CHECK_REQUESTED))
    reports = session.rows(DraftQualityReport)
    assert len(reports) == 1
    assert reports[0].status == "passed"

    await dispatcher.dispatch(session.event(WorkflowEventType.DRAFT_QUALITY_CHECKED))
    await dispatcher.dispatch(session.event(WorkflowEventType.MEDIA_RESOLUTION_REQUESTED))
    visuals = session.rows(VisualBrief)
    assert len(visuals) == 1
    assert visuals[0].status == "selected"

    await dispatcher.dispatch(session.event(WorkflowEventType.MEDIA_SELECTED))
    await dispatcher.dispatch(session.event(WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED))
    packages = session.rows(TelegramPostPackage)
    assert len(packages) == 1
    assert run.state == "final_approval_pending"

    await dispatcher.dispatch(session.event(WorkflowEventType.TELEGRAM_PACKAGE_READY))
    final_gate = session.event(WorkflowEventType.FINAL_APPROVAL_REQUESTED)
    await dispatcher.dispatch(final_gate)

    assert packages[0].approval_status == "pending"
    assert run.state == "final_approval_pending"
    assert not session.events(WorkflowEventType.POST_PACKAGE_APPROVED)
    assert not session.events(WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED)
    assert session.rows(TelegramDispatchRequest) == []


async def test_explicit_final_approval_event_is_required_before_dispatch_handoff():
    item = _content_item(full=True)
    run = _run(item, state="final_approval_pending")
    package = _package(run)
    session = MemorySession(item, run, package)
    dispatcher = build_core_event_dispatcher(session)
    premature = _run_event(
        WorkflowEventType.POST_PACKAGE_APPROVED,
        run,
        payload={"package_id": str(package.id)},
    )

    with pytest.raises(InvalidWorkflowTransition):
        await dispatcher.dispatch(premature)

    await TelegramPackageService(session).approve(run=run, package=package)
    approved = _run_event(
        WorkflowEventType.POST_PACKAGE_APPROVED,
        run,
        payload={"package_id": str(package.id)},
    )
    await dispatcher.dispatch(approved)

    dispatch_requested = session.event(WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED)
    assert dispatch_requested.causation_id == approved.event_id
    await dispatcher.dispatch(dispatch_requested)
    assert len(session.rows(TelegramDispatchRequest)) == 1
    assert run.state == "dispatch_failed"
    assert not session.events(WorkflowEventType.TELEGRAM_POST_PUBLISHED)


async def test_handler_failure_is_recorded_by_worker_for_retry():
    session = MemorySession()
    dispatcher = build_core_event_dispatcher(session)
    event = _event(
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
        aggregate_type="content_production_run",
        aggregate_id=uuid4(),
    )
    store = MemoryOutboxStore([event])
    worker = WorkflowEventWorker(store, dispatcher, max_attempts=2, retry_delay=timedelta(seconds=10))

    await worker.run_once()

    assert event.status == "pending"
    assert event.attempt_count == 1
    assert "content production run not found" in event.last_error
    assert event.available_at > datetime.now(UTC)


async def test_worker_candidate_selection_trace_is_completed_and_secret_safe():
    request = _request()
    item = _content_item(full=True)
    event = _event(
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={
            "request_id": str(request.id),
            "api_token": "must-not-be-stored",
            "content_text": "large article body " * 200,
        },
    )
    event.causation_id = uuid4()
    session = MemorySession(request, item, event)
    worker = WorkflowEventWorker(MemoryOutboxStore(session.added), build_core_event_dispatcher(session))

    await worker.run_once()

    trace = _trace(session, "candidate_selection")
    assert trace.production_run_id is None
    assert trace.status == "completed"
    assert trace.finished_at is not None
    assert trace.model_name is None
    assert trace.token_usage_json == {}
    assert trace.input_snapshot_json["request_id"] == str(request.id)
    assert trace.input_snapshot_json["event"] == {
        "event_id": str(event.event_id),
        "event_type": event.event_type,
        "correlation_id": str(event.correlation_id),
        "causation_id": str(event.causation_id),
        "attempt_count": 1,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": str(event.aggregate_id),
    }
    assert trace.output_snapshot_json["shortlist"]["candidate_count"] == 1
    serialized = json.dumps({"input": trace.input_snapshot_json, "output": trace.output_snapshot_json})
    assert "must-not-be-stored" not in serialized
    assert "large article body " * 20 not in serialized


async def test_worker_happy_path_records_all_required_completed_step_traces():
    request = _request()
    image = _media_asset()
    item = _content_item(full=True, primary_image_id=image.id)
    initial = _event(
        WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={"request_id": str(request.id)},
    )
    session = MemorySession(request, item, image, initial)
    worker = WorkflowEventWorker(MemoryOutboxStore(session.added), build_core_event_dispatcher(session))

    await _drain(worker)
    candidate = session.rows(CandidateShortlist)[0]
    candidate.approval_status = "approved"
    approval = _event(
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        correlation_id=request.id,
        payload={
            "request_id": str(request.id),
            "selection_execution_id": str(candidate.selection_execution_id),
            "content_item_ids": [str(item.id)],
        },
    )
    session.add(approval)
    await _drain(worker)

    run = session.rows(ContentProductionRun)[0]
    package = session.rows(TelegramPostPackage)[0]
    await TelegramPackageService(session).approve(run=run, package=package)
    final_approval = _run_event(
        WorkflowEventType.POST_PACKAGE_APPROVED,
        run,
        payload={"package_id": str(package.id)},
    )
    session.add(final_approval)
    await _drain(worker)

    completed_steps = {trace.step_name for trace in session.rows(AgentStepRun) if trace.status == "completed"}
    assert {"production_run_creation", "visual_brief_creation"}.isdisjoint(completed_steps)
    assert {
        "content_production_request_handling",
        "candidate_selection",
        "shortlist_preparation",
        "shortlist_approval_event_progression",
        "content_sufficiency",
        "editorial_brief_creation",
        "telegram_draft_generation",
        "draft_quality_check",
        "media_resolution",
        "telegram_package_creation",
        "final_approval_dispatch_progression",
        "dispatch_handoff",
    }.issubset(completed_steps)
    approval_trace = _trace(session, "shortlist_approval_event_progression")
    assert any(
        emitted["payload"]["production_run_id"] == str(run.id)
        for emitted in approval_trace.output_snapshot_json["emitted_events"]
    )
    media_trace = _trace(session, "media_resolution")
    assert media_trace.output_snapshot_json["artifact"]["artifact_type"] == "VisualBrief"
    dispatch_trace = _trace(session, "dispatch_handoff")
    assert dispatch_trace.output_snapshot_json["artifact"]["artifact_type"] == "TelegramDispatchRequest"

    artifact_models = (
        ContentProductionRun,
        ContentSufficiencyReport,
        EditorialBrief,
        TelegramDraft,
        DraftQualityReport,
        VisualBrief,
        TelegramPostPackage,
        TelegramDispatchRequest,
    )
    counts_before = {model: len(session.rows(model)) for model in artifact_models}
    events_before = len(session.rows(WorkflowEvent))
    replay_types = (
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED,
        WorkflowEventType.EDITORIAL_BRIEF_REQUESTED,
        WorkflowEventType.DRAFT_GENERATION_REQUESTED,
        WorkflowEventType.DRAFT_QUALITY_CHECK_REQUESTED,
        WorkflowEventType.MEDIA_RESOLUTION_REQUESTED,
        WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED,
        WorkflowEventType.POST_PACKAGE_APPROVED,
        WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED,
    )

    for event_type in replay_types:
        await worker.dispatcher.dispatch(session.event(event_type))

    assert {model: len(session.rows(model)) for model in artifact_models} == counts_before
    assert len(session.rows(WorkflowEvent)) == events_before
    assert len(session.rows(AgentStepRun)) >= len(completed_steps) + len(replay_types)


async def test_worker_extraction_and_enrichment_failure_path_is_traced():
    item = _content_item(full=False)
    item.canonical_url = None
    run = _run(item, state="sufficiency_partial")
    extraction = _run_event(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED, run)
    session = MemorySession(item, run, extraction)
    worker = WorkflowEventWorker(MemoryOutboxStore(session.added), build_core_event_dispatcher(session))

    await _drain(worker)

    completed_steps = {trace.step_name for trace in session.rows(AgentStepRun) if trace.status == "completed"}
    assert {
        "article_extraction",
        "article_extraction_failure_handling",
        "web_enrichment",
        "web_enrichment_failure_handling",
        "production_run_failure_handling",
    }.issubset(completed_steps)
    assert _trace(session, "article_extraction").output_snapshot_json["artifact"]["status"] == "failed"
    assert _trace(session, "web_enrichment").output_snapshot_json["artifact"]["status"] == "skipped"
    assert run.state == "failed"

    counts_before = {
        ArticleExtractionResult: len(session.rows(ArticleExtractionResult)),
        WebEnrichmentResult: len(session.rows(WebEnrichmentResult)),
        WorkflowEvent: len(session.rows(WorkflowEvent)),
    }
    await worker.dispatcher.dispatch(session.event(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED))
    await worker.dispatcher.dispatch(session.event(WorkflowEventType.WEB_ENRICHMENT_REQUESTED))
    assert {
        ArticleExtractionResult: len(session.rows(ArticleExtractionResult)),
        WebEnrichmentResult: len(session.rows(WebEnrichmentResult)),
        WorkflowEvent: len(session.rows(WorkflowEvent)),
    } == counts_before


async def test_real_extraction_adapter_is_injected_through_worker_and_trace_stays_bounded():
    item = _content_item(full=False)
    item.canonical_url = "https://publisher.test/article"
    run = _run(item, state="sufficiency_partial")
    extraction = _run_event(WorkflowEventType.ARTICLE_EXTRACTION_REQUESTED, run)
    session = MemorySession(item, run, extraction)
    body = "Public article evidence with names, dates, and concrete details. " * 100
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=f"<html><body><article><p>{body}</p></article></body></html>",
            headers={"content-type": "text/html"},
        )
    )

    async def public_resolver(hostname):
        return ["93.184.216.34"]

    async with httpx.AsyncClient(transport=transport) as client:
        provider = SafeArticleExtractionProvider(client=client, resolver=public_resolver)
        worker = WorkflowEventWorker(
            MemoryOutboxStore(session.added),
            build_core_event_dispatcher(session, extraction_provider=provider),
        )
        await worker.run_once()

    result = session.rows(ArticleExtractionResult)[0]
    assert result.status == "ok"
    assert result.content_text.startswith("Public article evidence")
    trace = _event_trace(session, "article_extraction", extraction)
    serialized = json.dumps(trace.output_snapshot_json)
    assert body not in serialized
    assert trace.output_snapshot_json["artifact"]["artifact_id"] == str(result.id)


async def test_worker_runs_fake_openrouter_brief_draft_quality_package_and_replays_without_provider_calls():
    request = _request()
    media = _media_asset()
    item = _content_item(full=True, primary_image_id=media.id)
    run = _run(item, state="sufficiency_sufficient")
    run.request_id = request.id
    initial = _run_event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, run)
    provider = OnePassFakeLLM(item.canonical_url)
    session = MemorySession(request, item, media, run, initial)
    worker = WorkflowEventWorker(
        MemoryOutboxStore(session.added),
        build_core_event_dispatcher(session, llm_provider=provider),
    )

    await _drain(worker)

    assert [call.operation for call in provider.calls] == [
        "editorial_brief",
        "persian_telegram_draft",
        "draft_quality_evaluation",
    ]
    assert run.state == "final_approval_pending"
    assert len(session.rows(TelegramPostPackage)) == 1
    assert session.rows(TelegramPostPackage)[0].approval_status == "pending"
    assert session.rows(TelegramDispatchRequest) == []
    brief = session.rows(EditorialBrief)[0]
    draft = session.rows(TelegramDraft)[0]
    assert brief.evidence_ids_json
    assert draft.evidence_ids_json
    assert set(draft.evidence_ids_json).issubset(set(brief.evidence_ids_json))
    for step in ("editorial_brief_creation", "telegram_draft_generation", "draft_quality_check"):
        trace = _trace(session, step)
        assert trace.model_name == "openai/gpt-5-mini"
        assert trace.token_usage_json == {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}
        assert trace.output_snapshot_json["provider_metadata"]["provider"] == "openrouter"
        assert trace.output_snapshot_json["provider_metadata"]["response_id"] == "gen-fixture"
        assert "prompt" not in trace.output_snapshot_json["provider_metadata"]

    calls_before_replay = len(provider.calls)
    events_before_replay = len(session.rows(WorkflowEvent))
    await worker.dispatcher.dispatch(initial)
    assert len(provider.calls) == calls_before_replay
    assert len(session.rows(WorkflowEvent)) == events_before_replay


async def test_permanent_llm_schema_failure_terminates_and_transient_failure_retries():
    request = _request()
    item = _content_item(full=True)
    run = _run(item, state="sufficiency_sufficient")
    run.request_id = request.id
    permanent = _run_event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, run)
    session = MemorySession(request, item, run, permanent)
    worker = WorkflowEventWorker(
        MemoryOutboxStore(session.added),
        build_core_event_dispatcher(session, llm_provider=InvalidFakeLLM()),
    )

    await _drain(worker)

    assert run.state == "failed"
    assert session.rows(EditorialBrief) == []
    failed = session.event(WorkflowEventType.PRODUCTION_RUN_FAILED)
    assert failed.payload["failure_type"] == "schema_validation_failed"

    retry_run = _run(item, state="sufficiency_sufficient")
    retry_run.request_id = request.id
    transient = _run_event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, retry_run)
    retry_session = MemorySession(request, item, retry_run, transient)
    retry_worker = WorkflowEventWorker(
        MemoryOutboxStore(retry_session.added),
        build_core_event_dispatcher(retry_session, llm_provider=TransientFakeLLM()),
    )
    await retry_worker.run_once()
    assert transient.status == "pending"
    assert transient.attempt_count == 1
    assert "provider_timeout" in transient.last_error


async def test_handler_failure_trace_re_raises_original_exception():
    run_id = uuid4()
    event = _event(
        WorkflowEventType.EDITORIAL_BRIEF_REQUESTED,
        aggregate_type="content_production_run",
        aggregate_id=run_id,
        payload={"production_run_id": str(run_id)},
    )
    session = MemorySession(event)
    dispatcher = build_core_event_dispatcher(session)

    with pytest.raises(LookupError, match="content production run not found"):
        await dispatcher.dispatch(event)

    trace = _trace(session, "editorial_brief_creation")
    assert trace.status == "failed"
    assert trace.finished_at is not None
    assert trace.error_message.startswith("LookupError:")
    assert trace.output_snapshot_json["error_class"] == "LookupError"
    assert trace.output_snapshot_json["failure_phase"] == "domain_handler"


async def test_worker_retry_keeps_failed_attempt_and_adds_completed_trace():
    request_id = uuid4()
    event = _event(
        WorkflowEventType.CONTENT_PRODUCTION_REQUEST_CREATED,
        aggregate_type="content_production_request",
        aggregate_id=request_id,
        correlation_id=request_id,
        payload={"request_id": str(request_id)},
    )
    session = MemorySession(event)
    worker = WorkflowEventWorker(
        MemoryOutboxStore(session.added),
        build_core_event_dispatcher(session),
        max_attempts=2,
        retry_delay=timedelta(0),
    )

    await worker.run_once()
    session.add(
        ContentProductionRequest(
            id=request_id,
            topic="retry trace",
            platform="telegram",
            language="fa",
            max_candidates=1,
            require_rewrite_ready=True,
            require_media=False,
            status="created",
            constraints_json={},
        )
    )
    await worker.run_once()

    traces = [trace for trace in session.rows(AgentStepRun) if trace.step_name == "content_production_request_handling"]
    assert [trace.status for trace in traces] == ["failed", "completed"]
    assert [trace.input_snapshot_json["event"]["attempt_count"] for trace in traces] == [1, 2]
    assert traces[0].error_message
    assert traces[0].finished_at is not None
    assert traces[1].error_message is None
    assert traces[1].finished_at is not None
    assert traces[0].id != traces[1].id


async def test_invalid_run_state_fails_visibly_without_emitting_next_event():
    request = _request()
    item = _content_item(full=True)
    run = _run(item, state="created", request_id=request.id)
    session = MemorySession(request, item, run)
    dispatcher = build_core_event_dispatcher(session)
    event = _run_event(WorkflowEventType.EDITORIAL_BRIEF_REQUESTED, run)

    with pytest.raises(InvalidWorkflowTransition):
        await dispatcher.dispatch(event)

    assert session.rows(EditorialBrief) == []
    assert not session.events(WorkflowEventType.EDITORIAL_BRIEF_CREATED)


async def test_package_event_replay_keeps_pinned_draft_and_new_command_creates_version():
    item = _content_item(full=True)
    run = _run(item, state="media_ready")
    brief = EditorialBrief(
        id=uuid4(), production_run_id=run.id, angle="AI", key_facts_json=[], source_claims_json=[]
    )
    draft_a = TelegramDraft(
        id=uuid4(), production_run_id=run.id, brief_id=brief.id, draft_text="draft A", source_links_json=[]
    )
    quality_a = DraftQualityReport(
        id=uuid4(), production_run_id=run.id, draft_id=draft_a.id, status="passed", score=1
    )
    visual = VisualBrief(id=uuid4(), production_run_id=run.id, status="selected", needs_generation=False)
    session = MemorySession(item, run, brief, draft_a, quality_a, visual)
    dispatcher = build_core_event_dispatcher(session)
    first = _run_event(
        WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED,
        run,
        payload={
            "draft_id": str(draft_a.id),
            "quality_report_id": str(quality_a.id),
            "visual_brief_id": str(visual.id),
        },
    )

    await dispatcher.dispatch(first)
    package_a = session.rows(TelegramPostPackage)[0]
    ready = session.event(WorkflowEventType.TELEGRAM_PACKAGE_READY)
    draft_b = TelegramDraft(
        id=uuid4(), production_run_id=run.id, brief_id=brief.id, draft_text="draft B", source_links_json=[]
    )
    quality_b = DraftQualityReport(
        id=uuid4(), production_run_id=run.id, draft_id=draft_b.id, status="passed", score=1
    )
    session.add(draft_b)
    session.add(quality_b)

    await dispatcher.dispatch(first)

    assert session.rows(TelegramPostPackage) == [package_a]
    assert package_a.draft_id == draft_a.id
    assert ready.payload["package_id"] == str(package_a.id)

    run.state = "media_ready"
    second = _run_event(
        WorkflowEventType.TELEGRAM_PACKAGE_REQUESTED,
        run,
        payload={
            "draft_id": str(draft_b.id),
            "quality_report_id": str(quality_b.id),
            "visual_brief_id": str(visual.id),
        },
    )
    await dispatcher.dispatch(second)

    packages = session.rows(TelegramPostPackage)
    assert len(packages) == 2
    assert packages[1].id != package_a.id
    assert packages[1].draft_id == draft_b.id
    await dispatcher.dispatch(first)
    trace = _event_trace(session, "telegram_package_creation", first)
    assert trace.output_snapshot_json["artifact"] == {
        "artifact_type": "TelegramPostPackage",
        "artifact_id": str(package_a.id),
        "status": None,
        "reused": True,
        "version_discriminator": str(draft_a.id),
    }
    assert str(packages[1].id) not in json.dumps(trace.output_snapshot_json)


async def test_approval_handlers_scope_overlapping_shortlist_executions():
    request = _request()
    items = [_content_item(full=True) for _ in range(3)]
    first_execution, second_execution = uuid4(), uuid4()
    candidates = [
        CandidateShortlist(
            id=uuid4(),
            request_id=request.id,
            selection_execution_id=execution_id,
            content_item_id=item.id,
            rank=rank,
            score=10,
            approval_status="approved",
            selection_reason_json={},
            risk_flags_json=[],
            source_snapshot_json={},
        )
        for execution_id, item, rank in (
            (first_execution, items[0], 1),
            (first_execution, items[1], 2),
            (second_execution, items[0], 1),
            (second_execution, items[2], 2),
        )
    ]
    session = MemorySession(request, *items, *candidates)
    dispatcher = build_core_event_dispatcher(session)
    first = _event(
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        payload={
            "selection_execution_id": str(first_execution),
            "content_item_ids": [str(items[0].id), str(items[1].id)],
        },
    )
    second = _event(
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        payload={
            "selection_execution_id": str(second_execution),
            "content_item_ids": [str(items[0].id), str(items[2].id)],
        },
    )

    await dispatcher.dispatch(first)
    await dispatcher.dispatch(second)
    await dispatcher.dispatch(first)
    await dispatcher.dispatch(second)

    assert len(session.rows(ContentProductionRun)) == 4
    assert len(session.events(WorkflowEventType.CONTENT_SUFFICIENCY_CHECK_REQUESTED)) == 4

    mixed = _event(
        WorkflowEventType.CANDIDATE_SHORTLIST_APPROVED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        payload={
            "selection_execution_id": str(first_execution),
            "content_item_ids": [str(items[0].id), str(items[2].id)],
        },
    )
    with pytest.raises(LookupError, match="not found"):
        await dispatcher.dispatch(mixed)
    assert len(session.rows(ContentProductionRun)) == 4


async def test_selection_trace_is_scoped_to_consumed_execution_after_newer_selection():
    request = _request()
    first_item, second_item = _content_item(full=True), _content_item(full=True)
    request.max_candidates = 2
    session = MemorySession(request, first_item, second_item)
    dispatcher = build_core_event_dispatcher(session)
    first = _event(
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        payload={"request_id": str(request.id)},
    )
    second = _event(
        WorkflowEventType.CANDIDATE_SELECTION_REQUESTED,
        aggregate_type="content_production_request",
        aggregate_id=request.id,
        payload={"request_id": str(request.id)},
    )

    await dispatcher.dispatch(first)
    first_rows = [row for row in session.rows(CandidateShortlist) if row.selection_execution_id == first.event_id]
    await dispatcher.dispatch(second)
    second_rows = [row for row in session.rows(CandidateShortlist) if row.selection_execution_id == second.event_id]
    await dispatcher.dispatch(first)

    trace = _event_trace(session, "candidate_selection", first)
    shortlist = trace.output_snapshot_json["shortlist"]
    assert shortlist["selection_execution_id"] == str(first.event_id)
    assert shortlist["candidate_ids"] == [str(row.id) for row in first_rows]
    assert shortlist["content_item_ids"] == [str(row.content_item_id) for row in first_rows]
    assert not set(shortlist["candidate_ids"]).intersection(str(row.id) for row in second_rows)


async def test_draft_trace_replay_resolves_original_command_version():
    item = _content_item(full=True)
    run = _run(item, state="brief_ready")
    brief = EditorialBrief(
        id=uuid4(),
        production_run_id=run.id,
        angle="AI",
        key_facts_json=[{"claim": "fact"}],
        source_claims_json=[{"url": "https://example.com/story", "claim": "fact"}],
    )
    session = MemorySession(item, run, brief)
    dispatcher = build_core_event_dispatcher(session)
    first = _run_event(WorkflowEventType.DRAFT_GENERATION_REQUESTED, run, payload={"brief_id": str(brief.id)})
    second = _run_event(WorkflowEventType.DRAFT_GENERATION_REQUESTED, run, payload={"brief_id": str(brief.id)})

    await dispatcher.dispatch(first)
    draft_a = session.rows(TelegramDraft)[0]
    run.state = "brief_ready"
    await dispatcher.dispatch(second)
    draft_b = session.rows(TelegramDraft)[1]
    await dispatcher.dispatch(first)

    trace = _event_trace(session, "telegram_draft_generation", first)
    assert trace.output_snapshot_json["artifact"]["artifact_id"] == str(draft_a.id)
    assert trace.output_snapshot_json["artifact"]["reused"] is True
    assert str(draft_b.id) not in json.dumps(trace.output_snapshot_json)


async def test_dispatch_handler_allows_distinct_command_versions_and_replay():
    item = _content_item(full=True)
    run = _run(item, state="final_approved")
    package = _package(run)
    package.approval_status = "approved"
    session = MemorySession(item, run, package)
    dispatcher = build_core_event_dispatcher(session)
    first = _run_event(
        WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED,
        run,
        payload={"package_id": str(package.id)},
    )
    second = _run_event(
        WorkflowEventType.TELEGRAM_DISPATCH_REQUESTED,
        run,
        payload={"package_id": str(package.id)},
    )

    await dispatcher.dispatch(first)
    await dispatcher.dispatch(first)
    await dispatcher.dispatch(second)
    await dispatcher.dispatch(second)
    await dispatcher.dispatch(first)

    dispatches = session.rows(TelegramDispatchRequest)
    assert len(dispatches) == 2
    assert dispatches[0].id != dispatches[1].id
    trace = _event_trace(session, "dispatch_handoff", first)
    assert trace.output_snapshot_json["artifact"]["artifact_id"] == str(dispatches[0].id)
    assert trace.output_snapshot_json["artifact"]["reused"] is True
    assert str(dispatches[1].id) not in json.dumps(trace.output_snapshot_json)


def _request():
    return ContentProductionRequest(
        id=uuid4(),
        topic="AI",
        platform="telegram",
        language="fa",
        max_candidates=1,
        require_rewrite_ready=True,
        require_media=False,
        status="created",
        constraints_json={},
    )


def _content_item(*, full: bool, primary_image_id=None):
    return ContentItem(
        id=uuid4(),
        item_type="rss",
        title="AI platform launch",
        summary="A short RSS summary about AI.",
        content_text=(
            "The company launched an AI platform for developers with sourced rollout details. " * 80 if full else ""
        ),
        canonical_url="https://example.com/story",
        primary_image_id=primary_image_id,
        tags=["ai"],
        sort_at=datetime(2026, 7, 11, tzinfo=UTC),
        date_parse_status="parsed",
        status="new",
        score=50,
        content_type="news",
        source_tier="A",
        freshness_bucket="fresh",
        quality_status="ok",
        is_rewrite_ready=full,
    )


def _run(item, *, state, request_id=None):
    return ContentProductionRun(
        id=uuid4(),
        request_id=request_id or uuid4(),
        content_item_id=item.id,
        platform="telegram",
        state=state,
    )


def _media_asset():
    return MediaAsset(
        id=uuid4(),
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        url_hash=uuid4().hex,
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=675,
        source_field="media",
        fetch_status="fetched",
        media_quality="good",
    )


def _package(run):
    return TelegramPostPackage(
        id=uuid4(),
        production_run_id=run.id,
        draft_id=uuid4(),
        package_json={"post_text": "AI update", "source_links": [], "media": {}},
        approval_status="pending",
    )


def _event(event_type, *, aggregate_type, aggregate_id, correlation_id=None, payload=None):
    return WorkflowEvent(
        event_id=uuid4(),
        event_type=event_type.value,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id or uuid4(),
        payload=payload or {},
        status="pending",
        attempt_count=0,
        available_at=datetime.now(UTC),
    )


def _run_event(event_type, run, *, payload=None):
    return _event(
        event_type,
        aggregate_type="content_production_run",
        aggregate_id=run.id,
        correlation_id=run.request_id,
        payload={"production_run_id": str(run.id), **(payload or {})},
    )


class MemorySession:
    def __init__(self, *rows):
        self.added = []
        self.by_key = {}
        for row in rows:
            self.add(row)

    def add(self, row):
        self.added.append(row)
        row_id = getattr(row, "event_id", None) or getattr(row, "id", None)
        if row_id is not None:
            self.by_key[(type(row), row_id)] = row

    async def get(self, model, row_id):
        return self.by_key.get((model, row_id))

    async def scalars(self, statement):
        return self._rows_for(statement)

    async def scalar(self, statement):
        rows = self._rows_for(statement)
        return rows[-1] if rows else None

    async def flush(self):
        return None

    async def commit(self):
        return None

    def rows(self, model):
        return [row for row in self.added if isinstance(row, model)]

    def events(self, event_type):
        return [row for row in self.rows(WorkflowEvent) if row.event_type == event_type.value]

    def event(self, event_type):
        events = self.events(event_type)
        assert events, f"missing {event_type.value}"
        return events[-1]

    def _rows_for(self, statement):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return self.rows(entity) if entity is not None else []


class MemoryOutboxStore:
    def __init__(self, events):
        self.events = events

    async def claim_pending_events(self, *, limit):
        events = [
            event
            for event in self.events
            if isinstance(event, WorkflowEvent)
            and event.status == "pending"
            and event.available_at <= datetime.now(UTC)
        ][:limit]
        for event in events:
            event.status = "processing"
        return events

    async def flush(self):
        return None

    async def commit(self):
        return None


async def _drain(worker, *, max_batches=40):
    for _ in range(max_batches):
        if await worker.run_once() == 0:
            return
    raise AssertionError("worker did not become idle")


async def _dispatch_sufficiency_stage(dispatcher, session, requested):
    await dispatcher.dispatch(requested)
    checked = next(
        event
        for event in reversed(session.events(WorkflowEventType.CONTENT_SUFFICIENCY_CHECKED))
        if event.causation_id == requested.event_id
    )
    await dispatcher.dispatch(checked)
    return checked


def _trace(session, step_name):
    traces = [trace for trace in session.rows(AgentStepRun) if trace.step_name == step_name]
    assert traces, f"missing trace {step_name}"
    return traces[-1]


def _event_trace(session, step_name, event):
    traces = [
        trace
        for trace in session.rows(AgentStepRun)
        if trace.step_name == step_name
        and trace.input_snapshot_json.get("event", {}).get("event_id") == str(event.event_id)
    ]
    assert traces, f"missing {step_name} trace for {event.event_id}"
    return traces[-1]


class OnePassFakeLLM:
    provider_name = "openrouter"

    def __init__(self, source_url):
        self.source_url = source_url
        self.calls = []

    async def generate(self, request):
        self.calls.append(request)
        output = {
            "editorial_brief": {
                "central_claim": "یک خبر مستند درباره محصول جدید",
                "why_it_matters": "این خبر برای کاربران فناوری اهمیت دارد.",
                "key_facts": [{"claim": "محصول جدید معرفی شده است.", "evidence_ids": ["rss:title"]}],
                "important_entities": ["OpenAI"],
                "source_context": [{"context": "اطلاعات از منبع اصلی است.", "evidence_ids": ["rss:excerpt"]}],
                "uncertainties": [],
                "prohibited_claims": ["جزئیات تاییدنشده اضافه نشود"],
                "persian_angle": "معرفی روشن محصول و کاربرد آن",
                "suggested_structure": ["تیتر", "خلاصه", "منبع"],
            },
            "persian_telegram_draft": _persian_draft_output(self.source_url),
            "draft_quality_evaluation": {
                "factual_fidelity": 5,
                "evidence_coverage": 4,
                "persian_readability": 5,
                "naturalness": 4,
                "concision": 4,
                "structure": 4,
                "headline_quality": 4,
                "source_attribution": 5,
                "unsupported_claim_risk": 5,
                "publication_readiness": 4,
                "unsupported_claims": [],
                "missing_essential_facts": [],
                "awkward_persian_phrases": [],
                "misleading_certainty": [],
                "irrelevant_content": [],
                "internal_instruction_leakage": [],
                "recommendation": "pass",
            },
        }[request.operation]
        return LLMResponse(
            output=output,
            provider_name=self.provider_name,
            model_name="openai/gpt-5-mini",
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
            latency_ms=12.5,
            response_id="gen-fixture",
        )


class InvalidFakeLLM:
    provider_name = "fake-llm"

    async def generate(self, request):
        return LLMResponse({}, self.provider_name, "fake", 1, 1, 2, 1.0)


class TransientFakeLLM:
    provider_name = "fake-llm"

    async def generate(self, request):
        raise LLMProviderError("provider_timeout", retryable=True)


def _persian_draft_output(source_url):
    headline = "معرفی محصولی تازه برای کاربران فناوری"
    body = (
        "این گزارش بر پایه اطلاعات منبع اصلی توضیح می‌دهد که محصول تازه چه کاربردی دارد و چرا برای کاربران "
        "فناوری مهم است. همه نکات بر شواهد منتشرشده تکیه دارند و هیچ ادعای تاییدنشده‌ای به متن افزوده نشده است."
    )
    return {
        "headline": headline,
        "body": body,
        "source_attribution": [{"label": "منبع اصلی", "url": source_url}],
        "hashtags": ["#فناوری"],
        "referenced_evidence_ids": ["rss:title", "rss:excerpt"],
        "uncertainty_flags": [],
        "final_text": f"{headline}\n\n{body}\n\nمنبع: {source_url}\n\n#فناوری",
    }
