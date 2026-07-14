from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.automations.models import AutomationDispatch, AutomationRoute
from app.core.faults import InjectedFault, ScriptedFaultInjector
from app.generation.models import AIProviderProfile
from app.generation.provider_settings import default_research_budgets
from app.jobs.errors import NeedsReviewJobError
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext
from app.research.base import ResearchBackendOutput, ResearchRequest, ResearchResult, ResearchUsage
from app.research.continuations import append_unique_continuation, enqueue_bound_continuation
from app.research.fake import FakeResearchBackend
from app.research.handlers import (
    DefaultResearchBackendResolver,
    _validate_continuation,
    _validate_job_binding,
    _validate_source,
    build_research_story_handler,
)
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.research.schemas import (
    CandidateCitation,
    CandidateClaim,
    CandidateResearchBrief,
    DiscoveredSourcePayload,
    ResearchBudget,
)
from app.research.service import ResearchRequestError, evidence_set_hash
from app.stories.evidence import EvidenceRecord
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision


def test_handler_recomputes_source_hash_and_key():
    text = "Fetched evidence with exact cited phrase."
    digest = sha256(text.encode()).hexdigest()
    source = DiscoveredSourcePayload.model_validate(
        {
            "evidence_key": f"url:https://news.example/report:{digest}",
            "url": "https://news.example/report",
            "title": "Report",
            "publisher": "News",
            "published_at": None,
            "retrieved_at": datetime.now(UTC),
            "content_text": text,
            "content_sha256": digest,
            "extraction_status": "ok",
        }
    )
    _validate_source(source)


def test_continuation_is_constrained_to_telegram_process():
    with pytest.raises(ValueError, match="type"):
        _validate_continuation(
            {
                "job_type": "telegram.publish",
                "payload": {},
                "idempotency_prefix": "telegram-route-process-after-research:x",
            }
        )


async def test_default_fake_backend_resolution_is_db_and_network_free():
    resolver = DefaultResearchBackendResolver(SimpleNamespace())
    profile_id = uuid4()
    backend = await resolver(SimpleNamespace(id=profile_id, provider_type="fake", settings={}, secret_ref=None))
    assert isinstance(backend, FakeResearchBackend)

    content = "The operator evidence confirms the deterministic acceptance release."
    digest = sha256(content.encode()).hexdigest()
    evidence = EvidenceRecord(
        evidence_key=f"operator-text:{digest}",
        evidence_snapshot_id=uuid4(),
        content_item_id=None,
        title="Acceptance release",
        content_text=content,
        content_sha256=digest,
        source_url=None,
        authors=(),
        published_at=None,
        captured_at=datetime.now(UTC),
    )
    empty_evidence = EvidenceRecord(
        evidence_key=f"operator-text:{sha256(b'').hexdigest()}",
        evidence_snapshot_id=uuid4(),
        content_item_id=None,
        title="Media-only evidence",
        content_text="",
        content_sha256=sha256(b"").hexdigest(),
        source_url=None,
        authors=(),
        published_at=None,
        captured_at=datetime.now(UTC),
    )
    result = await backend.research(
        ResearchRequest(
            run_id=uuid4(),
            story_id=uuid4(),
            provider_profile_id=profile_id,
            requested_model="fake-v1",
            mode="manual",
            evidence=[empty_evidence, evidence],
            budget=ResearchBudget(),
        )
    )

    assert result.output.sources == []
    assert result.output.brief.discovered_evidence_keys == []
    claim = result.output.brief.verified_facts[0]
    assert claim.citations[0].evidence_key == evidence.evidence_key
    assert claim.citations[0].locator == f"chars:0-{len(content)}"
    assert claim.citations[0].excerpt_sha256 == digest


