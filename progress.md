# NewsCraft Content Production Workflow Progress

## Phase 0: Repository Audit

Date/time: 2026-07-09 03:44:00 +0330

Objective: Inspect the existing backend architecture and identify the smallest safe path for an orchestrated, human-in-the-loop content production workflow without implementing new feature behavior yet.

Files changed:

- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- No runtime behavior was implemented in Phase 0.
- Completed an architecture audit of the current ingestion, content intelligence, media, draft, approval, API, migration, and test structure.

Current workflow capabilities:

- Ingestion stores durable RSS/Telegram source data through `sources`, `ingest_runs`, `raw_payloads`, `source_items`, `content_items`, `item_identities`, `media_assets`, and `item_media`.
- Content intelligence already classifies, scores, buckets, and readiness-checks content through `app.content.classification`, `app.content.scoring`, `app.content.buckets`, and `app.content.readiness`.
- `rewrite_candidates` exists for downstream rewrite queues.
- `content_drafts` exists as a simple platform draft table.
- `ApprovalService` can mark a `ContentItem` as approved by mutating item status and metrics.
- `DraftService` can create a basic draft tied directly to a `ContentItem`.
- `app.discovery.article_extractor.extract_article` provides reusable article extraction logic with fallback status and warnings.
- API routes expose ingestion, content listing, media listing, diagnostics, item detail, and item approval.

Reusable models/services:

- `ContentItem`, `SourceItem`, `ItemIdentity`, `MediaAsset`, and `ItemMedia` should remain the source-of-truth evidence and media inputs.
- `RewriteCandidate` can inform candidate selection, but it is not sufficient as the new production shortlist model.
- `ContentDraft` may be reused for legacy/basic draft display, but the required `TelegramDraft` needs production-run scoping, brief linkage, source links, hashtags, warnings, and status.
- Existing scoring/classification/readiness functions should feed candidate selection and sufficiency decisions.
- Existing article extraction should be wrapped as a production workflow step rather than replaced.

Missing models/services:

- Missing durable content production request, run, candidate shortlist, agent step trace, outbox/workflow event, sufficiency report, editorial brief, Telegram draft, quality report, visual brief/image request, Telegram package, and dispatch handoff concepts.
- Missing central state machine and explicit invalid-transition rejection.
- Missing typed event definitions and idempotent event handling.
- Missing production workflow repository/service boundary.
- Missing APIs under `/content-production/...`.
- Missing human shortlist approval and final package approval gates.
- Missing content sufficiency gate, enrichment provider abstraction, editorial brief builder, draft generator interface, quality gate, media resolver, package builder, and dispatch handoff service.

Migration needs:

- Add a new Alembic revision after `0003_content_intelligence_schema`.
- Use PostgreSQL UUID and JSONB consistently with current models.
- Add indexes for request status, run state/current step, shortlist request/content uniqueness, event status/availability/correlation, and production-run lookups.
- Add uniqueness/idempotency constraints where duplicate events or duplicate artifacts would be unsafe.

Tests added:

- None. Phase 0 is audit/documentation only.

Commands run:

- `sed -n '1,260p' TASK.md`
- `sed -n '261,620p' TASK.md`
- `sed -n '621,1040p' TASK.md`
- `sed -n '1041,1400p' TASK.md`
- `rg --files -g '!node_modules' -g '!vendor' -g '!dist' -g '!build'`
- `git status --short`
- `sed -n '1,620p' backend/app/db/models.py`
- `sed -n '1,260p' backend/app/workflows/approval.py`
- `sed -n '1,260p' backend/app/workflows/drafts.py`
- `sed -n '1,260p' backend/app/api/routes.py`
- `sed -n '1,320p' backend/alembic/versions/*.py`
- `sed -n '1,300p' backend/app/content/*.py`
- `sed -n '1,300p' backend/app/discovery/article_extractor.py`
- `sed -n '1,260p' backend/app/api/schemas.py`
- `sed -n '1,260p' backend/tests/test_draft_workflow.py`
- `sed -n '1,260p' backend/tests/test_approval_workflow.py`
- `sed -n '1,260p' backend/tests/test_repository.py`
- `sed -n '1,220p' backend/tests/test_models.py`
- `sed -n '1,260p' backend/pyproject.toml`
- `sed -n '1,260p' README.md`
- `sed -n '1,260p' docs/ingestion-backend.md`
- `sed -n '1,240p' backend/app/worker.py`
- `sed -n '1,200p' backend/app/main.py`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Audit commands passed.
- No automated test suite was required for this audit-only phase.

Known issues:

- The worktree had unrelated pre-existing modifications and deletions before Phase 0 started, including deleted `progress.md`; those were not reverted.
- Existing approval and draft workflows are not production-run scoped and do not satisfy the new human-in-the-loop orchestration requirements.
- No durable outbox or state transition enforcement exists yet.
- No dispatch code should be added until final approval gating exists.

Next phase recommendation:

- Phase 1 is safe to begin.
- Start with a small `app.content_production` package containing state/event definitions and repository/service helpers.
- Add models and migration first, then metadata tests, state transition tests, and outbox idempotency tests.

## Phase 1: Durable Workflow Foundation

Date/time: 2026-07-09 03:50:40 +0330

Objective: Add the durable backend foundation needed to create and track production workflow state safely, without implementing candidate selection, generation, packaging, or dispatch behavior.

Files changed:

- `backend/app/db/models.py`
- `backend/app/content_production/__init__.py`
- `backend/app/content_production/states.py`
- `backend/app/content_production/events.py`
- `backend/app/content_production/repository.py`
- `backend/alembic/versions/0004_content_production_foundation.py`
- `backend/tests/test_content_production_foundation.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `ContentProductionRequest`, `CandidateShortlist`, `ContentProductionRun`, `AgentStepRun`, and `WorkflowEvent` ORM models.
- Added PostgreSQL JSONB-backed Alembic migration `0004_content_production_foundation`.
- Added explicit workflow state enum and valid transition map.
- Added invalid transition rejection through `InvalidWorkflowTransition`.
- Added typed workflow event enum covering all required Phase 1 event names.
- Added repository helpers for request creation, shortlist candidate creation, run creation, state transition, agent step trace creation, pending event lookup, and idempotent event enqueue by `event_id`.
- Preserved the human approval safety invariant that dispatch cannot be reached from `package_ready`; final approval must occur first.

Tests added:

- `backend/tests/test_content_production_foundation.py`
  - verifies new tables are registered in SQLAlchemy metadata
  - verifies indexes and uniqueness constraints
  - verifies migration includes foundation tables and revises `0003_content_intelligence_schema`
  - verifies critical happy-path transitions
  - verifies invalid draft-before-sufficiency and dispatch-before-final-approval transitions
  - verifies required event type coverage
  - verifies repository transition rejection
  - verifies event enqueue idempotency by `event_id`

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_models.py tests/test_draft_workflow.py tests/test_approval_workflow.py -q`
- `.venv/bin/python -m pytest tests -q`
- `.venv/bin/python -m ruff check .`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0004_content_production_foundation.py backend/tests/test_content_production_foundation.py`
- `git status --short`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Targeted backend tests: passed, `14 passed`.
- Full backend tests: passed, `149 passed`.
- Ruff first run: failed because `.ruff_cache` was not writable in the existing workspace.
- Ruff rerun with `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache`: passed, `All checks passed!`.
- Pytest emitted a cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Event idempotency is implemented at the repository/API contract level by caller-provided `event_id` and the table primary key. Future concurrent worker processing may need stronger claim/lock semantics when polling is implemented.
- Phase 1 intentionally does not add runtime API endpoints yet; those start in Phase 2.
- Phase 1 intentionally does not add sufficiency, brief, draft, quality, media, package, or dispatch models; those belong to later phases unless a later migration consolidates them.
- Existing unrelated worktree changes remain untouched.

Next phase recommendation:

- Phase 2 is safe to begin.
- Start by adding request creation schemas/routes and a candidate selection service that uses existing `ContentItem` scoring, rewrite readiness, freshness, source tier, duplicate, topic, and media signals.
- Keep shortlist approval separate from existing item-level approval so the new human gate cannot be bypassed.

## Phase 2: Candidate Selection And Shortlist Approval

Date/time: 2026-07-09 04:19:02 +0330

Objective: Let an operator create a content-production request, receive a ranked shortlist from existing `content_items`, and approve or reject shortlist entries before any generation or sufficiency work begins.

Files changed:

- `backend/app/api/routes.py`
- `backend/app/api/schemas.py`
- `backend/app/content_production/candidates.py`
- `backend/app/content_production/repository.py`
- `backend/tests/test_content_production_candidates.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added request creation endpoint: `POST /content-production/requests`.
- Added request list/detail endpoints:
  - `GET /content-production/requests`
  - `GET /content-production/requests/{request_id}`
- Added shortlist endpoint: `GET /content-production/requests/{request_id}/shortlist`.
- Added human shortlist decision endpoints:
  - `POST /content-production/requests/{request_id}/shortlist/approve`
  - `POST /content-production/requests/{request_id}/shortlist/reject`
- Added deterministic `CandidateSelectionService` that ranks existing `ContentItem` rows using score, rewrite readiness, topic match, source tier, freshness, duplicate risk, content type risk, and media presence.
- Persisted ranked `CandidateShortlist` rows with reason, risk, and source snapshot JSON.
- Added `ShortlistApprovalService` to approve or reject only matching request-scoped shortlist entries.
- Created `ContentProductionRun` rows only after shortlist approval, initialized at `shortlist_approved` so Phase 3 can begin at the sufficiency gate.
- Emitted typed workflow events for request creation, candidate selection requested, shortlist prepared, approval requested, shortlist approved, and shortlist rejected.
- Kept generation, sufficiency checks, drafts, packages, and dispatch out of Phase 2.

Tests added:

- `backend/tests/test_content_production_candidates.py`
  - topic/rewrite/risk filtering and scoring
  - shortlist approval mutation
  - request creation endpoint preparing a shortlist
  - approval endpoint creating production runs only after the human gate

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --stat -- backend/app/api/routes.py backend/app/api/schemas.py backend/app/content_production backend/app/db/models.py backend/alembic/versions/0004_content_production_foundation.py backend/tests/test_content_production_foundation.py backend/tests/test_content_production_candidates.py progress.md phase-handoff.md`
- `git diff --check -- backend/app/api/routes.py backend/app/api/schemas.py backend/app/content_production backend/app/db/models.py backend/alembic/versions/0004_content_production_foundation.py backend/tests/test_content_production_foundation.py backend/tests/test_content_production_candidates.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Focused Phase 1/2 tests: passed, `12 passed`.
- Full backend suite: passed, `153 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Candidate selection is rule-based and synchronous in the API for the first implementation. The durable events are emitted, but no polling worker consumes them yet.
- Topic matching currently uses simple text matching and can be improved later with token-aware matching or search indexes.
- Approval endpoints create runs but do not yet enqueue sufficiency checks; Phase 3 should add that transition/event handling.
- The endpoints are backend-only and intentionally have no frontend.

Next phase recommendation:

- Phase 3 is safe to begin.
- Add `ContentSufficiencyReport` model/migration and a deterministic sufficiency service.
- Ensure approved runs cannot proceed to drafting unless sufficiency is `sufficient`.
- Add tests for title-only, short RSS summary, partial article, full article-like content, Telegram text, rejected promotional/low-signal content, and event handling.

## Phase 3: Content Sufficiency Gate

Date/time: 2026-07-09 04:29:13 +0330

Objective: Add a deterministic content sufficiency gate that persists structured decisions and prevents insufficient content from going directly to drafting or package creation.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0005_content_sufficiency_reports.py`
- `backend/app/content_production/sufficiency.py`
- `backend/tests/test_content_sufficiency.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `ContentSufficiencyReport` ORM model.
- Added Alembic migration `0005_content_sufficiency_reports`.
- Added `ContentSufficiencyService.check_run()` to transition approved runs into sufficiency checking, persist a report, and transition to `sufficiency_sufficient`, `sufficiency_partial`, `sufficiency_insufficient`, or `failed`.
- Added `evaluate_content_sufficiency()` with structured output:
  - `status`
  - `score`
  - `reasons`
  - `allowed_next_step`
  - `blocked_steps`
  - `minimum_needed`
  - `input_snapshot`
- Blocks `draft_generation` and `telegram_package` for partial and insufficient content.
- Rejects promotional, low-signal, duplicate, or unsafe content before generation.
- Allows only sufficient content to proceed to `editorial_brief`.

Tests added:

- `backend/tests/test_content_sufficiency.py`
  - schema registration and indexes
  - migration contents
  - title-only content
  - short RSS summary
  - partial article content
  - full article-like content
  - Telegram text with context
  - rejected promotional/low-signal content
  - service persistence and run transitions

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0005_content_sufficiency_reports.py backend/tests/test_content_sufficiency.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0005_content_sufficiency_reports.py backend/tests/test_content_sufficiency.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Focused Phase 1/2/3 tests: passed, `21 passed`.
- Full backend suite: passed, `162 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- The sufficiency gate is deterministic/rule-based. Later phases may add model-assisted review, but must preserve this blocking contract.
- Phase 3 persists reports and transitions runs but does not yet expose report API endpoints.
- Phase 3 does not yet enqueue sufficiency events from approval endpoints; the service entrypoint exists for Phase 4+ orchestration.
- Extracted article text is represented by current `content_text`/HTML fields until Phase 4 adds explicit extraction/enrichment artifacts.

Next phase recommendation:

- Phase 4 is safe to begin.
- Add extraction and enrichment result storage.
- Wrap existing `app.discovery.article_extractor.extract_article` behind a production workflow service.
- Add a web enrichment provider abstraction with no-secrets/no-network-by-default test providers.
- Add mocked tests for extraction success/failure, enrichment fallback, structured source attribution, and retry/failure behavior.

## Phase 4: Article Extraction And Web Enrichment

Date/time: 2026-07-09 04:52:33 +0330

Objective: Add production-run article extraction and secondary web enrichment paths for partial/insufficient content, reusing existing extraction code and keeping web enrichment source-attributed and non-primary.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0006_extraction_enrichment_results.py`
- `backend/app/content_production/enrichment.py`
- `backend/tests/test_content_enrichment.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `ArticleExtractionResult` ORM model.
- Added `WebEnrichmentResult` ORM model.
- Added Alembic migration `0006_extraction_enrichment_results`.
- Added `ArticleExtractionService` that adapts `ContentItem` into `DiscoveryItem` and reuses `app.discovery.article_extractor.extract_article`.
- Persisted extraction status, final URL, extracted text, title, summary, author, image URL, warnings, metadata, and error message.
- Added `WebEnrichmentProvider` protocol and `NullWebEnrichmentProvider`.
- Added `WebEnrichmentService` that stores provider status, strong-identifier query data, findings, source attribution, warnings, and errors.
- Added `build_enrichment_query()` using title, source name, source URL, source domain, publication date, and author when available.
- Ensured enrichment attribution marks findings as `web_enrichment_secondary`, preserving the rule that web/DDG is not primary truth.
- No secrets, live search, or auto-network DDG implementation was added.

Tests added:

- `backend/tests/test_content_enrichment.py`
  - extraction/enrichment schema registration
  - migration contents
  - mocked article extraction success
  - extraction missing-URL failure without raising
  - mocked web enrichment provider success with attribution
  - null provider skipped behavior without fake success
  - strong identifier query construction

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0006_extraction_enrichment_results.py backend/tests/test_content_enrichment.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0006_extraction_enrichment_results.py backend/tests/test_content_enrichment.py progress.md phase-handoff.md`
- `git status --short`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Focused Phase 1-4 tests: passed, `28 passed`.
- Full backend suite: passed, `169 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- No real DDG provider is implemented yet; the abstraction is ready, and tests use a fake provider.
- Null provider returns `skipped` and does not fake success.
- Extraction result text is stored separately but not yet merged into sufficiency re-check logic automatically.
- API/event worker wiring for extraction/enrichment is not yet exposed.

Next phase recommendation:

- Phase 5 is safe to begin.
- Add `EditorialBrief` model/migration and service.
- Build briefs only from sufficient or attributed evidence.
- Separate confirmed facts, unconfirmed context, unsafe claims, do-not-say items, angle, audience, and tone.
- Add tests for fact separation and unsupported claim blocking.

## Phase 5: Editorial Brief

Date/time: 2026-07-09 04:56:38 +0330

Objective: Create a structured editorial brief that separates confirmed evidence from unsafe/unverified claims before any draft generation.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0007_editorial_briefs.py`
- `backend/app/content_production/briefs.py`
- `backend/tests/test_editorial_briefs.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `EditorialBrief` ORM model.
- Added Alembic migration `0007_editorial_briefs`.
- Added `EditorialBriefService.create_brief()` to persist briefs and transition runs from `sufficiency_sufficient` to `briefing` and then `brief_ready`.
- Added deterministic `build_editorial_brief_payload()` that produces:
  - angle
  - key facts
  - source claims
  - unsafe or unverified claims
  - audience
  - tone
  - do-not-say guidance
- Uses primary content or successful extraction as confirmed evidence.
- Treats web enrichment findings as secondary/unconfirmed context.
- Adds explicit do-not-say guidance for unverified claims, failed/fallback extraction, and skipped enrichment.

Tests added:

- `backend/tests/test_editorial_briefs.py`
  - schema registration
  - migration contents
  - confirmed fact and unverified claim separation
  - failed extraction warning in do-not-say guidance
  - persisted brief and run transition behavior

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `.venv/bin/python -m pytest tests/test_editorial_briefs.py -q`
- `.venv/bin/python -m pytest tests -q`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0007_editorial_briefs.py backend/tests/test_editorial_briefs.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0007_editorial_briefs.py backend/tests/test_editorial_briefs.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Focused Phase 1-5 tests: passed, `33 passed`.
- Initial Ruff run found one line-length issue in `briefs.py`; fixed.
- Ruff with `/tmp` cache after fix: passed, `All checks passed!`.
- Focused brief tests after fix: passed, `5 passed`.
- Full backend suite after fix: passed, `174 passed`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Brief creation is deterministic and extractive; it does not call an LLM.
- Sentence extraction is intentionally simple and may need tuning for Persian segmentation.
- Brief service has no API endpoint yet.
- Draft generation is still blocked until Phase 6.

Next phase recommendation:

- Phase 6 is safe to begin.
- Add production-run-scoped `TelegramDraft` model/migration and service.
- Use only approved brief facts and source claims.
- Produce Persian Telegram structure deterministically for tests.
- Add revision support and tests proving unsupported facts are not introduced.

## Phase 6: Telegram Draft Generation

Date/time: 2026-07-09 04:59:33 +0330

Objective: Generate and persist a production-run-scoped Persian Telegram draft from the editorial brief without introducing unsupported facts.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0008_telegram_drafts.py`
- `backend/app/content_production/telegram_drafts.py`
- `backend/tests/test_telegram_drafts.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `TelegramDraft` ORM model.
- Added Alembic migration `0008_telegram_drafts`.
- Added `TelegramDraftService.create_draft()` to transition runs from `brief_ready` to `drafting` and then `draft_ready`.
- Added deterministic Persian Telegram draft payload generation from `EditorialBrief`.
- Drafts include title, body text, hashtags, source links, warnings, and status.
- Draft body uses `key_facts_json` and source links from the brief.
- Unsafe/unverified brief claims are not included as body facts and instead become warnings.

Tests added:

- `backend/tests/test_telegram_drafts.py`
  - schema registration
  - migration contents
  - Persian draft structure
  - source links and hashtags
  - warning generation
  - no unsupported unsafe claim included in body
  - persisted draft and run transitions

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0008_telegram_drafts.py backend/tests/test_telegram_drafts.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0008_telegram_drafts.py backend/tests/test_telegram_drafts.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Focused Phase 1-6 tests: passed, `37 passed`.
- Full backend suite: passed, `178 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Draft generation is deterministic and template-based, not provider-backed.
- Revision support is represented by draft status/storage foundation; richer revision workflows should be expanded with quality gate and request-revision phases.
- Persian phrasing is basic and should be improved once quality gate feedback exists.
- No draft API endpoint was added yet.

Next phase recommendation:

- Phase 7 is safe to begin.
- Add `DraftQualityReport` model/migration and quality gate service.
- Check unsupported claims by comparing draft text against brief facts and source links.
- Add style/readiness checks for Telegram structure, source link presence, hype, context, and tone mismatch.
- Add pass/fail/revision-needed tests.

## Phase 7: Quality Gate

Date/time: 2026-07-09 05:04:41 +0330

Objective: Add a quality/fact-check gate that prevents unsupported, unsourced, or structurally weak drafts from proceeding to packaging.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0009_draft_quality_reports.py`
- `backend/app/content_production/quality.py`
- `backend/tests/test_draft_quality.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `DraftQualityReport` ORM model.
- Added Alembic migration `0009_draft_quality_reports`.
- Added `DraftQualityService.check_draft()` to transition runs from `draft_ready` to `quality_checking`, persist the report, and transition to `quality_passed`, `quality_failed`, or `revision_requested`.
- Added deterministic quality evaluation for:
  - unsupported claims
  - missing source links
  - missing Telegram structure
  - too little context
  - too much hype
  - tone mismatch
- Added punctuation-tolerant supported-claim matching to avoid treating style punctuation as factual drift.

Tests added:

- `backend/tests/test_draft_quality.py`
  - schema registration
  - migration contents
  - clean draft pass
  - unsupported claim and missing source failure
  - style-only revision requested
  - persisted quality report and run transitions

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py -q`
- `.venv/bin/python -m pytest tests/test_draft_quality.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0009_draft_quality_reports.py backend/tests/test_draft_quality.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0009_draft_quality_reports.py backend/tests/test_draft_quality.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Initial focused Phase 1-7 tests exposed a style fixture that was also unsupported; adjusted the test and improved punctuation-tolerant claim comparison.
- Quality tests after fixes: passed, `6 passed`.
- Focused Phase 1-7 tests: passed, `43 passed`.
- Full backend suite: passed, `184 passed`.
- Initial Ruff run found one long line in `quality.py`; fixed.
- Ruff with `/tmp` cache after fix: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Unsupported-claim detection is deterministic and conservative, not semantic.
- Quality checks do not yet support human override; later final approval/package phases should define explicit override behavior.
- No API endpoint was added for quality reports.
- Media and packaging remain blocked until later phases.

Next phase recommendation:

- Phase 8 is safe to begin.
- Add visual brief/image generation request model and media resolver service.
- Prefer existing primary media and good linked media assets.
- Create pending visual brief/image request when no suitable media exists.
- Add tests for existing image, no image, weak image, and no-provider pending behavior.

## Phase 8: Media Resolver And Visual Brief

Date/time: 2026-07-09 05:09:05 +0330

Objective: Resolve suitable existing media for approved drafts, or create a pending visual brief/image request without faking provider success.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0010_visual_briefs.py`
- `backend/app/content_production/media.py`
- `backend/tests/test_media_resolver.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `VisualBrief` ORM model.
- Added Alembic migration `0010_visual_briefs`.
- Added `MediaResolverService` that transitions runs from `quality_passed` to `media_resolving`.
- Selects suitable existing images from `ContentItem.primary_media`, `primary_image_id`, or provided media assets.
- Rejects weak/tracking/failed/tiny/non-image media.
- Adds `ImageGenerationProvider` protocol and `NullImageGenerationProvider`.
- Creates pending visual brief/image-generation request when no suitable media exists and no provider is configured.
- Records provider-generated responses only when the provider explicitly returns `generated`.
- Uses valid image state transitions through `image_generation_pending`, `image_generating`, and `image_ready`.

Tests added:

- `backend/tests/test_media_resolver.py`
  - schema registration
  - migration contents
  - existing primary image selection
  - no-image pending visual brief with null provider
  - weak image fallback to visual prompt
  - provider-generated response handling
  - visual prompt construction

Commands run:

- `.venv/bin/python -m pytest tests/test_media_resolver.py -q`
- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0010_visual_briefs.py backend/tests/test_media_resolver.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0010_visual_briefs.py backend/tests/test_media_resolver.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Initial focused workflow test exposed an invalid direct transition from `media_resolving` to `image_ready`; fixed by transitioning through image generation states.
- Media resolver tests after fix: passed, `7 passed`.
- Focused Phase 1-8 tests: passed, `50 passed`.
- Full backend suite: passed, `191 passed`.
- Initial Ruff run found one long line in `test_media_resolver.py`; fixed.
- Ruff with `/tmp` cache after fix: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- Media resolver accepts media assets as service input; no database query helper for related `ItemMedia` rows is added yet.
- Null provider records pending behavior and does not create a generated asset.
- Provider-generated result stores provider data but does not create a `MediaAsset`; later integration should do that only with a real provider result.
- No media API endpoint was added yet.

Next phase recommendation:

- Phase 9 is safe to begin.
- Add `TelegramPostPackage` model/migration and package builder.
- Package should include draft text, source links, media or visual brief, quality report, warnings, approval status, and dispatch readiness.
- Add final package approval/rejection/revision endpoints or service behavior.
- Add tests for package creation and final approval gates.

## Phase 9: Telegram Package Builder And Final Approval

Date/time: 2026-07-09 05:13:16 +0330

Objective: Build reviewable Telegram-ready post packages and enforce final human approval before any dispatch handoff can occur.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0011_telegram_post_packages.py`
- `backend/app/content_production/packages.py`
- `backend/tests/test_telegram_packages.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `TelegramPostPackage` ORM model.
- Added Alembic migration `0011_telegram_post_packages`.
- Added `TelegramPackageService.build_package()` to create package JSON from draft, quality report, and visual/media decision.
- Package JSON includes platform, post text, source links, hashtags, quality report summary, media/visual state, warnings, approval status, and dispatch readiness.
- Dispatch readiness is explicitly `blocked_pending_final_approval` before approval.
- Added final approval, rejection, and revision-request service methods.
- Approval transitions run to `final_approved`; rejection transitions to `final_rejected`; revision transitions to `revision_requested`.
- Approval rejects invalid states that are not waiting for final approval.

Tests added:

- `backend/tests/test_telegram_packages.py`
  - schema registration
  - migration contents
  - package payload and dispatch readiness gate
  - package creation and final approval pending transition
  - final approval transition
  - rejection and revision gates
  - invalid approval state rejection

Commands run:

- `.venv/bin/python -m pytest tests/test_telegram_packages.py -q`
- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0011_telegram_post_packages.py backend/tests/test_telegram_packages.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0011_telegram_post_packages.py backend/tests/test_telegram_packages.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Package tests: passed, `7 passed`.
- Focused Phase 1-9 tests: passed, `57 passed`.
- Full backend suite: passed, `198 passed`.
- Initial Ruff run found one long line in `packages.py`; fixed.
- Ruff with `/tmp` cache after fix: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- No API endpoints were added for package retrieval or final approval yet; service behavior is implemented and tested.
- Dispatch handoff is not implemented until Phase 10.
- Package JSON is deterministic and minimal; API contract can expose it later.
- Human approval is enforced at service/state level, but client retry/idempotency can be strengthened later.

Next phase recommendation:

- Phase 10 is safe to begin.
- Add dispatch request/handoff model and service.
- Create dispatch requests only from `final_approved` state.
- If Telegram configuration is absent, mark dispatch blocked or pending rather than success.
- Add tests for no auto-publish before approval and blocked/pending dispatch behavior.

## Phase 10: Dispatch Handoff

Date/time: 2026-07-09 05:16:30 +0330

Objective: Add an explicit dispatch handoff that can only be created after final approval and never marks Telegram publishing successful unless it actually happens.

Files changed:

- `backend/app/db/models.py`
- `backend/alembic/versions/0012_telegram_dispatch_requests.py`
- `backend/app/content_production/dispatch.py`
- `backend/tests/test_dispatch_handoff.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added `TelegramDispatchRequest` ORM model.
- Added Alembic migration `0012_telegram_dispatch_requests`.
- Added `TelegramDispatchService.create_dispatch_request()`.
- Requires `ContentProductionRun.state == final_approved` and package `approval_status == approved`.
- Creates dispatch handoff rows only after final approval.
- If Telegram bot/channel configuration is missing, creates a `blocked` dispatch request and transitions the run to `dispatch_failed` with a failure reason.
- If configuration is present, creates a `pending` dispatch request and transitions the run to `dispatch_pending`.
- Does not publish automatically and does not set `dispatched_at`.

Tests added:

- `backend/tests/test_dispatch_handoff.py`
  - schema registration
  - migration contents
  - dispatch requires final approval
  - missing config creates blocked handoff
  - configured service creates pending handoff without publishing

Commands run:

- `.venv/bin/python -m pytest tests/test_dispatch_handoff.py -q`
- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py tests/test_dispatch_handoff.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `git diff --check -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0012_telegram_dispatch_requests.py backend/tests/test_dispatch_handoff.py progress.md phase-handoff.md`
- `git diff --stat -- backend/app/db/models.py backend/app/content_production backend/alembic/versions/0012_telegram_dispatch_requests.py backend/tests/test_dispatch_handoff.py progress.md phase-handoff.md`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Dispatch handoff tests: passed, `5 passed`.
- Focused Phase 1-10 tests: passed, `62 passed`.
- Full backend suite: passed, `203 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- No real Telegram publisher is implemented.
- Telegram config fields are not in settings yet; service accepts explicit bot token/channel values for future integration.
- Blocked dispatch currently transitions to `dispatch_failed`; this preserves no-fake-success behavior but may later be refined to a dedicated blocked state.
- No dispatch API endpoint was added.

Next phase recommendation:

- Phase 11 is safe to begin.
- Add mocked end-to-end workflow validation that exercises request, shortlist approval, sufficiency, extraction/enrichment, brief, draft, quality, media, package, final approval, and dispatch handoff.
- Run backend tests, lint, migration validation where feasible, and document a final validation report.

## Phase 11: End-To-End Validation

Date/time: 2026-07-09 05:20:00 +0330

Objective: Prove the backend content production workflow through focused tests, full regression tests, lint, migration history validation, and a final validation report.

Files changed:

- `backend/tests/test_content_production_e2e.py`
- `validation/content-production-workflow-report.md`
- `progress.md`
- `phase-handoff.md`
- `backend/app/content_production/quality.py`

Behavior implemented:

- Added a mocked end-to-end workflow test covering request creation, shortlist candidate approval, run creation, sufficiency check, editorial brief, Telegram draft, quality gate, media resolver, package builder, final approval, and dispatch handoff.
- Adjusted quality gate behavior so informational draft warnings remain visible but do not automatically block a draft unless unsupported claims, missing sources, or style issues exist.
- Added final validation report at `validation/content-production-workflow-report.md`.

Tests added:

- `backend/tests/test_content_production_e2e.py`

Commands run:

- `.venv/bin/python -m pytest tests/test_content_production_e2e.py -q`
- `.venv/bin/python -m pytest tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py tests/test_dispatch_handoff.py tests/test_content_production_e2e.py -q`
- `.venv/bin/python -m pytest tests -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/python -m ruff check .`
- `.venv/bin/alembic history`
- `git diff --check -- backend/app/content_production backend/tests/test_content_production_e2e.py validation/content-production-workflow-report.md progress.md phase-handoff.md`
- `git status --short`
- `date '+%Y-%m-%d %H:%M:%S %Z'`

Pass/fail results:

- Initial E2E test exposed informational warning behavior causing `revision_requested`; fixed by keeping informational warnings non-blocking.
- E2E test after fix: passed, `1 passed`.
- Focused Phase 1-11 workflow tests: passed, `63 passed`.
- Full backend suite: passed, `204 passed`.
- Ruff with `/tmp` cache: passed, `All checks passed!`.
- Alembic history: passed; migration chain is linear through `0012_telegram_dispatch_requests`.
- Diff whitespace check: passed.
- Pytest emitted the same cache write warning for `backend/.pytest_cache`; tests still passed.

Known issues:

- The repository has unrelated pre-existing dirty worktree changes that were not reverted.
- No frontend was built, by task requirement.
- Real providers for LLM, DDG, image generation, and Telegram publishing remain abstractions/handoffs.
- Some safety checks are deterministic and conservative rather than semantic.
- Follow-up resumed work added the missing run artifact, package approval/rejection/revision, and event listing API endpoints with API contract tests on 2026-07-09 22:52:27 +0330.

Next phase recommendation:

- The requested MVP backend workflow is implemented and validated.
- Next work should focus on API expansion for artifact retrieval/approval, real provider integrations with secrets management, and optional frontend/operator UI.
- Updated validation after resumed API work: focused workflow/API tests passed with `68 passed`; full backend suite passed with `209 passed`; Ruff passed.

## Orchestration Hardening Step 1: Outbox Worker / Poller

Date/time: 2026-07-11 01:45:55 +0330

Objective: Implement the real PostgreSQL-backed workflow event worker and polling contract without wiring core workflow handlers yet.

Files changed:

- `backend/app/content_production/orchestration.py`
- `backend/app/content_production/repository.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Added typed `EventDispatcher` registration and dispatch needed by the generic worker.
- Added `WorkflowEventWorker.run_once()` for claiming and processing available events.
- Added `WorkflowEventWorker.poll()` for continuous polling with an idle interval and optional stop event.
- Added successful completion with `status=processed`, `processed_at`, cleared `last_error`, and incremented `attempt_count`.
- Added retry handling with `status=pending`, delayed `available_at`, preserved error text, and bounded attempts.
- Added terminal failure handling with `status=failed` after `max_attempts`.
- Added PostgreSQL-safe repository claiming with `FOR UPDATE SKIP LOCKED`, ordered batching, and `status=processing`.
- Preserved event payload, `correlation_id`, and `causation_id` during processing.

Commands run:

- `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events -q`
- `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_foundation.py tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event -q`
- `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app/content_production/orchestration.py app/content_production/repository.py`
- `git diff --check -- backend/app/content_production/orchestration.py backend/app/content_production/repository.py`

Pass/fail results:

- Focused outbox worker tests: passed, `3 passed`.
- Adjacent foundation/dispatcher/worker integration tests: passed, `10 passed`.
- Ruff: passed, `All checks passed!`.
- Diff whitespace check: passed.

Known issues / intentionally pending:

- Core content-production handlers are not registered yet; this is Step 2.
- API request and approval routes remain service-driven until Step 3.
- Tracing, artifact idempotency, sufficiency re-check orchestration, and event-driven E2E remain pending later steps.
- The worker intentionally does not add an external queue or automatic Telegram publishing.

Next step:

- Implement Step 2 typed core event dispatch registry and handlers, then run only the focused dispatch tests.

## Orchestration Hardening Step 2: Core Workflow Event Handlers

Date/time: 2026-07-11 01:56:35 +0330

Objective: Connect the existing content-production domain services to the typed dispatcher while preserving human and external-provider boundaries.

Files changed:

- `backend/app/content_production/handlers.py`
- `backend/app/content_production/orchestration.py`
- `backend/tests/test_content_production_handlers.py`
- `progress.md`
- `phase-handoff.md`

Behavior implemented:

- Registered every `WorkflowEventType` with an explicit handler.
- Wired candidate selection, shortlist preparation, explicit shortlist approval/rejection, and production-run creation.
- Wired sufficiency checks and sufficient/partial/insufficient branching.
- Wired article extraction and web enrichment request/completion/failure paths.
- Wired editorial brief, Telegram draft, quality, media selection, and package service steps.
- Wired final approval result handling and Telegram dispatch handoff creation.
- Wired external image/publication completion and failure callbacks without implementing providers or publishing.
- Added strict UUID/string/integer/list payload validation and required aggregate/artifact loading.
- Added run-state validation before every stateful service call or callback transition.
- Added deterministic follow-up event IDs, preserved `correlation_id`, and set `causation_id` to the consumed event ID.
- Allowed handler exceptions to propagate to the Step 1 worker for retry/failure recording.

Explicit handler decisions:

- `ContentProductionRequestCreated` validates the request and emits nothing because the current API already writes the sibling `CandidateSelectionRequested` event. Step 3 will decide the final producer shape.
- `CandidateShortlistApprovalRequested` validates and pauses for an operator.
- `DraftRevisionRequested` validates and pauses for human revision.
- `ImageGenerationRequested` validates and pauses at the external-provider boundary; no real image generation was added.
- `FinalApprovalRequested` validates and pauses for an operator.
- `TelegramDispatchRequested` creates only a dispatch handoff; it never publishes.
- `TelegramPostPublished` and `TelegramPostFailed` only consume explicit external delivery callbacks.
- Rejection events validate persisted rejection state and terminate progression.

Event chains now supported:

- Candidate selection -> shortlist prepared -> shortlist approval requested.
- Explicit shortlist approval -> production run -> sufficiency check.
- Sufficient -> editorial brief -> draft -> quality -> media -> package -> final approval requested.
- Partial/insufficient -> extraction, with extraction completion requesting a sufficiency re-check.
- Extraction failure -> web enrichment; enrichment completion requests a sufficiency re-check.
- Explicit package approval -> dispatch requested -> dispatch handoff only.
- Quality revision, image generation, shortlist approval, final approval, and publishing remain paused at their required boundaries.

Tests added:

- `backend/tests/test_content_production_handlers.py`
  - complete registry coverage
  - candidate selection and explicit shortlist approval
  - correlation and causation propagation
  - sufficient and partial sufficiency branches
  - extraction and enrichment completion re-checks
  - service-backed brief-through-package chain
  - final approval pause and dispatch gate
  - worker retry behavior for handler failure
  - invalid-state rejection

Validation results:

- Focused handler tests: `10 passed`.
- Worker, dispatcher, handler, foundation, and adjacent content-production service tests: `84 passed`.
- Ruff: `All checks passed!`.
- Diff whitespace check: passed.

Remaining gaps for Step 3:

- Request creation still invokes candidate selection synchronously and writes completion events itself.
- Shortlist approval still creates production runs synchronously instead of only emitting the approval event.
- Final package approval does not yet emit `PostPackageApproved` from the API action.
- API event payloads need alignment with the validated handler contracts.
- Tracing, full artifact idempotency, and the complete event-driven E2E remain later hardening steps.

Next step:

- Implement Step 3 API deferral only, preserving the handler and worker contracts established here.

## Orchestration Hardening Step 3: Event-Driven API Producers

Date/time: 2026-07-11 02:13:30 +0330

Objective: Remove synchronous workflow advancement from content-production mutation APIs and persist command state plus durable outbox events in the same transaction.

Files changed:

- `backend/app/api/routes.py`
- `backend/app/content_production/repository.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_api_contract.py`
- `progress.md`

API routes changed:

- `POST /content-production/requests`
- `POST /content-production/requests/{request_id}/shortlist/approve`
- `POST /content-production/requests/{request_id}/shortlist/reject`
- `POST /content-production/packages/{package_id}/approve`
- `POST /content-production/packages/{package_id}/reject`

Synchronous advancement removed:

- Request creation no longer calls `CandidateSelectionService.prepare_shortlist()`.
- Request creation no longer creates shortlist, shortlist-prepared, or approval-requested results synchronously.
- Shortlist approval no longer creates `ContentProductionRun` rows directly.
- Final package approval does not create a `TelegramDispatchRequest` directly.

Event-driven producer behavior:

- Request creation persists `ContentProductionRequest`, `ContentProductionRequestCreated`, and `CandidateSelectionRequested`, then returns the current `created` state with an empty shortlist.
- The established Step 2 two-event request contract is intentionally retained: `ContentProductionRequestCreated` is an auditable validation event and `CandidateSelectionRequested` is the executable command. Their event IDs are deterministic per request/type, so they cannot duplicate within the request transaction.
- Shortlist approval persists the explicit candidate decision and emits `CandidateShortlistApproved`; the worker handler creates the run and `ContentSufficiencyCheckRequested`.
- Shortlist rejection persists rejection and emits `CandidateShortlistRejected`; its handler validates terminal state and creates no run.
- Final package approval persists approval and emits `PostPackageApproved`; worker processing emits `TelegramDispatchRequested`, and the next worker batch creates the handoff.
- Final rejection persists rejection and emits `PostPackageRejected`; it never creates dispatch.
- Revision request remains intentionally synchronous only for the human decision/state mutation and emits no automatic progression event, so the workflow pauses in `revision_requested`.

Payload and metadata alignment:

- Request events include `request_id` and use the request as aggregate and correlation ID.
- Shortlist decision events include `request_id` and `content_item_ids`.
- Package decision events use the production run aggregate and include `production_run_id`, `package_id`, and `approval_status`.
- API-originated events have no causation ID; handler-emitted events preserve correlation and set causation to the consumed event ID.
- API event IDs use UUIDv5 derived from aggregate, event type, and decision discriminator.

Idempotency contract within Step 3 scope:

- Repeated identical request payloads create distinct request commands because no client idempotency key is part of the API contract; each request has its own correlation ID.
- Repeated identical shortlist approval reuses one deterministic approval event and worker processing creates one run in the focused contract test.
- Repeated final approval returns HTTP `409` after the first decision and does not create another approval event.
- Rejection and revision remain non-dispatching terminal/pause decisions.

Test changes:

- Added `backend/tests/test_content_production_api_deferral.py` with seven focused API-to-worker tests.
- Updated the older candidate API assertions from synchronous shortlist/run completion to the stronger asynchronous producer contract required by `ACTIVE_PHASE.md`; no coverage was removed or weakened.
- Extended package API contract coverage to assert `PostPackageApproved` metadata and absence of synchronous dispatch.
- Extended the API contract fake session with normal ORM `add()` behavior so durable events are observable.

Commands run and exact results:

1. Initial focused API producer run:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py tests/test_content_production_orchestration.py::test_request_api_enqueues_candidate_selection_without_running_it tests/test_content_production_orchestration.py::test_shortlist_approval_api_emits_event_and_defers_run_creation tests/test_content_production_candidates.py::test_create_content_production_request_endpoint_defers_shortlist_to_worker tests/test_content_production_candidates.py::test_shortlist_approve_endpoint_defers_run_creation_to_worker tests/test_content_production_api_contract.py::test_content_production_package_approve_endpoint_uses_final_gate tests/test_content_production_api_contract.py::test_content_production_package_approve_endpoint_rejects_wrong_state -q`
   - Result: `3 failed, 7 passed`.
   - Finding: newly constructed outbox ORM rows depended on database server defaults for `status` and `attempt_count`, preventing the in-memory worker boundary from seeing them as pending.
2. Focused rerun after explicitly initializing outbox status/attempt fields:
   - Same focused command.
   - Result: `10 passed`.
3. Expanded API deferral contract:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py -q`
   - Result: `7 passed`.
4. Step 3 combined validation:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py tests/test_content_production_handlers.py tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_production_api_contract.py tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event tests/test_content_production_orchestration.py::test_request_api_enqueues_candidate_selection_without_running_it tests/test_content_production_orchestration.py::test_shortlist_approval_api_emits_event_and_defers_run_creation tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler tests/test_content_production_orchestration.py::test_sufficiency_progression_emits_the_required_next_event tests/test_content_production_orchestration.py::test_sufficiency_progression_stops_after_extraction_and_enrichment_attempts tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py tests/test_dispatch_handoff.py -q`
   - Result: `98 passed`.
5. Ruff first run:
   - Command: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app/api/routes.py app/content_production/repository.py tests/test_content_production_api_deferral.py tests/test_content_production_candidates.py tests/test_content_production_api_contract.py`
   - Result: one `E501` line-length finding in the new test; formatted without changing behavior.
6. Ruff rerun:
   - Same Ruff command.
   - Result: `All checks passed!`.
7. Diff whitespace:
   - Command: `git diff --check -- backend/app/api/routes.py backend/app/content_production/repository.py backend/tests/test_content_production_api_deferral.py backend/tests/test_content_production_candidates.py backend/tests/test_content_production_api_contract.py progress.md phase-handoff.md`
   - Result: passed before the external removal of `phase-handoff.md`.

Known risks and remaining work:

- The request API has no client-supplied idempotency key, so repeated equivalent payloads intentionally create distinct requests.
- Full artifact idempotency is not implemented in this step.
- `AgentStepRun` tracing is still missing and is the next active hardening concern.
- The complete event-driven E2E remains expected to fail later assertions until tracing and artifact idempotency steps are complete.
- `phase-handoff.md` was no longer present when final Step 3 reporting ran; it was not recreated because the user requested `progress.md` evidence and removed workspace files must not be restored implicitly.

Step 4 readiness:

- Step 3 completion criteria are satisfied by focused tests.
- Step 4 tracing is safe to begin in a separate run.

## Orchestration Hardening Step 3.5: Canonical Entry Event And PostgreSQL Atomicity

Date/time: 2026-07-11 05:52:36 +0330

Objective: Establish one canonical initial workflow event chain and prove aggregate/outbox atomicity with a real PostgreSQL rollback test before beginning tracing.

Files changed:

- `backend/app/api/routes.py`
- `backend/app/content_production/handlers.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_orchestration.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `progress.md`

Previous initial behavior:

```text
API creates ContentProductionRequest
-> API emits ContentProductionRequestCreated
-> API also emits CandidateSelectionRequested
-> ContentProductionRequestCreated handler only validates
```

Canonical initial event chain now implemented:

```text
API creates ContentProductionRequest
-> API emits ContentProductionRequestCreated only
-> worker consumes ContentProductionRequestCreated
-> handler validates request state and emits CandidateSelectionRequested
-> next worker batch consumes CandidateSelectionRequested
-> candidate selection service creates shortlist
```

API and handler changes:

- Removed direct `CandidateSelectionRequested` enqueueing from `POST /content-production/requests`.
- The request API still does not invoke candidate selection synchronously and still returns `created` with an empty shortlist.
- `ContentProductionRequestCreated` now requires the request to remain in `created` state and emits the selection command with `request_id` and `max_candidates`.
- Handler-emitted selection events use the request aggregate, preserve the initial event's correlation ID, and set causation ID to the consumed initial event ID.

Duplicate-event protection:

- Handler follow-up IDs remain UUIDv5 values derived from the consumed event ID, next event type, aggregate type, and aggregate ID.
- Reprocessing the same `ContentProductionRequestCreated` event derives the same selection event ID.
- `enqueue_event_once()` returns the existing selection event, so duplicate processing does not create another row.
- This step intentionally does not add client command/idempotency keys.

Canonical-chain tests added or updated:

- Request API emits exactly one `ContentProductionRequestCreated` event.
- No shortlist or `CandidateSelectionRequested` exists immediately after the API response.
- First worker batch emits one selection request with correct aggregate, payload, correlation, and causation.
- Second worker batch performs candidate selection and creates the shortlist.
- Direct reprocessing of the initial event creates one selection-request event.
- Legacy request API assertions were updated to the stricter one-event entry contract without removing the no-synchronous-selection assertions.

PostgreSQL integration-test design:

- Added `backend/tests/test_content_production_postgres_atomicity.py`.
- The fixture connects to `TEST_DATABASE_URL` or defaults to `postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft`.
- It creates a UUID-named PostgreSQL schema, creates current `Base.metadata` inside that schema, and drops the schema with `CASCADE` after the test.
- The test uses a real async SQLAlchemy session and `ContentProductionRepository`.
- It creates and flushes a `ContentProductionRequest`, verifies the row is present in the active transaction, then calls `enqueue_event_once()` with a null `correlation_id`.
- PostgreSQL raises `IntegrityError` from the real `workflow_events.correlation_id NOT NULL` constraint.
- The transaction is rolled back.
- A fresh session in the same isolated schema verifies that neither the request nor the workflow event persisted.
- The test fails explicitly with PostgreSQL startup/`TEST_DATABASE_URL` instructions if the database cannot be reached; it is never silently skipped.

Environment used:

- Started the repository PostgreSQL 18 service with `docker compose up -d postgres`.
- Confirmed `newscraft-postgres-1` was healthy on `localhost:5432`.
- Ran the integration test against the default test URL.
- The fixture dropped its isolated schema after each run.
- Stopped the PostgreSQL service after validation, restoring its prior stopped state.

Exact validation commands and results:

1. Initial canonical-chain focused run after implementation:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py::test_request_api_defers_shortlist_until_worker_processing tests/test_content_production_api_deferral.py::test_repeated_request_payload_creates_distinct_request_commands tests/test_content_production_api_deferral.py::test_reprocessing_initial_event_does_not_duplicate_selection_request tests/test_content_production_handlers.py::test_request_created_emits_one_causally_linked_candidate_selection_request tests/test_content_production_candidates.py::test_create_content_production_request_endpoint_defers_shortlist_to_worker tests/test_content_production_orchestration.py::test_request_api_enqueues_candidate_selection_without_running_it -q`
   - Result: `6 passed`.
2. First real PostgreSQL rollback run:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q`
   - Result: `1 passed`.
3. Required ordered canonical-chain validation:
   - Same command as item 1.
   - Result: `6 passed`.
4. API deferral request and decision tests:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py -q`
   - Result: `8 passed`.
5. Worker and dispatcher regression tests:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler -q`
   - Result: `6 passed`.
6. Handler regression tests:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_handlers.py -q`
   - Result: `11 passed`.
7. Required real PostgreSQL rollback rerun:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q`
   - Result: `1 passed`.
8. Broader workflow/API validation:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py tests/test_content_production_postgres_atomicity.py tests/test_content_production_handlers.py tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_production_api_contract.py tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event tests/test_content_production_orchestration.py::test_request_api_enqueues_candidate_selection_without_running_it tests/test_content_production_orchestration.py::test_shortlist_approval_api_emits_event_and_defers_run_creation tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler tests/test_content_production_orchestration.py::test_sufficiency_progression_emits_the_required_next_event tests/test_content_production_orchestration.py::test_sufficiency_progression_stops_after_extraction_and_enrichment_attempts tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py tests/test_dispatch_handoff.py -q`
   - Result: `101 passed`.
9. Ruff:
   - Command: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app/api/routes.py app/content_production/handlers.py tests/test_content_production_api_deferral.py tests/test_content_production_handlers.py tests/test_content_production_candidates.py tests/test_content_production_orchestration.py tests/test_content_production_postgres_atomicity.py`
   - Result: `All checks passed!`.
10. Diff whitespace:
    - Command: `git diff --check -- backend/app/api/routes.py backend/app/content_production/handlers.py backend/tests/test_content_production_api_deferral.py backend/tests/test_content_production_handlers.py backend/tests/test_content_production_candidates.py backend/tests/test_content_production_orchestration.py backend/tests/test_content_production_postgres_atomicity.py progress.md`
    - Result: passed.

Deferred limitation:

- UUIDv5 deduplication intentionally treats the same source event and derived event identity as one command.
- Future product commands that intentionally repeat the same aggregate/event/discriminator, such as regenerate, version, reselect, or redispatch, require explicit client command/idempotency keys.
- Those APIs and the broader event-ID design are outside Step 3.5 and were not implemented.

Step 4 readiness:

- The canonical entry event chain is unambiguous and tested.
- Real PostgreSQL behavior proves aggregate/outbox rollback atomicity.
- Steps 1 through 3 focused regressions remain green.
- Step 4 `AgentStepRun` tracing is safe to begin in a separate run.

## Orchestration Hardening Step 4: Production AgentStepRun Tracing

Date/time: 2026-07-11 06:07:51 +0330

Objective: Add complete operational `AgentStepRun` lifecycle tracing to every production workflow handler without beginning artifact idempotency hardening.

Tracing architecture:

- Added `WorkflowTraceService` as a shared dispatcher execution wrapper.
- Every registered core handler is wrapped once at dispatcher construction; workflow decisions remain in the existing handlers.
- The wrapper creates a `running` trace, executes the handler inside a nested transaction/savepoint when supported, captures bounded output, and marks the trace `completed`.
- On handler failure, the savepoint rolls back handler-side changes, the trace is marked `failed`, a bounded error is stored, `finished_at` is set, and the original exception is re-raised.
- Worker retry and terminal-failure behavior remains unchanged and receives the original handler exception.
- Compound handlers emit explicit additional completed traces for `production_run_creation` and `visual_brief_creation` rather than hiding those operations inside broader steps.

Schema and migration:

- Changed `AgentStepRun.production_run_id` to nullable so request-level steps can be traced without fake production runs.
- Request ID and complete event context are stored in bounded `input_snapshot_json`; no extra event-context columns were required.
- Added linear migration `0013_agent_step_run_request_tracing` after `0012_telegram_dispatch_requests`.
- No uniqueness or artifact constraints were added.

Files changed:

- `backend/app/db/models.py`
- `backend/app/content_production/repository.py`
- `backend/app/content_production/tracing.py`
- `backend/app/content_production/handlers.py`
- `backend/alembic/versions/0013_agent_step_run_request_tracing.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_hardening.py`
- `backend/tests/test_content_production_foundation.py`
- `progress.md`

Handlers instrumented:

- Request handling and candidate selection.
- Shortlist preparation, approval gate, approval handling, rejection handling, and production-run creation.
- Sufficiency checking and result routing.
- Article extraction, completion, and failure handling.
- Web enrichment, completion, and failure handling.
- Editorial brief creation/completion.
- Telegram draft generation/completion.
- Draft quality checking/result handling and revision requests.
- Media resolution, visual brief creation, and media selection.
- Image-generation request creation and success/failure callbacks.
- Telegram package creation/readiness.
- Final approval gate, approval handling, and rejection handling.
- Dispatch handoff.
- Telegram success/failure callbacks.
- Production-run failure handling.

Request-level tracing approach:

- `ContentProductionRequestCreated`, candidate selection, shortlist preparation, and approval-gate traces may have `production_run_id = NULL`.
- Their snapshots retain request ID, aggregate identity, event ID/type, correlation ID, causation ID, and worker attempt count.
- `production_run_creation` traces are recorded after run creation and use the created run IDs derived from emitted sufficiency events.

Trace data and lifecycle:

- Statuses are explicitly `running`, `completed`, and `failed`.
- `started_at` is written when the trace is created and `finished_at` on either success or failure.
- Input captures request/run identifiers, state before execution, sanitized event payload, and event/attempt context.
- Output captures state after execution, emitted event IDs/types/aggregates/payload summaries, shortlist identifiers/counts, and the latest relevant artifact ID/status.
- Deterministic services leave `model_name = NULL` and `token_usage_json = {}`.
- Provider abstractions currently do not expose model/token metadata, so no provider or token values are fabricated.

Snapshot sanitization policy:

- Recursion is capped at five levels.
- Dictionaries are capped at 30 keys and collections at 20 entries.
- Keys are bounded to 80 characters.
- Secret-like keys containing token, secret, password, API key, authorization, or credential are replaced with `[REDACTED]`.
- Large/body/content/HTML/prompt/text values are replaced by length, SHA-256, and an 80-character excerpt.
- Arbitrary long strings are summarized rather than copied in full.
- Error descriptions contain the exception class and at most 400 message characters; stack traces are not persisted.

Retry-attempt behavior:

- The worker increments `WorkflowEvent.attempt_count` before dispatch, and the trace records that value.
- Each handler execution creates a new trace UUID.
- A failed first attempt remains `failed`; a later successful retry creates a separate `completed` trace.
- Failed historical traces are never overwritten.
- Full artifact retry/idempotency behavior remains Step 5 scope and was not changed.

Tests added or updated:

- Candidate selection creates a completed request-level trace through the real worker/dispatcher/handler path.
- Event ID/type, correlation, causation, attempt count, and aggregate identity are retained.
- Secret and large-text payload data is sanitized.
- A worker-driven happy path records required completed traces through dispatch handoff.
- Production-run and visual-brief creation have explicit traces.
- Extraction and null-provider enrichment failure paths are traced through production failure.
- Direct handler failure creates a failed trace and re-raises the original `LookupError`.
- Worker retry keeps the failed attempt and adds a distinct completed attempt with attempt counts 1 and 2.
- The original sufficiency trace regression now exercises the production worker/handler path instead of calling a service helper directly.
- Foundation tests verify nullable request-level trace support and the minimal linear migration.

Exact commands and results:

1. Existing handler regression after wrapper integration:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_handlers.py -q`
   - Result: `11 passed`.
2. Initial focused tracing run:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_handlers.py tests/test_content_production_hardening.py::test_meaningful_workflow_step_records_a_completed_agent_step_run -q`
   - Result: `1 failed, 16 passed` because the updated regression fixture omitted its `WorkflowEvent` import.
3. Focused rerun after fixture import correction:
   - Same command.
   - Result: `1 failed, 16 passed`; the legacy test exposed the established `content_sufficiency` step-name contract.
4. Focused rerun after preserving the existing step name:
   - Same command.
   - Result: `17 passed`.
5. Ruff pre-validation:
   - Command: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app/db/models.py app/content_production/repository.py app/content_production/tracing.py app/content_production/handlers.py tests/test_content_production_handlers.py tests/test_content_production_hardening.py tests/test_content_production_foundation.py alembic/versions/0013_agent_step_run_request_tracing.py`
   - Result: one import-order and one line-length finding; both formatted without behavioral changes.
6. Focused tracing/schema/migration validation:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_handlers.py tests/test_content_production_hardening.py::test_meaningful_workflow_step_records_a_completed_agent_step_run tests/test_content_production_foundation.py -q`
   - Result: `27 passed`.
7. Worker, dispatcher, API deferral, candidate API, and package API regressions:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler tests/test_content_production_api_deferral.py tests/test_content_production_candidates.py tests/test_content_production_api_contract.py -q`
   - Result: `23 passed`.
8. PostgreSQL transactional atomicity regression:
   - Environment: repository PostgreSQL 18 container started and allowed to become ready; default test URL used.
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q`
   - Result: `1 passed`.
   - Cleanup: isolated schema dropped by the fixture; PostgreSQL container stopped to restore its prior state.
9. Broader workflow/API validation:
   - Command: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_handlers.py tests/test_content_production_foundation.py tests/test_content_production_candidates.py tests/test_content_production_api_contract.py tests/test_content_production_api_deferral.py tests/test_content_production_postgres_atomicity.py tests/test_content_production_orchestration.py::test_outbox_worker_claims_processes_and_marks_successful_events tests/test_content_production_orchestration.py::test_outbox_worker_retries_then_marks_a_poison_event_failed tests/test_content_production_orchestration.py::test_outbox_worker_skips_already_processed_events tests/test_content_production_orchestration.py::test_dispatch_registry_routes_handlers_by_event_type tests/test_content_production_orchestration.py::test_candidate_selection_is_performed_when_the_worker_processes_its_event tests/test_content_production_orchestration.py::test_request_api_enqueues_candidate_selection_without_running_it tests/test_content_production_orchestration.py::test_shortlist_approval_api_emits_event_and_defers_run_creation tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler tests/test_content_production_orchestration.py::test_sufficiency_progression_emits_the_required_next_event tests/test_content_production_orchestration.py::test_sufficiency_progression_stops_after_extraction_and_enrichment_attempts tests/test_content_production_hardening.py::test_meaningful_workflow_step_records_a_completed_agent_step_run tests/test_content_sufficiency.py tests/test_content_enrichment.py tests/test_editorial_briefs.py tests/test_telegram_drafts.py tests/test_draft_quality.py tests/test_media_resolver.py tests/test_telegram_packages.py tests/test_dispatch_handoff.py -q`
   - Result: `109 passed`.
