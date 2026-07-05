# NewsCraft Content Intelligence Upgrade Progress

## Current Status

Overall status: In Progress

## Phase Progress

| Phase | Name | Status | Commit |
|---:|---|---|---|
| 0 | Progress Tracking and Baseline Audit | Completed | 8489da6 |
| 1 | Schema and Data Model Design | Completed | 92766fc |
| 2 | Content Type Classification | Completed | 9279cb8 |
| 3 | Rewrite Buckets and Candidate Queues | Completed | d32411e |
| 4 | Telegram Title Normalization | Completed | 7728197 |
| 5 | Type-Aware Scoring and Ranking | Completed | ef5901c |
| 6 | Rewrite Readiness Gate | Completed | 235b64e |
| 7 | Media Quality and Primary Media Selection | Completed | d08c060 |
| 8 | Source Health and Diagnostics | Completed | f645efb |
| 9 | API Filters and Response Updates | Completed | Pending |
| 10 | Validation Report Upgrade | Pending | Pending |
| 11 | Documentation and Final Verification | Pending | Pending |

## Latest Update

- Completed Phase 9 API filters and response updates.
- Content item responses now expose content intelligence fields, and content list queries support type, bucket, readiness, source tier, and quality filters.

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
- Commit: d32411e
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 3.
  - Queue visibility/API filtering is deferred to Phase 9.

### Phase 4
- Status: Completed
- What changed:
  - Added title normalization module at `backend/app/normalization/titles.py`.
  - Detects empty, emoji-only, symbol-only, and very weak titles.
  - Generates Telegram titles from the first meaningful body sentence or line, preserving Persian text.
  - Limits generated titles to 100 characters.
  - Stores `title_quality` and `title_was_generated`.
  - Marks title normalization as `low_signal` when no meaningful title can be generated.
  - Runs title normalization before classification and scoring inside `_content_item_values()`.
- Files changed: `backend/app/normalization/titles.py`, `backend/app/ingestion/repository.py`, `backend/tests/test_title_normalization.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_title_normalization.py -q` -> 7 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_title_normalization.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_repository.py tests/test_ingestion_service.py -q` -> 35 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/normalization/titles.py app/ingestion/repository.py tests/test_title_normalization.py` -> passed
- Validation run: Not applicable for Phase 4.
- Commit: 7728197
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 4.

### Phase 5
- Status: Completed
- What changed:
  - Added `score_content_item()` in `backend/app/content/scoring.py`.
  - Implemented formula using relevance, source tier bonus, freshness score, capped media bonus, engagement, content type bonus, stale/archive/promo/low-signal/generated-title/overlong penalties.
  - Capped text length and media count contributions.
  - Added source tier detection for Tier A/B sources.
  - Stored `score_breakdown`, `ranking_metadata`, `freshness_bucket`, and `source_tier` during content item value construction.
- Files changed: `backend/app/content/scoring.py`, `backend/app/ingestion/repository.py`, `backend/tests/test_content_scoring.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_content_scoring.py -q` -> 9 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_content_scoring.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_title_normalization.py tests/test_repository.py tests/test_ingestion_service.py -q` -> 44 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/content/scoring.py app/ingestion/repository.py tests/test_content_scoring.py` -> passed
- Before/after examples: Focused tests verify fresh news outranks stale archive content, media bonus is capped, and promo/low-signal/archive penalties reduce score.
- Validation run: Not applicable for Phase 5.
- Commit: ef5901c
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 5.

### Phase 6
- Status: Completed
- What changed:
  - Added readiness evaluator at `backend/app/content/readiness.py`.
  - Ready items require meaningful title, source URL, enough text, supported non-promo/non-low-signal type, positive score, classification metadata, and no duplicate marker.
  - Blocks stale/archive items from daily news while allowing longform in `longform_analysis`.
  - Stores `is_rewrite_ready`, `rewrite_ready_reason`, and `rewrite_blockers` during content item value construction.
  - Keeps tutorial items ready in their tutorial bucket while marking `not_daily_news` as an informational blocker.
  - Updates rewrite candidate status to `blocked` only when readiness is explicitly false, and keeps promo/low-signal candidates excluded.
- Files changed: `backend/app/content/readiness.py`, `backend/app/ingestion/repository.py`, `backend/tests/test_rewrite_readiness.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_rewrite_readiness.py -q` -> 7 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_rewrite_readiness.py tests/test_content_scoring.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_title_normalization.py tests/test_repository.py tests/test_ingestion_service.py -q` -> 51 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/content/readiness.py app/ingestion/repository.py tests/test_rewrite_readiness.py` -> passed
- Validation run: Not applicable for Phase 6.
- Commit: 235b64e
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 6.