async def test_default_fake_backend_reports_all_empty_evidence_without_invalid_citation():
    resolver = DefaultResearchBackendResolver(SimpleNamespace())
    profile_id = uuid4()
    backend = await resolver(
        SimpleNamespace(id=profile_id, provider_type="fake", settings={}, secret_ref=None)
    )
    digest = sha256(b"").hexdigest()
    result = await backend.research(
        ResearchRequest(
            run_id=uuid4(),
            story_id=uuid4(),
            provider_profile_id=profile_id,
            requested_model="fake-v1",
            mode="manual",
            evidence=[
                EvidenceRecord(
                    evidence_key=f"operator-text:{digest}",
                    evidence_snapshot_id=uuid4(),
                    content_item_id=None,
                    title="Media-only evidence",
                    content_text="",
                    content_sha256=digest,
                    source_url=None,
                    authors=(),
                    published_at=None,
                    captured_at=datetime.now(UTC),
                )
            ],
            budget=ResearchBudget(),
        )
    )

    assert result.output.brief.verified_facts == []
    assert result.output.brief.disagreements == []
    assert result.output.brief.missing_information == [
        "The supplied evidence contains no textual content to cite."
    ]


def _binding_values():
    story_id = uuid4()
    profile_id = uuid4()
    snapshot = StoryEvidenceSnapshot(
        id=uuid4(),
        story_id=story_id,
        content_item_id=None,
        evidence_key="operator-text:" + "1" * 64,
        source_url=None,
        title="Evidence",
        content_text="evidence",
        authors=[],
        published_at=None,
        content_sha256="1" * 64,
        snapshot_metadata={},
        captured_at=datetime.now(UTC),
    )
    run = ResearchRun(
        id=uuid4(),
        story_id=story_id,
        requested_mode="manual",
        provider_profile_id=profile_id,
        status="queued",
        query_budget=4,
        page_budget=8,
        time_budget_seconds=120,
    )
    budget = ResearchBudget()
    payload = {
        "mode": "manual",
        "requested_model": "fake-v1",
        "evidence_set_hash": evidence_set_hash([snapshot]),
    }
    return run, snapshot, profile_id, budget, payload


@pytest.mark.parametrize(
    "drift",
    ["profile", "mode", "evidence", "query", "page", "time", "model", "full_budget"],
)
def test_locked_run_and_evidence_reject_mutable_job_payload_drift(drift):
    run, snapshot, profile_id, budget, payload = _binding_values()
    resolved_budget = budget
    if drift == "profile":
        profile_id = uuid4()
    elif drift == "mode":
        payload["mode"] = "auto_if_incomplete"
    elif drift == "evidence":
        payload["evidence_set_hash"] = "0" * 64
    elif drift == "query":
        run.query_budget += 1
    elif drift == "page":
        run.page_budget += 1
    elif drift == "time":
        run.time_budget_seconds += 1
    elif drift == "model":
        payload["requested_model"] = "fake-v2"
    else:
        budget = budget.model_copy(update={"max_output_tokens": budget.max_output_tokens + 1})
    with pytest.raises(ResearchRequestError, match="drifted"):
        _validate_job_binding(
            run=run,
            story_id=run.story_id,
            profile_id=profile_id,
            payload=payload,
            snapshots=[snapshot],
            resolved_model="fake-v1",
            resolved_budget=resolved_budget,
            payload_budget=budget,
        )


class _Transaction:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        self.session.transaction = True
        self.snapshot = deepcopy(self.session.values)

    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.session.values = self.snapshot
        self.session.transaction = False


