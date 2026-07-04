# Progress Report

## Phase 0 — Progress Tracking

Status: Completed

### What changed
- Created `progress.md` to track implementation progress phase by phase.
- Started the NewsCraft backend unification and stabilization workflow.
- Read `AGENT_PROMPT.md` and `TASKS.md` as the execution roadmap.

### Files changed
- `progress.md`

### Notes for commit
- Suggested commit message: `chore: add progress tracking`

## Phase 1 — Backend Unification

Status: Completed

### What changed
- Started comparing the legacy Streamlit/SQLite implementation with the FastAPI/PostgreSQL backend.
- Confirmed the FastAPI backend already has service/repository/API structure, but some services still wrap legacy modules or contain placeholders.
- Moved arXiv paper asset preparation into the backend asset service instead of recording a placeholder request.
- Added backend support for arXiv ID extraction, PDF download, PDF text extraction, text cleaning, section detection, and Markdown asset generation.
- Added configurable `PAPER_DATA_DIR` for generated paper assets.
- Fixed paper asset upserts so metadata-only status updates do not erase existing file paths.
- Added backend tests for arXiv asset preparation and asset path preservation.
- Moved source-aware ranking/scoring into `newscraft.services.ranking_service`.
- Updated backend ingestion to use the backend ranking service instead of importing the legacy `ranker.py`.
- Migrated RSS, Hacker News, arXiv, GitHub, Hugging Face, YouTube RSS, and Telegram fetchers into `newscraft.connectors.fetchers`.
- Removed the FastAPI backend's `sys.path` legacy adapter so ingestion no longer imports connector code from `ai-news-agent/`.
- Replaced placeholder backend diagnostics with real PostgreSQL and connector checks for RSS, Hacker News, arXiv, GitHub, Hugging Face, YouTube, and Telegram.
- Updated diagnostics routes to pass a database session into the diagnostics service.
- Removed the legacy Streamlit/SQLite implementation after migrating its useful ingestion, ranking, diagnostics, review, approved-article, and paper-asset logic into `newscraft/`.
- Updated the top-level README to identify FastAPI as the single source of truth and document that the legacy implementation has been removed.
- Confirmed `newscraft/` no longer imports legacy connector, Telegram connector, or ranker modules from the removed `ai-news-agent/` implementation.

### Files changed
- `progress.md`
- `README.md`
- `.env.example`
- `ai-news-agent/` (removed)
- `requirements.txt`
- `newscraft/core/config.py`
- `newscraft/connectors/__init__.py`
- `newscraft/connectors/fetchers.py`
- `newscraft/connectors/legacy.py` (removed)
- `newscraft/api/routers/diagnostics.py`
- `newscraft/api/routers/sources.py`
- `newscraft/services/diagnostics_service.py`
- `newscraft/services/ingestion_service.py`
- `newscraft/services/ranking_service.py`
- `newscraft/services/asset_service.py`
- `newscraft/repositories/paper_asset_repository.py`
- `tests/test_backend_foundation.py`

### Verification
- `.venv/bin/python -m pytest` — 46 passed
- `.venv/bin/python -m pytest tests/test_backend_foundation.py::test_backend_ranking_scores_source_specific_items tests/test_backend_foundation.py::test_ingestion_service_runs_fake_connector_and_skips_duplicates -q` — 2 passed
- `.venv/bin/python -m pytest tests/test_backend_foundation.py::test_backend_connector_registry_uses_newscraft_fetchers tests/test_backend_foundation.py::test_backend_rss_fetcher_normalizes_feed_without_legacy_import -q` — 2 passed
- `.venv/bin/python -m pytest tests/test_backend_foundation.py::test_diagnostics_service_returns_source_and_database_checks -q` — 1 passed
- `rg "ai-news-agent|connectors\\.legacy|from ranker|from connectors|telegram_connector|sys\\.path" newscraft tests scripts README.md` — no backend legacy imports found
- `rg "CHANNEL_ID_HERE" newscraft README.md .env.example` — no backend placeholder tokens found
- `.venv/bin/python -m pytest` — 50 passed
- `.venv/bin/python -m pytest` — 15 passed after removing legacy tests with the legacy implementation
- `git diff --check` — passed
- `test ! -e ai-news-agent` — passed

### Notes for commit
- Suggested commit message: `feat: unify backend ingestion foundation`

## Phase 2.1 — Audit Current Ingestion Quality

