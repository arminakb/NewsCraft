from __future__ import annotations

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
from app.generation.models import AIProviderProfile, PromptTemplateVersion
from app.jobs.errors import NeedsReviewJobError, PermanentJobError, RetryableJobError
from app.jobs.events import redact_event_data
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler
from app.jobs.types import JobExecution, job_payload_copy
from app.research.base import ResearchBackend, ResearchBudgetExceeded, ResearchRequest, ResearchResult, budget_exceeded
from app.research.citations import CitationIntegrityError, resolve_candidate_brief
from app.research.continuations import (
    enqueue_bound_continuation,
    normalize_continuation,
)
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.research.schemas import (
    DiscoveredSourcePayload,
    ResearchBrief,
    ResearchBudget,
    describe_source_integrity_violation,
)
from app.research.service import ResearchRequestError, ResearchService, evidence_set_hash
from app.stories.evidence import EvidenceRecord, evidence_record_from_snapshot
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision
from app.workflows.states import ResearchRunState, require_research_run_transition

type ResearchBackendResolver = Callable[[AIProviderProfile], ResearchBackend | Awaitable[ResearchBackend]]


class DefaultResearchBackendResolver:
    """Build DB-free research adapters from the already configured generation resolver."""

    def __init__(self, profile_resolver: Any) -> None:
        self.profile_resolver = profile_resolver

    async def __call__(self, profile: AIProviderProfile) -> ResearchBackend:
        from app.research.codex_adapter import CodexResearchBackend
        from app.research.duckduckgo import DuckDuckGoSearchClient
        from app.research.fake import EvidenceGroundedFakeResearchBackend
        from app.research.openrouter_loop import OpenRouterResearchBackend
        from app.research.safe_fetch import SafeArticleFetcher

        if profile.provider_type == "fake":
            return EvidenceGroundedFakeResearchBackend()
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

    async def resolve_with_session(self, profile: AIProviderProfile, *, session: Any) -> ResearchBackend:
        from app.llm_providers.models import LLMProvider
        from app.research.duckduckgo import DuckDuckGoSearchClient
        from app.research.fake import EvidenceGroundedFakeResearchBackend
        from app.research.openrouter_loop import OpenRouterResearchBackend
        from app.research.safe_fetch import SafeArticleFetcher

        generic = await session.get(LLMProvider, profile.id)
        if generic is None:
            return await self(profile)
        if generic.protocol == "fake":
            return EvidenceGroundedFakeResearchBackend()
        if generic.protocol != "openai_compatible":
            raise ValueError("Research provider profile is unsupported")
        resolved = await self.profile_resolver.resolve_with_session(profile, None, session=session)
        return OpenRouterResearchBackend(
            model=resolved.provider,
            search_client=DuckDuckGoSearchClient(),
            fetcher=SafeArticleFetcher(),
            profile=profile,
        )


def budget_termination_metadata(
    budget: ResearchBudget,
    usage: Any,
    elapsed_ms: int,
) -> dict[str, object]:
    """Describe why research stopped and what the budgets actually bought.

    A dimension at its limit is reported as the termination reason so the
    operator can tell "answered" from "ran out of queries/pages/time".
    """

    dimensions: dict[str, tuple[int, int]] = {
        "query_budget": (int(usage.queries), budget.max_queries),
        "page_budget": (int(usage.pages), budget.max_pages),
        "time_budget": (int(elapsed_ms), budget.max_elapsed_seconds * 1_000),
        "model_call_budget": (int(usage.model_calls), budget.max_model_calls),
        "output_token_budget": (int(usage.output_tokens), budget.max_output_tokens),
    }
    exhausted = [name for name, (used, limit) in dimensions.items() if used >= limit]
    return {
        "termination_reason": ("budget_exhausted:" + ",".join(sorted(exhausted))) if exhausted else "completed",
        "queries_executed": usage.queries,
        "pages_inspected": usage.pages,
        "elapsed_ms": elapsed_ms,
    }


async def _resolve_payload_system_prompt(session: Any, payload: dict[str, Any]) -> str | None:
    """Resolve the pinned research system prompt at the runtime boundary.

    Mirrors generation prompt integrity: the referenced version must still be
    the active row and its checksum must match the saved snapshot. The system
    prompt is configuration; runtime article input stays separate.
    """

    raw_id = payload.get("prompt_template_version_id")
    if raw_id is None:
        return None
    checksum = payload.get("prompt_checksum_sha256")
    if not isinstance(checksum, str):
        raise PermanentJobError(
            code="research_prompt_reference_invalid",
            message="Research job references a system prompt without a checksum",
        )
    version = await session.get(PromptTemplateVersion, UUID(str(raw_id)))
    if version is None or not version.is_active:
        raise PermanentJobError(
            code="research_prompt_unavailable",
            message="Selected research system prompt is no longer active",
        )
    if version.checksum_sha256 != checksum:
        raise PermanentJobError(
            code="research_prompt_checksum_mismatch",
            message="Research prompt checksum does not match the saved version",
        )
    return version.system_template


def _evidence(snapshot: StoryEvidenceSnapshot) -> EvidenceRecord:
    return evidence_record_from_snapshot(snapshot)


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
    if budget_exceeded(budget, usage, result.elapsed_ms):
        raise CitationIntegrityError("research result usage exceeds budget")
    source_characters = sum(len(source.content_text) for source in result.output.sources)
    if usage.pages < len(result.output.sources) or usage.fetched_characters != source_characters:
        raise CitationIntegrityError("research result source usage is inconsistent")


