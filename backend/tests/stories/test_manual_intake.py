from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.dialects import postgresql

from app.db.models import ContentItem, RawPayload, SourceItem
from app.discovery.models import ExtractedArticle
from app.generation.providers.registry import build_default_provider_registry
from app.jobs.errors import NeedsReviewJobError, RetryableJobError
from app.jobs.models import WorkflowEvent
from app.jobs.registry import JobContext, build_default_registry
from app.jobs.types import JobType
from app.stories import repository as stories_repository
from app.stories.evidence import EvidenceInput
from app.stories.handlers import handle_manual_intake
from app.stories.manual_intake import ManualIntakeFetchError, manual_discovery_item
from app.stories.models import Story, StoryEvidenceSnapshot
from app.stories.repository import StoryRepository
from app.stories.schemas import ManualIntakeRequest


def test_manual_intake_schema_is_strict_and_discriminated():
    adapter = TypeAdapter(ManualIntakeRequest)

    url_request = adapter.validate_python(
        {"kind": "url", "url": "https://example.com/report", "title": None}
    )
    text_request = adapter.validate_python(
        {
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        }
    )

    assert url_request.kind == "url"
    assert text_request.kind == "text"
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "url", "url": "not-a-url"})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "kind": "text",
                "title": "Operator note",
                "text": "too short",
                "source_label": "Interview",
                "extra": True,
            }
        )


def test_manual_url_discovery_item_uses_submitted_truth_without_publisher():
    request = TypeAdapter(ManualIntakeRequest).validate_python(
        {"kind": "url", "url": "https://example.com/report", "title": "Submitted title"}
    )

    item = manual_discovery_item(request)

    assert item.url == "https://example.com/report"
    assert item.title == "Submitted title"
    assert item.source_platform == "manual"
    assert item.source_name == ""
    assert item.author is None


class RecordingSession:
    def __init__(self):
        self.added: list[object] = []
        self.commits = 0
        self.story: Story | None = None
        self.executed: list[object] = []

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = uuid4()
        self.added.append(value)
        if isinstance(value, Story):
            self.story = value

    async def flush(self):
        return None

    async def scalar(self, statement):
        if "FROM workflow_events" in str(statement):
            return next(
                (
                    value.id
                    for value in self.added
                    if isinstance(value, WorkflowEvent)
                    and value.event_type == "manual_intake.completed"
                ),
                None,
            )
        return self.story

    async def commit(self):
        self.commits += 1

    def begin_nested(self):
        class Savepoint:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        return Savepoint()


def test_manual_intake_lock_is_transaction_scoped_and_uuid_deterministic():
    job_id = uuid4()

    key = stories_repository._manual_intake_lock_key(job_id)
    repeated = stories_repository._manual_intake_lock_key(job_id)
    sql = str(
        stories_repository._manual_intake_lock_statement(job_id).compile(
            dialect=postgresql.dialect()
        )
    ).upper()

    assert key == repeated
    assert -(2**63) <= key < 2**63
    assert "PG_ADVISORY_XACT_LOCK" in sql
    assert "PG_ADVISORY_LOCK(" not in sql


def _only(session: RecordingSession, model):
    return next(value for value in session.added if isinstance(value, model))


@pytest.mark.asyncio
async def test_text_manual_evidence_persists_raw_provenance_and_is_replay_safe():
    request = TypeAdapter(ManualIntakeRequest).validate_python(
        {
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        }
    )
    evidence = EvidenceInput.from_operator_text(request)
    session = RecordingSession()
    job_id = uuid4()
    repository = StoryRepository(session)

    story = await repository.create_from_manual_evidence(evidence, job_id)
    replayed = await repository.create_from_manual_evidence(evidence, job_id)

    assert replayed is story
    assert len([value for value in session.added if isinstance(value, Story)]) == 1
    raw = _only(session, RawPayload)
    content = _only(session, ContentItem)
    source = _only(session, SourceItem)
    snapshot = _only(session, StoryEvidenceSnapshot)
    assert raw.payload_kind == "manual_text_input"
    assert raw.request_url == "manual://operator"
    assert raw.final_url is raw.http_status is None
    assert raw.raw_text == request.text
    assert source.parser_meta["source_label"] == "Operator interview"
    assert source.source_url is None
    assert snapshot.source_url is None
    assert snapshot.content_text == request.text
    assert snapshot.content_item_id == content.id
    assert snapshot.evidence_key == f"content-item:{content.id}:{snapshot.content_sha256}"
    assert snapshot.snapshot_metadata["workflow_job_id"] == str(job_id)