Status: Completed

### What changed
- Read the updated `AGENT_PROMPT.md` Phase 2 requirements and confirmed Phase 2 is now high-quality ingestion foundation, not content generation.
- Confirmed `TASKS.md` and `pyproject.toml` are not present in the workspace.
- Inspected active ingestion files: `newscraft/services/ingestion_service.py`, `newscraft/connectors/fetchers.py`, `newscraft/repositories/article_repository.py`, `newscraft/repositories/ingestion_run_repository.py`, `newscraft/repositories/source_repository.py`, `newscraft/db/models.py`, `newscraft/domain/schemas.py`, and backend tests.
- Audited current ingestion quality problems:
  - No shared article normalization layer exists; connectors each build ad hoc dictionaries and `ArticleRepository._values()` does fallback mapping at persistence time.
  - Summaries can retain HTML or source-specific formatting, especially RSS summaries.
  - URLs are not canonicalized, so tracking/query params can cause duplicate records.
  - `published_at` parsing strips timezone info before SQLAlchemy stores the value.
  - `author`, `language`, tags/topics, canonical URL, source IDs, and media/enclosure metadata are inconsistently captured.
  - Source-specific metadata is mostly stored under `metrics`, and `_values()` maps either `metadata` or `metrics`, which can drop structured metadata when both are present.
  - Duplicate article upserts currently return the existing row without refreshing useful fields.
  - Ingestion skips malformed items silently and does not log skipped/malformed counts per source.
  - Seeded `sources` records are not used by `IngestionService`; ingestion still runs by connector name only.
  - Source logs track fetched/saved/failed, but not duplicate/skipped/malformed counts, last success, or last error on the source record.
  - YouTube and Telegram default source lists are empty in backend fetchers, so they require explicit configuration before useful ingestion.
- Identified Phase 2.2/2.3 fix plan:
  - Add a small shared normalizer for title, URL, summary, source metadata, dates, author, language, metrics, tags, and raw metadata.
  - Route all ingestion items through the normalizer before ranking and persistence.
  - Preserve source-specific metrics and structured metadata without one overwriting the other.
  - Add tests for malformed items, HTML summary cleanup, URL canonicalization, timezone handling, metadata preservation, and skipped item counts.
  - Start using configured `Source` rows for enabled/disabled state, grouping, category, language, and per-source limits.

### Files changed
- `progress.md`

### Verification
- Command: `.venv/bin/python -m pytest`
- Result: `50 passed`
- Notes: Audit-only sub-phase; no production code changed.

### Remaining issues
- Phase 2.2 still needs the shared normalization layer and ingestion wiring.
- Phase 2.3 still needs source configuration to drive ingestion quality controls.

### Notes for commit
- Suggested commit message: `docs: audit ingestion quality issues`

## Phase 2.2 — Standardize Article Normalization

Status: Completed

### What changed
- Added shared article normalization in `newscraft.services.normalization_service`.
- Normalized title, URL, summary/content, source metadata, author, language, category, score/status, dates, metrics, tags/topics, and raw metadata before persistence.
- Canonicalized URLs by lowercasing scheme/host, dropping fragments, and removing common tracking query parameters.
- Cleaned HTML and repeated whitespace from titles and summaries.
- Preserved source-specific metrics and tags under article metadata without dropping existing structured metadata.
- Converted parsed datetimes to UTC-aware `datetime` objects.
- Updated ingestion to reject malformed items without title or usable URL through the shared normalizer.
- Added per-source `skipped_malformed` counts to source run log metadata.
- Fixed connector/source type fallback after normalization for custom connector names.

### Files changed
- `newscraft/services/normalization_service.py`
- `newscraft/services/ingestion_service.py`
- `tests/test_backend_foundation.py`
- `progress.md`

### Verification
- Command: `.venv/bin/python -m pytest tests/test_backend_foundation.py::test_article_normalizer_cleans_url_summary_metadata_and_dates tests/test_backend_foundation.py::test_ingestion_service_normalizes_and_skips_malformed_items -q`
- Result: `2 passed`
- Command: `.venv/bin/python -m pytest`
- Result: `52 passed`

### Remaining issues
- Phase 2.3 still needs configured `Source` rows to drive enabled/disabled state, grouping, language/category defaults, per-source limits, and source-level last success/error tracking.

### Notes for commit
- Suggested commit message: `feat: standardize article normalization`
