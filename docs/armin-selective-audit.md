# Armin Selective Integration Audit

## Review Boundary

This audit reviews `origin/armin` against updated `main` after the `Amir` ingestion backend is merged. It is feature-level review, not a wholesale branch merge.

## Summary

- Decision: audit complete; see "Final Integration Result" below
- Default backend foundation: `backend/`
- Direct `newscraft/` package merge: rejected unless a later task proves a specific file should be ported manually

## Candidate Features

| Feature | Source paths in `armin` | Decision | Reason |
| --- | --- | --- | --- |
| Diagnostics API | `newscraft/services/diagnostics_service.py`, `newscraft/api/routers/diagnostics.py` | integrate | Behavior and async rewrite cost were acceptable |
| Approval workflow | `newscraft/repositories/approved_article_repository.py`, `newscraft/api/routers/approved.py` | integrate | Mapped onto the existing content status model |
| Draft workflow | `newscraft/repositories/content_draft_repository.py`, `newscraft/api/routers/content_pipeline.py` | integrate, later removed | Integrated as `backend/app/workflows/drafts.py`; removed as dead code in `33eb45b` once generation owned drafts |
| SQLite migration | `scripts/migrate_sqlite_to_postgres.py` | integrate, later removed | Ported as `backend/scripts/migrate_legacy_sqlite.py` in `0853f50`; removed as dead code in `33eb45b` |
| Docker migration startup | `docker-compose.yml` | integrate | Pattern adopted within the `backend/` layout |
| Telethon connector | `newscraft/connectors/fetchers.py` | reject | Current direction is public Telegram pages through `https://t.me/s/...` |
| Root `newscraft/` backend | `newscraft/**` | reject as wholesale merge | Competes with `backend/` foundation |

## Required Checks Before Porting

- Each accepted feature must have a failing test in `backend/tests/`.
- Each accepted feature must be adapted to async SQLAlchemy if it touches the database.
- No blocking network calls may be added to API request paths.
- No `telethon` dependency may be added for public Telegram channel ingestion.
- Existing RSS, public Telegram, media, and ingestion repository tests must continue passing.

## Final Integration Result

Integrated:

- Diagnostics endpoint.
- Approval workflow.
- Draft workflow. Ported as `backend/app/workflows/drafts.py`; superseded
  by the generation subsystem and removed as dead code in `33eb45b`.
- Docker migration startup.
- SQLite migration reader. Ported as `backend/scripts/migrate_legacy_sqlite.py`
  with `backend/tests/test_legacy_sqlite_migration.py` in `0853f50` — not
  under the `armin` name `scripts/migrate_sqlite_to_postgres.py` — and
  removed as dead code in `33eb45b`. Both commits are reachable from the
  current history; nothing in the tree reads SQLite today.

Rejected or deferred:

- Wholesale `newscraft/` backend merge.
- Telethon-based public Telegram ingestion.
- Flat article schema as canonical ingestion storage.
- Blocking network connectors inside API request paths.
