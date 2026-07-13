from __future__ import annotations

import hashlib
import inspect
import shutil
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.automations.models import AutomationDispatch
from app.core.codex_exec import CodexExecutor
from app.core.config import settings
from app.core.faults import FaultInjector, NoopFaultInjector
from app.core.redaction import redact_secrets, redact_string
from app.generation.models import AIProviderProfile
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.research.base import ResearchBackend, ResearchBudgetExceeded, ResearchRequest
from app.research.citations import CitationIntegrityError, resolve_candidate_brief
from app.research.continuations import (
    enqueue_bound_continuation,
    normalize_continuation,
)
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.research.schemas import CandidateResearchBrief, DiscoveredSourcePayload, ResearchBudget
from app.research.service import ResearchRequestError, ResearchService, evidence_set_hash
from app.stories.evidence import EvidenceRecord, build_evidence_key
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

type ResearchBackendResolver = Callable[[AIProviderProfile], ResearchBackend | Awaitable[ResearchBackend]]


class DefaultResearchBackendResolver:
    """Build DB-free research adapters from the already configured generation resolver."""

    def __init__(self, profile_resolver: Any) -> None:
        self.profile_resolver = profile_resolver

    async def __call__(self, profile: AIProviderProfile) -> ResearchBackend:
        from app.research.codex_adapter import CodexResearchBackend
        from app.research.duckduckgo import DuckDuckGoSearchClient
        from app.research.fake import FakeResearchBackend
        from app.research.openrouter_loop import OpenRouterResearchBackend
        from app.research.safe_fetch import SafeArticleFetcher

        if profile.provider_type == "fake":
            from app.research.base import ResearchBackendOutput

            return FakeResearchBackend(
                output=ResearchBackendOutput(
                    sources=[],
                    brief=CandidateResearchBrief(
                        summary="No additional research evidence was configured.",
                        verified_facts=[],
                        disagreements=[],
                        missing_information=[],
                        suggested_angles=[],
                        discovered_evidence_keys=[],
                    ),
                )
            )
        if profile.provider_type == "codex":
            executable = shutil.which(settings.codex_executable)
            if executable is None:
                raise ValueError("Codex research executable is unavailable")
            return CodexResearchBackend(
                executor=CodexExecutor(executable=executable),
                fetcher=SafeArticleFetcher(),
            )
        if profile.provider_type == "openrouter":
            resolved = await self.profile_resolver.resolve(profile, None)
            return OpenRouterResearchBackend(
                model=resolved.provider,
                search_client=DuckDuckGoSearchClient(),
                fetcher=SafeArticleFetcher(),
                profile=profile,
            )
        raise ValueError("Research provider profile is unsupported")


def _evidence(snapshot: StoryEvidenceSnapshot) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_key=snapshot.evidence_key,
        evidence_snapshot_id=snapshot.id,
        content_item_id=snapshot.content_item_id,
        title=snapshot.title,
        content_text=snapshot.content_text,
        content_sha256=snapshot.content_sha256,
        source_url=snapshot.source_url,
        authors=tuple(snapshot.authors),
        published_at=snapshot.published_at,
        captured_at=snapshot.captured_at,
    )


def _classification(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, ResearchBudgetExceeded):
        return "needs_review", "research_budget_exceeded", "Research budget was exhausted"
    classification = getattr(exc, "classification", None)
    code = getattr(exc, "code", None)
    if classification in {"retryable", "needs_review", "permanent"}:
        return classification, str(code or "research_backend_failed"), "Research backend failed"
    if isinstance(exc, (CitationIntegrityError, ValueError)):
        return "needs_review", "research_result_invalid", "Research result failed evidence validation"
    return "permanent", "research_failed", "Research could not be completed"


