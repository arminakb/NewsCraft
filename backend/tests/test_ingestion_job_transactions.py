import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.db.models import Source
from app.ingestion.workflow import (
    FetchedSourceBatch,
    IngestionWorkflow,
    PreparedIngestionRun,
    PreparedSource,
    SourcePersistResult,
)
from app.sources.base import MediaCandidate, ParsedSourceItem, ParsedSourcePayload


class TrackedTransaction(AbstractAsyncContextManager):
    """Records transaction boundaries; the work done inside names each phase."""

    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        assert self.session.active is False
        self.session.active = True
        self.session.events.append("begin")

    async def __aexit__(self, exc_type, exc, tb):
        self.session.active = False
        self.session.events.append("rollback" if exc else "commit")


class TransactionTrackingSession:
    def __init__(self):
        self.active = False
        self.events = []

    def begin(self):
        return TrackedTransaction(self)

    def in_transaction(self):
        return self.active


def _prepared_source():
    return PreparedSource(
        id=uuid4(),
        name="source-1",
        platform="rss",
        feed_url="https://example.com/feed.xml",
        telegram_username=None,
        default_timezone="UTC",
        etag=None,
        last_modified=None,
    )


class BoundaryWorkflow(IngestionWorkflow):
    def __init__(self, *, fail=False, cancel=False):
        super().__init__()
        self.source = _prepared_source()
        self.fail = fail
        self.cancel = cancel
        self.fetch_calls = []
        self.persist_calls = []
        self.failure_calls = []
        self.finished = []

    def _record(self, event):
        self._active_session.events.append(event)

    async def prepare_run(self, session, *, platforms, source_ids, trigger):
        self._record("prepare")
        return PreparedIngestionRun(run_id=uuid4(), sources=(self.source,))

    async def fetch_source(self, source, *, client=None):
        assert self._active_session.in_transaction() is False
        self.fetch_calls.append(source.name)
        if self.cancel:
            asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
        if self.fail:
            raise RuntimeError("network down")
        return FetchedSourceBatch(
            source=source,
            request_url=source.feed_url or "",
            final_url=source.feed_url or "",
            http_status=200,
            headers={},
            content_type="application/rss+xml",
            raw_text="<rss />",
            parser_warnings=(),
            parsed_items=(),
        )

    async def persist_source(self, session, *, run_id, batch):
        self._record(f"persist:{batch.source.name}")
        self.persist_calls.append(batch.source.name)
        return SourcePersistResult(fetched=1)

    async def record_source_failure(self, session, *, run_id, source, error):
        self._record(f"failure:{source.name}")
        self.failure_calls.append((source.name, str(error)))
        return SourcePersistResult(failed=1, errors=({"source": source.name, "error": str(error)},))

    async def finish_run(self, session, *, run_id, stats):
        self._record("finish")
        self.finished.append((run_id, stats.copy()))

    async def run(self, *, session, **kwargs):
        self._active_session = session
        return await super().run(session=session, **kwargs)


@pytest.mark.asyncio
async def test_ingestion_handler_has_no_database_transaction_during_source_network_fetch():
    session = TransactionTrackingSession()
    workflow = BoundaryWorkflow()

    result = await workflow.run(session=session, platforms=["rss"], source_ids=None, trigger="workflow_job")

    assert result["failed"] == 0
    assert workflow.fetch_calls == ["source-1"]
    assert session.events == [
        "begin",
        "prepare",
        "commit",
        "begin",
        "persist:source-1",
        "commit",
        "begin",
        "finish",
        "commit",
    ]


@pytest.mark.asyncio
async def test_fetch_failure_happens_outside_transaction_then_records_short_failure_transaction():
    session = TransactionTrackingSession()
    workflow = BoundaryWorkflow(fail=True)

    result = await workflow.run(session=session, platforms=None, source_ids=None, trigger="workflow_job")

    assert result["failed"] == 1
    assert workflow.failure_calls == [("source-1", "network down")]
    assert session.events == [
        "begin",
        "prepare",
        "commit",
        "begin",
        "failure:source-1",
        "commit",
        "begin",
        "finish",
        "commit",
    ]


