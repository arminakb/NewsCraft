from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.db.models import IngestRun, MediaAsset, Source
from app.db.session import get_session
from app.jobs.models import WorkflowJob
from app.jobs.repository import JobRepository
from app.jobs.types import JobOrigin, JobStatus
from app.main import app


async def test_health_endpoint_returns_ok():
    response = await _get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_cors_allows_frontend_origin():
    response = await _get("/health", headers={"Origin": "http://localhost:3000"})
    preflight = await _options(
        "/ingest/run",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_sources_endpoint_returns_source_summaries():
    source = Source(
        id=uuid4(),
        platform="rss",
        name="OpenAI News",
        feed_url="https://openai.com/news/rss.xml",
        source_group="ai",
        language_hint="en",
        active=True,
    )
    _override_session(FakeSession([source]))

    response = await _get("/sources")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["name"] == "OpenAI News"


async def test_sources_seed_endpoint_seeds_catalog(monkeypatch):
    import app.api.sources as sources

    async def fake_seed_sources(session):
        return 50

    fake_session = FakeSession([])
    monkeypatch.setattr(sources, "seed_sources", fake_seed_sources)
    _override_session(fake_session)

    response = await _post("/sources/seed")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"upserted": 50}
    assert fake_session.committed is True


async def test_ingest_run_endpoint_enqueues_one_idempotent_job_without_network(monkeypatch):
    request_id = uuid4()
    fake_session = FakeJobSession()

    def fail_if_constructed(*_args, **_kwargs):
        raise AssertionError("the API must not construct the network ingestion service")

    monkeypatch.setattr("app.ingestion.service.IngestionService.__init__", fail_if_constructed)
    _override_session(fake_session)

    payload = {
        "request_id": str(request_id),
        "platforms": ["rss"],
        "source_ids": ["source-1"],
    }
    try:
        first = await _post("/ingest/run", json=payload)
        second = await _post("/ingest/run", json=payload)
    finally:
        app.dependency_overrides.clear()
    assert first.status_code == second.status_code == 202
    assert first.json() == {
        "job_id": str(fake_session.job.id),
        "status": "queued",
        "deduplicated": False,
    }
    assert second.json() == {
        "job_id": str(fake_session.job.id),
        "status": "queued",
        "deduplicated": True,
    }
    assert fake_session.job.job_type == "ingest.collect"
    assert fake_session.job.origin == JobOrigin.MANUAL
    assert fake_session.job.pause_sensitive is False
    assert fake_session.job.idempotency_key == f"manual:ingest:{request_id}"
    assert fake_session.job.scheduled_for is not None
    assert fake_session.job.scheduled_for.tzinfo is not None
    assert fake_session.job.payload == {
        "platforms": ["rss"],
        "source_ids": ["source-1"],
    }
    assert fake_session.commit_count == 2


async def test_ingest_run_endpoint_requires_request_id(monkeypatch):
    class LegacyNetworkService:
        async def run_once(self, **_kwargs):
            return {"status": "succeeded"}

    monkeypatch.setattr(
        "app.ingestion.service.IngestionService.__init__",
        lambda self, _session: setattr(self, "run_once", LegacyNetworkService().run_once),
    )
    _override_session(FakeSession([]))
    try:
        response = await _post("/ingest/run", json={"platforms": ["rss"]})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


async def test_job_repository_assigns_runtime_schedule_when_caller_omits_it():
    session = FakeJobSession()

    result = await JobRepository(session).enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key="central-schedule-default",
        origin=JobOrigin.MANUAL,
        pause_sensitive=False,
    )

    assert result.job.scheduled_for is not None
    assert result.job.scheduled_for.tzinfo is not None


async def test_job_repository_repairs_null_schedule_on_idempotent_replay():
    session = FakeJobSession()
    repository = JobRepository(session)
    first = await repository.enqueue_job(
        job_type="ingest.collect",
        payload={},
        idempotency_key="legacy-null-schedule",
        origin=JobOrigin.MANUAL,
    )
    first.job.scheduled_for = None

    replay = await repository.enqueue_job(
        job_type="ingest.collect",
        payload={"ignored": True},
        idempotency_key="legacy-null-schedule",
        origin=JobOrigin.MANUAL,
    )

    assert replay.created is False
    assert replay.job.id == first.job.id
    assert replay.job.scheduled_for is not None
    assert replay.job.scheduled_for.tzinfo is not None