def _validate_job_binding(
    *,
    run: ResearchRun,
    story_id: UUID,
    profile_id: UUID,
    payload: dict[str, Any],
    snapshots: list[StoryEvidenceSnapshot],
    resolved_model: str,
    resolved_budget: ResearchBudget,
    payload_budget: ResearchBudget,
) -> None:
    if run.story_id != story_id:
        raise ResearchRequestError("Research job story drifted")
    if run.provider_profile_id != profile_id:
        raise ResearchRequestError("Research job provider profile drifted")
    if run.requested_mode != payload.get("mode"):
        raise ResearchRequestError("Research job requested mode drifted")
    if run.query_budget != payload_budget.max_queries:
        raise ResearchRequestError("Research job query budget drifted")
    if run.page_budget != payload_budget.max_pages:
        raise ResearchRequestError("Research job page budget drifted")
    if run.time_budget_seconds != payload_budget.max_elapsed_seconds:
        raise ResearchRequestError("Research job time budget drifted")
    if evidence_set_hash(snapshots) != payload.get("evidence_set_hash"):
        raise ResearchRequestError("Research job evidence set drifted")
    if resolved_model != payload.get("requested_model"):
        raise ResearchRequestError("Research job requested model drifted")
    if resolved_budget != payload_budget:
        raise ResearchRequestError("Research job budget drifted")


def _validate_result_contract(
    *,
    result: Any,
    profile: AIProviderProfile,
    requested_model: str,
    budget: ResearchBudget,
) -> None:
    if result.provider_profile_id != profile.id:
        raise CitationIntegrityError("research result profile mismatch")
    if result.provider_type != profile.provider_type:
        raise CitationIntegrityError("research result provider type mismatch")
    if result.requested_model != requested_model:
        raise CitationIntegrityError("research result requested model mismatch")
    usage = result.usage
    over_budget = (
        usage.model_calls > budget.max_model_calls
        or usage.input_tokens > budget.max_input_tokens
        or usage.output_tokens > budget.max_output_tokens
        or usage.estimated_cost_usd > budget.max_cost_usd
        or usage.queries > budget.max_queries
        or usage.pages > budget.max_pages
        or usage.fetched_characters > budget.max_total_chars
        or result.elapsed_ms > budget.max_elapsed_seconds * 1_000
    )
    if over_budget:
        raise CitationIntegrityError("research result usage exceeds budget")
    source_characters = sum(len(source.content_text) for source in result.output.sources)
    if usage.pages < len(result.output.sources) or usage.fetched_characters != source_characters:
        raise CitationIntegrityError("research result source usage is inconsistent")


