# Ingestion Backend

The backend service in `backend/` is the new ingestion path for RSS feeds and public Telegram channels. It uses FastAPI, PostgreSQL, Alembic, SQLAlchemy, `httpx`, `feedparser`, BeautifulSoup, and a worker command.

## Public Telegram

Public Telegram channels are fetched from static public pages:

```text
https://t.me/s/<telegram_username>
```

This replaces Telethon for public-channel ingestion. Telethon still makes sense for private channels or account-only access, but public pages avoid local Telegram user sessions and API credentials for the normal public-feed workflow.

## Proxy

If the host needs a proxy, export `ALL_PROXY` before running the worker or Docker Compose:

```bash
export ALL_PROXY=socks5h://127.0.0.1:10808
```

The service also accepts `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` through environment variables.

## Migrations

Run migrations from the backend environment:

```bash
cd backend
.venv/bin/alembic upgrade head
```

With Docker Compose:

```bash
docker compose run --rm api alembic upgrade head
```

## Legacy SQLite

`backend/scripts/migrate_legacy_sqlite.py` currently provides a minimal reader for legacy `news.db` article rows. It does not write into PostgreSQL yet.

## Content Scoring

Every parsed item is classified and scored before it is stored as a `content_items` row. The scorer uses keyword signals from the title, summary, content text, source categories, source group, and Telegram public-page engagement metadata when available.

Stored content items include:

- `score`: ranking signal for review and downstream post selection.
- `tags`: normalized source and classification tags.
- `metrics.classification`: category, keyword scores, matched keywords, source group, and engagement signals.

The content list endpoint supports review-oriented sorting:

```bash
curl 'http://localhost:8000/content-items?status=new&sort=score&limit=50'
```

## Selective `armin` Integration

Useful workflow ideas from `armin` are integrated only when adapted to the canonical `backend/` ingestion model and covered by tests. The backend continues to use public Telegram pages, RSS parsing with media extraction, raw payload storage, identity-based dedupe, and `media_assets` as the source media model.

## Seed Sources

The 50 active seed feeds live in `app/ingestion/seed_sources.py`. Seed them through the API:

```bash
curl -X POST http://localhost:8000/sources/seed
```

or from Python by calling `seed_sources(session)`.

## Trigger Ingestion

Run the worker manually:

```bash
cd backend
.venv/bin/python -m app.worker --trigger manual --platform rss --download-media
```

With Docker Compose:

```bash
docker compose run --rm worker
```

The API endpoint is:

```bash
curl -X POST http://localhost:8000/ingest/run \
  -H 'content-type: application/json' \
  -d '{"platforms":["rss"]}'
```

## Media Storage

Media candidates are stored in PostgreSQL first. Downloaded files are written under `MEDIA_ROOT`, defaulting to:

```text
/data/media/<sha-prefix>/<sha>.<ext>
```

The `media_assets` row stores checksum, MIME type, byte length, fetch status, and storage path.

## Future Post Agent Contract

The future post agent should read from:

- `content_items` for deduplicated article or Telegram post text.
- `item_identities` for provenance and dedupe confidence.
- `source_items` for source-specific raw fields and parser metadata.
- `media_assets` and `item_media` for primary images, inline images, enclosures, and attachments.
- `raw_payloads` for parser evidence and audit/debugging.

The agent should prefer `content_items.status = 'ready_for_agent'` when that workflow is added. Until then, `status = 'new'` marks freshly ingested content.