def test_routes_module_contains_no_legacy_handler_or_dependency_reexports():
    import app.api.routes as routes

    assert not hasattr(routes, "list_content_items")
    assert not hasattr(routes, "get_session")


async def test_content_items_endpoint_returns_latest_content_with_primary_media():
    content_item = SimpleNamespace(
        id=uuid4(),
        item_type="article",
        title="AI News",
        summary="Summary",
        canonical_url="https://example.com/a",
        source_url=None,
        language_code="en",
        direction="ltr",
        status="new",
        score=17,
        tags=["ai", "agent"],
        metrics={"classification": {"category": "AI"}},
        sort_at=datetime(2026, 7, 3, tzinfo=UTC),
        primary_image_id=uuid4(),
        primary_media=SimpleNamespace(
            id=uuid4(),
            normalized_url="https://example.com/image.jpg",
            kind="image",
            mime_type="image/jpeg",
            width=600,
            height=400,
            storage_path="/data/media/aa/image.jpg",
        ),
    )
    _override_session(FakeSession([content_item]))

    response = await _get("/content-items")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["score"] == 17
    assert response.json()[0]["tags"] == ["ai", "agent"]
    assert response.json()[0]["metrics"]["classification"]["category"] == "AI"
    assert response.json()[0]["primary_media"]["kind"] == "image"


async def test_content_items_endpoint_accepts_status_and_score_sort_params():
    content_item = SimpleNamespace(
        id=uuid4(),
        item_type="article",
        title="AI News",
        summary="Summary",
        canonical_url="https://example.com/a",
        source_url=None,
        language_code="en",
        direction="ltr",
        status="approved",
        score=22,
        tags=["ai"],
        metrics={},
        sort_at=datetime(2026, 7, 3, tzinfo=UTC),
        primary_image_id=None,
        primary_media=None,
    )
    _override_session(FakeSession([content_item]))

    response = await _get("/content-items?status=approved&sort=score&limit=25")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["status"] == "approved"
    assert response.json()[0]["score"] == 22