10. Final Ruff validation:
    - Command: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app/db/models.py app/content_production/repository.py app/content_production/tracing.py app/content_production/handlers.py tests/test_content_production_handlers.py tests/test_content_production_hardening.py tests/test_content_production_foundation.py alembic/versions/0013_agent_step_run_request_tracing.py`
    - Result: `All checks passed!`.
11. Alembic history:
    - Command: `.venv/bin/alembic history`
    - Result: linear history with `0013_agent_step_run_request_tracing (head)` after `0012_telegram_dispatch_requests`.
12. Diff whitespace:
    - Command: `git diff --check -- backend/app/db/models.py backend/app/content_production/repository.py backend/app/content_production/tracing.py backend/app/content_production/handlers.py backend/alembic/versions/0013_agent_step_run_request_tracing.py backend/tests/test_content_production_handlers.py backend/tests/test_content_production_hardening.py backend/tests/test_content_production_foundation.py progress.md`
    - Result: passed.

Model/provider metadata limitations:

- Existing extraction, enrichment, image, and text-generation abstractions do not expose standardized model names or token usage.
- Traces therefore leave `model_name` null and token usage empty rather than inventing metadata.
- Provider-specific metadata can be added when provider contracts expose it, without changing this lifecycle.

Known risks and deferred work:

- Snapshot summaries are deliberately operational and bounded; they do not preserve full provider inputs or article bodies.
- Request identity is stored in snapshots rather than a new indexed request foreign-key column; add one later only if operational query patterns justify it.
- The synchronous human revision API has no originating workflow event; event-driven draft revision handling is traced, while changing producer contracts remains out of Step 4 scope.
- Full artifact idempotency, uniqueness, and repeated-event artifact reuse remain Step 5 work and were not implemented.

Step 5 readiness:

- Step 4 tracing completion criteria are satisfied by worker-dispatched tests and regressions.
- Step 5 artifact idempotency hardening is safe to begin only in a separate run.

## Orchestration Hardening Step 4.5: Transaction-Safe And Complete Tracing

Date/time: 2026-07-11 06:38:08 +0330

Objective: Correct the six blocking Step 4 tracing findings without beginning Step 5 artifact idempotency.

Blocking findings addressed:

- Handler domain behavior, output snapshot creation, completed-trace finalization, and its flush now remain inside one nested transaction/savepoint.
- A handler or trace-finalization exception rolls back all domain work from that attempt before the outer transaction records a failed trace and the worker's retry/error state.
- PostgreSQL integration tests now prove failed-trace retention, failed-then-successful retry history, trace-finalization rollback, and completed-trace/domain rollback on an outer commit constraint failure.
- The five real human command mutations now have precise command-level traces at the API mutation point: shortlist approval/rejection and final package approval/rejection/revision.
- Migration 0013 now deterministically deletes request-level traces that have no pre-0013 representation before restoring `production_run_id NOT NULL`.
- Recursive sanitization now normalizes case, whitespace, hyphens, and underscores and covers authorization, cookies, sessions, API/private/provider keys, credentials, passwords, secrets, and token suffixes.
- Dispatcher coverage now compares the complete `WorkflowEventType` enum with the production registry.

Transaction and retry design:

- The initial `running` trace is flushed in the outer transaction.
- The handler and every success-finalization operation execute inside a savepoint; the savepoint is released only after the completed trace flush succeeds.
- Failure phase is recorded as `domain_handler`, `output_snapshot`, or `trace_finalization`; command traces distinguish `human_decision` from `trace_finalization`.
- On failure, the savepoint restores handler/domain state, then the outer transaction updates the original trace to `failed`; the worker reuses its existing retry or terminal-failure policy and commits the trace with event attempt/error state.
- Each retry creates a fresh trace UUID and records the already-incremented worker attempt count. PostgreSQL verification confirmed attempts 1 and 2 remain as separate failed/completed rows and one domain artifact exists.
- A real PostgreSQL `workflow_events.correlation_id NOT NULL` violation at the store commit boundary proved that an uncommitted completed trace and candidate artifact both roll back with the worker transaction.

Human decision tracing:

- `shortlist_approval_decision` and `shortlist_rejection_decision` retain request/aggregate identity, selected content item IDs, prior candidate status, new status, and resulting event ID without a fake run.
- `final_package_approval_decision` and `final_package_rejection_decision` retain request/run/package identity, prior and new run/package states, decision, and resulting event ID.
- `final_package_revision_request` traces the synchronous package/run mutation, records the absent revision reason explicitly as null, and records that no event is emitted.
- Downstream event traces were renamed to `shortlist_approval_event_progression`, `shortlist_rejection_event_handling`, `final_approval_dispatch_progression`, `final_rejection_event_validation`, and `draft_revision_pause` so they do not impersonate the earlier human action.
- Known command failures persist a failed decision trace before the API returns its existing 404/409 response.

Synthetic trace correction:

- Removed copied `production_run_creation` and `visual_brief_creation` trace rows.
- Created production-run IDs remain in the shortlist approval progression trace's emitted-event output.
- The created `VisualBrief` remains an explicit artifact ID/type/status in the genuine `media_resolution` trace.
- Tests assert the copied synthetic names are absent while the artifact evidence remains present.

Migration downgrade policy:

- Request-level null-run traces cannot be represented by the pre-0013 schema and are explicitly deleted on downgrade; no fake run is assigned.
- A real PostgreSQL test invokes migration 0013 upgrade and downgrade operations, inserts a null-run trace, confirms it is removed, and confirms the column returns to `NOT NULL`.
- Alembic remains linear with 0013 directly after 0012.

Snapshot policy:

- Secret keys are normalized with case folding and hyphen/underscore/whitespace equivalence.
- Authorization/proxy authorization, cookies, session variants, auth/API/private/provider keys, credentials, password/passwd, client secrets, and token/secret suffixes are recursively redacted.
- Prompt, provider request/response/payload, headers, configuration, and environment-like values store only a redacted marker, length, and SHA-256; no excerpt is retained.
- Ordinary large article text remains bounded as length, SHA-256, and an 80-character excerpt so operational identifiers and decisions remain useful.

Files changed:

- `backend/app/content_production/tracing.py`
- `backend/app/content_production/handlers.py`
- `backend/app/content_production/candidates.py`
- `backend/app/api/routes.py`
- `backend/alembic/versions/0013_agent_step_run_request_tracing.py`
- `backend/tests/test_content_production_tracing.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_orchestration.py`
- `backend/tests/test_content_production_foundation.py`
- `progress.md`

Validation evidence:

1. Initial tracing/API/handler/registry run: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_tracing.py tests/test_content_production_handlers.py tests/test_content_production_api_deferral.py tests/test_content_production_orchestration.py::test_core_dispatcher_registers_every_required_handler -q` -> `29 passed`.
2. Initial PostgreSQL run: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q` -> five transaction tests passed; migration test failed because `alembic/versions` is not a Python package.
3. Migration loader correction rerun: the migration downgrade test -> `1 passed`.
4. Complete PostgreSQL rerun: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q` -> `6 passed`.
5. Focused transaction tests -> `2 passed`.
6. PostgreSQL failed-handler retention -> `1 passed`.
7. PostgreSQL failed-then-successful retry history -> `1 passed`.
8. PostgreSQL trace-finalization rollback -> `1 passed`.
9. Human decision API tracing tests -> `5 passed`.
10. Snapshot sanitization tests -> `3 passed`.
11. Complete registry/unknown dispatch coverage set -> `3 passed`.
12. Migration PostgreSQL and structural tests -> `2 passed`.
13. Existing Step 4 tracing tests -> `20 passed`.
14. Steps 1 through 3.5 worker, dispatcher, canonical chain, API deferral, candidate/API, and request/outbox PostgreSQL regression set -> `33 passed`.
15. Broader in-scope workflow/API/service set, including all six PostgreSQL tests -> `118 passed`.
16. Ruff: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check ...` -> `All checks passed!`.
17. Alembic: `.venv/bin/alembic history` -> linear `0012 -> 0013 (head)`.

Validation notes and remaining limitations:

- The repository PostgreSQL 18 service was started, reached healthy state, and every PostgreSQL test ran rather than skipping.
- A broader exploratory run exposed three pre-existing Step 5 artifact-idempotency tests for duplicate drafts/packages/dispatch; they remain failing and were not changed because ACTIVE_PHASE explicitly prohibits implementing that behavior now.
- The phase-forward event-driven E2E fixture follows the existing partial-content/extraction/enrichment failure path rather than its future happy-path assertions; content-quality behavior was not changed because it is outside Step 4.5.
- Provider abstractions still expose no standardized model/token accounting, so deterministic/provider traces continue to leave those fields null/empty rather than fabricating metadata.
- No artifact uniqueness constraints, command idempotency keys, real external providers, publishing, or other Step 5 behavior was added.

Step readiness:

- All Step 4.5 completion criteria within the active scope are satisfied, including real PostgreSQL transaction evidence.
- Step 4 can now be accepted.
- Step 5 is safe to begin only in a separate run and must address its existing artifact-idempotency failures.

## Orchestration Hardening Step 5: Artifact Idempotency Audit

Date/time: 2026-07-11 +0330

Objective: Prevent duplicate production artifacts under replay, retry, repeated approval, and concurrent workers while preserving distinct future command/version identities.

| Artifact | Creator | Current lookup | Current database enforcement | Logical identity | Future versions | Required fix |
| --- | --- | --- | --- | --- | --- | --- |
| Production run | `CandidateShortlistApproved` handler / repository | Request runs scanned by content item | Primary key only | approval event + candidate content item | Yes, a new approval command may start another run | Deterministic event-derived ID, canonical reload on replay/race |
| Candidate shortlist row | Candidate selection service | None before insert | `request_id + content_item_id` unique | selection event + selected content item | Yes, a later selection execution may reconsider the item | Deterministic ID; remove over-broad request/item uniqueness and retain lookup index |
| Sufficiency report | Sufficiency service | None | Primary key only | sufficiency request event | Yes, extraction/enrichment rechecks use new events | Deterministic event-derived ID and canonical reuse |
| Article extraction result | Extraction service | None | Primary key only | extraction request event | Yes, intentional rerun uses a new event | Deterministic event-derived ID and canonical reuse |
| Web enrichment result | Enrichment service | None | Primary key only | enrichment request event | Yes, intentional rerun uses a new event | Deterministic event-derived ID and canonical reuse |
| Editorial brief | Brief service | Latest-by-run only in consumers | Primary key only | brief-generation event | Yes, revisions/regeneration use a new event | Deterministic event-derived ID and canonical reuse |
| Telegram draft | Draft service | None | Primary key only | draft-generation event | Yes, revised draft uses a new event | Deterministic event-derived ID and canonical reuse |
| Draft quality report | Quality service | None | Primary key only | quality-check event + draft identity | Yes, a new draft/recheck uses a new event | Deterministic event-derived ID and canonical reuse |
| Media decision / visual brief | Media resolver | None | Primary key only | media-resolution event | Yes, a new media command uses a new event | Deterministic event-derived ID and canonical reuse |
| Image-generation request | Media resolution represented by `VisualBrief` and pause event | Event artifact lookup only | Visual brief primary key; workflow event primary key | media-resolution event / deterministic follow-up event | Yes, new media event | Reuse canonical visual brief and deterministic follow-up event |
| Telegram package | Package service | None | Primary key only | package-build event | Yes, revised package uses a new event | Deterministic event-derived ID and canonical reuse |
| Final approval event | Human decision API event enqueue | Lookup by deterministic event ID | Workflow event primary key | package + decision + selected discriminator | Different package/decision remains distinct | Preserve deterministic enqueue and canonical event return |
| Telegram dispatch request | Dispatch service | None | Primary key only | dispatch-request event | Yes, intentional redispatch uses a new event | Deterministic event-derived ID and canonical reuse |

Chosen identity direction:

- Use `uuid5(source_event_id, artifact_type + purpose + optional discriminator)` as the canonical artifact primary key.
- The existing primary-key constraint supplies concurrency enforcement for the exact logical command while a new event/command identity naturally produces a new version.
- Follow-up workflow events already use deterministic IDs derived from the source event, type, aggregate type, and aggregate ID; replay must reuse the canonical artifact ID in those payloads.
- Migration 0014 will remove the over-broad shortlist request/content-item unique constraint, replace it with a non-unique lookup index, and use a deterministic documented downgrade policy for rows that cannot coexist under the old schema.

### Step 5 Completion Evidence

Date/time: 2026-07-11 06:57:09 +0330

Identity model and database enforcement:

- Every artifact-producing handler passes its immutable source `WorkflowEvent.event_id` as the command identity.
- `artifact_id()` derives a UUIDv5 primary key from command ID, artifact purpose, and an optional per-item/draft/package discriminator.
- PostgreSQL primary-key constraints therefore reject concurrent duplicates for the exact command while a distinct command ID produces a distinct valid version.
- `create_or_get_artifact()` checks for the canonical row, wraps the complete domain mutation and insert in a savepoint, catches only the expected table primary-key constraint, rolls back losing state transitions, and reloads the winner.
- Unrelated integrity violations continue to propagate.
- Existing deterministic workflow-event IDs continue to provide one follow-up event per source command, and replay payloads use the canonical artifact ID.

Schema and migration:

- Added linear migration `0014_artifact_idempotency` after 0013.
- Removed `uq_candidate_shortlists_request_content_item`, which incorrectly prohibited future selection executions from reconsidering the same content item.
- Added non-unique `ix_candidate_shortlists_request_content_item` for approval and audit lookup.
- No one-artifact-per-run uniqueness constraints were added; deterministic primary keys encode logical command identity instead.
- Downgrade keeps the earliest `(created_at, id)` shortlist row for each request/content-item pair, removes later rows that the old schema cannot represent, drops the lookup index, and restores the old unique constraint.
- A real PostgreSQL migration test proves two distinct selection versions are accepted after upgrade, downgrade retains one deterministic canonical row, and the restored constraint rejects another duplicate.

Artifact creators hardened:

- Production runs use approval-event plus candidate-item identity.
- Candidate shortlist rows use selection-event plus content-item identity.
- Sufficiency, extraction, enrichment, editorial brief, and visual brief use their request event identity.
- Telegram drafts and quality reports include their brief/draft discriminator.
- Telegram packages include the source draft discriminator.
- Dispatch requests include the approved package discriminator.
- Image-generation handoff remains a deterministic workflow event linked to the canonical `VisualBrief`; no external image-generation implementation was added.
- Final approval API events retain their accepted deterministic event IDs and candidate/package discriminators.

Replay and recovery behavior:

- Requested-event handlers first resolve their deterministic artifact; a replay may run after the aggregate has advanced and still returns the canonical artifact without repeating state transitions.
- Replayed shortlist approval resolves the same production run per candidate and reuses its deterministic sufficiency event.
- Replayed sufficiency, extraction, enrichment, brief, draft, quality, media, package, and dispatch commands retain one artifact and one follow-up event.
- Replayed `PostPackageApproved` returns immediately when its deterministic dispatch event already exists.
- The event-driven E2E redelivers the original approval event ID and verifies one run, draft, package, dispatch request, and stable follow-up events.
- Repeated API submissions with an identical shortlist set retain one approval event; a changed candidate set produces a distinct approval command/event.
- Worker tracing remains attempt-based, so replay executions may create separate trace rows without duplicating domain artifacts.

Intentional-version behavior:

- Unit/service tests prove a new command identity can create a new sufficiency recheck, revised draft, revised package, and intentional dispatch request.
- Candidate-selection tests prove replay reuses rows while a distinct selection command can create a new version for the same request/content item.
- No regeneration API or client idempotency-key contract was introduced; future product commands must allocate and persist an explicit command identity before uncertain submission retries.

PostgreSQL concurrency scenarios:

- Two independent sessions concurrently create the same production run command and both return one canonical run ID.
- Two independent sessions concurrently create the same Telegram draft command and both return one canonical draft ID.
- Two independent sessions concurrently create the same Telegram package command and both return one canonical package ID.
- Two independent sessions concurrently create the same dispatch command and both return one canonical dispatch ID.
- Each losing insert rolls back its local state transitions inside the savepoint before reloading the committed winner.
- The complete PostgreSQL file, including Step 3.5/4.5 transaction regressions, passes with `11 passed`; no test was skipped.

Files changed:

- `backend/app/content_production/idempotency.py`
- `backend/app/content_production/repository.py`
- `backend/app/content_production/candidates.py`
- `backend/app/content_production/sufficiency.py`
- `backend/app/content_production/enrichment.py`
- `backend/app/content_production/briefs.py`
- `backend/app/content_production/telegram_drafts.py`
- `backend/app/content_production/quality.py`
- `backend/app/content_production/media.py`
- `backend/app/content_production/packages.py`
- `backend/app/content_production/dispatch.py`
- `backend/app/content_production/handlers.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/0014_artifact_idempotency.py`
- `backend/tests/test_content_production_hardening.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_orchestration.py`
- `backend/tests/test_content_production_foundation.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `progress.md`

Exact validation results:

1. Existing artifact duplicate and handler tests: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_hardening.py tests/test_content_production_handlers.py -q` -> `20 passed`.
2. Identity and intentional-version tests: `tests/test_content_production_hardening.py -q` -> `6 passed`.
3. Initial PostgreSQL concurrency run exposed fixture insertion ordering only: run race passed; three fixtures failed before their race began.
4. PostgreSQL concurrency rerun after ordered fixture flushes: `tests/test_content_production_postgres_atomicity.py -k 'concurrent_' -q` -> `4 passed, 6 deselected`.
5. PostgreSQL migration 0014 upgrade/version/downgrade test -> `1 passed`.
6. Complete PostgreSQL transaction/concurrency/migration suite: `tests/test_content_production_postgres_atomicity.py -q` -> `11 passed`.
7. Artifact, handler, candidate, foundation, orchestration, and API replay set -> `63 passed`.
8. Event-driven E2E replay test -> `1 passed`.
9. Initial full backend run exposed legacy fake sessions without `get()` and one fake that ignored SQL predicates: `18 failed, 257 passed`.
10. Focused compatibility rerun after shared lookup and predicate filtering -> `52 passed`.
11. Full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider tests -q` -> `275 passed`.
12. Ruff: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app tests alembic/versions` -> `All checks passed!`.
13. Alembic history: linear `0013 -> 0014_artifact_idempotency (head)`.

Remaining limitations and next-phase readiness:

- Explicit client command/idempotency keys remain a future API requirement for intentional regeneration or redispatch across uncertain client retries; current APIs derive stable identities from their accepted aggregate/discriminator contracts.
- Existing rows keep their original random primary keys and remain valid. Idempotency applies to new command-driven creation; migration does not fabricate event relationships for historical artifacts.
- No automatic sufficiency loop, real DDG, real image generation, Telegram publishing, generalized locks, or next-phase behavior was added.
- Step 5 completion criteria are satisfied. The next phase is safe to begin only in a separate run.

## Step 5.5 - Correct Artifact Identity Stability And Prove Concurrency Recovery

Objective:

- Correct the four blocking Step 5 review findings without starting the automatic sufficiency loop or Step 6.
- Preserve UUIDv5 command-derived artifact identities, savepoint conflict recovery, tracing, worker transactions, and human gates.

Package replay and event consistency:

- `TelegramPackageRequested` now carries immutable `draft_id`, `quality_report_id`, and `visual_brief_id` inputs.
- Media resolution pins the passing draft/quality pair before emitting media or image completion events; those identities are propagated into the package request.
- The package handler loads only the pinned records, verifies that all belong to the run, verifies that the quality report passed for the exact draft, and never falls back to the latest draft.
- Replaying the original package event after a newer draft exists reuses the original package and its stable `TelegramPackageReady` payload. A distinct package event pinned to the newer draft creates a distinct package version.
- `enqueue_event_once()` now compares event type, aggregate identity, correlation, causation, and payload when a deterministic event ID already exists. Identical replay is accepted; conflicting reuse raises `WorkflowEventConsistencyError`.

Candidate ordering and selection execution identity:

- Candidate ordering is total and deterministic: business score descending, recency descending, then immutable `ContentItem.id` ascending. The PostgreSQL candidate query uses the same immutable ID tie-break direction.
- Added non-null `CandidateShortlist.selection_execution_id`, populated from `CandidateSelectionRequested.event_id` for new selections.
- Shortlist rows are uniquely constrained by `selection_execution_id + content_item_id` and indexed by `request_id + selection_execution_id`.
- Shortlist responses expose `selection_execution_id`; approval and rejection payloads require it.
- Approval/rejection services, API events, prepared/gate events, and production handlers scope every lookup to the exact execution. Overlapping executions such as `S1: A,B` and `S2: A,C` no longer mix rows.
- Approval event IDs include the execution identity and normalized candidate set. Replaying the same execution/set is stable; a changed set or execution is distinct.

Migration:

- Added linear migration `0015_shortlist_selection_execution` after `0014_artifact_idempotency`.
- Upgrade preserves every existing shortlist row and deterministically assigns all legacy rows for one request to `md5(request_id || ':legacy_candidate_selection')::uuid`.
- Upgrade adds the execution lookup index and one-content-item-per-execution constraint.
- Downgrade drops only the new constraint, index, and column; it does not delete shortlist rows.
- A real PostgreSQL test proves deterministic legacy backfill, enforced per-execution uniqueness, and reversible downgrade.

PostgreSQL concurrency proof:

- The PostgreSQL fixture now creates tables with the test schema as the exclusive setup search path, preventing public-schema tables from defeating schema isolation.
- Each run, draft, package, and dispatch race uses two independent sessions and a shared `asyncio.Barrier` around the first canonical lookup.
- Instrumentation proves both initial lookups missed, exactly one primary-key conflict reached the expected recovery branch, and both sessions successfully queried after recovery.
- Both callers return the same canonical ID and exactly one row commits.
- A real foreign-key violation through `create_or_get_artifact()` proves unrelated integrity errors propagate, the invalid row is absent, and the session remains usable after savepoint rollback.

Production replay/version coverage:

- Dispatcher tests cover two overlapping shortlist executions, replay of both approvals, targeted run creation, and rejection of a mixed-execution approval.
- Dispatcher tests cover package replay after a newer draft, a distinct package command, dispatch replay, and a distinct dispatch command after a failed handoff.
- The worker E2E now replays actual candidate-selection, package-creation, shortlist-approval, and final-approval events while retaining one artifact/follow-up per logical command and preserving human gates and traces.

Files changed for Step 5.5:

- `backend/app/api/routes.py`
- `backend/app/api/schemas.py`
- `backend/app/content_production/candidates.py`
- `backend/app/content_production/handlers.py`
- `backend/app/content_production/repository.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/0015_shortlist_selection_execution.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_e2e.py`
- `backend/tests/test_content_production_foundation.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_orchestration.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `progress.md`

Exact validation evidence:

1. Initial focused contract run: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_candidates.py tests/test_content_production_foundation.py tests/test_content_production_handlers.py -q` -> expected legacy-contract failures, then `36 passed` after explicit execution IDs and focused tests were added.
2. Focused candidate/foundation/handler/orchestration run -> `53 passed`.
3. Initial PostgreSQL command failed explicitly with connection refused on `localhost:5432`; no test was skipped.
4. Started the repository database with `docker compose up -d postgres`.
5. Forced run/draft/package/dispatch races plus unrelated integrity error -> `5 passed, 7 deselected`; each race asserted `2` initial misses, `1` primary-key conflict, and `2` usable sessions.
6. Complete real PostgreSQL suite after migration and isolation corrections: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q` -> `14 passed`.
7. Adjacent workflow/API/content-production suite -> `135 passed`.
8. Handler regression after production dispatch-version coverage -> `19 passed`.
9. Final full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider tests -q` -> `284 passed`.
10. Ruff: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app tests alembic/versions` -> `All checks passed!`.
11. Alembic history -> linear `0014_artifact_idempotency -> 0015_shortlist_selection_execution (head)`.
12. `git diff --check` -> clean.

Deferred limitations and readiness:

- Pre-Step-5 artifacts may retain random IDs. Historical replay is unsupported for this local project and could create deterministic artifacts beside old rows. A production backfill/audit is required before external deployment.
- Generalized client command/idempotency keys remain deferred. Future intentional commands that repeat the same aggregate, event type, and discriminator across uncertain client retries need an explicit persisted command identity.
- No automatic sufficiency loop, real DDG, image generation, Telegram publishing, tracing redesign, worker redesign, or Step 6 behavior was added.
- Step 5 and Step 5.5 can now be accepted. Step 6 is safe to begin only in a separate run.

## Step 5.6 - Complete Migration Safety, Canonical Commands, Ranking Consistency, And Version-Aware Tracing