@pytest.mark.asyncio
async def test_workflow_failure_stats_are_sanitized_before_finish_and_return():
    class SecretBoundaryWorkflow(BoundaryWorkflow):
        async def fetch_source(self, source, *, client=None):
            raise RuntimeError('fetch {"authorization":"Bearer workflow-message-canary"}')

    session = TransactionTrackingSession()
    workflow = SecretBoundaryWorkflow()
    workflow.source = replace(
        workflow.source,
        name="api_key=workflow-source-canary",
    )

    result = await workflow.run(
        session=session,
        platforms=None,
        source_ids=None,
        trigger="workflow_job",
    )

    rendered = str({"returned": result, "finished": workflow.finished})
    assert "workflow-message-canary" not in rendered
    assert "workflow-source-canary" not in rendered
    assert "[REDACTED]" in rendered


@pytest.mark.asyncio
async def test_workflow_does_not_overwrite_repository_sanitized_parser_warnings(
    monkeypatch,
):
    source = _production_source()
    prepared = _prepared_source()

    class Session:
        async def get(self, model, identifier):
            return source if model is Source and identifier == source.id else None

    class SanitizingRepository:
        payload = None

        def __init__(self, _session):
            pass

        async def save_raw_payload(self, **_kwargs):
            self.__class__.payload = SimpleNamespace(
                id=uuid4(),
                parser_warnings=["bozo_feed: api_key=[REDACTED]"],
            )
            return self.__class__.payload

    prepared = replace(prepared, id=source.id)
    batch = FetchedSourceBatch(
        source=prepared,
        request_url=prepared.feed_url or "",
        final_url=prepared.feed_url or "",
        http_status=304,
        headers={},
        content_type="application/rss+xml",
        raw_text="",
        parser_warnings=("bozo_feed: api_key=workflow-warning-canary",),
        parsed_items=(),
    )
    monkeypatch.setattr(
        "app.ingestion.workflow.IngestionRepository",
        SanitizingRepository,
    )

    result = await IngestionWorkflow().persist_source(
        Session(),
        run_id=uuid4(),
        batch=batch,
    )

    assert result.skipped == 1
    assert "workflow-warning-canary" not in str(SanitizingRepository.payload.parser_warnings)
    assert "[REDACTED]" in str(SanitizingRepository.payload.parser_warnings)


@pytest.mark.asyncio
async def test_cancellation_between_fetch_and_persistence_leaves_recoverable_running_run():
    session = TransactionTrackingSession()
    workflow = BoundaryWorkflow(cancel=True)

    with pytest.raises(asyncio.CancelledError):
        await workflow.run(session=session, platforms=None, source_ids=None, trigger="workflow_job")

    assert workflow.persist_calls == []
    assert workflow.failure_calls == []
    assert workflow.finished == []
    assert session.events == ["begin", "prepare", "commit"]


@pytest.mark.asyncio
async def test_exception_escaping_the_source_loop_marks_the_run_failed_before_propagating():
    """A stranded `running` row blocks every later ingest for the collection."""

    class ExplodingBookkeepingWorkflow(BoundaryWorkflow):
        def __init__(self):
            super().__init__(fail=True)
            self.aborted = []

        async def record_source_failure(self, session, *, run_id, source, error):
            self._record(f"failure:{source.name}")
            raise RuntimeError("failure bookkeeping exploded")

        async def abort_run(self, session, *, run_id, stats, error):
            self._record("abort")
            self.aborted.append((run_id, stats, error))

    session = TransactionTrackingSession()
    workflow = ExplodingBookkeepingWorkflow()

    with pytest.raises(RuntimeError, match="failure bookkeeping exploded"):
        await workflow.run(session=session, platforms=None, source_ids=None, trigger="workflow_job")

    assert workflow.finished == []
    assert len(workflow.aborted) == 1
    _, aborted_stats, aborted_error = workflow.aborted[0]
    assert aborted_error == "failure bookkeeping exploded"
    assert aborted_stats["checked"] == 1
    assert session.events == [
        "begin",
        "prepare",
        "commit",
        "begin",
        "failure:source-1",
        "rollback",
        "begin",
        "abort",
        "commit",
    ]