def build_research_story_handler(
    backend_resolver: ResearchBackendResolver,
    *,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def handle(job: WorkflowJob, context: JobContext) -> dict[str, Any]:
        session = context.session
        workflow_job_id = job.id
        payload = dict(job.payload or {})
        try:
            run_id = UUID(str(payload["run_id"]))
            story_id = UUID(str(payload["story_id"]))
            profile_id = UUID(str(payload["provider_profile_id"]))
            budget = ResearchBudget.model_validate(payload["budget"])
        except KeyError, TypeError, ValueError:
            raise PermanentJobError(
                code="research_job_payload_invalid", message="Research job payload is invalid"
            ) from None

        if session.in_transaction():
            await session.rollback()
        active_attempt_id: UUID
        request: ResearchRequest | None = None
        backend: ResearchBackend
        preparation_error: Exception | None = None
        async with session.begin():
            run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
            story = (
                await session.scalar(select(Story).where(Story.id == run.story_id).with_for_update())
                if run is not None
                else None
            )
            profile = await session.get(AIProviderProfile, profile_id)
            if run is None or story is None or profile is None:
                raise PermanentJobError(code="research_context_missing", message="Research context is incomplete")
            if run.status == "succeeded":
                return {
                    "run_id": str(run.id),
                    "story_revision_id": str(run.result_story_revision_id),
                    "idempotent": True,
                }
            snapshots = list(
                await session.scalars(
                    select(StoryEvidenceSnapshot)
                    .where(StoryEvidenceSnapshot.story_id == story.id)
                    .order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id)
                )
            )
            if not snapshots:
                raise PermanentJobError(code="research_evidence_missing", message="Story evidence is unavailable")
            prior_attempts = list(
                await session.scalars(
                    select(ResearchAttempt)
                    .where(ResearchAttempt.research_run_id == run.id)
                    .order_by(ResearchAttempt.attempt_number)
                    .with_for_update()
                )
            )
            for stale in prior_attempts:
                if stale.status == "running":
                    stale.status = "failed"
                    stale.error_class = "retryable"
                    stale.error_code = "stale_research_attempt"
                    stale.error_message = "Research attempt lease was superseded"
                    stale.finished_at = datetime.now(UTC)
            attempt = ResearchAttempt(
                research_run_id=run.id,
                attempt_number=max((item.attempt_number for item in prior_attempts), default=0) + 1,
                queries=[],
                status="running",
                usage={},
                started_at=datetime.now(UTC),
            )
            session.add(attempt)
            run.status = "running"
            run.started_at = run.started_at or datetime.now(UTC)
            await session.flush()
            active_attempt_id = attempt.id
            try:
                resolved_profile = await ResearchService(session).resolve_profile(profile_id, payload["depth"])
                _validate_job_binding(
                    run=run,
                    story_id=story_id,
                    profile_id=profile_id,
                    payload=payload,
                    snapshots=snapshots,
                    resolved_model=resolved_profile.model,
                    resolved_budget=resolved_profile.budget,
                    payload_budget=budget,
                )
                request = ResearchRequest(
                    run_id=run.id,
                    story_id=story.id,
                    provider_profile_id=profile.id,
                    requested_model=resolved_profile.model,
                    mode=payload["mode"],
                    depth=payload["depth"],
                    query_hint=payload.get("query_hint"),
                    evidence=[_evidence(item) for item in snapshots],
                    budget=budget,
                )
            except (KeyError, TypeError, ValueError) as exc:
                preparation_error = exc
        try:
            if preparation_error is not None:
                raise preparation_error
            if request is None:  # pragma: no cover - guarded by preparation validation
                raise ResearchRequestError("Research request preparation failed")
            resolved = backend_resolver(profile)
            backend = await resolved if inspect.isawaitable(resolved) else resolved
            result = await backend.research(request)
            await injector.hit(
                "research.after_provider_before_persist",
                {
                    "workflow_job_id": str(workflow_job_id),
                    "research_run_id": str(run_id),
                    "research_attempt_id": str(active_attempt_id),
                },
            )
            now = datetime.now(UTC)
            if session.in_transaction():
                await session.rollback()
            async with session.begin():
                run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
                story = await session.scalar(select(Story).where(Story.id == story_id).with_for_update())
                attempt = await session.scalar(
                    select(ResearchAttempt).where(ResearchAttempt.id == active_attempt_id).with_for_update()
                )
                attempts = list(
                    await session.scalars(
                        select(ResearchAttempt)
                        .where(ResearchAttempt.research_run_id == run_id)
                        .order_by(ResearchAttempt.attempt_number)
                        .with_for_update()
                    )
                )
                current_attempt = max(attempts, key=lambda item: item.attempt_number, default=None)
                if (
                    run is None
                    or story is None
                    or attempt is None
                    or run.status != "running"
                    or current_attempt is None
                    or current_attempt.id != active_attempt_id
                    or attempt.status != "running"
                ):
                    raise CitationIntegrityError("research run state changed")
                persisted_profile = await session.get(AIProviderProfile, run.provider_profile_id)
                if persisted_profile is None:
                    raise CitationIntegrityError("research profile is unavailable")
                _validate_result_contract(
                    result=result,
                    profile=persisted_profile,
                    requested_model=str(payload["requested_model"]),
                    budget=budget,
                )
                existing = list(
                    await session.scalars(
                        select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.story_id == story.id)
                    )
                )
                evidence_by_key = {item.evidence_key: _evidence(item) for item in existing}
                source_ids: dict[str, UUID] = {}
                discovered_keys: set[str] = set()
                for source in result.output.sources:
                    _validate_source(source)
                    if source.evidence_key in evidence_by_key or source.evidence_key in discovered_keys:
                        raise CitationIntegrityError("duplicate research evidence key")
                    discovered_keys.add(source.evidence_key)
                    research_source = ResearchSource(
                        research_run_id=run.id,
                        url=str(source.url),
                        title=source.title,
                        publisher=source.publisher,
                        published_at=source.published_at,
                        content_sha256=source.content_sha256,
                        extraction_status=source.extraction_status,
                        relevance=0,
                        citation_key=source.evidence_key,
                        snapshot_metadata={"retrieved_at": source.retrieved_at.isoformat()},
                    )
                    session.add(research_source)
                    await session.flush()
                    snapshot = StoryEvidenceSnapshot(
                        story_id=story.id,
                        content_item_id=None,
                        evidence_key=source.evidence_key,
                        source_url=str(source.url),
                        title=source.title,
                        content_text=source.content_text,
                        authors=[],
                        published_at=source.published_at,
                        content_sha256=source.content_sha256,
                        snapshot_metadata={
                            "research_source_id": str(research_source.id),
                            "evidence_key": source.evidence_key,
                            "retrieved_at": source.retrieved_at.isoformat(),
                        },
                    )
                    session.add(snapshot)
                    await session.flush()
                    evidence_by_key[source.evidence_key] = _evidence(snapshot)
                    source_ids[source.evidence_key] = research_source.id
                brief = resolve_candidate_brief(result.output.brief, evidence_by_key, source_ids)
                parent = await session.scalar(
                    select(StoryRevision)
                    .where(StoryRevision.story_id == story.id)
                    .order_by(StoryRevision.revision_number.desc())
                    .limit(1)
                    .with_for_update()
                )
                revision = StoryRevision(
                    story_id=story.id,
                    parent_revision_id=parent.id if parent else None,
                    revision_number=(parent.revision_number + 1) if parent else 1,
                    narrative=brief.summary,
                    facts=[item.model_dump(mode="json") for item in brief.verified_facts],
                    disagreements=[item.model_dump(mode="json") for item in brief.disagreements],
                    angles=brief.suggested_angles,
                    citations=[
                        citation.model_dump(mode="json")
                        for claim in (*brief.verified_facts, *brief.disagreements)
                        for citation in claim.citations
                    ],
                    created_by="research",
                )
                session.add(revision)
                await session.flush()
                for claim_index, claim in enumerate((*brief.verified_facts, *brief.disagreements), start=1):
                    claim_key = f"claim:{claim_index}"
                    linked_snapshot_ids: set[UUID] = set()
                    for citation in claim.citations:
                        if citation.evidence_snapshot_id in linked_snapshot_ids:
                            continue
                        linked_snapshot_ids.add(citation.evidence_snapshot_id)
                        session.add(
                            StoryEvidenceLink(
                                story_revision_id=revision.id,
                                evidence_snapshot_id=citation.evidence_snapshot_id,
                                claim_key=claim_key,
                                relationship="supports",
                            )
                        )
                attempt.status = "succeeded"
                durable_queries = redact_secrets(
                    [event for event in result.sanitized_events if event.get("action") == "search"]
                )
                attempt.queries = durable_queries if isinstance(durable_queries, list) else []
                durable_usage = redact_secrets(result.usage.model_dump(mode="json"))
                attempt.usage = durable_usage if isinstance(durable_usage, dict) else {}
                attempt.finished_at = now
                run.status = "succeeded"
                run.result_story_revision_id = revision.id
                run.finished_at = now
                session.add(
                    WorkflowEvent(
                        workflow_job_id=workflow_job_id,
                        event_type="research.succeeded",
                        actor="automation",
                        event_data=redact_event_data(
                            {
                                "run_id": str(run.id),
                                "story_id": str(story.id),
                                "result_revision_id": str(revision.id),
                                "provider_type": result.provider_type,
                                "resolved_model": result.resolved_model,
                                "backend_events": result.sanitized_events,
                            }
                        ),
                    )
                )
                canonical_job = await session.scalar(
                    select(WorkflowJob).where(WorkflowJob.id == workflow_job_id).with_for_update()
                )
                if canonical_job is None:
                    raise CitationIntegrityError("canonical research job is unavailable")
                continuation_jobs = []
                for descriptor in (canonical_job.payload or {}).get("continuations", []):
                    continuation_jobs.append(
                        (
                            await enqueue_bound_continuation(
                                session,
                                descriptor=descriptor,
                                run=run,
                                result_revision=revision,
                            )
                        ).job
                    )
                await session.flush()
                return {
                    "run_id": str(run.id),
                    "story_revision_id": str(revision.id),
                    "continuation_job_id": (str(continuation_jobs[0].id) if continuation_jobs else None),
                    "continuation_job_ids": [str(item.id) for item in continuation_jobs],
                }
        except Exception as exc:
            if session.in_transaction():
                await session.rollback()
            error_class, code, message = _classification(exc)
            durable_code = redact_string(code)
            durable_message = redact_string(message)
            stale_attempt_ignored = False
            async with session.begin():
                run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
                attempt = await session.scalar(
                    select(ResearchAttempt).where(ResearchAttempt.id == active_attempt_id).with_for_update()
                )
                attempts = list(
                    await session.scalars(
                        select(ResearchAttempt)
                        .where(ResearchAttempt.research_run_id == run_id)
                        .order_by(ResearchAttempt.attempt_number)
                        .with_for_update()
                    )
                )
                latest = max(attempts, key=lambda item: item.attempt_number, default=None)
                owns_current = bool(
                    run is not None
                    and run.status != "succeeded"
                    and attempt is not None
                    and attempt.status == "running"
                    and latest is not None
                    and latest.id == active_attempt_id
                )
                stale_attempt_ignored = not owns_current
                now = datetime.now(UTC)
                if owns_current and run is not None:
                    run.status = "needs_review" if error_class == "needs_review" else "failed"
                    run.finished_at = now
                if owns_current and attempt is not None:
                    attempt.status = "needs_review" if error_class == "needs_review" else "failed"
                    attempt.error_class = error_class
                    attempt.error_code = durable_code
                    attempt.error_message = durable_message
                    attempt.finished_at = now
                canonical_job = await session.scalar(
                    select(WorkflowJob).where(WorkflowJob.id == workflow_job_id).with_for_update()
                )
                if owns_current and canonical_job is not None:
                    for descriptor in (canonical_job.payload or {}).get("continuations", []):
                        try:
                            normalized = normalize_continuation(descriptor)
                            dispatch_id = UUID(normalized["payload"]["dispatch_id"])
                        except TypeError, ValueError:
                            continue
                        dispatch = await session.scalar(
                            select(AutomationDispatch).where(AutomationDispatch.id == dispatch_id).with_for_update()
                        )
                        if dispatch is not None and dispatch.variant_revision_id is None:
                            dispatch.status = "needs_review"
                            dispatch.error_code = durable_code
                            dispatch.error_message = durable_message
                if owns_current:
                    session.add(
                        WorkflowEvent(
                            workflow_job_id=workflow_job_id,
                            event_type="research.failed",
                            actor="automation",
                            event_data=redact_event_data(
                                {
                                    "run_id": str(run_id),
                                    "error_class": error_class,
                                    "error_code": durable_code,
                                }
                            ),
                        )
                    )
                else:
                    existing_stale_event = await session.scalar(
                        select(WorkflowEvent).where(
                            WorkflowEvent.workflow_job_id == workflow_job_id,
                            WorkflowEvent.event_type == "research.stale_attempt_ignored",
                            WorkflowEvent.event_data["attempt_id"].as_string() == str(active_attempt_id),
                        )
                    )
                    if existing_stale_event is None:
                        session.add(
                            WorkflowEvent(
                                workflow_job_id=workflow_job_id,
                                event_type="research.stale_attempt_ignored",
                                actor="automation",
                                event_data=redact_event_data(
                                    {
                                        "run_id": str(run_id),
                                        "attempt_id": str(active_attempt_id),
                                    }
                                ),
                            )
                        )
            if stale_attempt_ignored:
                return {
                    "run_id": str(run_id),
                    "attempt_id": str(active_attempt_id),
                    "stale_attempt_ignored": True,
                }
            if error_class == "retryable":
                raise RetryableJobError(code=code, message=message) from None
            if error_class == "needs_review":
                raise NeedsReviewJobError(code=code, message=message) from None
            raise PermanentJobError(code=code, message=message) from None

    return handle


def _validate_source(source: DiscoveredSourcePayload) -> None:
    digest = hashlib.sha256(source.content_text.encode()).hexdigest()
    expected = build_evidence_key(content_item_id=None, source_url=str(source.url), content_sha256=digest)
    if digest != source.content_sha256 or expected != source.evidence_key:
        raise CitationIntegrityError("research source integrity check failed")


def _validate_continuation(value: Any) -> dict[str, Any]:
    try:
        return normalize_continuation(value)
    except ValueError as exc:
        raise CitationIntegrityError(str(exc)) from None


__all__ = [
    "DefaultResearchBackendResolver",
    "ResearchBackendResolver",
    "build_research_story_handler",
]
