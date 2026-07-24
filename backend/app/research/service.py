from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redaction import redact_secrets, redact_string
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import (
    CodexProviderSettings,
    OpenRouterProviderSettings,
    ResearchBudgetSettings,
    default_research_budgets,
    effective_codex_provider_settings,
)
from app.jobs.capability_gate import api_capability_gate_enabled
from app.jobs.credential_capabilities import CapabilityStatusService, provider_shape_capabilities
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin
from app.research.completeness import CompletenessEvidence, evaluate_completeness
from app.research.continuations import (
    append_unique_continuation,
    continuation_can_reuse_result,
    enqueue_bound_continuation,
    normalize_continuation,
)
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.research.schemas import CompletenessReport, ResearchBudget
from app.stories.models import Story, StoryEvidenceSnapshot, StoryRevision


class ResearchRequestError(ValueError):
    pass


def _redacted_dict(value: object) -> dict:
    redacted = redact_secrets(value)
    return redacted if isinstance(redacted, dict) else {}


def _redacted_optional_text(value: object | None) -> str | None:
    return redact_string(str(value)) if value is not None else None


def _redacted_citation_key(value: object, content_sha256: str | None) -> str:
    text = str(value)
    suffix = f":{content_sha256}" if content_sha256 else ""
    if suffix and text.startswith("url:") and text.endswith(suffix):
        return f"url:{redact_string(text[4 : -len(suffix)])}{suffix}"
    return redact_string(text)


class ResearchDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disposition: Literal["skipped", "complete_without_research", "enqueued"]
    run_id: UUID | None
    job_id: UUID | None
    completeness: CompletenessReport


@dataclass(frozen=True, slots=True)
class ResolvedResearchProfile:
    profile: AIProviderProfile
    model: str
    budget: ResearchBudget


def _budget(value: ResearchBudgetSettings) -> ResearchBudget:
    return ResearchBudget.model_validate(value.model_dump(mode="python"))


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def evidence_set_hash(snapshots: list[StoryEvidenceSnapshot]) -> str:
    return _canonical_hash([(item.evidence_key, item.content_sha256) for item in snapshots])