@pytest.mark.asyncio
async def test_url_manual_evidence_records_extraction_truth_without_inventing_http():
    extracted = ExtractedArticle(
        url="https://example.com/submitted",
        final_url="https://publisher.example/final",
        title="Extracted title",
        summary="Summary",
        content_text="Verified extracted report body long enough to retain.",
        content_html=None,
        author="Reporter",
        published_at=None,
        image_url=None,
        extraction_status="fallback",
        extraction_warnings=["short_extraction"],
    )
    evidence = EvidenceInput.from_extracted_article(extracted, title_override="Operator title")
    session = RecordingSession()
    job_id = uuid4()

    story = await StoryRepository(session).create_from_manual_evidence(evidence, job_id)

    raw = _only(session, RawPayload)
    source = _only(session, SourceItem)
    snapshot = _only(session, StoryEvidenceSnapshot)
    assert story.title == "Operator title"
    assert raw.payload_kind == "manual_url_input"
    assert raw.request_url == extracted.url
    assert raw.final_url == extracted.final_url
    assert raw.http_status is None
    assert raw.raw_text is None
    assert raw.parser_warnings == ["short_extraction"]
    assert source.parser_meta["extraction_status"] == "fallback"
    assert source.parser_meta["extraction_warnings"] == ["short_extraction"]
    assert source.parser_meta.get("publisher") is None
    assert snapshot.content_text == extracted.content_text
    assert snapshot.source_url == extracted.final_url


@pytest.mark.asyncio
async def test_extracted_html_remains_raw_and_is_never_assigned_to_sanitized_content():
    malicious_html = "<article>Report<script>alert('xss')</script></article>"
    extracted = ExtractedArticle(
        url="https://example.com/submitted",
        final_url="https://publisher.example/final",
        title="Report",
        summary="Summary",
        content_text="Verified extracted report body long enough to retain.",
        content_html=malicious_html,
        author=None,
        published_at=None,
        image_url=None,
        extraction_status="ok",
        extraction_warnings=[],
    )
    session = RecordingSession()

    await StoryRepository(session).create_from_manual_evidence(
        EvidenceInput.from_extracted_article(extracted),
        uuid4(),
    )

    content = _only(session, ContentItem)
    source = _only(session, SourceItem)
    assert content.content_html_sanitized is None
    assert source.content_html_raw == malicious_html


