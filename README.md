# NewsCraft

NewsCraft is moving to a backend-first architecture for collecting, normalizing, reviewing, and preparing AI and technology news.

The FastAPI backend is now the architectural center. The existing Streamlit app in `ai-news-agent/` is preserved as a legacy/temporary interface while the backend stabilizes.

## Backend Stack

- FastAPI API in `newscraft/api/`
- PostgreSQL primary persistence through SQLAlchemy 2.x
- Alembic migrations in `newscraft/db/migrations/`
- Pydantic request/response schemas
- Service/repository boundaries for ingestion, review, sources, assets, and content drafts
- Existing RSS, Hacker News, arXiv, GitHub, Hugging Face, YouTube RSS, and Telegram connectors reused through a compatibility adapter

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
  --news-db ai-news-agent/news.db \
  --approved-db ai-news-agent/approved_articles.db
```

The migration skips missing SQLite files and duplicate article URLs. It preserves article status where the old rows expose it.

## Legacy Streamlit

The old dashboard still lives in `ai-news-agent/`:

```bash
cd ai-news-agent
../.venv/bin/streamlit run app.py
```

It still uses the legacy SQLite modules. New backend work should target `newscraft/`.

## Tests

```bash
python -m compileall .
pytest
```
