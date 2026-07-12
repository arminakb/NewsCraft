# NewsCraft

NewsCraft is a FastAPI and PostgreSQL system for collecting, normalizing, ranking, reviewing, and producing Persian news content from public sources.

The active backend lives in `backend/`. The ingestion dashboard lives in `frontend/`. The legacy Streamlit MVP has been removed; new ingestion and review workflows should use the backend service, worker, API, and dashboard.

## Features

- Ingests RSS/Atom feeds and public Telegram channel pages.
- Stores raw payloads, source items, deduplicated content items, identities, and media assets in PostgreSQL.
- Extracts feed media, Telegram images/previews/documents, and stores media metadata for downstream use.
- Classifies, scores, buckets, and readiness-checks content for downstream rewriting.
- Supports approval and draft workflows for downstream post generation.
- Runs a durable event-driven Persian content-production workflow with replay-safe artifacts and traced handler execution.
- Enforces separate human shortlist and final-package approval gates before creating a Telegram dispatch handoff.
- Supports safe article extraction, bounded DuckDuckGo enrichment, OpenAI Responses, and OpenRouter Chat Completions adapters.
- Provides source health diagnostics, validation reports, and manual ingestion endpoints.
- Provides a Next.js ingestion dashboard for source health, runs, content queue, media extraction, and source detail review.
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
- Next.js
- TanStack Query/Table
- Tailwind CSS and shadcn/ui
- Docker Compose

## Project Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── content/
│   │   ├── content_production/
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
├── frontend/
│   ├── app/
│   ├── components/
│   ├── e2e/
│   ├── lib/
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

Run the dashboard with the API and database:

```bash
docker compose up frontend api postgres
```

The dashboard is available at `http://localhost:3000` and proxies API calls through the frontend to the backend service.

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

Export a date-range daily news bundle for the writing agent:

```bash
docker compose run --rm api python -m app.daily_bundle \
  --start 2026-07-05 \
  --end 2026-07-06 \
  --topic "AI" \
  --topic "economy" \
  --output /workspace/today-news/2026-07-05 \
  --download-media
```

The bundle command first runs the existing RSS, Atom, and public Telegram ingestion path, then adds no-signup discovery from GDELT, Google News RSS, and Hacker News. It writes `index.md`, `items.json`, `sources.json`, article markdown files, and image references under the selected output folder.

Or trigger ingestion through the API:

```bash
curl -X POST http://localhost:8000/ingest/run \
  -H 'content-type: application/json' \
  -d '{"platforms":["rss"]}'
```

## Content Production

The content-production backend uses a durable PostgreSQL outbox and an explicit event dispatcher:

```text
API command
→ durable outbox
→ worker
→ dispatcher
→ traced handlers
→ idempotent artifacts
→ human approval
→ dispatch handoff
```

After shortlist approval, each selected item passes through bounded sufficiency routing. The workflow may safely extract the source article and perform bounded enrichment before re-checking sufficiency. Sufficient items proceed through an evidence-grounded editorial brief, one-pass Persian draft, automated quality evaluation, media/package resolution, and a second mandatory human approval gate.

Approval creates a `TelegramDispatchRequest` handoff only. NewsCraft does not publish to Telegram.

Apply migrations before processing content-production events:

```bash
cd backend
.venv/bin/alembic upgrade head
.venv/bin/alembic heads
```

The expected migration head is `0016_persian_llm_generation`. API contracts include request creation and inspection, shortlist approval/rejection, run artifact inspection, final package approval/rejection, revision requests, and event inspection under `/content-production/*`.

See [Content production architecture](docs/content-production.md) for module boundaries, provider configuration, safety controls, test commands, and current limitations.

## Useful Endpoints

- `GET /health`
- `GET /dashboard/summary`
- `GET /diagnostics`
- `GET /sources`
- `GET /sources/{source_id}`
- `POST /sources/seed`
- `GET /ingest/runs`
- `POST /ingest/run`
- `GET /media-assets`
- `GET /content-items`
- `GET /content-items?status=new&sort=score&limit=50`
- `GET /content-items?content_type=news&is_rewrite_ready=true&sort=score`
- `GET /content-items?rewrite_bucket=tutorial`
- `GET /content-items?quality_status=low_signal`
- `GET /content-items/{content_item_id}`
- `POST /content-items/{content_item_id}/approve`

Content item responses include `score`, `content_type`, `rewrite_bucket`, rewrite readiness fields, score breakdowns, `primary_image_id`, and `primary_media` with media quality metadata when available.

Generate the content intelligence validation report:

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/content_intelligence_report.py
```

The report is written to `validation/content-intelligence-report.md`.

## Local Backend Development

```bash
cd backend
.venv/bin/python -m pytest tests -v
```

If the virtual environment does not exist yet, create it and install backend dependencies from `backend/pyproject.toml`.

## Local Frontend Development

```bash
cd frontend
npm install
npm run dev
```

Useful frontend checks:

```bash
npm run test
npm run build
npm run test:e2e
```

If Playwright browser downloads are unavailable in your environment, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to an installed Chromium binary. The local config defaults to `/usr/bin/chromium`.

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
NO_PROXY=postgres,localhost,127.0.0.1
```

Content-production providers default to disabled for safe local and automated testing. Configure credentials only through the process environment; `.env.example` contains empty placeholders. Never use live provider credentials in the test suite.

If your network needs a proxy, export it before running Compose:

```bash
export ALL_PROXY=socks5h://host.docker.internal:10808
```

Use `127.0.0.1` only for backend commands that run directly on the host. Docker containers need `host.docker.internal` to reach a proxy bound to the host loopback interface.

## Documentation

- Backend ingestion details: `docs/ingestion-backend.md`
- Content production architecture: `docs/content-production.md`
- Source catalog notes: `docs/ingestion-source-catalog.md`
- Selective integration audit: `docs/armin-selective-audit.md`

## Notes

- Local databases, virtual environments, generated media, cache files, and `.env` files are ignored by Git.
- The legacy SQLite reader only reads old article rows; it does not write into PostgreSQL yet.