class ResearchService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _story_evidence(self, story_id: UUID) -> list[StoryEvidenceSnapshot]:
        return list(
            await self.session.scalars(
                select(StoryEvidenceSnapshot)
                .where(StoryEvidenceSnapshot.story_id == story_id)
                .order_by(StoryEvidenceSnapshot.captured_at, StoryEvidenceSnapshot.id)
            )
        )

    @staticmethod
    def _completeness(snapshots: list[StoryEvidenceSnapshot]) -> CompletenessReport:
        return evaluate_completeness(
            [
                CompletenessEvidence(
                    evidence_key=item.evidence_key,
                    content_text=item.content_text,
                    source_url=item.source_url,
                    source_identity=(item.snapshot_metadata or {}).get("source_label"),
                    is_primary=bool((item.snapshot_metadata or {}).get("is_primary")),
                )
                for item in snapshots
            ]
        )

    async def resolve_profile(self, profile_id: UUID, depth: Literal["standard", "deep"]) -> ResolvedResearchProfile:
        profile = await self.session.get(AIProviderProfile, profile_id)
        if profile is None or not profile.enabled:
            raise ResearchRequestError("Selected research provider profile is unavailable")
        from app.llm_providers.models import LLMProvider
        from app.llm_providers.schemas import LLMProviderSettings

        generic = (
            await self.session.get(LLMProvider, profile_id)
            if isinstance(self.session, AsyncSession)
            else None
        )
        if generic is not None:
            if not generic.enabled or generic.research_capability != "ready":
                raise ResearchRequestError("Selected research provider profile is unavailable")
            if generic.protocol == "fake":
                selected = getattr(default_research_budgets(), depth)
            elif generic.protocol == "openai_compatible":
                try:
                    configured_generic = LLMProviderSettings.model_validate(generic.settings)
                except ValueError:
                    raise ResearchRequestError("Selected research provider profile is invalid") from None
                selected = getattr(configured_generic.research_budgets, depth)
            else:  # pragma: no cover - database constraint
                raise ResearchRequestError("Selected research provider profile is unsupported")
            return ResolvedResearchProfile(profile=profile, model=generic.default_model, budget=_budget(selected))
        shaped, _codes = provider_shape_capabilities(profile)
        if not shaped["research"]:
            raise ResearchRequestError("Selected research provider profile is invalid")
        model = profile.default_model
        if profile.provider_type == "fake":
            if profile.secret_ref is not None or dict(profile.settings or {}):
                raise ResearchRequestError("Selected research provider profile is invalid")
            model = model or "fake-v1"
            selected = getattr(default_research_budgets(), depth)
        elif profile.provider_type == "codex":
            if profile.secret_ref is not None or not model:
                raise ResearchRequestError("Selected research provider profile is invalid")
            try:
                configured = effective_codex_provider_settings(
                    CodexProviderSettings.model_validate(dict(profile.settings or {}))
                )
            except ValueError:
                raise ResearchRequestError("Selected research provider profile is invalid") from None
            assert configured.research_budgets is not None
            selected = getattr(configured.research_budgets, depth)
        elif profile.provider_type == "openrouter":
            if not profile.secret_ref or not model:
                raise ResearchRequestError("Selected research provider profile is invalid")
            try:
                configured_or = OpenRouterProviderSettings.model_validate(dict(profile.settings or {}))
            except ValueError:
                raise ResearchRequestError("Selected research provider profile is invalid") from None
            if configured_or.pricing is None or configured_or.research_budgets is None:
                raise ResearchRequestError("Selected research provider profile is unavailable")
            selected = getattr(configured_or.research_budgets, depth)
        else:
            raise ResearchRequestError("Selected research provider profile is unsupported")
        return ResolvedResearchProfile(profile=profile, model=model, budget=_budget(selected))

    async def request(
        self,
        *,
        story_id: UUID,
        mode: Literal["off", "manual", "auto_if_incomplete"],
        depth: Literal["standard", "deep"],
        provider_profile_id: UUID | None,
        query_hint: str | None,
        continuation: dict | None = None,
    ) -> ResearchDisposition:
        story = await self.session.scalar(select(Story).where(Story.id == story_id).with_for_update())
        if story is None or story.superseded_by_id is not None:
            raise ResearchRequestError("Active story was not found")
        snapshots = await self._story_evidence(story_id)
        completeness = self._completeness(snapshots)
        if mode == "off":
            if provider_profile_id is not None:
                raise ResearchRequestError("Off research mode cannot select a provider profile")
            return ResearchDisposition(disposition="skipped", run_id=None, job_id=None, completeness=completeness)
        if provider_profile_id is None:
            raise ResearchRequestError("Research provider profile is required")
        resolved = await self.resolve_profile(provider_profile_id, depth)
        if mode == "auto_if_incomplete" and completeness.complete:
            if continuation is not None:
                succeeded_run = await self.session.scalar(
                    select(ResearchRun)
                    .where(
                        ResearchRun.story_id == story.id,
                        ResearchRun.provider_profile_id == resolved.profile.id,
                        ResearchRun.requested_mode == mode,
                        ResearchRun.status == "succeeded",
                        ResearchRun.result_story_revision_id.is_not(None),
                    )
                    .order_by(ResearchRun.finished_at.desc(), ResearchRun.id.desc())
                    .limit(1)
                    .with_for_update()
                )
                if succeeded_run is not None:
                    canonical_job = await self.session.scalar(
                        select(WorkflowJob)
                        .where(WorkflowJob.payload["run_id"].as_string() == str(succeeded_run.id))
                        .with_for_update()
                    )
                    canonical_payload = dict(canonical_job.payload or {}) if canonical_job else {}
                    if (
                        canonical_job is not None
                        and canonical_payload.get("requested_model") == resolved.model
                        and canonical_payload.get("depth") == depth
                    ):
                        result_revision = await self.session.get(StoryRevision, succeeded_run.result_story_revision_id)
                        if result_revision is None:
                            raise ResearchRequestError("Research result revision is unavailable")
                        normalized_continuation = normalize_continuation(continuation)
                        if not await continuation_can_reuse_result(
                            self.session,
                            descriptor=normalized_continuation,
                            run=succeeded_run,
                            result_revision=result_revision,
                        ):
                            return ResearchDisposition(
                                disposition="complete_without_research",
                                run_id=None,
                                job_id=None,
                                completeness=completeness,
                            )
                        updated_payload, subscriber_added = append_unique_continuation(
                            canonical_payload, normalized_continuation
                        )
                        canonical_job.payload = updated_payload
                        if subscriber_added:
                            descriptor_identity = normalized_continuation["subscriber_id"]
                            descriptor = next(
                                item
                                for item in updated_payload["continuations"]
                                if item["subscriber_id"] == descriptor_identity
                            )
                            await enqueue_bound_continuation(
                                self.session,
                                descriptor=descriptor,
                                run=succeeded_run,
                                result_revision=result_revision,
                            )
                        return ResearchDisposition(
                            disposition="enqueued",
                            run_id=succeeded_run.id,
                            job_id=canonical_job.id,
                            completeness=completeness,
                        )
            return ResearchDisposition(
                disposition="complete_without_research",
                run_id=None,
                job_id=None,
                completeness=completeness,
            )
        if api_capability_gate_enabled(self.session):
            await CapabilityStatusService(self.session).require_available(
                "provider",
                resolved.profile.id,
                "research",
                job_type="research_story",
            )
        if not snapshots:
            raise ResearchRequestError("Story has no persisted evidence")
        evidence_hash = evidence_set_hash(snapshots)
        run = ResearchRun(
            story_id=story.id,
            requested_mode=mode,
            provider_profile_id=resolved.profile.id,
            status="queued",
            query_budget=resolved.budget.max_queries,
            page_budget=resolved.budget.max_pages,
            time_budget_seconds=resolved.budget.max_elapsed_seconds,
        )
        self.session.add(run)
        await self.session.flush()
        payload, _subscriber_added = append_unique_continuation(
            {
                "run_id": str(run.id),
                "story_id": str(story.id),
                "provider_profile_id": str(resolved.profile.id),
                "requested_model": resolved.model,
                "mode": mode,
                "depth": depth,
                "query_hint": query_hint,
                "evidence_set_hash": evidence_hash,
                "completeness": completeness.model_dump(mode="json"),
                "budget": resolved.budget.model_dump(mode="json"),
            },
            continuation,
        )
        key = f"research_story:{story.id}:{evidence_hash}:{resolved.profile.id}:{resolved.model}:{mode}:{depth}"
        accepted = await JobRepository(self.session).enqueue_job(
            job_type="research_story",
            payload=payload,
            idempotency_key=key,
            origin=JobOrigin.MANUAL if mode == "manual" else JobOrigin.AUTOMATION,
        )
        if not accepted.created:
            canonical_job = await self.session.scalar(
                select(WorkflowJob).where(WorkflowJob.id == accepted.job.id).with_for_update()
            )
            if canonical_job is None:
                raise ResearchRequestError("Canonical research job is unavailable")
            updated_payload, subscriber_added = append_unique_continuation(
                dict(canonical_job.payload or {}), continuation
            )
            canonical_job.payload = updated_payload
            existing_run_id = updated_payload.get("run_id")
            await self.session.delete(run)
            run_id = UUID(existing_run_id) if existing_run_id else None
            existing_run = await self.session.get(ResearchRun, run_id) if run_id else None
            if (
                subscriber_added
                and existing_run is not None
                and existing_run.status == "succeeded"
                and existing_run.result_story_revision_id is not None
            ):
                result_revision = await self.session.get(StoryRevision, existing_run.result_story_revision_id)
                if result_revision is None:
                    raise ResearchRequestError("Research result revision is unavailable")
                descriptor = next(
                    item
                    for item in updated_payload["continuations"]
                    if item["subscriber_id"] == normalize_continuation(continuation)["subscriber_id"]
                )
                await enqueue_bound_continuation(
                    self.session,
                    descriptor=descriptor,
                    run=existing_run,
                    result_revision=result_revision,
                )
        else:
            run_id = run.id
        return ResearchDisposition(
            disposition="enqueued",
            run_id=run_id,
            job_id=accepted.job.id,
            completeness=completeness,
        )

    async def get_run(self, run_id: UUID) -> dict:
        run = await self.session.get(ResearchRun, run_id)
        if run is None:
            raise ResearchRequestError("Research run was not found")
        profile = await self.session.get(AIProviderProfile, run.provider_profile_id)
        attempts = list(
            await self.session.scalars(
                select(ResearchAttempt)
                .where(ResearchAttempt.research_run_id == run.id)
                .order_by(ResearchAttempt.attempt_number)
            )
        )
        sources = list(
            await self.session.scalars(
                select(ResearchSource)
                .where(ResearchSource.research_run_id == run.id)
                .order_by(ResearchSource.created_at, ResearchSource.id)
            )
        )
        job = await self.session.scalar(
            select(WorkflowJob).where(WorkflowJob.payload["run_id"].as_string() == str(run.id))
        )
        events = (
            list(
                await self.session.scalars(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.workflow_job_id == job.id)
                    .order_by(WorkflowEvent.created_at, WorkflowEvent.id)
                )
            )
            if job
            else []
        )
        succeeded_event = next(
            (item for item in reversed(events) if item.event_type == "research.succeeded"),
            None,
        )
        job_payload = _redacted_dict(job.payload) if job else {}
        return {
            "id": run.id,
            "story_id": run.story_id,
            "requested_mode": run.requested_mode,
            "status": run.status,
            "provider": {
                "id": profile.id,
                "name": redact_string(str(profile.name)),
                "provider_type": redact_string(str(profile.provider_type)),
            }
            if profile
            else None,
            "budget": {
                "max_queries": run.query_budget,
                "max_pages": run.page_budget,
                "max_elapsed_seconds": run.time_budget_seconds,
                **(job_payload.get("budget", {}) if isinstance(job_payload.get("budget"), dict) else {}),
            },
            "requested_model": _redacted_optional_text(job_payload.get("requested_model") if job else None),
            "resolved_model": (
                _redacted_optional_text((succeeded_event.event_data or {}).get("resolved_model"))
                if succeeded_event
                else None
            ),
            "evidence_set_hash": job_payload.get("evidence_set_hash") if job else None,
            "completeness": job_payload.get("completeness") if job else None,
            "attempts": [
                {
                    "id": item.id,
                    "attempt_number": item.attempt_number,
                    "status": item.status,
                    "usage": _redacted_dict(item.usage),
                    "error_class": _redacted_optional_text(item.error_class),
                    "error_code": _redacted_optional_text(item.error_code),
                    "error_message": _redacted_optional_text(item.error_message),
                }
                for item in attempts
            ],
            "sources": [
                {
                    "id": item.id,
                    "url": redact_string(str(item.url)),
                    "title": _redacted_optional_text(item.title),
                    "publisher": _redacted_optional_text(item.publisher),
                    "published_at": item.published_at,
                    "content_sha256": item.content_sha256,
                    "citation_key": _redacted_citation_key(
                        item.citation_key,
                        item.content_sha256,
                    ),
                    "extraction_status": redact_string(str(item.extraction_status)),
                }
                for item in sources
            ],
            "events": [
                {
                    "id": item.id,
                    "event_type": redact_string(str(item.event_type)),
                    "actor": redact_string(str(item.actor)),
                    "event_data": _redacted_dict(item.event_data),
                    "created_at": item.created_at,
                }
                for item in events
            ],
            "result_revision_id": run.result_story_revision_id,
            "job_status": job.status if job else None,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

    async def list_runs(self, story_id: UUID) -> list[dict]:
        ids = list(
            await self.session.scalars(
                select(ResearchRun.id)
                .where(ResearchRun.story_id == story_id)
                .order_by(ResearchRun.created_at.desc(), ResearchRun.id.desc())
            )
        )
        return [await self.get_run(run_id) for run_id in ids]


__all__ = [
    "ResearchDisposition",
    "ResearchRequestError",
    "ResearchService",
    "evidence_set_hash",
]
