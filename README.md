# NewsCraft

NewsCraft is a FastAPI and PostgreSQL backend for collecting, normalizing, ranking, and reviewing news content from public sources.

The active backend lives in `backend/`. The ingestion dashboard lives in `frontend/`. The legacy Streamlit MVP has been removed; new ingestion and review workflows should use the backend service, worker, API, and dashboard.

## Features

- Ingests RSS/Atom feeds and public Telegram channel pages.
- Stores raw payloads, source items, deduplicated content items, identities, and media assets in PostgreSQL.
- Extracts feed media, Telegram images/previews/documents, and stores media metadata for downstream use.
- Classifies, scores, buckets, and readiness-checks content for downstream rewriting.
- Supports evidence-backed research, multi-platform package generation, immutable editorial revisions, exact approval, deterministic exports, reviewed Telegram scheduling/publishing, and manual publication tracking for Instagram, X, and blog.
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

## Workflow runtime

`docker compose up --build` starts PostgreSQL, API, frontend, capability-separated leased workers, and a scheduler. The source/generation worker cannot publish, and the publishing worker cannot construct source or AI dependencies. The scheduler creates source collection jobs; API mutation endpoints enqueue jobs and return immediately.

- Newsroom: http://127.0.0.1:3000
- API: http://127.0.0.1:8000
- Global pause holds scheduled/automation work; manual Run ingest remains available.
- Review is the default. No live credentials or publishing are used by default tests.

### Local Telegram automation dry run

1. Copy `.env.example` to `.env`, leave real credential values empty, and configure credential references in the UI.
2. Create the destination and run its destination check before enabling a route.
3. Activate the route to record a gap-free new-only boundary; activation does not backfill older messages.
4. Select the fake provider and start a dry run. A dry run is always review-only and cannot publish.
5. Open the generated draft, compare its source evidence, and review the exact revision.
6. Only after the fake-provider review succeeds should an operator opt in to real credentials by filling the referenced environment variables, then restart the API and only the relevant worker.

Source access uses `TELEGRAM_SOURCE_EDITOR_API_ID`, `TELEGRAM_SOURCE_EDITOR_API_HASH`, and `TELEGRAM_SOURCE_EDITOR_SESSION`. Generation uses `OPENROUTER_API_KEY` only when an enabled OpenRouter profile references it. Publishing alone receives `TELEGRAM_DESTINATION_NEWS_TOKEN`. The scheduler receives none of these values.

### Research and generation

Manual source intake and evidence-backed research are operated from Inbox. Generated Telegram,
Instagram, X, and blog content packages, immutable editorial revisions, and exact approval are
handled in Drafts and Review, with provider and prompt-template configuration in Content
Settings. Fake mode is credential-free; OpenRouter and local Codex execution are explicit
opt-ins with bounded, validated provider-profile settings. Instagram, X, and blog are
manual-only destinations; Telegram uses its separate reviewed publishing boundary. All
platform previews are approximations rather than live platform state.

See the [research and generation operator runbook](docs/operations/research-and-generation.md)
for exact environment settings and generation safety boundaries. See the
[multi-platform manual publishing runbook](docs/operations/manual-publishing-packages.md) for
the exact review, immutable edit, approval, copy/export, manual-plan, checklist, and completion
flow plus offline acceptance limitations.

Run the PostgreSQL queue contract suite:

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests/postgres -q
```

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
  -d '{"request_id":"123e4567-e89b-42d3-a456-426614174000","platforms":["rss"]}'
```

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

Content item responses include complete text, authors, publication time, source ID, classification metadata, `score`, `content_type`, `rewrite_bucket`, rewrite readiness fields, score breakdowns, `primary_image_id`, and `primary_media` with media quality metadata when available.

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
npm run typecheck
npm run build
npm run test:e2e
```

The Compose stack is local-only by default: it binds PostgreSQL, API, and frontend host ports to `127.0.0.1`.

Playwright uses its managed Chromium browser unless `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` is set. On this host, browser verification requires the installed Chromium binary and single-process mode:

```bash
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/wingman/.cache/puppeteer/chrome-headless-shell/linux-150.0.7871.24/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npm run test:e2e
```

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

If your network needs a proxy, export it before running Compose:

```bash
export ALL_PROXY=socks5h://host.docker.internal:10808
```

Use `127.0.0.1` only for backend commands that run directly on the host. Docker containers need `host.docker.internal` to reach a proxy bound to the host loopback interface.

## Documentation

- Multi-platform manual publishing: [operator runbook](docs/operations/manual-publishing-packages.md)
- Research and generation: [operator runbook](docs/operations/research-and-generation.md)
- Backend ingestion details: `docs/ingestion-backend.md`
- Source catalog notes: `docs/ingestion-source-catalog.md`
- Selective integration audit: `docs/armin-selective-audit.md`

## Notes

- Local databases, virtual environments, generated media, cache files, and `.env` files are ignored by Git.
- The legacy SQLite reader only reads old article rows; it does not write into PostgreSQL yet.