@pytest.mark.asyncio
async def test_finish_run_failure_still_marks_the_run_failed():
    class ExplodingFinishWorkflow(BoundaryWorkflow):
        def __init__(self):
            super().__init__()
            self.aborted = []

        async def finish_run(self, session, *, run_id, stats):
            raise RuntimeError("finish exploded")

        async def abort_run(self, session, *, run_id, stats, error):
            self._record("abort")
            self.aborted.append((run_id, stats, error))

    session = TransactionTrackingSession()
    workflow = ExplodingFinishWorkflow()

    with pytest.raises(RuntimeError, match="finish exploded"):
        await workflow.run(session=session, platforms=None, source_ids=None, trigger="workflow_job")

    assert len(workflow.aborted) == 1
    assert workflow.aborted[0][2] == "finish exploded"
    assert session.events[-3:] == ["begin", "abort", "commit"]


class StagedTransaction(AbstractAsyncContextManager):
    """Records boundaries plus the writes each transaction actually carried.

    The staged kinds identify the phase far more directly than a label the
    workflow hands the session would.
    """

    def __init__(self, session, label, *, nested=False):
        self.session = session
        self.label = label
        self.nested = nested

    async def __aenter__(self):
        if not self.nested:
            assert not self.session.pending
        self.session.pending.append([])
        self.session.events.append(f"begin:{self.label}")

    async def __aexit__(self, exc_type, exc, tb):
        staged = self.session.pending.pop()
        wrote = "+".join(kind for kind, _ in staged) or "nothing"
        if exc:
            self.session.events.append(f"rollback:{self.label}:{wrote}")
            return None
        if self.session.pending:
            self.session.pending[-1].extend(staged)
        else:
            self.session.committed.extend(staged)
        self.session.events.append(f"commit:{self.label}:{wrote}")
        return None


class ProductionWorkflowSession:
    def __init__(self, source):
        self.source = source
        self.events = []
        self.pending = []
        self.committed = []

    def begin(self):
        return StagedTransaction(self, "top")

    def begin_nested(self):
        return StagedTransaction(self, "savepoint", nested=True)

    def in_transaction(self):
        return bool(self.pending)

    async def get(self, model, key):
        return self.source if model is Source and key == self.source.id else None

    def stage(self, kind, value):
        assert self.pending
        self.pending[-1].append((kind, value))


class ProductionWorkflowRepository:
    fail_media = False

    def __init__(self, session):
        self.session = session

    async def create_run(self, *, trigger, parser_version):
        run = SimpleNamespace(id=uuid4())
        self.session.stage("run", {"id": run.id, "trigger": trigger, "parser_version": parser_version})
        return run

    async def get_active_sources(self, *, platforms=None):
        return [self.session.source]

    async def save_raw_payload(self, **kwargs):
        payload = SimpleNamespace(id=uuid4(), parser_warnings=[])
        self.session.stage("raw", kwargs.copy())
        return payload

    async def upsert_source_item_with_created(self, **kwargs):
        value = SimpleNamespace(id=uuid4(), content_item_id=None)
        self.session.stage("source_item", kwargs.copy())
        # `False` keeps this double off the source-item event path, which needs
        # the real automations tables rather than this staged session.
        return value, False

    async def upsert_content_item(self, **kwargs):
        value = SimpleNamespace(id=uuid4())
        self.session.stage("content_item", kwargs.copy())
        return value

    async def attach_identities(self, **kwargs):
        self.session.stage("identities", kwargs.copy())

    async def upsert_media_assets(self, parsed_item):
        if self.fail_media:
            raise RuntimeError("media exploded")
        return []

    async def attach_item_media(self, **kwargs):
        self.session.stage("item_media", kwargs.copy())

    async def finish_run(self, run_id, *, status, stats, error=None):
        self.session.stage("finish", {"run_id": run_id, "status": status, "stats": stats.copy(), "error": error})