@pytest.mark.asyncio
async def test_late_persistence_failure_rolls_back_savepoint_and_maps_retryable():
    class Savepoint:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            self.session.savepoint_entered = True
            self.added_before = list(self.session.added)
            self.story_before = self.session.story
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            if exc_type is not None:
                self.session.added = self.added_before
                self.session.story = self.story_before
            self.session.savepoint_exited = True
            return False

    class LateFailureSession(RecordingSession):
        def __init__(self):
            super().__init__()
            self.savepoint_entered = False
            self.savepoint_exited = False
            self.failed = False

        def begin_nested(self):
            return Savepoint(self)

        async def flush(self):
            if (
                not self.failed
                and any(isinstance(value, WorkflowEvent) for value in self.added)
            ):
                self.failed = True
                raise RuntimeError("late database failure")

    session = LateFailureSession()
    job = SimpleNamespace(
        id=uuid4(),
        payload={
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        },
    )

    with pytest.raises(RetryableJobError, match="Manual intake persistence failed") as error:
        await handle_manual_intake(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    assert error.value.code == "manual_intake_persistence_failed"
    assert session.savepoint_entered is True
    assert session.savepoint_exited is True
    assert session.added == []
    assert await session.scalar(None) is None


@pytest.mark.asyncio
async def test_manual_url_handler_commits_before_network_and_emits_completion(monkeypatch):
    trace: list[str] = []
    session = RecordingSession()
    story = SimpleNamespace(id=uuid4())
    extracted = ExtractedArticle(
        url="https://example.com/report",
        final_url="https://example.com/final",
        title="Report",
        summary="Summary",
        content_text="Verified extracted report body long enough to retain.",
        content_html=None,
        author=None,
        published_at=None,
        image_url=None,
        extraction_status="ok",
        extraction_warnings=[],
    )

    class FakeClient:
        async def __aenter__(self):
            trace.append("client_enter")
            return self

        async def __aexit__(self, *args):
            return None

    def client_factory(**kwargs):
        assert kwargs == {"timeout": 30}
        return FakeClient()

    async def extract(client, item):
        trace.append("extract")
        assert item.source_name == ""
        return extracted

    class FakeStories:
        async def create_from_manual_evidence(self, evidence, job_id):
            trace.append("persist")
            assert evidence.title == "Operator title"
            return story

    async def commit():
        trace.append("commit")

    session.commit = commit
    monkeypatch.setattr("app.stories.manual_intake.ManualIntakeHttpClient", client_factory)
    monkeypatch.setattr("app.stories.manual_intake.extract_article", extract)
    monkeypatch.setattr("app.stories.handlers.StoryRepository", lambda _session: FakeStories())
    job = SimpleNamespace(
        id=uuid4(),
        payload={
            "kind": "url",
            "url": "https://example.com/report",
            "title": "Operator title",
        },
    )

    result = await handle_manual_intake(
        job,
        JobContext(session=session, providers=build_default_provider_registry()),
    )

    assert trace == ["commit", "client_enter", "extract", "persist"]
    assert result == {"story_id": str(story.id)}
    event = _only(session, WorkflowEvent)
    assert event.event_type == "manual_intake.completed"
    assert event.actor == "worker"
    assert event.event_data == {"story_id": str(story.id)}


@pytest.mark.asyncio
async def test_manual_intake_handler_replay_creates_one_story_snapshot_and_completion_event():
    session = RecordingSession()
    job = SimpleNamespace(
        id=uuid4(),
        payload={
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        },
    )
    context = JobContext(session=session, providers=build_default_provider_registry())

    first = await handle_manual_intake(job, context)
    replay = await handle_manual_intake(job, context)

    assert replay == first
    assert len([value for value in session.added if isinstance(value, Story)]) == 1
    assert len(
        [value for value in session.added if isinstance(value, StoryEvidenceSnapshot)]
    ) == 1
    events = [
        value
        for value in session.added
        if isinstance(value, WorkflowEvent)
        and value.event_type == "manual_intake.completed"
    ]
    assert len(events) == 1
    assert events[0].workflow_job_id == job.id
    assert events[0].actor == "worker"
    assert events[0].event_data == {"story_id": first["story_id"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("extraction_status", "content_text"),
    [("failed", "Report"), ("ok", "   ")],
)
async def test_failed_or_empty_url_extraction_needs_review_and_creates_no_story(
    monkeypatch,
    extraction_status,
    content_text,
):
    failed = ExtractedArticle(
        url="https://example.com/report",
        final_url="https://example.com/report",
        title="Report",
        summary="",
        content_text=content_text,
        content_html=None,
        author=None,
        published_at=None,
        image_url=None,
        extraction_status=extraction_status,
        extraction_warnings=["http_503"],
    )

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    session = RecordingSession()
    monkeypatch.setattr(
        "app.stories.manual_intake.ManualIntakeHttpClient",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr("app.stories.manual_intake.extract_article", AsyncMock(return_value=failed))
    job = SimpleNamespace(
        id=uuid4(),
        payload={"kind": "url", "url": "https://example.com/report", "title": None},
    )

    with pytest.raises(NeedsReviewJobError) as error:
        await handle_manual_intake(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    assert error.value.code == "manual_extraction_failed"
    assert not any(isinstance(value, Story) for value in session.added)


@pytest.mark.asyncio
async def test_unsafe_url_failure_maps_to_fixed_redacted_needs_review(monkeypatch):
    class UnsafeClient:
        async def __aenter__(self):
            raise ManualIntakeFetchError(
                "unsafe target contained https://user:secret@127.0.0.1/private"
            )

        async def __aexit__(self, *args):
            return None

    session = RecordingSession()
    monkeypatch.setattr(
        "app.stories.manual_intake.ManualIntakeHttpClient",
        lambda **kwargs: UnsafeClient(),
    )
    job = SimpleNamespace(
        id=uuid4(),
        payload={"kind": "url", "url": "https://example.com/report", "title": None},
    )

    with pytest.raises(NeedsReviewJobError) as error:
        await handle_manual_intake(
            job,
            JobContext(session=session, providers=build_default_provider_registry()),
        )

    assert error.value.code == "manual_extraction_failed"
    assert error.value.message == "Manual URL extraction failed"
    assert "secret" not in error.value.message
    assert session.added == []


def test_default_ingestion_registry_includes_manual_intake_job_type():
    registry = build_default_registry(capabilities=("ingestion",))

    assert JobType.MANUAL_INTAKE == "manual_intake"
    assert registry.get("manual_intake") is handle_manual_intake
