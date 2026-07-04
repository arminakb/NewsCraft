import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from newscraft.api.deps import get_db
from newscraft.api.main import app
from newscraft.db.base import Base
from newscraft.domain.schemas import ArticleCreate, ContentDraftCreate
from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.approved_article_repository import ApprovedArticleRepository
from newscraft.repositories.content_draft_repository import ContentDraftRepository
from newscraft.repositories.ingestion_run_repository import IngestionRunRepository
from newscraft.services.article_service import ArticleService
from newscraft.services.content_pipeline_service import ContentPipelineService
from newscraft.services.ingestion_service import IngestionService
from scripts.migrate_sqlite_to_postgres import migrate


@pytest.fixture()
def db_session(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False}, future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


def test_fastapi_imports_and_health_works(client):
    status, body = asyncio.run(_asgi_get(client, "/health"))

    assert status == 200
    assert b'"status":"ok"' in body
    assert b'"database":"ok"' in body


def test_article_repository_insert_list_update_and_deduplicate(db_session):
    repo = ArticleRepository(db_session)
    article = ArticleCreate(title="OpenAI ships model", url="https://example.com/a", source="Example")

    first = repo.upsert(article.model_dump())
    duplicate = repo.upsert(article.model_dump())
    repo.update_status(first.id, "approved")
    rows = repo.list(limit=10)

    assert first.id == duplicate.id
    assert len(rows) == 1
    assert rows[0].status == "approved"


def test_ingestion_service_runs_fake_connector_and_skips_duplicates(db_session):
    service = IngestionService(
        db_session,
        connector_fetchers={
            "fake": lambda **_: [
                {"title": "AI agent", "url": "https://example.com/agent", "source": "Fake", "summary": "AI tool"},
                {"title": "AI agent", "url": "https://example.com/agent", "source": "Fake", "summary": "AI tool"},
            ]
        },
    )

    run = service.run(selected_sources=["fake"])

    assert run.total_fetched == 2
    assert run.total_saved == 1
    assert run.total_duplicates == 1
    assert ArticleRepository(db_session).list()[0].connector == "fake"


def test_article_approval_flow(db_session):
    article_repo = ArticleRepository(db_session)
    approved_repo = ApprovedArticleRepository(db_session)
    article = article_repo.upsert({"title": "Approve me", "url": "https://example.com/approve", "source": "Example"})
    service = ArticleService(db_session, article_repo=article_repo, approved_repo=approved_repo)

    approved = service.approve(article.id)

    assert approved.status == "approved"
    assert article_repo.get(article.id).status == "approved"
    assert approved_repo.list()[0].url == article.url


def test_content_draft_crud(db_session):
    article = ArticleRepository(db_session).upsert({"title": "Draft me", "url": "https://example.com/draft", "source": "Example"})
    service = ContentPipelineService(db_session, repo=ContentDraftRepository(db_session))

    draft = service.create(ContentDraftCreate(article_id=article.id, platform="telegram", draft_text="Draft"))
    updated = service.update(draft.id, {"status": "needs_review", "human_notes": "tighten hook"})

    assert updated.status == "needs_review"
    assert service.list()[0].human_notes == "tighten hook"


def test_migration_script_missing_old_dbs_does_not_crash(db_session, tmp_path):
    summary = migrate(
        db_session,
        news_db_path=tmp_path / "missing-news.db",
        approved_db_path=tmp_path / "missing-approved.db",
    )

    assert summary["articles_seen"] == 0
    assert summary["approved_seen"] == 0


def test_api_schemas_validate_content_draft_status():
    draft = ContentDraftCreate(article_id=1, platform="telegram", draft_text="hello", status="draft")

    assert draft.status == "draft"
    with pytest.raises(ValueError):
        ContentDraftCreate(article_id=1, platform="telegram", draft_text="hello", status="bad")


async def _asgi_get(asgi_app, path):
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await asgi_app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
        },
        receive,
        send,
    )
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return status, body