Objective:

- Correct the four remaining Step 5 blockers: valid historical shortlist migration, canonical approval/rejection commands, one authoritative candidate ranking contract, and command/version-aware trace output.
- Preserve package input pinning, deterministic events and artifacts, PostgreSQL savepoint recovery, worker transactions, human gates, and the canonical event chain.

Migration strategy and legacy grouping:

- Amended unreleased migration `0015_shortlist_selection_execution` rather than adding `0016`. The repository migrations are not committed/distributed, the project is local, and a later migration could not repair databases that fail while passing through the original 0015.
- Legacy rows are ordered deterministically within each request by `(created_at, id)`.
- A new rank cycle begins at the first row and whenever the current rank is less than or equal to the preceding rank. This reconstructs normal historical `1..N, 1..N` shortlist executions where the stored evidence permits it.
- Rows in one reconstructed cycle share a deterministic execution UUID derived from request ID plus the stable cycle number.
- If the same content item appears more than once inside one reconstructed cycle, later ambiguous occurrences receive a deterministic row-ID discriminator. This conservative fallback preserves every row and prevents false merging/uniqueness failure.
- No generated timestamps, random values, rows, or fake production runs are introduced. Upgrade deletes nothing.
- Exact original execution grouping cannot be perfectly reconstructed when legacy timestamps/ranks are insufficient; the policy prioritizes preservation, deterministic replay, and no uniqueness collision.
- The real PostgreSQL migration fixture contains `S1: A(rank 1), B(rank 2)` and `S2: A(rank 1), C(rank 2)`. Upgrade preserves all four rows, groups A/B and A/C separately, permits execution-scoped lookup, rejects a duplicate inside one execution, downgrades without row loss, and produces the same row-to-execution mapping on re-upgrade.

Canonical approval/rejection commands:

- `ShortlistDecisionIn` rejects duplicate candidate IDs with HTTP 422.
- Valid candidate IDs are sorted by UUID integer value during schema validation.
- The canonical list is therefore used consistently by the domain service, persisted event payload, deterministic event discriminator, and human-decision trace.
- Approval and rejection tests submit `[A, B]` followed by `[B, A]` and prove one event with one canonical payload. `[A, B]` and `[A, C]` remain distinct.
- Deterministic event consistency tests now cover identical replay, dictionary and nested-dictionary key order, ordered-list conflicts, aggregate conflicts, correlation conflicts, causation conflicts, and conflicting artifact payloads. Ordered JSON lists remain order-sensitive globally; only the candidate-set field is canonicalized.

Authoritative candidate ranking:

- Chose the MVP-safe Python-authoritative strategy. PostgreSQL fetches the eligible working set without ordering or a mismatched raw-score pre-limit; Python computes and selects the final shortlist.
- Total order is calculated business score descending, effective sort time descending, and immutable content item UUID ascending.
- Effective sort time is `sort_at`, else `created_at`, else fixed `datetime.min` UTC. Runtime `now()` is not an ordering fallback.
- Persisted `content_items.sort_at` is non-null under the current schema. The `created_at` and fixed-minimum fallbacks protect transient/legacy objects and are covered in memory without weakening the database constraint.
- Real PostgreSQL tests prove a lower raw-score candidate can win through calculated business signals, more than 25 higher-raw-score decoys cannot exclude the calculated winner, persisted timestamp ordering is stable, tied candidates cross a shortlist boundary deterministically, and replay returns identical rows, ranks, execution ID, and artifact IDs.

Execution-aware and version-aware tracing:

- Candidate-selection trace output filters by request ID plus the consumed `CandidateSelectionRequested.event_id` persisted as `selection_execution_id`.
- Candidate traces report execution ID, shortlist row IDs, selected content item IDs, ranks, count, and exact causally emitted events.
- Artifact-producing trace steps now derive the exact artifact ID from consumed event ID, artifact purpose, and immutable discriminator (`brief_id`, `draft_id`, or `package_id` where applicable).
- Trace finalization loads that exact canonical artifact rather than the latest artifact for the run.
- Artifact snapshots include type, ID, status, reused flag, and version discriminator. Pinned draft/quality/visual IDs remain visible in sanitized input payload snapshots; follow-up event IDs remain causation-scoped.
- Handler tests create S1 then S2 and replay S1, and create draft/package/dispatch command A then B and replay A. Every replay trace references only A's canonical rows/artifact and excludes B.
- Handler work and successful trace finalization remain inside the existing handler savepoint. Failed trace persistence and distinct retry attempt history remain covered by real PostgreSQL tests.

Existing automatic routing inventory:

- Existing `ContentSufficiencyChecked` routing sends sufficient content to editorial brief creation.
- Partial/insufficient content routes to article extraction when no extraction artifact exists, then web enrichment when extraction exists but enrichment does not, then production failure after both attempts.
- Successful article extraction and web enrichment emit another `ContentSufficiencyCheckRequested`; extraction failure routes directly to enrichment, and enrichment failure routes to production failure.
- There is no numeric loop counter. Termination is bounded by persisted extraction/enrichment artifact-existence flags and the final failure branch after both attempts.
- Current handler/orchestration tests cover sufficient, extraction, enrichment, recheck, failure, and approval-gate paths.
- Step 5.6 did not add or expand any routing, loop policy, external DDG, image generation, Telegram publishing, or sufficiency behavior. The next phase description must account for this already-existing bounded routing rather than claim routing is absent.

Files changed for Step 5.6:

- `backend/alembic/versions/0015_shortlist_selection_execution.py`
- `backend/app/api/schemas.py`
- `backend/app/content_production/candidates.py`
- `backend/app/content_production/tracing.py`
- `backend/tests/test_content_production_api_deferral.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_foundation.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `progress.md`

Exact validation evidence:

1. Exact repeated request/content PostgreSQL migration collision test -> `1 passed`.
2. Canonical approval/rejection and deterministic-event semantic tests: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_api_deferral.py tests/test_content_production_foundation.py -q` -> `29 passed`.
3. Migration plus calculated-score, timestamp, boundary, tie, and replay ranking focus -> `8 passed, 17 deselected`.
4. Version-aware selection/draft/package/dispatch handler trace suite: `tests/test_content_production_handlers.py -q` -> `21 passed`.
5. Complete real PostgreSQL atomicity, migration, ranking, conflict, and tracing suite: `tests/test_content_production_postgres_atomicity.py -q` -> `17 passed`.
6. Tracing and handler regressions -> `24 passed`.
7. Broader workflow/API/content-production suite -> `149 passed`.
8. Full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider tests -q` -> `297 passed`.
9. Ruff: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app tests alembic/versions` -> `All checks passed!`.
10. Alembic history -> linear `0014_artifact_idempotency -> 0015_shortlist_selection_execution (head)`.
11. `git diff --check` -> clean.

Remaining non-blocking limitations and readiness:

- Callers omitting `selection_execution_id` receive HTTP 422; no legacy latest-execution fallback exists.
- Integrity filtering is structurally strict for the exact table primary key, but real PostgreSQL coverage samples a foreign-key error rather than every possible NOT NULL/check/unrelated-unique category.
- Intentional redispatch is representable by a distinct event identity but has no public API.
- Pre-Step-5 random artifact IDs and perfectly unreconstructable pre-0015 execution groupings require an explicit audit/backfill policy before external deployment.
- Image generation remains a null-provider pause, and Telegram dispatch remains a non-publishing handoff.
- Step 5, Step 5.5, and Step 5.6 completion criteria are satisfied. The next phase must be redefined around the routing behavior that already exists and may begin only in a separate run.

## Step 6 - Validate And Harden The Existing Sufficiency Routing

Objective and pre-change inventory:

- Validate and complete the existing bounded original -> extraction -> enrichment sufficiency route without adding a generic loop engine or changing provider products.
- Before Step 6, handlers already emitted rechecks after successful extraction/enrichment and used extraction/enrichment artifact presence to choose a next step.
- The prior rechecks still evaluated only the original `ContentItem`, so derived content could never improve a sufficiency decision.
- Stage was inferred from mutable run artifact presence rather than persisted in the command. Brief creation also loaded latest extraction/enrichment artifacts.
- Extraction failure routed to enrichment and enrichment failure routed to `ProductionRunFailed`, but terminal payloads lacked complete structured routing context.

Authoritative stage and input model:

- Added explicit logical stages: `original`, `post_extraction`, and `post_enrichment`.
- Each `ContentSufficiencyCheckRequested` event carries one stage plus exact extraction/enrichment artifact IDs required by that stage.
- `SufficiencyInputAssembler` is the single input-selection boundary. It loads exact artifacts, rejects missing stage inputs, rejects invalid stage combinations, and verifies run/content-item ownership.
- Report identity remains command/event-derived, so S0, S1, and S2 produce distinct canonical reports while replay of one stage reuses its report.
- Report input snapshots record stage, source event ID, extraction ID, enrichment ID, and enrichment provider without putting article/search bodies in event payloads.
- Sufficiency evaluation combines original content with exact successful extraction text and exact successful enrichment finding title/snippet data.
- Evaluation results distinguish `sufficient`, `partial`/`insufficient`, `rejected`, and `evaluation_failed`; evaluator failure records a structured reason and terminates rather than being treated as ordinary insufficiency.

Final routing behavior:

- `original + sufficient` emits one editorial brief request and no extraction/enrichment request.
- `original + partial/insufficient` emits one extraction request.
- Successful or weak/fallback extraction emits `post_extraction` sufficiency check with the exact extraction result. It never generates a brief directly.
- `post_extraction + sufficient` emits the brief request and terminates routing.
- `post_extraction + partial/insufficient` emits one enrichment request carrying the extraction result ID.
- Successful enrichment emits `post_enrichment` sufficiency check carrying exact extraction/enrichment IDs.
- `post_enrichment + sufficient` emits the brief request exactly once.
- `post_enrichment + partial/insufficient` emits one `ProductionRunFailed` with `terminal_content_insufficient`, attempt availability, and `no_more_automatic_stages=true`; brief creation is not started.
- Brief requests carry the exact report/extraction/enrichment identities. Brief creation no longer resolves latest routing artifacts.

Failure policies:

- Extraction `failed` results are persisted and route once to enrichment. Missing source is classified `extraction_unavailable`; HTTP/provider failures are classified `technical`.
- Weak or empty-but-completed extraction uses the existing fallback result path, receives a post-extraction sufficiency decision, and proceeds to enrichment only when still insufficient.
- Enrichment `failed` or `skipped` results emit an explicit terminal failure containing provider, bounded reason, artifact IDs, extraction availability, current state, and termination marker.
- Unexpected handler/provider exceptions still propagate to the existing worker retry mechanism. The real PostgreSQL failed-then-successful enrichment test continues to prove separate retry attempts and rollback safety.
- A deterministic evaluator exception becomes an `evaluation_failed` report and explicit terminal event rather than an insufficient score.

Termination proof and replay behavior:

- The only automatic stage transitions are `original -> post_extraction -> post_enrichment`.
- Original insufficiency can emit extraction only; post-extraction insufficiency can emit enrichment only; post-enrichment insufficiency can emit terminal failure only.
- Maximum automatic sufficiency checks are three, maximum extraction attempts are one, and maximum enrichment attempts are one for the canonical routing chain.
- Deterministic follow-up IDs plus command-derived report/extraction/enrichment IDs make replay converge to the same artifacts and events.
- Focused replay reprocesses the final sufficiency command and extraction/enrichment failure completions without adding reports, requests, or terminal events.
- Correlation, causation, artifact/event transaction boundaries, human gates, and worker retry semantics remain unchanged.

Tracing:

- Sufficiency traces remain version-aware through command-derived report lookup.
- Trace output now includes exact stage, decision, extraction ID, enrichment ID, reasons, reused artifact state, and exact causally emitted follow-up events.
- Existing sanitization continues to bound supplemental content because full derived content is stored only in artifacts, not routing payloads.

Branch and vertical tests:

- Branch A proves original sufficient content creates one report/brief request and no extraction/enrichment.
- Branch B proves extraction can make content sufficient with two reports, one extraction, no enrichment, and one brief request.
- Branch C proves enrichment can make content sufficient with three reports, one extraction, one enrichment, and one brief request.
- Branch D proves final insufficiency creates one explicit terminal event/state, no brief, and no further route after replay.
- Branch E proves extraction technical failure records classification and routes once to enrichment.
- Branch F proves enrichment technical failure records provider context and terminates without a brief.
- The mocked vertical test runs API -> outbox worker -> dispatcher/tracing -> handlers with a mocked HTTP article response: request creation, candidate selection, shortlist approval pause, run creation, original insufficiency, extraction, post-extraction sufficiency, brief, draft, quality, media, package approval pause, final approval, and dispatch handoff.
- The vertical path uses no live RSS, search, Telegram, image, or LLM service; replays selection, package, final approval, and shortlist approval events without duplicate artifacts. Dispatch remains a handoff.

Files changed for Step 6:

- `backend/app/content_production/sufficiency.py`
- `backend/app/content_production/handlers.py`
- `backend/app/content_production/tracing.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_hardening.py`
- `backend/tests/test_content_production_orchestration.py`
- `progress.md`

Exact validation evidence:

1. Six branch, replay, tracing, service, and mocked vertical tests with adjacent routing coverage -> `64 passed`.
2. Real PostgreSQL atomicity, retry history, migrations, ranking, and forced concurrency suite -> `17 passed`.
3. Mocked extraction vertical plus handler routing set -> `27 passed`.
4. First full backend run exposed one test-local variable typo after `301` tests passed; focused correction -> `1 passed`.
5. Final full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider tests -q` -> `302 passed`.
6. Ruff: `RUFF_CACHE_DIR=/tmp/newscraft-ruff-cache .venv/bin/ruff check app tests alembic/versions` -> `All checks passed!`.
7. Alembic history remains linear through `0015_shortlist_selection_execution (head)`.
8. `git diff --check` -> clean.

Remaining limitations and provider readiness:

- No real enrichment/DDG, image generation, Telegram publishing, client command keys, arbitrary loop counter, routing DSL, or configurable iteration engine was added.
- The current null enrichment provider intentionally produces a terminal unavailable outcome; it does not fabricate success.
- Real provider integration is safe to begin as a separate phase at the existing extraction/enrichment interfaces because routing is bounded and failures are explicit. Production readiness still requires provider-specific status/error mapping, timeout/rate-limit policy, credentials handling, and integration/load tests.
- Step 6 is complete. No later phase work has begun.

## Step 7 - Real Provider Pilot And Output Quality Validation

Objective and provider inventory:

- Add one production-safe public article extractor and one bounded enrichment provider behind the existing workflow boundaries, then run a three-item event-driven pilot without changing approval gates or enabling publishing.
- The pre-Step-7 extraction path reused `app.discovery.article_extractor.extract_article` with Trafilatura plus BeautifulSoup fallback, but followed redirects automatically and did not enforce URL, DNS, content-type, response-size, or redirect safety.
- `WebEnrichmentProvider` existed with only `NullWebEnrichmentProvider`; no real search adapter was configured.
- Editorial brief, Telegram draft, and quality evaluation are deterministic local services. The repository has no compatible real LLM provider boundary, model configuration, or LLM credential. No OpenAI, Anthropic, Gemini, Google, Tavily, or Serper credential was available in the live environment.
- Image generation remains `NullImageGenerationProvider`. Telegram dispatch remains a durable non-publishing handoff and has no bot credential in the pilot.

Extraction implementation and safety:

- Added `SafeArticleExtractionProvider` using bounded `httpx` streaming plus the existing Trafilatura/BeautifulSoup document parser.
- Only `http` and `https` URLs are accepted. Userinfo URLs, missing hosts, loopback, private, link-local, and other non-global resolved addresses are rejected before a request.
- Every redirect target is re-resolved and revalidated; automatic redirects are disabled and the configured maximum is four.
- Defaults are a 15-second request timeout, 2,000,000-byte response cap, four redirects, a clear NewsCraft user agent, and HTML/XHTML content types only.
- Responses are streamed and aborted when oversized. JavaScript is never executed. Raw HTML is neither persisted in artifacts nor included in traces/evidence.
- Common `nav`, `header`, `footer`, `aside`, `form`, `script`, `style`, and `noscript` elements are removed before extraction.
- Failures are structured bounded codes such as `unsupported_scheme`, `private_address`, `timeout`, `unsupported_content_type`, `response_too_large`, `http_403`, and `network_error`; provider exception text and possible secrets are not persisted.

Enrichment implementation and configuration:

- Added one `DuckDuckGoEnrichmentProvider` against the HTML search endpoint; no second search provider or fallback graph was introduced.
- Search text is derived from bounded title/source/author/date inputs and capped at 300 characters.
- Results are parsed without browsing result pages, canonicalized, de-duplicated, exclude the exact original article URL, and are capped by default at five findings with 500-character snippets.
- `empty` results are distinct from `failed` provider/network/timeout outcomes. Findings are explicitly marked `unverified_secondary` and retain URL/title/source/snippet attribution.
- Search is disabled by default through `ENRICHMENT_PROVIDER=none`; `duckduckgo` must be explicitly configured. Configuration validates all timeout, size, redirect, result, and snippet bounds.
- No provider credential is required by DuckDuckGo HTML. `.env.example` contains limits and the opt-in provider switch, but no credential field or secret.
- Provider objects are injected through the existing dispatcher/handler options. Tests continue using mocks; production workflow construction for the pilot uses `build_production_provider_options(settings)`.

Controlled pilot command and human gates:

- Added `python -m app.content_production.pilot` with `start`, `process`, `approve-shortlist`, `approve-package`, and `report` commands.
- `start` invokes the existing request API function and emits only the canonical initial event. `process` uses `WorkflowEventWorker`, the typed dispatcher, tracing wrapper, real production handlers, and PostgreSQL outbox persistence.
- Shortlist and package approvals are separate explicit commands. `process` exposes no auto-approval, publish, Telegram token, or publish option.
- The runner accepts explicit pilot content-item IDs through the request's existing `constraints_json`. Candidate selection still executes in the worker, but the pilot working set is restricted to those operator-selected IDs. Normal unscoped ranking is unchanged.
- The first live OpenAI source ingestion unexpectedly returned 1,040 historical feed entries. That was larger than the intended pilot preparation. The ingestion shortcut was removed from the pilot CLI; existing ingestion API/worker paths must prepare and inspect source data before starting a pilot. The evaluated workflow set itself was restricted to exactly three items.

Live pilot items and actual routing:

1. Item A, BAIR `Adaptive Parallel Reasoning`, content item `2e3214e3-b66c-4555-9e61-6187855fa54b`, request `2b624aa5-4c18-41d7-83a0-92f94b85fd3c`:
   - `original -> sufficient (0.98) -> brief -> draft -> automated quality passed (1.0) -> existing media selected -> package -> final approval pending`.
   - No extraction or enrichment was needed. Full workflow time from run creation to package gate was approximately 6.66 seconds. Meaningful trace durations included sufficiency 58.84 ms, brief 44.05 ms, draft 32.77 ms, quality 65.04 ms, media 31.06 ms, and package 29.00 ms.
2. Item B, Mehr `باقری: مشکلی برای همکاری با پرسپولیس ندارم...`, content item `29efaca9-2972-409f-97c8-ceef73db0cff`, request `514b9382-aabc-437a-9d8f-3a33266cb936`:
   - `original -> partial (0.60) -> real extraction ok (484 chars, 454.27 ms) -> post_extraction sufficient (0.78) -> brief -> draft -> automated quality passed (1.0) -> existing media selected -> package -> final approval pending`.
   - This proves the real extractor can advance the Step 6 extraction branch on a public article.
3. Item C, OpenAI Academy `ChatGPT Sites`, content item `9dea0320-d054-49bb-966e-6378b90e11d5`, request `c3f06ea2-4b80-4c06-a7ae-3bcdf8e371a1`:
   - `original -> partial (0.60) -> extraction failed http_403 (746.25 ms) -> DuckDuckGo enrichment ok (5 findings, 1515.84 ms) -> post_enrichment sufficient (0.78) -> brief -> draft -> automated quality passed (1.0) -> media requires unavailable image generation -> image_generation_pending`.
   - The enrichment evidence was bounded but largely unrelated to the exact product page. This exposed an overly permissive sufficiency decision: finding volume/length can raise the score without adequate relevance.
- A separate attempted OpenAI `Modeling an AI jobs transition` extraction also returned `http_403`; enrichment returned five results. This confirms the 403 is a provider/source compatibility issue rather than an isolated page.
- No LLM was called. Every trace correctly has `model_name=null` and `token_usage={}`; token cost is zero and no metadata was fabricated.
- No image generation or Telegram publish call occurred. No package was approved and no dispatch handoff was created because human review rejected the drafts.

Human quality findings:

- Item A scores: fidelity 4, coverage 3, Persian readability 1, concision 3, structure 3, hook 2, attribution 4, unsupported-claim risk safety 4, publication readiness 1.
- Item B scores: fidelity 4, coverage 3, Persian readability 2, concision 3, structure 3, hook 2, attribution 4, unsupported-claim risk safety 4, publication readiness 2.
- Item C scores: fidelity 2, coverage 1, Persian readability 1, concision 3, structure 3, hook 1, attribution 3, unsupported-claim risk safety 2, publication readiness 1.
- All three were marked `not_publication_ready`. Items A and C are primarily English. Item B preserves useful Persian facts but still includes an English editorial angle and safety warning plus irrelevant `#هوش_مصنوعی` hashtags.
- Automated quality reported `passed` with score `1.0` for all three drafts, demonstrating that the current structural/extractive checker does not measure Persian readability, relevance, editorial naturalness, or publication readiness.
- No critical unsupported claim was approved. Both available packages remain at `final_approval_pending`; Item C remains at the explicit unavailable image-generation boundary.
- The Step 7 acceptance threshold of at least two drafts usable with minor human editing was not met. Real provider integration works technically but is not accepted as a publishable product workflow.

