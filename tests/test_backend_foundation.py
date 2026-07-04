import asyncio
from pathlib import Path

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
from newscraft.repositories.paper_asset_repository import PaperAssetRepository
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


def test_backend_ranking_scores_source_specific_items():
    from newscraft.services.ranking_service import classify_and_score

    github = classify_and_score(
        {
            "source_type": "github",
            "title": "owner/agent-framework",
            "summary": "LLM agent framework",
            "metrics": {"stars": 100, "forks": 3},
        }
    )
    huggingface = classify_and_score(
        {
            "source_type": "huggingface",
            "title": "org/model",
            "summary": "text-generation llm",
            "metrics": {"likes": 5, "downloads": 250},
        }
    )
    telegram = classify_and_score(
        {
            "source_type": "telegram",
            "title": "AI agent launch",
            "summary": "https://example.com",
            "metrics": {"views": 1000, "forwards": 2, "quality_weight": 1.5},
        }
    )

    assert github["category"] == "Tool"
    assert github["score"] > 100
    assert huggingface["category"] == "Model"
    assert huggingface["score"] >= 8
    assert telegram["category"] == "AI"
    assert telegram["score"] >= 10


def test_backend_connector_registry_uses_newscraft_fetchers():
    from newscraft.connectors import get_connector_fetchers

    fetchers = get_connector_fetchers()

    assert set(fetchers) == {"rss", "hacker_news", "arxiv", "github", "huggingface", "youtube", "telegram"}
    assert all(fetcher.__module__.startswith("newscraft.connectors.") for fetcher in fetchers.values())


def test_backend_rss_fetcher_normalizes_feed_without_legacy_import(monkeypatch):
    from newscraft.connectors import fetchers

    entry = {
        "title": "AI story",
        "link": "https://example.com/ai",
        "published": "Thu, 02 Jul 2026 00:00:00 GMT",
        "summary": "<p>Hello</p>",
    }
    monkeypatch.setattr(fetchers, "RSS_FEEDS", [{"name": "Example Feed", "url": "https://example.com/feed", "source_group": "company_news"}])
    monkeypatch.setattr(fetchers.feedparser, "parse", lambda _url: type("Feed", (), {"feed": {}, "entries": [entry]})())

    articles = fetchers.fetch_rss_articles()

    assert articles == [
        {
            "source": "Example Feed",
            "source_type": "rss",
            "connector": "rss",
            "source_group": "company_news",
            "title": "AI story",
            "url": "https://example.com/ai",
            "published_at": "2026-07-02T00:00:00",
            "summary": "<p>Hello</p>",
            "category": "General",
            "score": 0,
            "metrics": {},
        }
    ]


def test_diagnostics_service_returns_source_and_database_checks(db_session, monkeypatch):
    import newscraft.services.diagnostics_service as diagnostics_module

    def ok_fetch(**_kwargs):
        return [{"title": "ok", "url": "https://example.com"}]

    for name in (
        "fetch_rss_articles",
        "fetch_hacker_news",
        "fetch_arxiv_ai",
        "fetch_github_repositories",
        "fetch_huggingface_models",
        "fetch_youtube_videos",
        "fetch_telegram_posts_sync",
    ):
        monkeypatch.setattr(diagnostics_module.fetchers, name, ok_fetch, raising=False)

    result = diagnostics_module.DiagnosticsService(db_session).source_diagnostics()
    checks = {check["name"]: check for check in result["checks"]}

    assert result["status"] == "ok"
    assert set(checks) == {"postgresql", "rss", "hacker_news", "arxiv", "github", "huggingface", "youtube", "telegram"}
    assert all(check["status"] == "ok" for check in checks.values())
    assert all("latency_ms" in check for check in checks.values())
    assert checks["postgresql"]["message"] == "database reachable"