class TransactionalSession:
    def __init__(self, values):
        self.values = list(values)
        self.transaction = False

    def in_transaction(self):
        return self.transaction

    async def rollback(self):
        self.transaction = False

    def begin(self):
        return _Transaction(self)

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        values = [value for value in self.values if isinstance(value, entity)]
        identifiers = [
            getattr(getattr(criterion, "right", None), "value", None)
            for criterion in getattr(statement, "_where_criteria", ())
            if getattr(getattr(criterion, "left", None), "name", None) == "id"
        ]
        identifier = next((value for value in identifiers if isinstance(value, UUID)), None)
        if identifier is not None:
            matched = [value for value in values if getattr(value, "id", None) == identifier]
            values = matched
        if entity is StoryRevision:
            return max(values, key=lambda value: value.revision_number, default=None)
        return values[0] if values else None

    async def scalars(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return [value for value in self.values if isinstance(value, entity)]

    async def get(self, model, identifier):
        return next(
            (value for value in self.values if isinstance(value, model) and value.id == identifier),
            None,
        )

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.values.append(value)

    async def flush(self):
        return None

    async def delete(self, value):
        self.values.remove(value)


class ObservingBackend:
    name = "fake"

    def __init__(self, session, output):
        self.session = session
        self.output = output
        self.calls = 0
        self.saw_running_attempt = False

    async def research(self, request):
        self.calls += 1
        assert self.session.in_transaction() is False
        self.saw_running_attempt = any(
            isinstance(value, ResearchAttempt) and value.status == "running" for value in self.session.values
        )
        return ResearchResult(
            provider_profile_id=request.provider_profile_id,
            provider_type="fake",
            requested_model=request.requested_model,
            resolved_model=request.requested_model,
            output=self.output,
            usage=ResearchUsage(
                model_calls=1,
                input_tokens=0,
                output_tokens=0,
                estimated_cost_usd=0,
                queries=0,
                pages=len(self.output.sources),
                fetched_characters=sum(len(source.content_text) for source in self.output.sources),
            ),
            elapsed_ms=0,
            sanitized_events=[],
        )


class InvalidResultBackend(ObservingBackend):
    def __init__(self, session, output, mutation):
        super().__init__(session, output)
        self.mutation = mutation

    async def research(self, request):
        result = await super().research(request)
        field, value = self.mutation
        if field in ResearchUsage.model_fields:
            return result.model_copy(update={"usage": result.usage.model_copy(update={field: value})})
        return result.model_copy(update={field: value})


def _lifecycle_fixture(*, unknown_key=False):
    now = datetime.now(UTC)
    story = Story(
        id=uuid4(),
        title="Story",
        status="inbox",
        primary_language="en",
        superseded_by_id=None,
        created_at=now,
        updated_at=now,
    )
    original_text = "Original persisted evidence."
    original_digest = sha256(original_text.encode()).hexdigest()
    original = StoryEvidenceSnapshot(
        id=uuid4(),
        story_id=story.id,
        content_item_id=None,
        evidence_key=f"operator-text:{original_digest}",
        source_url=None,
        title="Original",
        content_text=original_text,
        authors=[],
        published_at=None,
        content_sha256=original_digest,
        snapshot_metadata={},
        captured_at=now,
    )
    profile = AIProviderProfile(
        id=uuid4(),
        name="Fake",
        provider_type="fake",
        default_model="fake-v1",
        secret_ref=None,
        settings={},
        enabled=True,
    )
    budget = ResearchBudget.model_validate(default_research_budgets().standard.model_dump(mode="python"))
    run = ResearchRun(
        id=uuid4(),
        story_id=story.id,
        requested_mode="manual",
        provider_profile_id=profile.id,
        status="queued",
        query_budget=budget.max_queries,
        page_budget=budget.max_pages,
        time_budget_seconds=budget.max_elapsed_seconds,
        created_at=now,
    )
    source_text = "Fetched evidence with exact cited phrase."
    source_digest = sha256(source_text.encode()).hexdigest()
    source_key = f"url:https://news.example/report:{source_digest}"
    source = DiscoveredSourcePayload.model_validate(
        {
            "evidence_key": source_key,
            "url": "https://news.example/report",
            "title": "Report",
            "publisher": "News",
            "published_at": None,
            "retrieved_at": now,
            "content_text": source_text,
            "content_sha256": source_digest,
            "extraction_status": "ok",
        }
    )
    cited_key = "unknown:key" if unknown_key else source_key
    brief = CandidateResearchBrief(
        summary="Verified research summary",
        verified_facts=[
            CandidateClaim(
                text="Fetched",
                citations=[
                    CandidateCitation(
                        evidence_key=cited_key,
                        locator="chars:0-7",
                        excerpt_sha256=sha256(source_text[:7].encode()).hexdigest(),
                    )
                ],
            )
        ],
        disagreements=[],
        missing_information=[],
        suggested_angles=[],
        discovered_evidence_keys=[source_key],
    )
    output = ResearchBackendOutput(sources=[source], brief=brief)
    payload = {
        "run_id": str(run.id),
        "story_id": str(story.id),
        "provider_profile_id": str(profile.id),
        "requested_model": "fake-v1",
        "mode": "manual",
        "depth": "standard",
        "query_hint": None,
        "evidence_set_hash": evidence_set_hash([original]),
        "budget": budget.model_dump(mode="json"),
        "continuations": [],
    }
    job = WorkflowJob(
        id=uuid4(),
        job_type="research_story",
        payload=payload,
        idempotency_key=str(uuid4()),
        origin="manual",
        attempt_count=1,
    )
    session = TransactionalSession([story, original, profile, run, job])
    return session, job, run, output


def _subscribe_dispatch(session, job, run):
    story = next(value for value in session.values if isinstance(value, Story))
    current_revision = next(
        (value for value in session.values if isinstance(value, StoryRevision) and value.story_id == story.id),
        None,
    )
    if current_revision is None:
        current_revision = StoryRevision(
            id=uuid4(),
            story_id=story.id,
            revision_number=1,
            narrative="Current",
            facts=[],
            disagreements=[],
            angles=[],
            citations=[],
            created_by="telegram",
        )
        session.values.append(current_revision)
    route = AutomationRoute(
        id=uuid4(),
        source_id=uuid4(),
        destination_id=uuid4(),
        brand_profile_id=uuid4(),
        prompt_template_version_id=uuid4(),
        ai_provider_profile_id=uuid4(),
        research_mode="auto_if_incomplete",
        content_filters={"research_provider_profile_id": str(run.provider_profile_id)},
    )
    dispatch = AutomationDispatch(
        id=uuid4(),
        route_id=route.id,
        source_item_id=uuid4(),
        story_revision_id=current_revision.id,
        source_key="source:1",
        source_fingerprint="f" * 64,
        source_message_ids=[1],
        dispatch_kind="live",
        status="researching",
    )
    descriptor = {
        "job_type": "telegram.route.process",
        "payload": {"dispatch_id": str(dispatch.id), "force_review": False},
        "idempotency_prefix": f"telegram-route-process-after-research:{dispatch.id}",
        "subscriber_id": f"telegram-dispatch:{dispatch.id}",
        "expected_route_id": str(route.id),
        "expected_story_id": str(story.id),
        "expected_story_revision_id": str(current_revision.id),
        "expected_provider_profile_id": str(run.provider_profile_id),
        "expected_research_mode": "auto_if_incomplete",
    }
    session.values.extend([route, dispatch])
    job.payload = {
        **job.payload,
        "continuations": [*(job.payload.get("continuations") or []), descriptor],
    }
    return dispatch


async def test_production_handler_persists_atomic_research_lifecycle_outside_transaction():
    session, job, run, output = _lifecycle_fixture()
    backend = ObservingBackend(session, output)
    result = await build_research_story_handler(lambda _profile: backend)(
        job, JobContext(session=session, providers=SimpleNamespace())
    )
    assert backend.calls == 1 and backend.saw_running_attempt is True
    assert result["run_id"] == str(run.id)
    assert len([value for value in session.values if isinstance(value, ResearchSource)]) == 1
    assert len([value for value in session.values if isinstance(value, StoryRevision)]) == 1
    assert len([value for value in session.values if isinstance(value, StoryEvidenceLink)]) == 1
    assert any(
        isinstance(value, WorkflowEvent) and value.event_type == "research.succeeded" for value in session.values
    )


async def test_unknown_candidate_key_rolls_back_materialization_and_records_review_attempt():
    session, job, run, output = _lifecycle_fixture(unknown_key=True)
    _subscribe_dispatch(session, job, run)
    backend = ObservingBackend(session, output)
    with pytest.raises(NeedsReviewJobError):
        await build_research_story_handler(lambda _profile: backend)(
            job, JobContext(session=session, providers=SimpleNamespace())
        )
    assert backend.calls == 1
    assert not any(isinstance(value, ResearchSource) for value in session.values)
    assert len([value for value in session.values if isinstance(value, StoryRevision)]) == 1
    assert not any(isinstance(value, StoryEvidenceLink) for value in session.values)
    attempts = [value for value in session.values if isinstance(value, ResearchAttempt)]
    assert len(attempts) == 1
    assert attempts[0].status == "needs_review"
    persisted_dispatch = next(value for value in session.values if isinstance(value, AutomationDispatch))
    assert persisted_dispatch.status == "needs_review"
    assert persisted_dispatch.variant_revision_id is None
    assert persisted_dispatch.publish_job_id is None


async def test_research_attempt_and_subscriber_dispatch_redact_backend_error_code_canary():
    session, job, run, output = _lifecycle_fixture()
    dispatch = _subscribe_dispatch(session, job, run)

    class SecretResearchError(RuntimeError):
        classification = "needs_review"
        code = 'research_failure={"authorization":"Bearer research-code-canary"}'

    class SecretBackend(ObservingBackend):
        async def research(self, request):
            self.calls += 1
            raise SecretResearchError from None

    backend = SecretBackend(session, output)
    with pytest.raises(NeedsReviewJobError) as caught:
        await build_research_story_handler(lambda _profile: backend)(
            job, JobContext(session=session, providers=SimpleNamespace())
        )

    assert "research-code-canary" in caught.value.code
    attempt = next(value for value in session.values if isinstance(value, ResearchAttempt))
    assert "research-code-canary" not in attempt.error_code
    assert "[REDACTED]" in attempt.error_code
    assert "research-code-canary" not in dispatch.error_code
    assert "[REDACTED]" in dispatch.error_code
    failure_event = next(
        value for value in session.values if isinstance(value, WorkflowEvent) and value.event_type == "research.failed"
    )
    assert "research-code-canary" not in str(failure_event.event_data)


@pytest.mark.parametrize(
    "drift",
    ["profile", "mode", "evidence", "query", "page", "time", "model", "full_budget"],
)
async def test_production_handler_rejects_persisted_input_drift_before_backend(drift):
    session, job, run, output = _lifecycle_fixture()
    if drift == "profile":
        run.provider_profile_id = uuid4()
    elif drift == "mode":
        job.payload = {**job.payload, "mode": "auto_if_incomplete"}
    elif drift == "evidence":
        job.payload = {**job.payload, "evidence_set_hash": "0" * 64}
    elif drift == "query":
        run.query_budget += 1
    elif drift == "page":
        run.page_budget += 1
    elif drift == "time":
        run.time_budget_seconds += 1
    elif drift == "model":
        job.payload = {**job.payload, "requested_model": "fake-v2"}
    else:
        changed = {**job.payload["budget"]}
        changed["max_output_tokens"] += 1
        job.payload = {**job.payload, "budget": changed}
    backend = ObservingBackend(session, output)
    with pytest.raises(NeedsReviewJobError):
        await build_research_story_handler(lambda _profile: backend)(
            job, JobContext(session=session, providers=SimpleNamespace())
        )
    assert backend.calls == 0
    assert not any(isinstance(value, ResearchSource) for value in session.values)
    attempts = [value for value in session.values if isinstance(value, ResearchAttempt)]
    assert len(attempts) == 1 and attempts[0].status == "needs_review"


@pytest.mark.parametrize(
    "mutation",
    [
        ("provider_profile_id", uuid4()),
        ("provider_type", "codex"),
        ("requested_model", "fake-v2"),
        ("model_calls", 2),
        ("input_tokens", 60_001),
        ("output_tokens", 12_001),
        ("estimated_cost_usd", Decimal("0.01")),
        ("queries", 5),
        ("pages", 9),
        ("fetched_characters", 120_001),
        ("elapsed_ms", 180_001),
    ],
)
async def test_result_contract_overage_or_identity_mismatch_rolls_back_for_review(mutation):
    session, job, _run, output = _lifecycle_fixture()
    backend = InvalidResultBackend(session, output, mutation)
    with pytest.raises(NeedsReviewJobError):
        await build_research_story_handler(lambda _profile: backend)(
            job, JobContext(session=session, providers=SimpleNamespace())
        )
    assert backend.calls == 1
    assert not any(isinstance(value, ResearchSource) for value in session.values)
    assert not any(isinstance(value, StoryRevision) for value in session.values)
    attempts = [value for value in session.values if isinstance(value, ResearchAttempt)]
    assert len(attempts) == 1 and attempts[0].status == "needs_review"


async def test_successful_research_enqueues_exactly_one_deterministic_continuation(monkeypatch):
    session, job, run, output = _lifecycle_fixture()
    dispatch = _subscribe_dispatch(session, job, run)
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.research.continuations.JobRepository", FakeJobs)
    backend = ObservingBackend(session, output)
    handler = build_research_story_handler(lambda _profile: backend)
    first = await handler(job, JobContext(session=session, providers=SimpleNamespace()))
    second = await handler(job, JobContext(session=session, providers=SimpleNamespace()))
    assert first["continuation_job_id"] is not None
    assert second["idempotent"] is True
    assert backend.calls == 1
    assert len(calls) == 1
    assert calls[0]["idempotency_key"].startswith(f"telegram-route-process-after-research:{dispatch.id}:")


async def test_two_subscribers_arriving_before_finalization_each_continue_once(monkeypatch):
    session, job, run, output = _lifecycle_fixture()
    first = _subscribe_dispatch(session, job, run)
    second = _subscribe_dispatch(session, job, run)
    payload, created = append_unique_continuation(job.payload, job.payload["continuations"][0])
    job.payload = payload
    assert created is False
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(job=SimpleNamespace(id=uuid4()), created=True)

    monkeypatch.setattr("app.research.continuations.JobRepository", FakeJobs)
    result = await build_research_story_handler(lambda _profile: ObservingBackend(session, output))(
        job, JobContext(session=session, providers=SimpleNamespace())
    )
    assert len(result["continuation_job_ids"]) == 2
    assert len(calls) == 2
    assert {call["payload"]["dispatch_id"] for call in calls} == {str(first.id), str(second.id)}
    assert len({call["idempotency_key"] for call in calls}) == 2


class InterleavingBackend(ObservingBackend):
    def __init__(self, session, output, second_handler, job, context):
        super().__init__(session, output)
        self.second_handler = second_handler
        self.job = job
        self.context = context

    async def research(self, request):
        await self.second_handler(self.job, self.context)
        return await super().research(request)


async def test_stale_attempt_cannot_persist_or_downgrade_newer_success():
    session, job, run, output = _lifecycle_fixture()
    context = JobContext(session=session, providers=SimpleNamespace())
    second_backend = ObservingBackend(session, output)
    second_handler = build_research_story_handler(lambda _profile: second_backend)
    first_backend = InterleavingBackend(session, output, second_handler, job, context)
    first_handler = build_research_story_handler(lambda _profile: first_backend)
    stale = await first_handler(job, context)
    persisted_run = next(value for value in session.values if isinstance(value, ResearchRun))
    attempts = sorted(
        (value for value in session.values if isinstance(value, ResearchAttempt)),
        key=lambda value: value.attempt_number,
    )
    assert persisted_run.status == "succeeded"
    assert [value.status for value in attempts] == ["failed", "succeeded"]
    assert len([value for value in session.values if isinstance(value, ResearchSource)]) == 1
    assert len([value for value in session.values if isinstance(value, StoryRevision)]) == 1
    assert stale["stale_attempt_ignored"] is True
    events = [value for value in session.values if isinstance(value, WorkflowEvent)]
    assert any(value.event_type == "research.succeeded" for value in events)
    assert not any(value.event_type == "research.failed" for value in events)
    assert sum(value.event_type == "research.stale_attempt_ignored" for value in events) <= 1


async def test_crash_after_research_provider_retries_without_duplicate_materialization():
    session, job, _run, output = _lifecycle_fixture()
    backend = ObservingBackend(session, output)

    injector = ScriptedFaultInjector({"research.after_provider_before_persist": 1})
    crashing = build_research_story_handler(
        lambda _profile: backend,
        fault_injector=injector,
    )

    with pytest.raises(InjectedFault):
        await crashing(job, JobContext(session=session, providers=SimpleNamespace()))

    assert [hit.point for hit in injector.hits] == ["research.after_provider_before_persist"]
    assert backend.calls == 1
    assert not any(isinstance(value, ResearchSource) for value in session.values)
    assert not any(isinstance(value, StoryRevision) for value in session.values)
    attempts = [value for value in session.values if isinstance(value, ResearchAttempt)]
    assert len(attempts) == 1 and attempts[0].status == "running"

    job.attempt_count = 2
    result = await build_research_story_handler(lambda _profile: backend)(
        job,
        JobContext(session=session, providers=SimpleNamespace()),
    )

    assert result["story_revision_id"]
    assert backend.calls == 2
    attempts = sorted(
        (value for value in session.values if isinstance(value, ResearchAttempt)),
        key=lambda value: value.attempt_number,
    )
    assert [value.status for value in attempts] == ["failed", "succeeded"]
    assert len([value for value in session.values if isinstance(value, ResearchSource)]) == 1
    assert len([value for value in session.values if isinstance(value, StoryRevision)]) == 1


@pytest.mark.parametrize(
    "attack",
    [
        "route",
        "story",
        "profile",
        "subscriber",
        "mode",
        "current_revision",
        "dispatch",
        "result_lineage",
    ],
)
async def test_continuation_binding_rejects_cross_context_substitution(monkeypatch, attack):
    session, job, run, _output = _lifecycle_fixture()
    dispatch = _subscribe_dispatch(session, job, run)
    descriptor = deepcopy(job.payload["continuations"][0])
    story = next(value for value in session.values if isinstance(value, Story))
    result_revision = StoryRevision(
        id=uuid4(),
        story_id=story.id,
        revision_number=2,
        parent_revision_id=UUID(descriptor["expected_story_revision_id"]),
        narrative="Result",
        facts=[],
        disagreements=[],
        angles=[],
        citations=[],
        created_by="research",
    )
    session.values.append(result_revision)
    if attack == "route":
        descriptor["expected_route_id"] = str(uuid4())
    elif attack == "story":
        descriptor["expected_story_id"] = str(uuid4())
    elif attack == "profile":
        descriptor["expected_provider_profile_id"] = str(uuid4())
    elif attack == "subscriber":
        descriptor["subscriber_id"] = f"telegram-dispatch:{uuid4()}"
    elif attack == "mode":
        route = next(value for value in session.values if isinstance(value, AutomationRoute))
        route.research_mode = "manual"
    elif attack == "current_revision":
        current = next(
            value
            for value in session.values
            if isinstance(value, StoryRevision) and value.id == dispatch.story_revision_id
        )
        current.story_id = uuid4()
    elif attack == "dispatch":
        other_id = uuid4()
        descriptor["payload"]["dispatch_id"] = str(other_id)
        descriptor["subscriber_id"] = f"telegram-dispatch:{other_id}"
        descriptor["idempotency_prefix"] = f"telegram-route-process-after-research:{other_id}"
    else:
        result_revision.parent_revision_id = uuid4()
    calls = []

    class FakeJobs:
        def __init__(self, _session):
            pass

        async def enqueue_job(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("app.research.continuations.JobRepository", FakeJobs)
    original_revision_id = dispatch.story_revision_id
    with pytest.raises(ValueError, match="continuation"):
        await enqueue_bound_continuation(session, descriptor=descriptor, run=run, result_revision=result_revision)
    assert dispatch.story_revision_id == original_revision_id
    assert calls == []
