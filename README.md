# NewsCraft

NewsCraft is a FastAPI and PostgreSQL backend for collecting, normalizing, ranking, and reviewing news content from public sources.

The active backend lives in `backend/`. The legacy Streamlit MVP has been removed; new ingestion and review workflows should use the backend service, worker, and API.

## Features

- Ingests RSS/Atom feeds and public Telegram channel pages.
- Stores raw payloads, source items, deduplicated content items, identities, and media assets in PostgreSQL.
- Extracts feed media, Telegram images/previews/documents, and stores media metadata for downstream use.
- Scores and classifies content with backend-native keyword and engagement signals.
- Supports approval and draft workflows for downstream post generation.
- Provides diagnostics and manual ingestion endpoints.
- Includes a minimal legacy SQLite article reader for user-provided old `news.db` files.

## Tech Stack

- FastAPI
- PostgreSQL
- SQLAlchemy 2 async ORM
- Alembic
- httpx
- feedparser
- BeautifulSoup/lxml
- pytest
- Docker Compose

## Project Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── content/
│   │   ├── db/
│   │   ├── diagnostics/
│   │   ├── ingestion/
│   │   ├── media/
│   │   ├── normalization/
│   │   ├── sources/
│   │   └── workflows/
│   ├── alembic/
│   ├── scripts/
│   └── tests/
├── docs/
├── docker-compose.yml
└── README.md
```

## Run With Docker Compose

```bash
docker compose build
docker compose up -d postgres
docker compose up api
```

The API service runs Alembic migrations before Uvicorn starts.

Check health:

```bash
curl http://localhost:8000/health
```

Seed sources:

```bash
curl -X POST http://localhost:8000/sources/seed
```

Run one manual worker ingestion pass:

```bash
docker compose run --rm worker
```

Or trigger ingestion through the API:

```bash
curl -X POST http://localhost:8000/ingest/run \
  -H 'content-type: application/json' \
  -d '{"platforms":["rss"]}'
```

## Useful Endpoints

- `GET /health`
- `GET /diagnostics`
- `GET /sources`
- `POST /sources/seed`
- `POST /ingest/run`
- `GET /content-items`
- `GET /content-items?status=new&sort=score&limit=50`
- `GET /content-items/{content_item_id}`
- `POST /content-items/{content_item_id}/approve`

Content item responses include `score`, `tags`, classification metadata, `primary_image_id`, and `primary_media` when a primary media asset is available.

## Local Backend Development

```bash
cd backend
.venv/bin/python -m pytest tests -v
```

If the virtual environment does not exist yet, create it and install backend dependencies from `backend/pyproject.toml`.

## Environment

Copy the root example if useful:

```bash
cp .env.example .env
```

Common variables:

```bash
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft
MEDIA_ROOT=/data/media
ALL_PROXY=
```

If your network needs a proxy, export it before running Compose:

```bash
export ALL_PROXY=socks5h://127.0.0.1:10808
```

## Documentation

- Backend ingestion details: `docs/ingestion-backend.md`
- Source catalog notes: `docs/ingestion-source-catalog.md`
- Selective integration audit: `docs/armin-selective-audit.md`

## Notes

- Local databases, virtual environments, generated media, cache files, and `.env` files are ignored by Git.
- The legacy SQLite reader only reads old article rows; it does not write into PostgreSQL yet.