Evidence bundles:

- Generated local ignored reports: `validation/pilot/item-a.json`, `validation/pilot/item-b.json`, and `validation/pilot/item-c.json`.
- Human rubric source: `validation/pilot/human-reviews.json`.
- Reports include source item/URL/excerpt, extraction and enrichment artifacts, stage-specific sufficiency, brief, draft, automated report, media/package state, claim/source map, bounded trace snapshots, per-step latency, model/token metadata, and human review.
- Generated pilot output is ignored by Git and is not part of the committed code surface.

Migration compatibility discovered during the live pilot:

- The existing local database was at `0003`. Real upgrade failed before `0004` because Alembic's default `version_num VARCHAR(32)` could not store `0004_content_production_foundation` (34 characters).
- Amended unreleased migration `0004` to widen `alembic_version.version_num` to `VARCHAR(64)` at upgrade start and restore `VARCHAR(32)` at downgrade end.
- Re-running the real PostgreSQL upgrade then completed linearly from `0003` through `0015` with all ingested content preserved.

Files changed for Step 7:

- `.env.example`
- `.gitignore`
- `backend/alembic/versions/0004_content_production_foundation.py`
- `backend/app/content_production/candidates.py`
- `backend/app/content_production/enrichment.py`
- `backend/app/content_production/handlers.py`
- `backend/app/content_production/pilot.py`
- `backend/app/content_production/providers.py`
- `backend/app/core/config.py`
- `backend/app/discovery/article_extractor.py`
- `backend/tests/test_content_enrichment.py`
- `backend/tests/test_content_production_candidates.py`
- `backend/tests/test_content_production_foundation.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_pilot.py`
- `backend/tests/test_content_production_providers.py`
- `progress.md`

Exact automated and live validation evidence:

1. Initial extraction/enrichment provider focus exposed navigation contamination; after boilerplate removal, provider/enrichment suite -> `19 passed`.
2. Provider, pilot command, enrichment, and handler integration suite -> `48 passed`.
3. Tracing, handlers, idempotency, orchestration, E2E, and API deferral/contract regressions -> `71 passed`.
4. Pre-pilot full backend suite -> `317 passed`.
5. Real PostgreSQL migration initially failed with `StringDataRightTruncationError` updating `alembic_version` to `0004_content_production_foundation`; corrected retry upgraded `0003 -> ... -> 0015` successfully.
6. Final provider/pilot/candidate/foundation/handler focus -> `66 passed`.
7. Final full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `318 passed`.
8. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
9. Alembic history -> linear through `0015_shortlist_selection_execution (head)`.
10. `git diff --check` -> clean.
11. Live extraction: Mehr article `ok`, 484 extracted characters, 454.27 ms; OpenAI pages returned structured `http_403` failures.
12. Live enrichment: DuckDuckGo HTML `ok`, five bounded findings, 1515.84 ms for Item C.
13. Human gates: three explicit shortlist approvals; zero automatic approvals; zero final approvals; zero dispatch handoffs; zero publish attempts.

Acceptance and next product-quality action:

- Safe extraction and bounded enrichment adapters are implemented and validated. Provider configuration is secret-safe and automated tests require neither internet nor credentials.
- The live provider pilot was genuinely attempted and produced real extraction, enrichment, routing, latency, failure, evidence, and human-review data.
- Step 7 real provider integration is **not accepted for publishing** because zero of three drafts met the “usable with minor edits” threshold, the automated quality score disagreed materially with human review, and enrichment relevance was not enforced by sufficiency.
- The single recommended next product-quality action is to introduce one real Persian-capable LLM generation/evaluation boundary for brief, draft, and rubric output, with prompts grounded only in the existing claim/source evidence and with human review retained. Do not add a rewrite loop before one-pass Persian generation and relevance-aware evaluation are measured.
- No generalized quality loop, prompt optimizer, real image generation, Telegram publishing, or later-phase work was added.

## Step 8 - One-Pass Persian LLM Generation And Evidence-Relevance Validation

Date/time: 2026-07-12 00:00:30 +0330

Objective and pre-change gaps:

- Add exactly one Persian-capable real LLM boundary for one editorial-brief call, one Persian Telegram-draft call, and one evidence-grounded quality-evaluation call.
- Prevent unrelated DuckDuckGo result volume from making weak content sufficient.
- Preserve the existing worker, dispatcher, tracing savepoint, deterministic artifact IDs, bounded sufficiency route, shortlist approval gate, final package approval gate, and non-publishing dispatch boundary.
- Before Step 8, no LLM provider boundary or credential configuration existed. Brief, draft, and quality services were deterministic. `AgentStepRun` could not obtain provider/model/token metadata. Enrichment findings had no relevance annotation, and every successful result title/snippet contributed to sufficiency.
- Existing artifact schemas had no semantically correct location for generated evidence IDs, provider/token metadata, or the ten-field quality rubric. A focused current-phase schema test exposed this blocking storage gap.

Provider and model:

- Selected one provider: OpenAI Responses API over the existing `httpx` dependency. No OpenAI SDK, second provider, model router, fallback model, or conversational abstraction was added.
- Default real-provider model configuration is `gpt-5-mini`. The model remains configurable through `LLM_MODEL`, but one configured model is used for all three operations.
- Requests use strict Responses API JSON Schema output, `store=false`, a default 45-second timeout, and a default 1,800 output-token limit.
- Configuration fields are `LLM_PROVIDER`, `LLM_MODEL`, `LLM_REQUEST_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `LLM_BASE_URL`, and secret `OPENAI_API_KEY`.
- `LLM_PROVIDER=none` remains the automated-test/default path and uses the existing deterministic local services. If `LLM_PROVIDER=openai` is explicitly requested without a key, application configuration fails immediately and never silently falls back.
- `SecretStr` prevents the key from appearing in settings representations. Provider errors are bounded codes and never include response bodies, authorization headers, or credential text.

Minimal LLM contract:

- Added `LLMRequest` with operation, bounded instructions, structured evidence, expected JSON Schema, timeout, and maximum output tokens.
- Added `LLMResponse` with structured output, provider, model, input/output/total tokens when returned, and measured latency.
- Added one `LLMProvider` protocol and one `OpenAIResponsesProvider` implementation.
- Provider failure codes distinguish `provider_unavailable`, `authentication_failed`, `provider_timeout`, `rate_limited`, `provider_network_error`, HTTP errors, `malformed_provider_response`, and `malformed_structured_output`.
- Timeout, rate-limit, network, and server-unavailable errors are retryable through the existing worker. Authentication/configuration, malformed output, evidence failure, and schema validation are permanent and emit a causally linked `ProductionRunFailed` instead of consuming retries or being mislabeled as content insufficiency.

Evidence contract:

- Added bounded evidence records with stable `evidence_id`, kind, text, source URL, source name, publication time, and acceptance state.
- Original title is `rss:title`; original excerpt is `rss:excerpt`; extraction is `extraction:<artifact-id>`; accepted enrichment is `enrichment:<artifact-id>:<index>`.
- Original excerpts are capped at 1,600 characters, extracted article text at 6,000, enrichment evidence at 700, and the complete bundle at 12 entries.
- Raw HTML, full search pages, traces, database internals, prompts, credentials, authorization headers, and hidden reasoning are not included.
- Prompt hashes and evidence IDs are persisted instead of complete prompt/provider payloads.

Deterministic enrichment relevance policy:

- Every persisted finding receives `relevance_status`, bounded `relevance_score`, `matched_signals`, `rejection_reason`, and `accepted_for_evidence`.
- Signals are exact normalized title phrase, target-title term overlap, original organization/source-name match, and source-domain match.
- Exact original URL results are rejected. Accepted evidence is de-duplicated to one finding per source domain.
- A finding is strong/relevant at score `>= 0.65`. A moderate/ambiguous finding is score `>= 0.45`; moderate evidence is accepted only when at least two independent domains meet that threshold. Weak and unrelated findings never contribute.
- Provider success with no accepted evidence is retained distinctly with `no_relevant_findings`; it is not converted into provider failure.
- A lone moderate/ambiguous result that cannot meet the independent-source policy terminates with `enrichment_relevance_human_review_required` and `human_review_required=true`; it never claims sufficiency or starts brief generation.
- `SufficiencyInputs.supplemental_text`, LLM evidence assembly, and editorial secondary context use only `accepted_for_evidence=true` findings.
- Tests prove ten or twenty long unrelated results contribute zero supplemental text and cannot turn a short item into `sufficient`.

Brief prompt and schema:

- The brief call receives only accepted evidence plus bounded audience/tone instructions.
- `BriefGenerationOutput` requires central claim, why it matters, grounded key facts, important entities, grounded source context, uncertainty, prohibited claims, Persian angle, and suggested Telegram structure.
- Every key fact/context row must reference existing evidence IDs. Unknown references or schema-invalid output produce `schema_validation_failed` and stop progression.
- Generated brief facts retain evidence IDs and source URLs. The artifact persists evidence IDs and bounded provider/model/token/latency/prompt-hash metadata.

Draft prompt and schema:

- The draft call receives the validated brief plus the same approved source evidence. It is exactly one generation call with no critic, rewrite, or regeneration pass.
- `DraftGenerationOutput` requires headline, body, source attribution, optional hashtags, referenced evidence IDs, uncertainty flags, and complete final Telegram text.
- Validation enforces a 120-3,000 character body, 180-4,096 final text, Persian-character ratio of at least 0.65, existing evidence references, only approved source URLs, no internal/editorial instruction markers, and no generic `#هوش_مصنوعی` hashtag when evidence is not AI-related.
- Primarily English output, internal warning leakage, unsupported URLs, unknown evidence IDs, empty/short output, and irrelevant hashtags stop progression before packaging.
- The persisted `TelegramDraft` contains only final text, headline, source links, relevant hashtags, uncertainty flags, evidence IDs, and bounded generation metadata. Prompt or internal safety text is never copied into the post.

Quality prompt, schema, and gate:

- The quality call receives the exact draft, validated brief summary, and exact approved evidence set; it does not evaluate hidden reasoning.
- `QualityEvaluationOutput` requires 1-5 scores for factual fidelity, evidence coverage, Persian readability, naturalness, concision, structure, headline quality, source attribution, unsupported-claim risk, and publication readiness.
- It also requires unsupported claims, missing facts, awkward Persian, misleading certainty, irrelevant content, instruction leakage, and `pass`, `human_review_required`, or `reject` recommendation.
- Pass requires no critical unsupported claim/instruction leakage and at least 4 for factual fidelity, Persian readability, publication readiness, and attribution.
- Borderline recommendation/attribution maps to existing `revision_requested` and pauses. Critical unsupported content, poor Persian, poor fidelity/readiness, or reject maps to `quality_failed`. No automatic regeneration occurs.
- The normalized report score is the average of all ten rubric values divided by five, so it is not hardcoded to `1.0`. Full rubric and evaluation metadata persist on the canonical report.
- The LLM evaluator remains advisory. A passing report may progress to package creation, but final package approval remains an explicit human command.

Tracing and idempotency:

- The dispatcher injects the same configured provider into the existing brief, draft, and quality handlers.
- Canonical artifacts remain derived from consumed event IDs and immutable discriminators; replay returns the original brief/draft/report and does not call the provider again.
- Existing handler savepoints still contain domain mutation, artifact creation, output snapshot, and completed trace finalization atomically.
- Successful LLM traces obtain provider model and actual input/output/total token metadata from the exact canonical artifact.
- Trace output includes operation, latency, prompt hash, evidence IDs, output artifact ID, and quality decision when applicable. It excludes full prompts, provider responses, credentials, and hidden reasoning.
- Permanent generation/schema failures emit explicit terminal workflow events. Transient failures re-raise into the existing worker retry path and retain failed attempt traces.

Schema and migration:

- Added linear reversible migration `0016_persian_llm_generation` after `0015_shortlist_selection_execution`.
- Added `evidence_ids_json` and `generation_metadata_json` to editorial briefs and Telegram drafts.
- Added `rubric_json` and `evaluation_metadata_json` to draft quality reports.
- All columns are non-null JSONB with empty server defaults, so existing rows remain valid.
- Applied `0016` successfully to the real local PostgreSQL pilot database.

Pilot evidence reporting:

- Existing `python -m app.content_production.pilot` continues to trigger only API commands and the real outbox worker; it never calls LLM services sequentially.
- Reports now include accepted/rejected enrichment annotations, brief/draft evidence IDs, generation/evaluation metadata, complete automated rubric, provider/model/token/latency data, unavailable-cost marker, and automated-versus-human score deltas.
- Pricing is not configured, so estimated cost is recorded as `unavailable_no_configured_pricing` rather than fabricated or fetched live.
- Shortlist and final package gates remain separate explicit commands. No Telegram publish action exists in the pilot.

Files changed for Step 8:

- `.env.example`
- `backend/alembic/versions/0016_persian_llm_generation.py`
- `backend/app/core/config.py`
- `backend/app/db/models.py`
- `backend/app/content_production/evidence.py`
- `backend/app/content_production/llm.py`
- `backend/app/content_production/enrichment.py`
- `backend/app/content_production/sufficiency.py`
- `backend/app/content_production/briefs.py`
- `backend/app/content_production/telegram_drafts.py`
- `backend/app/content_production/quality.py`
- `backend/app/content_production/handlers.py`
- `backend/app/content_production/providers.py`
- `backend/app/content_production/tracing.py`
- `backend/app/content_production/pilot.py`
- `backend/tests/test_content_production_llm.py`
- `backend/tests/test_content_production_handlers.py`
- `backend/tests/test_content_production_foundation.py`
- `backend/tests/test_editorial_briefs.py`
- `progress.md`

Automated validation evidence:

1. First Step 8 test run failed during collection with `ModuleNotFoundError: app.content_production.evidence`, proving the provider/evidence boundary was absent before implementation.
2. Relevance/provider/schema/config focus after the initial implementation -> `13 passed`.
3. Service-level grounded brief -> Persian draft -> variable quality chain after metadata schema integration -> `15 passed`.
4. First adjacent integration run -> `2 failed, 69 passed`; both failures were legacy test artifacts without the new explicit relevance contract. Fixtures were updated to represent accepted relevant findings without removing their original progression/secondary-context assertions.
5. LLM plus handler workflow focus -> `44 passed`.
6. Relevance, provider, brief, draft, quality, handler, extraction/enrichment, and sufficiency focus -> `75 passed`.
7. Relevance/count-inflation plus migration focus -> `33 passed`.
8. Tracing, handler, idempotency, orchestration, E2E, API, and Step 7 provider regressions -> `85 passed`.
9. Pre-final full backend suite -> `337 passed`.
10. Final LLM/pilot/handler/tracing/provider focus -> `62 passed`.
11. Final relevance-classification/LLM/handler focus -> `46 passed`.
12. Final full backend suite with local PostgreSQL access: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `338 passed`.
13. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
14. Alembic history -> linear `0015_shortlist_selection_execution -> 0016_persian_llm_generation (head)`.
15. Real PostgreSQL migration: `0015 -> 0016_persian_llm_generation` completed successfully.
16. `git diff --check` -> clean.

Mocked versus live work:

- Automated tests made zero internet or real LLM calls. `httpx.MockTransport` proves OpenAI structured output, tokens/model/latency, timeout, authentication, rate limit, malformed output, and secret-safe error behavior.
- A deterministic `fake-llm` worker test proves `worker -> dispatcher -> tracing -> sufficiency-ready brief -> Persian draft -> LLM quality -> media -> package -> final approval pending`, with one call per LLM operation and actual fake metadata on three distinct traces.
- The mocked strong output passes with a nonconstant normalized score; primarily English, leaked instructions, unsupported evidence/URLs, poor Persian, irrelevant hashtags, and critical unsupported claims are rejected in focused tests.
- No fake response is described as live provider success.

Live pilot and credential limitation:

- `OPENAI_API_KEY` is unset. `backend/.env` and repository `.env` are absent.
- Exact attempted command: `DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@localhost:5432/newscraft LLM_PROVIDER=openai ENRICHMENT_PROVIDER=duckduckgo .venv/bin/python -m app.content_production.pilot process`.
- Exact result: exit code `1` before database session/worker processing, with configuration validation `OPENAI_API_KEY is required when LLM_PROVIDER=openai`.
- No new live request, shortlist, run, provider call, draft, package, approval, dispatch, evidence report, or human score was created. Existing Step 7 pilot data was not relabeled as Step 8 evidence.
- A real Step 8 pilot requires one valid OpenAI API key exported as `OPENAI_API_KEY` with `LLM_PROVIDER=openai`. Network access and local PostgreSQL are otherwise available; migration `0016` is applied.
- Because no credentialed output exists, provider/model tokens, live latency, Persian draft quality, automated-versus-human agreement, and provider cost cannot be measured. Cost remains unavailable because no pricing configuration was supplied.

Acceptance threshold and remaining limitation:

- Code, deterministic relevance hardening, mocked one-pass workflow, failure semantics, tracing, schema, migration, full backend, Ruff, Alembic, and whitespace criteria pass.
- The Step 8 product-validation acceptance threshold is **not demonstrated and therefore not met**: there are no three live LLM drafts and no new human rubrics. It would be incorrect to claim at least two usable drafts or meaningful automated/human correlation from mocks.
- Irrelevant enrichment count inflation is fixed and proven deterministically. Both approval gates remain mandatory. No image generation, Telegram publishing, rewrite loop, prompt optimization, multiple provider, or later-phase behavior was added.
- The one necessary next action is to provide `OPENAI_API_KEY` and rerun the existing three-item controlled pilot once, followed by human scoring. No code or prompt revision should occur before that evidence exists.

### Step 8 credentialed live-pilot attempt

Date/time: 2026-07-12

Security and configuration validation:

- A credential was supplied for this local pilot and was passed only through the interactive process environment. It was never written to `.env`, `.env.example`, source code, tests, migrations, event payloads, database artifacts, traces, or reports.
- Before execution, the credential was confirmed present without displaying it. `git grep` found zero tracked-file matches, `git status` showed no secret-bearing environment file, and `backend/.env` was not created.
- Runtime configuration validation succeeded with `LLM_PROVIDER=openai`, provider `openai`, model `gpt-5-mini`, `ENRICHMENT_PROVIDER=duckduckgo`, and the local PostgreSQL database.
- Real PostgreSQL reported `0016_persian_llm_generation (head)` from both `alembic current` and `alembic heads`.
- There were zero pending workflow events before the pilot and all three controlled content items existed.
- After execution, tracked-file and generated-report scans each found zero credential matches. The process environment was cleared. No secret was committed or persisted.

Controlled item and request identities:

1. Item A: content item `2e3214e3-b66c-4555-9e61-6187855fa54b`, request `1be0e69a-65c1-4b10-a782-c41c37252a06`, run `dc3d303a-8845-50d3-b3af-b6ee4f4e1d56`.
2. Item B: content item `29efaca9-2972-409f-97c8-ceef73db0cff`, request `ec53e158-1f79-4385-90ad-10a88c26d932`, run `9b3d51ac-f2b1-5ee1-b17c-eda8d95976b1`.
3. Item C: content item `9dea0320-d054-49bb-966e-6378b90e11d5`, request `4061a096-1b4d-401b-a2ec-e00c9c5ef297`, run `40720bfe-2422-5f39-999b-e5ed5428c3ae`.
- The first combined request selected only Item A because the supplied topic filter excluded the other two articles. Two subsequent topic-bearing item requests produced zero-candidate shortlists and made no provider calls. Items B and C were then started once without a topic, matching the established item-scoped Step 7 methodology. No LLM output was regenerated or retried to improve quality.
- All three intended items passed separate explicit shortlist approvals. No final package approval was performed.

Actual worker-driven routes:

1. Item A: `request created -> candidate selection -> shortlist prepared -> explicit shortlist approval -> original sufficiency sufficient -> editorial brief requested -> editorial brief handler failed`.
   - The `EditorialBriefRequested` event exhausted its bounded worker attempts and is `failed` with `MissingGreenlet` from the real async SQLAlchemy execution path.
   - Two failed `editorial_brief_creation` traces were retained with durations `2079.76 ms` and `29574.81 ms`.
   - No editorial brief was committed, so no draft, quality report, media decision, package, or dispatch handoff exists.
