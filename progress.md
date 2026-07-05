# NewsCraft Content Intelligence Upgrade Progress

## Current Status

Overall status: In Progress

## Phase Progress

| Phase | Name | Status | Commit |
|---:|---|---|---|
| 0 | Progress Tracking and Baseline Audit | Completed | Pending |
| 1 | Schema and Data Model Design | Pending | Pending |
| 2 | Content Type Classification | Pending | Pending |
| 3 | Rewrite Buckets and Candidate Queues | Pending | Pending |
| 4 | Telegram Title Normalization | Pending | Pending |
| 5 | Type-Aware Scoring and Ranking | Pending | Pending |
| 6 | Rewrite Readiness Gate | Pending | Pending |
| 7 | Media Quality and Primary Media Selection | Pending | Pending |
| 8 | Source Health and Diagnostics | Pending | Pending |
| 9 | API Filters and Response Updates | Pending | Pending |
| 10 | Validation Report Upgrade | Pending | Pending |
| 11 | Documentation and Final Verification | Pending | Pending |

## Latest Update

- Completed Phase 0 progress tracking and baseline backend audit.
- Baseline test run collected 47 tests but hung at the first API health test.

## Baseline Audit

- Models: `backend/app/db/models.py` defines canonical `ContentItem`, `SourceItem`, `ItemIdentity`, `MediaAsset`, `ItemMedia`, `Source`, `RawPayload`, `IngestRun`, and `ContentDraft` tables. `ContentItem` is the deduplicated content record and already has `primary_image_id`, `primary_media`, `status`, `score`, `metrics`, and duplicate tracking.
- Migrations: `backend/alembic/versions/0001_initial_ingestion_schema.py` creates ingestion, content, identity, and media tables. `backend/alembic/versions/0002_content_workflow.py` adds `content_drafts`.
- Ingestion: `backend/app/ingestion/service.py` fetches active RSS/Atom and Telegram public sources, stores raw payloads, parses items, upserts source/content records, attaches identities, and links media.
- Repository: `backend/app/ingestion/repository.py` owns deduplication, content upsert, media upsert, primary image assignment, and current classification/scoring storage in `ContentItem.score`, `ContentItem.tags`, and `ContentItem.metrics`.
- Scoring/classification: `backend/app/content/scoring.py` has a combined keyword category and score helper (`classify_and_score`) with AI/Tech/Economy/Farsi news keywords. There is no dedicated content-type classifier, rewrite bucket layer, readiness gate, freshness bucket, or score breakdown column yet.
- Media extraction/storage: parser-level media candidates use `backend/app/sources/base.py`; URL media-kind inference lives in `backend/app/normalization/media.py`; download/storage logic lives in `backend/app/media/downloader.py`. Current `ItemMedia.role` supports simple primary/thumbnail/inline/attachment assignment.
- Diagnostics: `backend/app/diagnostics/service.py` only checks database, parser labels, and media storage configuration. Source health is not persisted yet.
- API: `backend/app/api/routes.py` exposes `/sources`, `/sources/seed`, `/ingest/run`, `/content-items`, `/content-items/{id}`, approval, and `/diagnostics`. Content list filtering is currently limited to `status`, `sort`, and `limit`.
- Schemas: `backend/app/api/schemas.py` returns basic source, media, content, ingest, diagnostics, and approval shapes. Content intelligence fields are not exposed yet.
- Tests: `backend/tests` contains API, approval, scoring, diagnostics, Docker config, draft workflow, ingestion service, legacy migration, media downloader, models, normalization, repository, RSS parser, seed sources, and Telegram parser tests.

## Phase Notes

### Phase 0
- Status: Completed
- What changed: Added this progress tracker and baseline audit notes.
- Files changed: `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests -v`
  - Result: collected 47 tests, then hung at `tests/test_api.py::test_health_endpoint_returns_ok` for more than 90 seconds. No pass/fail summary was produced.
- Validation run: Not applicable for Phase 0.
- Commit: Pending
- Known issues:
  - Baseline full test suite currently hangs before the first test completes. The last visible output was `tests/test_api.py::test_health_endpoint_returns_ok`.
  - The hung command could not be interrupted through the exec session stdin. Future baseline debugging should start with the API health test and `TestClient(app)` behavior.
