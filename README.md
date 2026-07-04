# NewsCraft

NewsCraft is a backend-first service for collecting, normalizing, reviewing, and preparing AI and technology news.

The FastAPI backend in `newscraft/` is the single source of truth. The legacy Streamlit/SQLite implementation has been removed after its useful ingestion, ranking, diagnostics, review, approved-article, and paper-asset logic was migrated into the backend.

## Backend Stack

- FastAPI API in `newscraft/api/`
- PostgreSQL primary persistence through SQLAlchemy 2.x
- Alembic migrations in `newscraft/db/migrations/`
- Pydantic request/response schemas
- Service/repository boundaries for ingestion, review, sources, assets, and content drafts
- Backend-owned RSS, Hacker News, arXiv, GitHub, Hugging Face, YouTube RSS, and Telegram connectors

## Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Set `DATABASE_URL` in `.env`:

```bash
DATABASE_URL=postgresql+psycopg://newscraft:newscraft@localhost:5432/newscraft
```

Optional connector variables:

```bash
GITHUB_TOKEN=
HUGGINGFACE_TOKEN=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_NAME=telegram_news_session
LOG_LEVEL=INFO
```

Do not commit `.env`, Telegram session files, or local database files.

## Run Locally

```bash
alembic upgrade head
python scripts/seed_sources.py
uvicorn newscraft.api.main:app --reload
```

Then open `http://127.0.0.1:8000/docs`.

## Docker

```bash
docker compose up --build
```

This starts PostgreSQL and the API, runs Alembic migrations, and exposes the API on `http://127.0.0.1:8000`.

## API Examples

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/sources
curl -X POST http://127.0.0.1:8000/ingestion/runs \
  -H "Content-Type: application/json" \
  -d '{"selected_sources":["rss","hacker_news","arxiv"]}'
curl http://127.0.0.1:8000/articles
curl -X POST http://127.0.0.1:8000/articles/1/approve
curl http://127.0.0.1:8000/approved-articles
```

## SQLite Migration

Existing SQLite data can be copied into PostgreSQL after migrations:

```bash
python scripts/migrate_sqlite_to_postgres.py \
  --news-db /path/to/news.db \
  --approved-db /path/to/approved_articles.db
```

The migration skips missing SQLite files and duplicate article URLs. It preserves article status where the old rows expose it.

## Tests

```bash
python -m compileall .
pytest
```