async def test_content_item_detail_endpoint_returns_item():
    content_item = SimpleNamespace(
        id=uuid4(),
        item_type="article",
        title="AI News",
        summary="Summary",
        canonical_url="https://example.com/a",
        language_code="en",
        direction="ltr",
        status="new",
        score=17,
        tags=["ai"],
        metrics={},
        sort_at=datetime(2026, 7, 3, tzinfo=UTC),
        primary_image_id=None,
        primary_media=None,
    )
    fake_session = FakeSession([], item=content_item)
    _override_session(fake_session)

    response = await _get(f"/content-items/{content_item.id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["id"] == str(content_item.id)
    assert response.json()["title"] == "AI News"


async def test_content_item_detail_endpoint_returns_404_for_missing_item():
    fake_session = FakeSession([])
    _override_session(fake_session)

    response = await _get(f"/content-items/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "content item not found"


async def test_dashboard_summary_endpoint_returns_counts():
    _override_session(FakeSession([], scalar_results=[50, 3, 1284, 912, 18]))

    response = await _get("/dashboard/summary")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {
        "rss_feeds": 50,
        "telegram_channels": 3,
        "content_items": 1284,
        "media_assets": 912,
        "warnings": 18,
    }


async def test_ingest_runs_endpoint_returns_latest_runs():
    run = IngestRun(
        id=uuid4(),
        trigger="api",
        parser_version="test",
        status="succeeded",
        stats={"items": 12},
        started_at=datetime(2026, 7, 6, 8, 0, tzinfo=UTC),
        finished_at=datetime(2026, 7, 6, 8, 2, tzinfo=UTC),
    )
    _override_session(FakeSession([run]))

    response = await _get("/ingest/runs")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["status"] == "succeeded"
    assert response.json()[0]["stats"]["items"] == 12


async def test_media_assets_endpoint_returns_latest_media():
    media = MediaAsset(
        id=uuid4(),
        original_url="https://example.com/image.jpg",
        normalized_url="https://example.com/image.jpg",
        url_hash="hash",
        kind="image",
        mime_type="image/jpeg",
        width=1200,
        height=675,
        byte_length=64000,
        source_field="image",
        fetch_status="fetched",
        storage_path="/data/media/image.jpg",
    )
    _override_session(FakeSession([media]))

    response = await _get("/media-assets")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["normalized_url"] == "https://example.com/image.jpg"
    assert response.json()[0]["width"] == 1200
    assert response.json()[0]["byte_length"] == 64000


async def test_source_detail_endpoint_returns_source_detail():
    source = Source(
        id=uuid4(),
        platform="rss",
        name="TechCrunch",
        feed_url="https://techcrunch.com/feed/",
        source_group="ai",
        language_hint="en",
        active=True,
        health_status="healthy",
        last_parse_count=128,
        last_suitable_count=42,
        last_media_count=76,
    )
    fake_session = FakeSession([], item=source)
    _override_session(fake_session)

    response = await _get(f"/sources/{source.id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["name"] == "TechCrunch"
    assert response.json()["health_status"] == "healthy"
    assert response.json()["last_parse_count"] == 128


async def test_source_detail_endpoint_returns_404_for_missing_source():
    _override_session(FakeSession([]))

    response = await _get(f"/sources/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "source not found"


async def test_approve_content_item_endpoint_marks_item_approved():
    item = SimpleNamespace(id=uuid4(), status="new", metrics={})
    fake_session = FakeSession([], item=item)
    _override_session(fake_session)

    response = await _post(f"/content-items/{item.id}/approve", json={"notes": "ready"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["metrics"]["approval"]["notes"] == "ready"
    assert item.status == "approved"
    assert fake_session.committed is True
    assert fake_session.flushed is True


async def test_approve_content_item_endpoint_returns_404_for_missing_item():
    fake_session = FakeSession([])
    _override_session(fake_session)

    response = await _post(f"/content-items/{uuid4()}/approve", json={})

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "content item not found"
    assert fake_session.committed is False


class FakeSession:
    def __init__(self, rows, item=None, scalar_results=None):
        self.rows = rows
        self.item = item
        self.scalar_results = list(scalar_results or [])
        self.committed = False
        self.flushed = False

    async def scalars(self, stmt):
        return self.rows

    async def scalar(self, stmt):
        if self.scalar_results:
            return self.scalar_results.pop(0)
        return self.item

    async def get(self, model, item_id):
        return self.item if self.item and self.item.id == item_id else None

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


class FakeInsertResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeJobSession(FakeSession):
    def __init__(self):
        super().__init__([])
        self.job = None
        self.commit_count = 0

    async def execute(self, statement):
        params = statement.compile().params
        idempotency_key = params["idempotency_key"]
        if self.job is not None:
            assert self.job.idempotency_key == idempotency_key
            return FakeInsertResult(None)

        self.job = WorkflowJob(
            id=uuid4(),
            job_type=params["job_type"],
            status=JobStatus.QUEUED,
            payload=params["payload"],
            result={},
            priority=params["priority"],
            idempotency_key=idempotency_key,
            origin=params["origin"],
            pause_sensitive=params["pause_sensitive"],
            scheduled_for=params["scheduled_for"],
            attempt_count=0,
            max_attempts=params["max_attempts"],
            progress=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        return FakeInsertResult(self.job.id)

    async def get(self, model, item_id):
        assert model is WorkflowJob
        return self.job if self.job and self.job.id == item_id else None

    async def scalar(self, _statement):
        return self.job

    def add(self, _value):
        pass

    async def commit(self):
        self.committed = True
        self.commit_count += 1


def _override_session(fake_session: FakeSession) -> None:
    async def override():
        yield fake_session

    app.dependency_overrides[get_session] = override


async def _get(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(path, **kwargs)


async def _post(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(path, **kwargs)


async def _options(path: str, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.options(path, **kwargs)