def _production_source():
    return Source(
        id=uuid4(),
        platform="rss",
        name="source-1",
        feed_url="https://example.com/feed.xml",
        source_group="news",
        default_timezone="UTC",
        active=True,
    )


def _parsed_payload_with_media():
    candidate = MediaCandidate(
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        kind="image",
        source_field="enclosure",
    )
    item = ParsedSourceItem(
        external_id_raw="one",
        external_id_norm="one",
        source_url="https://example.com/one",
        source_url_norm="https://example.com/one",
        canonical_url_candidate="https://example.com/one",
        title="One",
        summary="Summary",
        content_html=None,
        content_text="Long enough content " * 10,
        author=None,
        categories=[],
        published_raw=None,
        published_at=None,
        date_parse_status="missing",
        media_candidates=[candidate],
    )
    return ParsedSourcePayload(items=[item])


def _successful_client(session):
    def handler(request):
        assert session.in_transaction() is False
        return httpx.Response(
            200,
            text="<rss />",
            headers={"content-type": "application/rss+xml", "etag": "fresh-etag"},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _top_level_events(session):
    return [event for event in session.events if "savepoint" not in event]


@pytest.mark.asyncio
async def test_real_workflow_parser_failure_preserves_fetched_raw_evidence_and_records_separate_failure(
    monkeypatch,
):
    session = ProductionWorkflowSession(_production_source())
    monkeypatch.setattr("app.ingestion.workflow.IngestionRepository", ProductionWorkflowRepository)

    def fail_parser(*args, **kwargs):
        assert session.in_transaction() is False
        raise RuntimeError("parser exploded")

    monkeypatch.setattr("app.ingestion.workflow.parse_source_payload", fail_parser)
    async with _successful_client(session) as client:
        result = await IngestionWorkflow(http_client=client).run(
            session=session,
            platforms=["rss"],
            source_ids=None,
            trigger="workflow_job",
        )

    raw = next(value for kind, value in session.committed if kind == "raw")
    assert result["fetched"] == 1
    assert result["failed"] == 1
    assert raw["http_status"] == 200
    assert raw["headers"]["etag"] == "fresh-etag"
    assert raw["raw_text"] == "<rss />"
    assert _top_level_events(session) == [
        "begin:top",
        "commit:top:run",
        "begin:top",
        "commit:top:raw",
        "begin:top",
        "commit:top:nothing",
        "begin:top",
        "commit:top:finish",
    ]


@pytest.mark.asyncio
async def test_real_workflow_media_failure_preserves_raw_evidence_and_rolls_back_parsed_writes(
    monkeypatch,
):
    session = ProductionWorkflowSession(_production_source())
    ProductionWorkflowRepository.fail_media = True
    monkeypatch.setattr("app.ingestion.workflow.IngestionRepository", ProductionWorkflowRepository)
    monkeypatch.setattr(
        "app.ingestion.workflow.parse_source_payload",
        lambda *args, **kwargs: _parsed_payload_with_media(),
    )
    try:
        async with _successful_client(session) as client:
            result = await IngestionWorkflow(http_client=client).run(
                session=session,
                platforms=["rss"],
                source_ids=None,
                trigger="workflow_job",
            )
    finally:
        ProductionWorkflowRepository.fail_media = False

    committed_kinds = [kind for kind, _ in session.committed]
    assert result["fetched"] == 1
    assert result["failed"] == 1
    assert "raw" in committed_kinds
    assert "source_item" not in committed_kinds
    assert "content_item" not in committed_kinds
    assert _top_level_events(session) == [
        "begin:top",
        "commit:top:run",
        "begin:top",
        "commit:top:raw",
        "begin:top",
        "commit:top:nothing",
        "begin:top",
        "commit:top:finish",
    ]