class ResearchStoryHandler:
    def __init__(
        self,
        backend_resolver: ResearchBackendResolver,
        *,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.backend_resolver = backend_resolver
        self.injector = fault_injector if fault_injector is not None else NoopFaultInjector()

    async def _invoke_backend(
        self,
        profile: AIProviderProfile,
        session: Any,
        request: ResearchRequest,
    ) -> ResearchResult:
        resolve_with_session = getattr(self.backend_resolver, "resolve_with_session", None)
        resolved = (
            resolve_with_session(profile, session=session)
            if resolve_with_session is not None
            else self.backend_resolver(profile)
        )
        backend = await resolved if inspect.isawaitable(resolved) else resolved
        return await backend.research(request)

    @staticmethod
    async def _materialize_sources(
        session: Any,
        *,
        run: ResearchRun,
        story: Story,
        sources: list[DiscoveredSourcePayload],
        evidence_by_key: dict[str, EvidenceRecord],
    ) -> dict[str, UUID]:
        source_ids: dict[str, UUID] = {}
        discovered_keys: set[str] = set()
        for source in sources:
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
        return source_ids

    @staticmethod
    def _resolve_brief(
        result: ResearchResult,
        evidence_by_key: dict[str, EvidenceRecord],
        source_ids: dict[str, UUID],
    ) -> ResearchBrief:
        return resolve_candidate_brief(result.output.brief, evidence_by_key, source_ids)

    @staticmethod
    async def _fan_out_continuations(
        session: Any,
        *,
        workflow_job_id: UUID,
        run: ResearchRun,
        revision: StoryRevision,
    ) -> list[WorkflowJob]:
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
        return continuation_jobs

    @staticmethod
    async def _record_failure(
        session: Any,
        *,
        run_id: UUID,
        active_attempt_id: UUID,
        workflow_job_id: UUID,
        error_class: str,
        code: str,
        message: str,
    ) -> bool:
        durable_code = redact_string(code)
        durable_message = redact_string(message)
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
            now = datetime.now(UTC)
            if owns_current and run is not None:
                target_status: ResearchRunState = "needs_review" if error_class == "needs_review" else "failed"
                run.status = require_research_run_transition(run.status, target_status)
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
        return not owns_current

    async def __call__(self, job: JobExecution, context: JobContext) -> dict[str, Any]:
        session = context.session
        workflow_job_id = job.id
        payload = job_payload_copy(job)
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
            new_attempt = ResearchAttempt(
                research_run_id=run.id,
                attempt_number=max((item.attempt_number for item in prior_attempts), default=0) + 1,
                queries=[],
                status="running",
                usage={},
                started_at=datetime.now(UTC),
            )
            session.add(new_attempt)
            run.status = require_research_run_transition(run.status, "running")
            run.started_at = run.started_at or datetime.now(UTC)
            await session.flush()
            active_attempt_id = new_attempt.id
            try:
                resolved_profile = await ResearchService(session).resolve_profile(profile_id, payload["depth"])
                budget_overrides = payload.get("budget_overrides") or {}
                effective_resolved_budget = (
                    resolved_profile.budget.model_copy(update=budget_overrides)
                    if budget_overrides
                    else resolved_profile.budget
                )
                _validate_job_binding(
                    run=run,
                    story_id=story_id,
                    profile_id=profile_id,
                    payload=payload,
                    snapshots=snapshots,
                    resolved_model=resolved_profile.model,
                    resolved_budget=effective_resolved_budget,
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
                    system_prompt=await _resolve_payload_system_prompt(session, payload),
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
            result = await self._invoke_backend(profile, session, request)
            await self.injector.hit(
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
                source_ids = await self._materialize_sources(
                    session,
                    run=run,
                    story=story,
                    sources=result.output.sources,
                    evidence_by_key=evidence_by_key,
                )
                brief = self._resolve_brief(result, evidence_by_key, source_ids)
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
                run.status = require_research_run_transition(run.status, "succeeded")
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
                continuation_jobs = await self._fan_out_continuations(
                    session,
                    workflow_job_id=workflow_job_id,
                    run=run,
                    revision=revision,
                )
                await session.flush()
                return {
                    "run_id": str(run.id),
                    "story_revision_id": str(revision.id),
                    "continuation_job_id": (str(continuation_jobs[0].id) if continuation_jobs else None),
                    "continuation_job_ids": [str(item.id) for item in continuation_jobs],
                    "budget_termination": budget_termination_metadata(budget, result.usage, result.elapsed_ms),
                }
        except Exception as exc:
            if session.in_transaction():
                await session.rollback()
            error_class, code, message = _classification(exc)
            stale_attempt_ignored = await self._record_failure(
                session,
                run_id=run_id,
                active_attempt_id=active_attempt_id,
                workflow_job_id=workflow_job_id,
                error_class=error_class,
                code=code,
                message=message,
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



def build_research_story_handler(
    backend_resolver: ResearchBackendResolver,
    *,
    fault_injector: FaultInjector | None = None,
) -> JobHandler:
    return ResearchStoryHandler(backend_resolver, fault_injector=fault_injector)


def _validate_source(source: DiscoveredSourcePayload) -> None:
    """Re-assert discovered-source integrity at the persistence boundary.

    The payload model already enforces this on construction; this keeps the
    guarantee for instances that bypass validation (``model_construct``) and
    translates it into the job-side citation error.
    """

    violation = describe_source_integrity_violation(
        url=str(source.url),
        content_text=source.content_text,
        content_sha256=source.content_sha256,
        evidence_key=source.evidence_key,
    )
    if violation is not None:
        raise CitationIntegrityError("research source integrity check failed")


__all__ = [
    "DefaultResearchBackendResolver",
    "ResearchBackendResolver",
    "build_research_story_handler",
]