### Phase 7
- Status: Completed
- What changed:
  - Classifies media assets with `media_quality`, `media_confidence`, `media_source_type`, `asset_role`, `is_primary_candidate`, and `is_primary`.
  - Marks Medium stat URLs and 1x/2x images as `tracking_pixel` media and excludes them from primary selection.
  - Marks tiny, low-confidence, and unknown-role media as non-primary candidates.
  - Allows usable images, including YouTube thumbnails, to become `primary_image`.
  - Treats Telegram CDN URLs as `temporary_external` until an existing stored asset is re-ingested, then preserves `stored`.
  - Clears stale `primary_image_id` when no usable primary media is available.
  - Exposes media quality metadata on `MediaAssetOut` for content item API responses.
- Files changed: `backend/app/ingestion/repository.py`, `backend/app/api/schemas.py`, `backend/tests/test_media_quality.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_media_quality.py -q` -> 8 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_media_quality.py tests/test_rewrite_readiness.py tests/test_content_scoring.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_title_normalization.py tests/test_repository.py tests/test_ingestion_service.py tests/test_models.py tests/test_content_intelligence_migration.py -q` -> 64 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/ingestion/repository.py app/api/schemas.py tests/test_media_quality.py` -> passed
- Validation run: Not applicable for Phase 7.
- Commit: d08c060
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 7.
  - Phase 5 already caps media scoring; Phase 7 did not change the ranking formula.

### Phase 8
- Status: Completed
- What changed:
  - Source ingestion now records `last_http_status`, `last_success_at`, `last_failure_at`, `failure_count`, `last_error_type`, `last_error_message`, `last_parse_count`, `last_suitable_count`, `last_media_count`, and `health_status`.
  - HTTP 403/404 responses are marked `broken` with normalized `http_403` / `http_404` error types.
  - DNS/connect failures are marked `broken` using the exception class and message.
  - Malformed/bozo feeds, zero parsed items, and zero suitable items are marked `degraded`.
  - Disabled sources remain represented as `disabled`; no sources are hard-deleted.
  - Diagnostics now includes source health counts and severity-sorted problem source details.
  - Diagnostics fails closed if the source health query cannot run, returning a degraded status instead of raising.
- Health fields updated: `last_success_at`, `last_failure_at`, `failure_count`, `last_http_status`, `last_error_type`, `last_error_message`, `last_parse_count`, `last_suitable_count`, `last_media_count`, `health_status`, `disabled_reason`.
- Files changed: `backend/app/ingestion/service.py`, `backend/app/diagnostics/service.py`, `backend/app/api/schemas.py`, `backend/tests/test_source_health.py`, `backend/tests/test_diagnostics.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_source_health.py tests/test_diagnostics.py -q` -> 9 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_source_health.py tests/test_diagnostics.py tests/test_ingestion_service.py tests/test_media_quality.py tests/test_rewrite_readiness.py tests/test_content_scoring.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_title_normalization.py tests/test_repository.py tests/test_models.py tests/test_content_intelligence_migration.py -q` -> 73 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/ingestion/service.py app/diagnostics/service.py app/api/schemas.py tests/test_source_health.py tests/test_diagnostics.py` -> passed
- Validation run: Not applicable for Phase 8.
- Commit: f645efb
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 8.

### Phase 9
- Status: Completed
- Endpoint changes:
  - `GET /content-items` now accepts `content_type`, `rewrite_bucket`, `is_rewrite_ready`, `source_tier`, and `quality_status` filters.
  - Existing `status`, `sort`, and `limit` behavior remains unchanged.
- Schema changes:
  - `ContentItemOut` now includes `content_type`, `rewrite_bucket`, `is_rewrite_ready`, `rewrite_ready_reason`, `rewrite_blockers`, `classification_reasons`, `source_tier`, `freshness_bucket`, `quality_status`, and `score_breakdown`.
  - `primary_media` remains present and includes the Phase 7 media quality fields.
- Files changed: `backend/app/api/routes.py`, `backend/app/api/schemas.py`, `backend/tests/test_api_content_intelligence.py`, `progress.md`
- Tests run:
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_content_intelligence.py -q` -> 2 passed
  - `cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_content_intelligence.py tests/test_source_health.py tests/test_diagnostics.py tests/test_ingestion_service.py tests/test_media_quality.py tests/test_rewrite_readiness.py tests/test_content_scoring.py tests/test_content_classification.py tests/test_rewrite_buckets.py tests/test_title_normalization.py tests/test_repository.py tests/test_models.py tests/test_content_intelligence_migration.py -q` -> 75 passed
  - `cd backend && PYTHONPATH=. .venv/bin/ruff check app/api/routes.py app/api/schemas.py tests/test_api_content_intelligence.py` -> passed
- Validation run: Not applicable for Phase 9.
- Commit: Pending
- Known issues:
  - Full test suite still has the Phase 0 baseline hang and was not rerun for Phase 9.
