# NewsCraft Content Intelligence Upgrade Progress

## Current Status

Overall status: In Progress

## Phase Progress

| Phase | Name | Status | Commit |
|---:|---|---|---|
| 0 | Progress Tracking and Baseline Audit | Completed | 8489da6 |
| 1 | Schema and Data Model Design | Completed | 92766fc |
| 2 | Content Type Classification | Completed | 9279cb8 |
| 3 | Rewrite Buckets and Candidate Queues | Completed | Pending |
| 4 | Telegram Title Normalization | Pending | Pending |
| 5 | Type-Aware Scoring and Ranking | Pending | Pending |
| 6 | Rewrite Readiness Gate | Pending | Pending |
| 7 | Media Quality and Primary Media Selection | Pending | Pending |
| 8 | Source Health and Diagnostics | Pending | Pending |
| 9 | API Filters and Response Updates | Pending | Pending |
| 10 | Validation Report Upgrade | Pending | Pending |
| 11 | Documentation and Final Verification | Pending | Pending |

## Latest Update

- Completed Phase 3 rewrite bucket assignment and candidate queue upsert.
- Added deterministic bucket mapping and idempotent `rewrite_candidates` writes.

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
- Commit: 8489da6
- Known issues:
  - Baseline full test suite currently hangs before the first test completes. The last visible output was `tests/test_api.py::test_health_endpoint_returns_ok`.
  - The hung command could not be interrupted through the exec session stdin. Future baseline debugging should start with the API health test and `TestClient(app)` behavior.

### Phase 1
- Status: Completed
- What changed:
  - Added `ContentItem` fields: `content_type`, `content_type_confidence`, `classification_reasons`, `classification_metadata`, `rewrite_bucket`, `freshness_bucket`, `source_tier`, `quality_status`, `is_rewrite_ready`, `rewrite_ready_reason`, `rewrite_blockers`, `score_breakdown`, `ranking_metadata`, `title_quality`, `title_was_generated`, and `content_intent`.
  - Added `MediaAsset` fields: `media_quality`, `media_confidence`, `is_primary_candidate`, `is_primary`, `media_source_type`, and `asset_role`.
  - Added `Source` health fields: `last_success_at`, `last_failure_at`, `failure_count`, `last_http_status`, `last_error_type`, `last_error_message`, `last_parse_count`, `last_suitable_count`, `last_media_count`, `health_status`, and `disabled_reason`.
  - Added generic `rewrite_candidates` table with unique `(content_item_id, bucket_type)` rows.
- Files changed: `backend/app/db/models.py`, `backend/alembic/versions/0003_content_intelligence_schema.py`, `backend/tests/test_models.py`, `backend/tests/test_content_intelligence_migration.py`, `progress.md`
- Migration: `backend/alembic/versions/0003_content_intelligence_schema.py`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_content_intelligence_migration.py -q` -> 5 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_repository.py tests/test_content_intelligence_migration.py -q` -> 10 passed
  - `cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head --sql` -> rendered SQL successfully
- Validation run: Alembic offline SQL render only.
- Commit: 92766fc
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 1.
  - New fields are schema-only in this phase; ingestion/classification behavior will be wired in later phases.

### Phase 2
- Status: Completed
- What changed:
  - Added classifier module at `backend/app/content/classification.py`.
  - Implemented deterministic rules for `news`, `article`, `tutorial`, `research`, `video`, `tool_update`, `vendor_update`, `longform`, `promo`, and `low_signal`.
  - Added Persian and English keyword support for tutorial, research, news, promo, and longform signals.
  - Added source-specific handling for YouTube/video sources and known vendor domains/source names.
  - Wired classifier into `_content_item_values()` so ingestion stores `content_type`, `content_type_confidence`, `classification_reasons`, `classification_metadata`, and low-signal `quality_status`.
- Files changed: `backend/app/content/classification.py`, `backend/app/ingestion/repository.py`, `backend/tests/test_content_classification.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_content_classification.py -q` -> 12 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_content_classification.py tests/test_content_scoring.py tests/test_repository.py tests/test_ingestion_service.py -q` -> 25 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_content_intelligence_migration.py -q` -> 5 passed
- Validation run: Not applicable for Phase 2.
- Commit: 9279cb8
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 2.
  - Classifier is deterministic and rule-based; ranking/readiness refinements are deferred to later phases.

### Phase 3
- Status: Completed
- What changed:
  - Added bucket assignment module at `backend/app/content/buckets.py`.
  - Mapped content types to buckets: `news -> daily_news`, `article -> technical_article`, `tutorial -> tutorial`, `research -> research`, `video -> video`, `vendor_update -> vendor_update`, `longform -> longform_analysis`, `promo -> promo_review`, `low_signal -> low_signal_review`.
  - Routed `tool_update` to `vendor_update` for vendor sources and `daily_news` otherwise.
  - Marked `promo` and `low_signal` candidates as `excluded`.
  - Stored `rewrite_bucket` during content item value construction.
  - Added idempotent PostgreSQL upsert for `rewrite_candidates` on `(content_item_id, bucket_type)`.
- Bucket architecture chosen: generic `rewrite_candidates` table.
- Files changed: `backend/app/content/buckets.py`, `backend/app/ingestion/repository.py`, `backend/tests/test_rewrite_buckets.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_rewrite_buckets.py -q` -> 6 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_rewrite_buckets.py tests/test_content_classification.py tests/test_repository.py tests/test_ingestion_service.py -q` -> 28 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/content/buckets.py app/content/classification.py app/ingestion/repository.py tests/test_rewrite_buckets.py tests/test_content_classification.py` -> passed
- Validation run: Not applicable for Phase 3.
- Commit: Pending
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 3.
  - Queue visibility/API filtering is deferred to Phase 9.
