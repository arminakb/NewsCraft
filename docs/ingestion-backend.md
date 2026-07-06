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
export ALL_PROXY=socks5h://host.docker.internal:10808
```

Use `127.0.0.1` only for commands that run directly on the host. Docker containers need `host.docker.internal` to reach a proxy bound to the host loopback interface. The service accepts `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` through environment variables.

See `docs/proxy-validation-notes.md` for the 2026-07-06 requested source validation benchmark and Docker proxy failure analysis.

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

Every parsed item is normalized, classified, bucketed, scored, and checked for rewrite readiness before it is stored as a `content_items` row. The pipeline keeps one canonical deduplicated content item record and stores content intelligence metadata on that row.

Stored content items include:

- `score`: ranking signal for review and downstream post selection.
- `content_type`: one of `news`, `article`, `tutorial`, `research`, `video`, `tool_update`, `vendor_update`, `longform`, `promo`, or `low_signal`.
- `rewrite_bucket`: one of `daily_news`, `technical_article`, `tutorial`, `research`, `video`, `vendor_update`, `longform_analysis`, `promo_review`, or `low_signal_review`.
- `is_rewrite_ready`, `rewrite_ready_reason`, and `rewrite_blockers`: readiness gate output for downstream generation.
- `source_tier`, `freshness_bucket`, `quality_status`, `classification_reasons`, `classification_metadata`, `score_breakdown`, and `ranking_metadata`.
- `tags` and `metrics.classification`: legacy-compatible normalized source and classification tags.

The scorer stores a breakdown based on:

```text
final_score =
    relevance_score
  + source_tier_bonus
  + freshness_score
  + capped_media_quality_bonus
  + engagement_bonus
  + content_type_bonus
  - stale_penalty
  - archive_penalty
  - promotional_penalty
  - low_signal_penalty
  - emoji_title_penalty
  - overlong_penalty
```

Source tiers are stored as ranking metadata. Tier A currently covers high-trust AI and technical sources such as DeepMind Blog, AWS Machine Learning Blog, LLM Hugging Face, CVision, AI2 YouTube, and Machine Learning Mastery Blog. Tier B covers conditional or narrower sources.

The rewrite readiness gate blocks unsupported, promotional, low-signal, duplicate, under-specified, stale/archive daily-news, or scoreless items. Longform archive items may remain ready for `longform_analysis`.

The content list endpoint supports review-oriented sorting:

```bash
curl 'http://localhost:8000/content-items?status=new&sort=score&limit=50'
```

Review by content intelligence fields:

```bash
curl 'http://localhost:8000/content-items?content_type=news&is_rewrite_ready=true&sort=score'
curl 'http://localhost:8000/content-items?rewrite_bucket=tutorial'
curl 'http://localhost:8000/content-items?quality_status=low_signal'
```

Fetch one content item, including primary media metadata when available:

```bash
curl 'http://localhost:8000/content-items/<content_item_id>'
```

## Media Quality

Media candidates are classified before they are linked to content:

- `media_quality`: `good`, `low`, `tracking`, or `unknown`.
- `media_confidence`: normalized confidence used for primary selection.
- `media_source_type`: `external`, `temporary_external`, or `stored`.
- `asset_role`: `primary_image`, `thumbnail`, `inline_image`, `video`, `document`, `preview`, `tracking_pixel`, or `unknown`.
- `is_primary_candidate` and `is_primary`: primary media selection state.

Tracking pixels, Medium stat URLs, tiny images, unknown assets, and low-confidence assets are excluded from primary media selection. YouTube thumbnails are allowed as primary images for video content. Telegram CDN URLs are treated as temporary external media until downloaded and stored locally.

## Source Health

Sources persist fetch and parsing health:

- `healthy`: recent fetch parsed usable content.
- `degraded`: fetch succeeded but the feed was malformed, parsed zero items, or produced zero suitable items.
- `broken`: HTTP errors such as 403/404 or network failures such as DNS/connect errors.
- `disabled`: source is inactive or has an explicit disabled reason.

Stored health fields include last HTTP status, last success/failure timestamps, failure count, last error type/message, parsed count, suitable count, and media count. The diagnostics endpoint returns source health totals and severity-sorted problem sources.

## Validation Report

Generate a markdown report from the configured database:

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/content_intelligence_report.py
```

The report is written to:

```text
validation/content-intelligence-report.md
```

It summarizes source health, content type distribution, rewrite buckets, top candidates per bucket, promo/excluded items, low-signal/parser problems, media quality, scoring warnings, duplicates, score breakdown examples, and final recommendations.

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
