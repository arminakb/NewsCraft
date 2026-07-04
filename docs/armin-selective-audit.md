# Armin Selective Integration Audit

## Review Boundary

This audit reviews `origin/armin` against updated `main` after the `Amir` ingestion backend is merged. It is feature-level review, not a wholesale branch merge.

## Summary

- Decision: audit in progress
- Default backend foundation: `backend/`
- Direct `newscraft/` package merge: rejected unless a later task proves a specific file should be ported manually

## Candidate Features

| Feature | Source paths in `armin` | Decision | Reason |
| --- | --- | --- | --- |
| Diagnostics API | `newscraft/services/diagnostics_service.py`, `newscraft/api/routers/diagnostics.py` | review | Check behavior and async rewrite cost |
| Approval workflow | `newscraft/repositories/approved_article_repository.py`, `newscraft/api/routers/approved.py` | review | May map cleanly to `content_items.status` |
| Draft workflow | `newscraft/repositories/content_draft_repository.py`, `newscraft/api/routers/content_pipeline.py` | review | Useful for future agent output |
| SQLite migration | `scripts/migrate_sqlite_to_postgres.py` | review | Useful only if legacy SQLite files still matter |
| Docker migration startup | `docker-compose.yml` | review | Useful pattern, must fit `backend/` layout |
| Telethon connector | `newscraft/connectors/fetchers.py` | reject | Current direction is public Telegram pages through `https://t.me/s/...` |
| Root `newscraft/` backend | `newscraft/**` | reject as wholesale merge | Competes with `backend/` foundation |

## Required Checks Before Porting

- Each accepted feature must have a failing test in `backend/tests/`.
- Each accepted feature must be adapted to async SQLAlchemy if it touches the database.
- No blocking network calls may be added to API request paths.
- No `telethon` dependency may be added for public Telegram channel ingestion.
- Existing RSS, public Telegram, media, and ingestion repository tests must continue passing.