def test_article_normalizer_cleans_url_summary_metadata_and_dates():
    from newscraft.services.normalization_service import normalize_article

    normalized = normalize_article(
        {
            "title": "  OpenAI   ships\nmodel  ",
            "url": "HTTPS://Example.COM/story?utm_source=x&keep=1#section",
            "summary": "<p>Hello&nbsp;<strong>world</strong></p>",
            "source": " Example ",
            "source_type": "rss",
            "source_group": " company_news ",
            "author": " Ada ",
            "published_at": "Thu, 02 Jul 2026 10:30:00 GMT",
            "language": " EN ",
            "metrics": {"views": 12},
            "metadata": {"structured_summary": {"what_it_is": "A story"}},
            "tags": ["AI", "Launch"],
        }
    )

    assert normalized["title"] == "OpenAI ships model"
    assert normalized["url"] == "https://example.com/story?keep=1"
    assert normalized["summary"] == "Hello world"
    assert normalized["source"] == "Example"
    assert normalized["source_group"] == "company_news"
    assert normalized["author"] == "Ada"
    assert normalized["language"] == "en"
    assert normalized["published_at"].isoformat() == "2026-07-02T10:30:00+00:00"
    assert normalized["metadata"]["canonical_url"] == "https://example.com/story?keep=1"
    assert normalized["metadata"]["original_url"] == "HTTPS://Example.COM/story?utm_source=x&keep=1#section"
    assert normalized["metadata"]["metrics"] == {"views": 12}
    assert normalized["metadata"]["tags"] == ["AI", "Launch"]
    assert normalized["raw_data"]["title"] == "  OpenAI   ships\nmodel  "


def test_ingestion_service_normalizes_and_skips_malformed_items(db_session):
    service = IngestionService(
        db_session,
        connector_fetchers={
            "fake": lambda **_: [
                {
                    "title": "  AI&nbsp;story ",
                    "url": "https://example.com/story?utm_campaign=x",
                    "source": " Fake Feed ",
                    "source_type": "rss",
                    "summary": "<b>Useful</b> summary",
                    "metrics": {"views": 3},
                },
                {"title": "Missing URL"},
            ]
        },
    )

    run = service.run(selected_sources=["fake"])
    article = ArticleRepository(db_session).list()[0]

    assert run.total_fetched == 2
    assert run.total_saved == 1
    assert article.title == "AI story"
    assert article.url == "https://example.com/story"
    assert article.summary == "Useful summary"
    assert article.source == "Fake Feed"
    assert article.article_metadata["metrics"] == {"views": 3}
    assert run.source_logs[0].log_metadata["skipped_malformed"] == 1


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


def test_asset_service_prepares_arxiv_files_from_backend(db_session, tmp_path, monkeypatch):
    import newscraft.services.asset_service as asset_module

    article = ArticleRepository(db_session).upsert(
        {
            "title": "Reliable AI Agents",
            "url": "https://arxiv.org/abs/2602.12345",
            "source": "arXiv",
            "source_type": "arxiv",
            "summary": "This paper studies reliable AI agents.",
            "metadata": {"authors": ["Ada Lovelace"]},
        }
    )
    paper_root = tmp_path / "papers"

    def fake_download(arxiv_id, output_dir, force=False):
        paper_dir = Path(output_dir) / arxiv_id
        paper_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = paper_dir / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")
        return str(pdf_path)

    monkeypatch.setattr(asset_module, "download_arxiv_pdf", fake_download, raising=False)
    monkeypatch.setattr(
        asset_module,
        "extract_text_from_pdf",
        lambda _path: """
        Abstract
        This paper studies reliable AI agents.
        Introduction
        Current agents fail silently.
        Method
        We add lightweight checks.
        Results
        The checks catch common failures.
        """,
        raising=False,
    )

    asset = asset_module.AssetService(db_session).prepare_arxiv_assets(article.id, output_dir=str(paper_root))

    assert asset.asset_metadata["status"] == "ready"
    assert asset.asset_metadata["arxiv_id"] == "2602.12345"
    assert Path(asset.pdf_path).exists()
    assert Path(asset.text_path).read_text(encoding="utf-8").startswith("Abstract")
    assert Path(asset.notebooklm_brief_path).name == "research_brief.md"
    assert Path(asset.instagram_brief_path).name == "instagram_brief.md"
    assert Path(asset.podcast_brief_path).name == "podcast_brief.md"


def test_paper_asset_upsert_preserves_existing_paths_when_only_metadata_changes(db_session):
    repo = PaperAssetRepository(db_session)

    ready = repo.upsert(
        {
            "article_id": 1,
            "pdf_path": "paper.pdf",
            "text_path": "full_text.txt",
            "notebooklm_brief_path": "research_brief.md",
            "instagram_brief_path": "instagram_brief.md",
            "podcast_brief_path": "podcast_brief.md",
            "metadata": {"status": "ready"},
        }
    )
    failed = repo.upsert({"article_id": ready.article_id, "metadata": {"status": "failed", "error": "temporary"}})

    assert failed.pdf_path == "paper.pdf"
    assert failed.text_path == "full_text.txt"
    assert failed.asset_metadata["status"] == "failed"


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