2. Item B: `request created -> candidate selection -> shortlist prepared -> explicit shortlist approval -> original sufficiency partial -> extraction requested -> extraction timeout -> enrichment requested -> enrichment timeout -> production run failed`.
   - Extraction trace duration: `24623.60 ms`; enrichment trace duration: `10061.95 ms`.
   - Terminal failure reason: `provider_timeout`. No LLM stage was reached.
3. Item C: `request created -> candidate selection -> shortlist prepared -> explicit shortlist approval -> original sufficiency partial -> extraction requested -> extraction timeout -> enrichment requested -> enrichment timeout -> production run failed`.
   - Extraction trace duration: `15105.76 ms`; enrichment trace duration: `10096.27 ms`.
   - Terminal failure reason: `provider_timeout`. No LLM stage was reached.
- All orchestration used the existing API command, outbox worker, typed dispatcher, traced production handlers, PostgreSQL persistence, and explicit human gate. No service was called sequentially outside the workflow.

Provider, model, token, latency, and quality evidence:

- Configured provider/model: OpenAI Responses API / `gpt-5-mini`.
- No successful structured provider response was committed. Model metadata is therefore `null` on the failed traces and recorded token usage is `{}`; input, output, and total token counts are unavailable rather than fabricated.
- The only LLM-stage latency evidence is the two failed Item A brief traces listed above. Items B and C did not reach an LLM handler.
- Artifact totals across the three intended runs: three sufficiency reports, two failed extraction results, two failed enrichment results, zero editorial briefs, zero Telegram drafts, zero quality reports, zero packages, and zero dispatch requests.
- Automated quality scores are unavailable because no draft-quality evaluation ran. Human quality scores and automated/human disagreement are unavailable because no draft was produced for human review.
- Ignored bounded reports were generated at `validation/pilot/step-8-item-a.json`, `validation/pilot/step-8-item-b.json`, and `validation/pilot/step-8-item-c.json`. They contain no credential.

Acceptance and safety result:

- The credentialed live pilot was genuinely attempted once through the production workflow, but it did not produce a Persian draft. The Step 8 acceptance threshold remains **not demonstrated and not met**: zero of three items produced a draft, so the requirement that at least two be usable with minor editing cannot be evaluated or satisfied.
- The run exposed one real LLM-path transaction/session failure at editorial brief creation and real extraction/enrichment timeouts for the other two items. No production code, prompt, threshold, provider configuration, or retry policy was changed during this pilot.
- Both human gates remained mandatory. There were three explicit shortlist approvals, zero final approvals, zero packages, zero dispatch handoffs, and zero Telegram publishing attempts.
- No later phase was begun. The remaining product limitation is that the live LLM path must first be corrected and then explicitly authorized for a new controlled validation run; the current evidence cannot support a quality or publishing claim.

## Step 8.1 - Repair The Credentialed Live Execution Path

Date/time: 2026-07-12

Objective and gap analysis:

- Repair only the real async editorial-brief execution failure, prove the path with PostgreSQL, diagnose the two provider timeouts without guessing, and run a canary only with a newly generated credential.
- Before this step, `EditorialBriefRequested` had fake-session success coverage but no PostgreSQL worker test covering tracing, nested artifact savepoints, evidence assembly, provider execution, artifact persistence, and replay together.
- No prompt, quality threshold, model, output-token limit, relevance policy, routing policy, schema, provider architecture, approval gate, or publishing behavior was changed.

Sanitized `MissingGreenlet` reproduction and root cause:

- Added a real-PostgreSQL reproduction using a permanent fake-provider failure. The first run failed as expected while the successful provider/replay test already passed: `1 failed, 1 passed`.
- The complete sanitized traceback proved the original provider exception was `LLMProviderError("schema_validation_failed")` from the provider boundary.
- `EditorialBriefService.create_brief()` transitions and flushes the run inside `create_or_get_artifact()`'s nested savepoint. The permanent provider exception rolls that artifact savepoint back, causing SQLAlchemy to expire the modified `ContentProductionRun` instance.
- The handler caught the permanent provider exception and passed the expired run to `_emit_llm_failure()`. The terminal-event helper then synchronously evaluated `run.id` in `_emit_run_event()`; the reproduced pre-fix traceback identified `app/content_production/handlers.py:988` at `str(run.id)` as the exact implicit-I/O trigger.
- SQLAlchemy attempted `SELECT ... FROM content_production_runs WHERE id = $1` through the expired scalar loader outside an awaited async ORM call and raised `sqlalchemy.exc.MissingGreenlet`. The secondary ORM error masked the original bounded provider failure in the live event and trace.

Async ORM fix:

- `editorial_brief_requested`, `draft_generation_requested`, and `draft_quality_check_requested` now materialize the primitive run UUID before entering their artifact/provider savepoint (`handlers.py:475`, `handlers.py:527`, and `handlers.py:566`).
- `_emit_llm_failure()` now accepts that UUID and calls `_emit()` directly with primitive aggregate/payload identity (`handlers.py:853-872`). It performs no access to an expired ORM object and adds no query, commit, session-setting change, eager-loading policy, or independent transaction.
- The same narrow correction covers the three LLM services because each uses the same permanent-failure helper and can roll back a run transition inside its artifact savepoint.
- Existing outer tracing savepoints, failed-trace persistence, worker retries, artifact/event atomicity, and canonical replay behavior remain unchanged.

Files changed:

- `backend/app/content_production/handlers.py`
- `backend/tests/test_content_production_postgres_atomicity.py`
- `progress.md`

PostgreSQL and transaction validation:

1. Initial red reproduction plus successful worker path -> `1 failed, 1 passed`; failure was the exact expired `run.id` `MissingGreenlet` described above.
2. Post-fix permanent-failure and successful canonical replay tests -> `2 passed in 3.18s`.
3. Focused PostgreSQL test proves `worker -> dispatcher -> tracing wrapper -> EditorialBriefRequested -> evidence assembly -> fake provider -> one editorial brief`, persisted provider/model/token metadata, completed trace, and replay with one provider call and one canonical brief.
4. Permanent provider failure test proves the original failure is converted to one causally linked `ProductionRunFailed` event and the trace completes without `MissingGreenlet`.
5. PostgreSQL tracing/transaction regression set, including failed trace retention, retry history, trace-finalization rollback, and outer-commit rollback -> `6 passed in 6.89s`.

Extraction and enrichment timeout diagnosis:

- Production configuration still passes `ARTICLE_FETCH_TIMEOUT_SECONDS=15` to `ArticleFetchPolicy` and `ENRICHMENT_TIMEOUT_SECONDS=10` to `DuckDuckGoEnrichmentProvider`. Step 8 did not alter those values or their propagation.
- The safe extractor still creates one client for one operation, validates every URL/redirect before streaming, applies the configured timeout to the stream request, enforces the existing response cap, and closes only its owned client after the operation.
- DuckDuckGo still creates one client for one bounded search, applies the configured timeout to that request, parses at most five results, and closes only its owned client after the operation.
- No `HTTP_PROXY`, `HTTPS_PROXY`, or `ALL_PROXY` value was configured in the diagnostic environment. The adapters retain normal `httpx` environment behavior, matching Step 7.
- Mocked extraction/enrichment adapter tests -> `19 passed in 2.76s`.
- Exactly one direct diagnostic against the previously successful Mehr article used the production safety limits and returned `ok`, no warnings, `484` extracted characters, and `630.09 ms` latency.
- Exactly one direct diagnostic for the prior `ChatGPT Sites` DuckDuckGo query returned `ok`, five bounded findings, no error, and `1414.49 ms` latency.
- These calls created no workflow artifacts and are not pilot evidence. Their immediate success under unchanged settings classifies the prior extraction/enrichment timeouts as transient external/network failures, not a reproducible configuration regression or HTTP-client lifecycle defect. No timeout correction was justified or made.

Deterministic validation:

1. Step 8 LLM, handler, tracing, orchestration, API, extraction, and enrichment regressions -> `102 passed in 3.94s`.
2. Full backend suite, including real PostgreSQL tests -> `340 passed in 18.69s`.
3. Ruff -> `All checks passed!`.
4. Alembic heads -> `0016_persian_llm_generation (head)`.
5. Real local PostgreSQL `alembic current` -> `0016_persian_llm_generation (head)`.
6. `git diff --check` -> clean.

## Step 8.2 - OpenRouter Structured-Output Compatibility Diagnostics

Date/time: 2026-07-12

Scope:

- Do not run another production workflow canary.
- Remove the exposed temporary credential from `ACTIVE_PHASE.md`, verify it is absent from tracked files, generated validation files, and Git history, and require a new process-environment credential for any live provider diagnostic.
- Diagnose and harden only the OpenAI-compatible Responses provider boundary and LLM schema-failure reporting. No prompt, model, routing workflow, migration, artifact schema, quality threshold, human gate, or publishing behavior was changed.

Credential cleanup:

- The exposed temporary credential was removed from `ACTIVE_PHASE.md` and replaced with the placeholder `OPENROUTER_API_KEY=<provided through process environment>`.
- Pattern scans found no OpenRouter key pattern in tracked files, generated validation files, or Git commits.
- The user confirmed the exposed credential was revoked.
- No `OPENROUTER_API_KEY` or `OPENAI_API_KEY` is present in the current process environment, so the required one-shot live provider-level diagnostic was not run.

Contract and root-cause evidence:

- Official OpenRouter Responses API docs and OpenAPI schema confirm the endpoint is `/api/v1/responses`, bearer authentication is required, and the Responses request schema accepts `instructions`, `input`, `text.format`, `max_output_tokens`, and `store=false`.
- Official structured-output docs and model metadata for `openai/gpt-5-mini` also identify `response_format` / `structured_outputs` as supported parameters and recommend parameter-compatible routing with `require_parameters` for structured outputs.
- The previous canary failure remains bounded to the editorial brief operation. Because no fresh provider credential is present, the exact real response body/shape that caused `malformed_structured_output` could not be isolated in this step.

Implemented deterministic hardening:

- `LLMProviderError` now carries bounded diagnostics without raw output text.
- Responses parsing now records structural diagnostics: HTTP status, response status, response keys, output item count/types, content part types, output-text presence and length, output-text SHA-256, prefix class, provider/model, response ID, provider error type, and usage keys.
- The parser now distinguishes `provider_response_failed`, `incomplete_output`, `no_output_text_found`, `provider_refusal`, `text_not_valid_json`, `markdown_wrapped_json`, and `structured_output_not_object` instead of collapsing these into `malformed_structured_output`.
- The parser only accepts assistant `message` / `output_text` parts and ignores non-message output such as reasoning items.
- OpenRouter token aliases `prompt_tokens` and `completion_tokens` are mapped to persisted input/output token fields when returned.
- LLM service schema failures now attach bounded validation paths, and terminal `ProductionRunFailed` events include the bounded diagnostics payload.

Tests added or updated:

- OpenRouter/Responses request-shape assertion for the current `text.format` request field.
- Response-shape parser tests for documented `output[].content[].type == output_text`, multiple output items, empty content, failed response, refusal content, valid JSON, Markdown-fenced JSON classification, prose-wrapped JSON rejection, and usage metadata aliases.
- Editorial brief schema-validation diagnostics test.

Validation:

1. LLM parser/schema tests: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_llm.py` -> `27 passed in 1.00s`.
2. Content-production handler/tracing/orchestration focused suite: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_llm.py tests/test_content_production_handlers.py tests/test_content_production_tracing.py tests/test_content_production_orchestration.py` -> `76 passed in 2.77s`.
3. Focused PostgreSQL brief failure/replay regressions -> `2 passed in 2.92s`.
4. Full backend suite with local PostgreSQL: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `351 passed in 12.57s`.
5. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
6. Alembic heads -> `0016_persian_llm_generation (head)`.
7. Alembic current against local PostgreSQL -> `0016_persian_llm_generation (head)`.
8. `git diff --check` -> clean.

Remaining limitation and authorization:

- The exact OpenRouter compatibility root cause is not fully closed because Step 8.2's required one-shot provider-level diagnostic needs a newly generated credential in the process environment.
- No synthetic fixture from a real observed OpenRouter response was added for the same reason.
- A new production canary is **not authorized** yet. Next authorized action is the bounded provider-level compatibility diagnostic with a fresh credential, not a workflow canary.

## Step 8.1 - OpenRouter Credentialed Canary Attempt

Date/time: 2026-07-12

Scope:

- Run exactly one credentialed production-workflow canary for Item A using the existing API/pilot command, outbox worker, dispatcher, tracing wrapper, and production handlers.
- Do not change production code, prompts, schemas, model, token limits, thresholds, routing, retry policy, approval gates, or publishing behavior.
- Use OpenRouter through the current OpenAI-compatible provider configuration: `LLM_PROVIDER=openai`, `LLM_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL=openai/gpt-5-mini`, and `ENRICHMENT_PROVIDER=duckduckgo`.
- Do not run source ingestion, source cleanup, a second canary request, final package approval, dispatch creation, Telegram publishing, or the full three-item pilot.

Preflight:

- Checkpoint remained `edeac2d feat: complete event-driven content production pilot foundation`.
- PostgreSQL availability check returned `postgres 1`.
- Alembic current returned `0016_persian_llm_generation (head)`.
- Alembic heads returned `0016_persian_llm_generation (head)`.
- Runtime settings resolved to OpenRouter API root, model `openai/gpt-5-mini`, DuckDuckGo enrichment, and a present runtime credential.
- Official OpenRouter docs and OpenAPI schema verified `/api/v1/responses`, bearer authentication, `input`, `instructions`, `text.format.type=json_schema`, `max_output_tokens`, and `store=false`. The current NewsCraft provider appends `/responses`, so the configured base URL used the API root rather than the full Responses endpoint.
- Item A existed, was rewrite-ready, and had URL/title data available: `2e3214e3-b66c-4555-9e61-6187855fa54b`.
- Preflight workflow queue state for pending/processing events was zero. One pre-existing failed event remained in the database and was treated as historical baseline, not canary output.

Canary route and IDs:

- Content item: `2e3214e3-b66c-4555-9e61-6187855fa54b`
- New request: `1f43a3b4-a8f9-41d3-b76b-f678b08c1fa4`
- Selection execution: `b70667d0-5617-5bcc-b037-5dc65ab5569b`
- Explicitly approved shortlist item: `2e3214e3-b66c-4555-9e61-6187855fa54b`
- New production run: `c0baa060-8922-558a-9dd2-f5926b7878fb`
- Actual route reached: API request -> workflow outbox -> worker -> candidate selection -> shortlist prepared -> explicit shortlist approval -> production run -> original sufficiency -> editorial brief request -> handled production-run failure.
- Original sufficiency report: `ba130c51-6051-54d1-a77a-e9462145b16e`, status `sufficient`, score `0.98`, allowed next step `editorial_brief`, reasons `full_article_like_content` and `rewrite_ready`.

Failure evidence:

- Final run state: `failed`
- Final current step: `workflow_failure`
- Run failure reason: `editorial_brief:malformed_structured_output`
- The canary failed before a committed editorial brief, Persian draft, or quality report.
- The failure was handled as a non-retryable LLM failure event with payload operation `editorial_brief`, retryable `false`, failure type `malformed_structured_output`, and failure reason `editorial_brief:malformed_structured_output`.
- No `MissingGreenlet` appeared in the canary workflow event errors, run failure reason, or trace evidence.

Workflow events for the canary:

1. `ContentProductionRequestCreated` -> processed, attempt `1`
2. `CandidateSelectionRequested` -> processed, attempt `1`
3. `CandidateShortlistPrepared` -> processed, attempt `1`
4. `CandidateShortlistApprovalRequested` -> processed, attempt `1`
5. `CandidateShortlistApproved` -> processed, attempt `1`
6. `ContentSufficiencyCheckRequested` -> processed, attempt `1`
7. `ContentSufficiencyChecked` -> processed, attempt `1`
8. `EditorialBriefRequested` -> processed, attempt `1`
9. `ProductionRunFailed` -> processed, attempt `1`

Trace evidence:

- `content_sufficiency` / `ContentSufficiencyService` -> completed, `39.78 ms`, no model or token metadata expected.
- `sufficiency_result_handling` / `CoreWorkflowEventHandlers` -> completed, `6.41 ms`.
- `editorial_brief_creation` / `EditorialBriefService` -> completed, `21378.73 ms`; emitted `ProductionRunFailed` with bounded error `malformed_structured_output`; no artifact/provider metadata was committed.
- `production_run_failure_handling` / `CoreWorkflowEventHandlers` -> completed, `8.3 ms`.

Artifacts and gates:

- Editorial brief artifacts: `0`
- Telegram draft artifacts: `0`
- Draft quality reports: `0`
- Visual briefs: `0`
- Telegram packages: `0`
- Telegram dispatch requests: `0`
- Final approvals: `0`
- Telegram publish attempts: `0`
- Because no draft was produced, no automated quality rubric, automated recommendation, Persian-character ratio, or human review result exists.

Verdict:

- Technical canary success: **not achieved**. The workflow did not reach a committed editorial brief, Persian draft, or quality evaluation.
- Product-quality verdict: unavailable; no draft was produced.
- Full three-item pilot authorization: **not authorized**.
- Required stop condition was followed: no second canary request was submitted, no code/config/prompt/model/threshold change was made, and the full pilot was not started.

Canary, full-pilot authorization, and safety:

- No newly generated credential is configured in the current process environment. The previously supplied credential was not reused, in accordance with Step 8.1's explicit compromise/revocation rule.
- The credentialed workflow canary was therefore not run. There are no canary provider calls, token counts, provider latency, brief, Persian draft, quality report, package, or human score to report.
- Because the canary did not run, it could not authorize the new three-item pilot. The full pilot was not run.
- Zero final approvals, dispatch requests, Telegram calls, or publishing actions occurred during Step 8.1.
- Step 8.1 implementation and deterministic validation are complete, but the phase acceptance threshold remains blocked on a newly generated credential and a successful single canary reaching quality evaluation. No live-provider or product-quality success is claimed.

## Repository Stabilization Checkpoint

Date/time: 2026-07-12

Scope:

- Preserve the accepted event-driven content-production implementation before any live canary.
- Do not change production behavior, prompts, thresholds, providers, approval gates, or publishing behavior.

Working-tree audit decisions:

- Intended production source: content-production package, API content-production endpoints, schemas, provider configuration, workflow models, safe extraction update, and `.env.example` provider defaults.
- Intended migrations: `0004_content_production_foundation` through `0016_persian_llm_generation`.
- Intended automated tests: content-production, enrichment, dispatch, draft, media, package, LLM, tracing, provider, API deferral/contract, orchestration, hardening, and PostgreSQL atomicity tests.
- Intended maintained documentation: `TASK.md`, `ACTIVE_PHASE.md`, `progress.md`, and `.gitignore`.
- Generated validation output excluded from checkpoint: `validation/content-production-workflow-report.md` and ignored `validation/pilot/`.
- Local generated/runtime directory excluded from checkpoint: `.sentry-native/`, which is untracked, unreadable to the current user, and safely ignored rather than permission-modified or deleted.
- Unrelated or uncertain tracked changes excluded from checkpoint: RSS seed cleanup, ingestion/source-health docs and tests, frontend mock/count updates, and deletions of legacy/root notes.

Deleted-file review:

- `ROADMAP.md` appears to be an obsolete legacy Streamlit/SQLite MVP roadmap superseded by `README.md` and `progress.md`; deletion is not required for the content-production checkpoint and was left unstaged.
- `media-asset.md` appears to be generated source/media validation notes with many public media URLs; current ingestion/source catalog docs supersede it for maintained documentation, but deletion was left unstaged.
- `summery.md` appears to be an old selective-integration handoff note superseded by maintained docs/progress; deletion was left unstaged.

Security and safety:

- Secret scan of intended checkpoint paths found only synthetic redaction-test strings and provider construction code, not committed credentials.
- No `.env` or `backend/.env` file is present.
- Generated pilot reports remain ignored and unstaged.
- No canary, live LLM provider call, final approval, dispatch, Telegram call, or publishing action was performed during repository stabilization.

Validation before checkpoint:

1. Focused Step 8.1 PostgreSQL regression file: `.venv/bin/python -m pytest -p no:cacheprovider tests/test_content_production_postgres_atomicity.py -q` -> `19 passed in 22.21s`.
2. Full backend suite: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `340 passed in 15.75s`.
3. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
4. Alembic heads: `0016_persian_llm_generation (head)`.
5. Sandboxed `alembic current` hung and was interrupted; bounded escalated local PostgreSQL rerun completed with `0016_persian_llm_generation (head)`.
6. `git diff --check` -> clean.

## Step 8.2 - OpenRouter Provider Diagnostic Completion Addendum

Date/time: 2026-07-12

Scope:

- Complete Step 8.2 only after the stopped OpenRouter workflow canary failed at `editorial_brief:malformed_structured_output`.
- Do not run another production workflow canary.
- Do not change prompts, model, token limits, routing, workflow orchestration, migrations, artifact schemas, approval gates, or publishing behavior.
- Use only bounded structural provider diagnostics; do not store credentials, prompts, raw provider text, hidden reasoning, or full response bodies.

