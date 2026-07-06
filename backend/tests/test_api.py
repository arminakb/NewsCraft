from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import Source
from app.db.session import get_session
from app.main import app


def test_health_endpoint_returns_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_sources_endpoint_returns_source_summaries():
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

    response = TestClient(app).get("/sources")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["name"] == "OpenAI News"


def test_sources_seed_endpoint_seeds_catalog(monkeypatch):
    import app.api.routes as routes

    async def fake_seed_sources(session):
        return 50

    fake_session = FakeSession([])
    monkeypatch.setattr(routes, "seed_sources", fake_seed_sources)
    _override_session(fake_session)

    response = TestClient(app).post("/sources/seed")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"upserted": 50}
    assert fake_session.committed is True


def test_ingest_run_endpoint_triggers_ingestion(monkeypatch):
    import app.api.routes as routes

    class FakeService:
        def __init__(self, session):
            self.session = session

        async def run_once(self, platforms, source_ids, trigger):
            return {"status": "succeeded", "checked": 1, "items": 2, "platforms": platforms, "source_ids": source_ids}

    monkeypatch.setattr(routes, "IngestionService", FakeService)
    fake_session = FakeSession([])
    _override_session(fake_session)

    response = TestClient(app).post("/ingest/run", json={"platforms": ["rss"], "source_ids": ["source-1"]})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["items"] == 2
    assert response.json()["status"] == "succeeded"
    assert fake_session.committed is True


def test_content_items_endpoint_returns_latest_content_with_primary_media():
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

    response = TestClient(app).get("/content-items")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["score"] == 17
    assert response.json()[0]["tags"] == ["ai", "agent"]
    assert response.json()[0]["metrics"]["classification"]["category"] == "AI"
    assert response.json()[0]["primary_media"]["kind"] == "image"


def test_content_items_endpoint_accepts_status_and_score_sort_params():
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

    response = TestClient(app).get("/content-items?status=approved&sort=score&limit=25")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()[0]["status"] == "approved"
    assert response.json()[0]["score"] == 22


def test_content_item_detail_endpoint_returns_item():
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

    response = TestClient(app).get(f"/content-items/{content_item.id}")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["id"] == str(content_item.id)
    assert response.json()["title"] == "AI News"


def test_content_item_detail_endpoint_returns_404_for_missing_item():
    fake_session = FakeSession([])
    _override_session(fake_session)

    response = TestClient(app).get(f"/content-items/{uuid4()}")

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "content item not found"


def test_approve_content_item_endpoint_marks_item_approved():
    item = SimpleNamespace(id=uuid4(), status="new", metrics={})
    fake_session = FakeSession([], item=item)
    _override_session(fake_session)

    response = TestClient(app).post(f"/content-items/{item.id}/approve", json={"notes": "ready"})

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["metrics"]["approval"]["notes"] == "ready"
    assert item.status == "approved"
    assert fake_session.committed is True
    assert fake_session.flushed is True


def test_approve_content_item_endpoint_returns_404_for_missing_item():
    fake_session = FakeSession([])
    _override_session(fake_session)

    response = TestClient(app).post(f"/content-items/{uuid4()}/approve", json={})

    app.dependency_overrides.clear()
    assert response.status_code == 404
    assert response.json()["detail"] == "content item not found"
    assert fake_session.committed is False


class FakeSession:
    def __init__(self, rows, item=None):
        self.rows = rows
        self.item = item
        self.committed = False
        self.flushed = False

    async def scalars(self, stmt):
        return self.rows

    async def scalar(self, stmt):
        return self.item

    async def get(self, model, item_id):
        return self.item if self.item and self.item.id == item_id else None

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.committed = True


def _override_session(fake_session: FakeSession) -> None:
    async def override():
        yield fake_session

    app.dependency_overrides[get_session] = override