One-shot provider-level diagnostic result:

- Exactly one direct provider compatibility diagnostic was run against OpenRouter using the existing `OpenAIResponsesProvider`, model `openai/gpt-5-mini`, the editorial-brief schema, bounded synthetic evidence, no database mutation, and no workflow request.
- Result: `LLMProviderError(code="incomplete_output", retryable=False)`.
- HTTP status: `200`.
- Provider response status: `incomplete`.
- Provider model: `openai/gpt-5-mini-2025-08-07`.
- Response ID: `gen-1783816854-G4WFqnrMN9yt4iTFGdqj`.
- Output shape: one `output` item with type `reasoning`; no assistant `message` item and no `output_text` content part.
- Content part types: none.
- Output text found: `false`.
- Provider error type: none.
- Usage keys observed: `cost`, `cost_details`, `input_tokens`, `input_tokens_details`, `is_byok`, `output_tokens`, `output_tokens_details`, and `total_tokens`.
- No raw generated text was returned or recorded by the diagnostic path.

Compatibility conclusion:

- The original workflow canary symptom `malformed_structured_output` is now better classified as a provider response that can complete the HTTP request but produce no assistant `output_text`.
- The direct diagnostic did not prove a Markdown-fence issue, prose-wrapped JSON issue, schema-envelope issue, authentication issue, failed HTTP status, or provider refusal.
- The current request contract remains the Responses endpoint with `text.format.type=json_schema`, schema `name`, `schema`, `strict=true`, `max_output_tokens`, and `store=false`.
- OpenRouter documentation also advertises `response_format` and `provider.require_parameters` for structured outputs, but the one allowed diagnostic did not test or prove that alternate request field succeeds. No request-field change was made without live evidence.

Implemented after diagnostic:

- Added a deterministic synthetic regression fixture reproducing the observed sanitized OpenRouter structure: `status=incomplete`, one `reasoning` output item, no `output_text`, and OpenRouter-style usage keys.
- The fixture proves this shape is classified as `incomplete_output`, preserves bounded diagnostics, and does not expose raw output text.
- No production-code behavior was changed after the diagnostic; the existing parser/diagnostic hardening already covered the observed shape.

Validation:

1. Observed OpenRouter shape fixture: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_llm.py::test_openai_provider_classifies_observed_openrouter_reasoning_only_incomplete_response` -> `1 passed in 1.10s`.
2. LLM parser/schema tests: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_llm.py` -> `28 passed in 1.08s`.
3. Step 8 content-production regression set: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_llm.py tests/test_content_production_handlers.py tests/test_content_production_tracing.py tests/test_content_production_orchestration.py` -> `77 passed in 3.57s`.
4. Focused PostgreSQL worker brief regressions against local PostgreSQL -> `2 passed in 3.23s`.
5. Full backend suite against local PostgreSQL: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `352 passed in 13.78s`.
6. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
7. Alembic heads -> `0016_persian_llm_generation (head)`.
8. Alembic current against local PostgreSQL -> `0016_persian_llm_generation (head)`.
9. `git diff --check` -> clean.
10. Secret-pattern scans for the OpenRouter key prefix in tracked files and generated documentation/report locations -> none found.

Authorization:

- A new production workflow canary is **not authorized** by this addendum because the one allowed provider diagnostic did not reach a structured assistant output.
- The full three-item pilot remains **not authorized**.
- No workflow canary, final approval, dispatch request, Telegram call, or publishing action was run during this addendum.

## Step 8.3 - Agent-Assisted Offline Persian Quality Pilot

Date/time: 2026-07-12

Scope:

- Evaluate evidence adequacy, schema practicality, Persian generation quality, claim grounding, and quality-rubric usefulness using agent-assisted offline fixtures.
- Do not run OpenRouter, OpenAI, provider diagnostics, production canaries, or the full live pilot.
- Do not modify OpenRouter compatibility, prompts, schemas, thresholds, routing, orchestration, migrations, approval gates, or publishing behavior.
- Exercise only offline fake-provider fixtures through the existing worker -> dispatcher -> tracing wrapper -> production handlers path.

Security cleanup:

- `ACTIVE_PHASE.md` now reflects Step 8.3 and contains only a non-secret `OPENROUTER_API_KEY=<provided through process environment only if a future phase explicitly authorizes it>` placeholder.
- The prior revocation confirmation remains documented from Step 8.2.
- Secret-pattern scans found no OpenRouter key prefix in tracked files, staged diff, Git history, `progress.md`, `ACTIVE_PHASE.md`, validation reports, or docs.

Offline evidence sources:

- Item A `2e3214e3-b66c-4555-9e61-6187855fa54b`: `rss:title`, `rss:excerpt` from BAIR Blog, published `2026-05-08T09:00:00+00:00`.
- Item B `29efaca9-2972-409f-97c8-ceef73db0cff`: `rss:title`, `rss:excerpt` from Mehr News, published `2026-07-06T22:21:10+00:00`.
- Item C `9dea0320-d054-49bb-966e-6378b90e11d5`: `rss:title`, `rss:excerpt` from OpenAI News, published `2026-06-02T10:00:00+00:00`.
- Existing Step 8/local DB evidence for Items B and C had no accepted extraction or enrichment evidence available for this offline run, so no rejected or unrelated enrichment was used.

Generated ignored reports:

- `validation/pilot/step-8-3-offline-item-a.json`
- `validation/pilot/step-8-3-offline-item-b.json`
- `validation/pilot/step-8-3-offline-item-c.json`
- `validation/pilot/step-8-3-offline-summary.json`

Schema and quality results:

1. Item A:
   - Brief schema: passed.
   - Draft schema: passed.
   - Quality schema: passed.
   - Agent-generated quality policy state: `passed`.
   - Agent rubric: factual fidelity `5`, evidence coverage `4`, Persian readability `5`, naturalness `4`, concision `4`, structure `4`, headline quality `4`, source attribution `5`, unsupported-claim risk `5`, publication readiness `4`, recommendation `pass`.
   - Independent human-style decision: `usable_with_minor_edits`.
   - Main defect: define APR more plainly before publication.
2. Item B:
   - Brief schema: passed.
   - Draft schema: passed.
   - Quality schema: passed.
   - Agent-generated quality policy state: `passed`.
   - Agent rubric: factual fidelity `5`, evidence coverage `4`, Persian readability `5`, naturalness `5`, concision `4`, structure `4`, headline quality `4`, source attribution `5`, unsupported-claim risk `5`, publication readiness `4`, recommendation `pass`.
   - Independent human-style decision: `usable_with_minor_edits`.
   - Main defect: source label could be localized, but no critical claim defect.
3. Item C:
   - Brief schema: passed.
   - Draft schema: passed.
   - Quality schema: passed.
   - Agent-generated quality policy state: `failed`.
   - Agent rubric: factual fidelity `5`, evidence coverage `3`, Persian readability `5`, naturalness `4`, concision `4`, structure `4`, headline quality `3`, source attribution `5`, unsupported-claim risk `5`, publication readiness `3`, recommendation `human_review_required`.
   - Independent human-style decision: `requires_major_revision`.
   - Main defect: evidence is too thin for full product-news publication.

Workflow fixture results:

- Item A:
  - Brief artifact `b78e9d79-7325-52e3-8c0f-fa39a59dd56e`.
  - Draft artifact `7a6906b8-ee55-5ebc-9dae-9ef99ab8495a`.
  - Quality report `7a8cc565-9d1f-5391-8fd5-98c1bf7f5b9f`.
  - Package `525e9adb-4fb6-53b7-bdc5-7a635615b2c3`.
  - Final run state `final_approval_pending`.
- Item B:
  - Brief artifact `08658546-5d68-5106-b308-3df6625eeeaf`.
  - Draft artifact `021bb102-f760-5dba-aea0-6704ed997e09`.
  - Quality report `db0921ec-eaf4-59d9-a899-b215f5313cf5`.
  - Package `916e3db8-8b8d-5fee-94ad-214ccfa2f18d`.
  - Final run state `final_approval_pending`.
- Item C:
  - Brief artifact `e62d7b12-735d-5f49-bff8-82eef97bea16`.
  - Draft artifact `e4cf3b0b-62e9-5db6-86b4-344f4ea1ec99`.
  - Quality report `1f983072-a3d0-592b-91c2-973812cf999b`.
  - No package because quality policy failed.
  - Final run state `quality_failed`.
- Each item used exactly three fake-provider fixture responses on the first pass: editorial brief, Persian draft, and quality evaluation.
- Replay of the initial brief event requested zero additional fixture responses for every item.
- Evidence IDs remained intact on brief and draft artifacts.
- Final approvals: `0`.
- Dispatch requests: `0`.
- Telegram publish attempts: `0`.

Acceptance:

- Offline product-quality pilot result: **succeeded** against the Step 8.3 threshold because two of three drafts were usable with minor edits, no accepted draft had a critical unsupported claim, Persian was predominantly natural, schema validation passed, and both human gates remained intact.
- This was **not** a live-provider pilot and does not validate HTTP provider integration, authentication, OpenRouter compatibility, token accounting, latency, retries, or real provider tracing.
- The full live three-item pilot remains unauthorized.

Validation:

1. Offline schema/workflow/replay fixture runner: `backend/.venv/bin/python validation/pilot/step_8_3_offline_fixture_runner.py` -> completed; A/B reached `final_approval_pending`, C reached `quality_failed`, and replay fixture calls were `0` for all items.
2. Workflow/API/tracing regressions: `.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_content_production_tracing.py tests/test_content_production_handlers.py tests/test_content_production_orchestration.py tests/test_content_production_api_deferral.py tests/test_content_production_api_contract.py tests/test_content_production_candidates.py` -> `76 passed in 3.22s`.
3. Full backend suite against local PostgreSQL: `.venv/bin/python -m pytest -p no:cacheprovider -q` -> `352 passed in 14.75s`.
4. Ruff: `.venv/bin/ruff check --no-cache .` -> `All checks passed!`.
5. Alembic heads -> `0016_persian_llm_generation (head)`.
6. Alembic current against local PostgreSQL -> `0016_persian_llm_generation (head)`.
7. `git diff --check` -> clean.

Recommended provider-integration decision:

- Do not run another OpenRouter canary on the current Responses configuration. The offline product path is viable enough to justify a provider-boundary decision next, but live integration should first choose a documented structured-output route that can return assistant `output_text` reliably without changing prompts, schemas, gates, or workflow orchestration.

## Step 8.4 - OpenRouter Chat Completions Deterministic Readiness

Date/time: 2026-07-12

Scope and transport decision:

- Implemented the narrow OpenRouter Chat Completions transport required by `ACTIVE_PHASE.md`; no production workflow canary or standalone paid provider call was run.
- The adapter posts non-streaming requests to `https://openrouter.ai/api/v1/chat/completions` and uses `response_format.type=json_schema` with the existing operation schema, `strict=true`, and one configured model.
- The request contains only `model`, two bounded messages, `response_format`, and `max_completion_tokens`. The system message preserves the existing operation instructions; the user message contains the existing bounded evidence plus the operation/schema output requirements.
- The implementation does not add model routing, fallback, plugins, response healing, streaming, conversational history, prompt changes, schema changes, quality-policy changes, regeneration, or publishing.
- The existing direct OpenAI Responses adapter remains available unchanged as the `openai` provider configuration.

Configuration and security:

- Added explicit `LLM_PROVIDER=openrouter` support and a separate `OPENROUTER_API_KEY` `SecretStr`; the OpenAI secret is not overloaded.
- OpenRouter configuration requires an HTTPS `openrouter.ai` base URL and rejects missing credentials or malformed base URLs before provider construction.
- `.env.example` documents only the variable name and process-environment requirement; it contains no credential value.
- Provider errors and diagnostics never persist complete response bodies, assistant content, refusal text, authorization headers, or credentials.
- No `OPENROUTER_API_KEY` or `OPENAI_API_KEY` was present in the execution process. No credential was requested, printed, inspected, persisted, or reused.

Response and failure contract:

- Parsing accepts only `choices[0].message` with role `assistant` and a non-empty string `content`; content must parse as exactly one JSON object.
- The existing brief, draft, and quality services continue to validate parsed JSON against their existing Pydantic production schemas and evidence rules.
- Bounded failures distinguish authentication, rate limit, request timeout, network failure, provider HTTP failure, model unavailability, unsupported structured output, missing choices, missing assistant message, empty assistant content, refusal, invalid JSON, non-object JSON, malformed provider envelopes, and embedded provider failures.
- Timeout, rate-limit, network, model/provider-unavailable failures remain retryable through the existing worker. Compatibility, refusal, malformed output, and schema failures remain permanent workflow failures.
- Provider/model, prompt/completion/total token counts, measured latency, and safe response ID are mapped into the existing `LLMResponse` and artifact metadata without an artifact-schema change.

Workflow integration evidence:

- Extended the existing fake-provider worker test through `WorkflowEventWorker -> dispatcher -> tracing -> brief -> draft -> quality -> media -> package` using OpenRouter provider metadata.
- The test proves exactly one provider call for each canonical LLM operation, provider/model/token/response-ID metadata persistence, evidence-ID preservation, final package approval still pending, zero dispatch requests, and zero additional provider calls when the original brief event is replayed.
- No direct sequential production-service orchestration was introduced.

Files changed for Step 8.4:

- `.env.example`
- `backend/app/core/config.py`
- `backend/app/content_production/llm.py`
- `backend/app/content_production/providers.py`
- `backend/tests/test_content_production_llm.py`
- `backend/tests/test_content_production_providers.py`
- `backend/tests/test_content_production_handlers.py`
- `progress.md`

Deterministic validation:

1. Initial focused run failed during collection with `ImportError: cannot import name 'OpenRouterChatCompletionsProvider'`, proving the adapter was absent before implementation.
2. OpenRouter request/response/error/configuration and provider tests -> `57 passed in 2.56s`.
3. OpenRouter plus fake worker-path integration focus -> `58 passed in 3.05s`.
4. LLM/provider/handler/tracing/orchestration/API regression set -> `124 passed in 3.48s`.
5. Initial PostgreSQL regression run reached no test logic because local PostgreSQL was stopped; all 19 fixture setups reported connection refusal.
6. After starting only the repository PostgreSQL service, the complete PostgreSQL atomicity/worker regression file -> `19 passed in 11.45s`.
7. Full backend suite against local PostgreSQL -> `369 passed in 14.29s`.
8. Ruff -> `All checks passed!`.
9. Alembic code head and database version -> `0016_persian_llm_generation`.
10. `git diff --check` -> clean.

Non-paid canary preflight and stop state:

- Checkpoint commit `edeac2d feat: complete event-driven content production pilot foundation` remains present.
- Item A `2e3214e3-b66c-4555-9e61-6187855fa54b` exists exactly once in the local PostgreSQL database.
- Pending/processing workflow-event count is zero.
- Database `alembic_version` is `0016_persian_llm_generation`.
- A fresh `OPENROUTER_API_KEY` is absent from the current process, so runtime OpenRouter settings cannot validly be constructed and the first paid call cannot safely begin through the production workflow.
- The one-item credentialed canary was therefore not attempted. There are no Step 8.4 canary request/run/artifact IDs, provider tokens, live latency, quality result, final approval, dispatch request, or publish attempt to report.
- Deterministic Step 8.4 implementation is ready, but phase completion and technical live-transport acceptance remain pending exactly one newly credentialed Item A production-workflow canary.
- The full three-item live pilot remains **not authorized**.

### Step 8.4 one-item OpenRouter production-workflow canary

Date/time: 2026-07-12

Preflight and security:

- A newly configured `OPENROUTER_API_KEY` was confirmed present by boolean presence only. Its value was not printed, inspected, persisted, logged, or included in any command output or report.
- Checkpoint commit `edeac2d feat: complete event-driven content production pilot foundation` is present.
- `git diff --check` was clean before the canary. No `graphify-out/` file was staged or committed.
- Runtime configuration validated as `LLM_PROVIDER=openrouter`, `LLM_BASE_URL=https://openrouter.ai/api/v1`, `LLM_MODEL=openai/gpt-5-mini`, and `ENRICHMENT_PROVIDER=duckduckgo`.
- PostgreSQL was available. Alembic current and heads both reported `0016_persian_llm_generation (head)`.
- Pending and processing workflow-event counts were both zero before request creation.
- Item A `2e3214e3-b66c-4555-9e61-6187855fa54b` existed.
- Exact-credential scans after execution found zero matches in tracked files and zero matches in generated reports, `progress.md`, and `ACTIVE_PHASE.md`. No `.env` file was created. Each credential-bearing canary process exited, and subsequent evidence collection explicitly removed the credential from its child environment.

Canary identities and route:

- Content item: `2e3214e3-b66c-4555-9e61-6187855fa54b`.
- Request: `41d033fd-7cd3-4fdf-9a9d-a0c9684fef5d`.
- Selection execution: `3c4e8087-df87-58eb-9c30-ab87aa359144`.
- Production run: `f55b9cfb-a078-5621-b293-c903a20b223b`.
- Route: `API request -> ContentProductionRequestCreated -> CandidateSelectionRequested -> CandidateShortlistPrepared -> CandidateShortlistApprovalRequested -> explicit shortlist approval -> CandidateShortlistApproved -> ContentSufficiencyCheckRequested -> original ContentSufficiencyChecked(sufficient) -> EditorialBriefRequested(provider_timeout)`.
- The canonical sufficiency report is `410b26c3-ccf7-5872-9ce1-9d508ae351a4` with reasons `full_article_like_content` and `rewrite_ready`.
- Exactly one canary request was created. The final package gate was never reached or approved.

Failure evidence and stop decision:

- The first real OpenRouter operation, `editorial_brief`, made one workflow attempt and failed with bounded `LLMProviderError: provider_timeout`.
- Safe HTTP category: request timeout. No response body, authorization header, credential, or provider content was retained.
- `EditorialBriefRequested` remains `pending` with `attempt_count=1` and `last_error=provider_timeout`, preserving the existing bounded worker retry contract.
- The failed `editorial_brief_creation` trace is retained with `failure_phase=domain_handler`, state `sufficiency_sufficient`, and duration `45606.85 ms`.
- The canary stopped immediately after reading the durable failure state. The pending retry was not processed, no second request or canary was submitted, and no direct diagnostic or full pilot was run.

Artifacts and metadata:

- Editorial brief ID: unavailable; zero briefs committed.
- Draft ID: unavailable; zero drafts committed.
- Quality report ID: unavailable; zero quality reports committed.
- Package ID: unavailable; zero packages committed.
- Dispatch request: zero.
- Configured provider/model: OpenRouter / `openai/gpt-5-mini`.
- Persisted provider/model metadata: unavailable because no structured provider response completed.
- Input, output, and total tokens: unavailable; no token values were fabricated.
- Provider-operation latency: failed editorial-brief trace `45606.85 ms`.
- Automated rubric, recommendation, Persian-character ratio, and human review: unavailable because no draft or quality evaluation exists.

Verdict and safety:

- Technical canary verdict: **failed** at the first real provider operation due to timeout. The required three-operation transport chain did not complete.
- Product-quality verdict: **not assessed** because no Persian draft was produced.
- Final workflow state: `sufficiency_sufficient`; current step `content_sufficiency`; the retryable brief event remains pending.
- Human approvals: one explicit shortlist approval, zero final package approvals.
- Dispatch count: zero. Telegram publish-attempt count: zero.
- The full three-item live pilot remains **not authorized**. No additional canary, later phase, dispatch, or publishing work was begun.

#### Operator-authorized SOCKS proxy retry of the existing canary

- No new request or second production run was created. The existing pending `EditorialBriefRequested` event for request `41d033fd-7cd3-4fdf-9a9d-a0c9684fef5d` and run `f55b9cfb-a078-5621-b293-c903a20b223b` was processed once through the existing worker with the operator-supplied `https_proxy` value.
- SOCKS support was available in the installed HTTP client stack. The credential was confirmed present by boolean presence only.
- The proxied provider operation no longer ended in transport timeout. It completed after `33082.54 ms` but returned no usable assistant content, producing the bounded permanent error `empty_assistant_content`.
- The original event reached `attempt_count=2` and was processed through the handler's permanent-failure path. A causally linked `ProductionRunFailed` event was created and processed once.
- Final run state: `failed`; current step `workflow_failure`; failure reason `editorial_brief:empty_assistant_content`.
- The second editorial-brief trace is `completed` because terminal failure handling completed atomically; it contains no provider/model/token metadata because no valid structured assistant output was available.
- Committed artifacts remain zero editorial briefs, zero drafts, zero quality reports, zero packages, and zero dispatch requests.
- No further retry, new request, direct diagnostic, model change, final approval, dispatch, or publishing action was performed. The full three-item pilot remains **not authorized**.
- Post-run exact-credential scans again found zero tracked or generated-file matches. Credential-bearing child processes exited; evidence collection explicitly removed the credential from its child environment.
