# AGENT_PROMPT.md — NewsCraft Quality-First Engineering Agent

You are a senior backend/full-stack engineering agent working on the private GitHub project **NewsCraft**.

Your job is to refactor, unify, improve, test, document, and prepare the project for a clean GitHub push.

This is an implementation task, not a brainstorming task.

The project must evolve in the correct order:

1. First, unify the backend.
2. Then improve the quality, completeness, reliability, filtering, ranking, and enrichment of ingested news/articles.
3. Only near the end, after ingestion quality is strong, implement content generation.

Do **not** jump into content generation early. Bad input data will produce bad content. The current priority is high-quality news/article ingestion.

---

# Project Context

The project currently contains two implementations:

## Legacy implementation

```text
ai-news-agent/
```

Known characteristics:

- Streamlit UI
- SQLite
- mature connector logic
- RSS/Hacker News/arXiv/GitHub/Hugging Face/YouTube/Telegram ingestion logic
- ranking/scoring logic
- diagnostics logic
- arXiv paper asset logic
- review/approval workflow

## New backend implementation

```text
newscraft/
```

Known characteristics:

- FastAPI
- PostgreSQL
- SQLAlchemy
- API/service/repository structure
- newer backend architecture
- some services may be incomplete or placeholder-only

The final target architecture must be:

```text
FastAPI + PostgreSQL + SQLAlchemy + service/repository architecture
```

The FastAPI backend inside `newscraft/` must become the **single backend source of truth**.

---

# Absolute Priority Order

Follow this priority order strictly:

```text
Phase 0  — Project audit and progress tracking
Phase 1  — Full backend unification
Phase 2  — High-quality ingestion foundation
Phase 3  — Connector quality and source coverage
Phase 4  — Article extraction and enrichment
Phase 5  — Ranking, filtering, deduplication, and freshness
Phase 6  — Diagnostics, observability, and source health
Phase 7  — Full ingestion API configuration
Phase 8  — Media asset management
Phase 9  — Authentication and basic security
Phase 10 — Content generation workflow
Phase 11 — Production readiness and final cleanup
```

Content generation is intentionally Phase 10, not Phase 2.

Do not start Phase 10 until the ingestion, ranking, enrichment, diagnostics, media, API configuration, and security phases are complete or explicitly blocked.

---

# Non-Negotiable Rules

## Rule 1 — No fake completion

Do not mark any phase as completed unless every required checklist item is implemented, tested, and documented.

If something cannot be completed, mark it as:

```text
Blocked
```

and explain:

- what is blocked
- why it is blocked
- what file/dependency/API caused it
- what partial work was completed
- what the user must provide or decide
- whether the next phase can safely continue

## Rule 2 — No moving forward early

Do not move to the next phase until the current phase passes its final gate.

This applies to every phase.

## Rule 3 — No vague progress reports

Every `progress.md` entry must include:

- exact status
- concrete changes
- files changed
- verification command
- verification result
- remaining issues
- precise suggested commit message

Bad progress report:

```text
Improved ingestion.
```

Good progress report:

```text
Migrated RSS ingestion into `newscraft/connectors/rss.py`, wired it into `IngestionService`, preserved source language/category metadata, added tests for successful RSS parsing and failed feed handling.
```

## Rule 4 — Commit messages must match actual work

Do not suggest broad commit messages unless the broad work is truly complete.

Bad:

```text
feat: complete backend unification
```

when only arXiv assets were migrated.

Good:

```text
feat: migrate arXiv asset processing to FastAPI backend
```

## Rule 5 — One backend source of truth

The final backend must be `newscraft/`.

The legacy `ai-news-agent/` code must not remain as a separate backend implementation.

After migration, legacy Streamlit must be one of:

1. removed,
2. archived/deprecated,
3. or converted into a thin UI/client that calls the FastAPI backend.

It must not keep independent business logic that competes with the FastAPI backend.

## Rule 6 — Keep routes thin

Do not put business logic directly inside API route handlers.

Use this structure:

```text
newscraft/api/             # API routes only
newscraft/services/        # business logic
newscraft/repositories/    # database access
newscraft/models/          # SQLAlchemy models
newscraft/schemas/         # Pydantic schemas
newscraft/connectors/      # external source connectors
newscraft/core/            # config, security, shared utilities
```

## Rule 7 — Do not commit secrets or generated files

Never commit:

```text
.env
.env.local
.env.production
*.db
*.sqlite
*.sqlite3
data/papers/
generated assets
downloaded PDFs
API keys
tokens
Telegram session files
.venv/
node_modules/
__pycache__/
dist/
build/
.next/
```

Update `.gitignore` if needed.

## Rule 8 — Every phase needs verification

For every phase, run the relevant verification.

At minimum, run:

```bash
python -m pytest
```

or the project-specific test command.

If tests cannot run, document the exact reason in `progress.md`.

Do not simply write “tests not run”.

## Rule 9 — Preserve existing working behavior

Do not break existing tests or working backend behavior.

If behavior changes intentionally, document:

- old behavior
- new behavior
- reason for change
- affected files/tests

## Rule 10 — Quality over feature count

The current priority is not “more sources at any cost”.

The priority is:

- reliable sources
- complete metadata
- useful summaries
- correct dates
- meaningful ranking
- deduplication
- source health
- high signal-to-noise ratio

## Rule 11 — No early social/content generation

Do not implement Instagram/LinkedIn/Telegram/podcast content generation until Phase 10.

Before Phase 10, the project must focus on making the article/news data excellent.

---

# Required Files to Read First

Before implementation, read these files if they exist:

```text
README.md
ROADMAP.md
TASKS.md
progress.md
.env.example
requirements.txt
pyproject.toml
docker-compose.yml
alembic.ini
```

Also inspect:

```text
ai-news-agent/
newscraft/
tests/
```

---

# progress.md Requirements

Create or update:

```text
progress.md
```

Use this format after every phase and sub-phase:

```markdown
## Phase X.Y — Phase Name

Status: Completed / In Progress / Blocked

### What changed
- Specific change 1
- Specific change 2

### Files changed
- `path/to/file.py`
- `path/to/other_file.py`

### Verification
- Command: `python -m pytest`
- Result: `46 passed`
- Notes: ...

### Remaining issues
- None

### Notes for commit
- Suggested commit message: `type: exact commit message`
```

A phase is not complete until `progress.md` is updated.

---

# Phase 0 — Project Audit and Progress Tracking

## Objective

Set up strict progress tracking and understand the project before changing code.

## Required tasks

- Create or update `progress.md`.
- Confirm that this prompt was read.
- Confirm that `TASKS.md` was read if it exists.
- Inspect the project structure.
- Identify active backend files.
- Identify legacy files.
- Identify existing tests.
- Identify current dependencies.
- Run or attempt tests.
- Write an initial audit summary in `progress.md`.

## Completion criteria

Phase 0 is complete only when:

- `progress.md` exists.
- Phase 0 entry exists.
- The entry lists inspected top-level folders.
- The entry mentions whether tests currently run.
- Missing dependencies, if any, are listed.
- Suggested commit message exists.

## Required verification

Run:

```bash
python -m pytest
```

If it fails, document the exact failure.

## Suggested commit message

```text
chore: add strict progress tracking
```

---

# Phase 1 — Full Backend Unification

## Objective

Migrate useful legacy Streamlit/SQLite features into the FastAPI/PostgreSQL backend.

The final backend source of truth must be:

```text
newscraft/
```

Do not move to Phase 2 until every Phase 1 sub-phase is completed or explicitly blocked.

---

## Phase 1.1 — Legacy vs FastAPI Feature Audit

### Required tasks

Inspect both implementations and create a feature comparison.

Must inspect:

```text
ai-news-agent/app.py
ai-news-agent/connectors.py
ai-news-agent/telegram_connector.py
ai-news-agent/ranker.py
ai-news-agent/
newscraft/api/
newscraft/services/
newscraft/repositories/
newscraft/models/
newscraft/schemas/
tests/
```

### Required output in progress.md

Add a table or bullet list with:

- feature name
- exists in legacy: yes/no
- exists in FastAPI: yes/no
- migration status
- notes

### Completion criteria

This sub-phase is complete only when all major feature gaps are identified.

### Suggested commit message

```text
docs: audit legacy and FastAPI backend feature gaps
```

---

## Phase 1.2 — Migrate Core Backend Logic

### Required tasks

Move or rewrite these capabilities into `newscraft/`:

- ingestion orchestration
- connector interfaces
- ranking/scoring entry points
- article review/approval workflow
- source/run logging basics
- asset preparation service entry points

### Requirements

- Do not keep duplicate competing backend logic.
- Keep FastAPI as the backend source of truth.
- Preserve existing behavior where good.
- Improve architecture where needed.

### Completion criteria

- FastAPI backend has clear service-layer ownership for ingestion, ranking, review, diagnostics, and assets.
- Legacy code is no longer required for core backend behavior.
- Tests are added or updated.
- `progress.md` is updated.

### Suggested commit message

```text
feat: migrate core legacy backend logic into FastAPI services
```

---

## Phase 1.3 — Deprecate or Convert Legacy Streamlit

### Required tasks

After migration, decide what to do with `ai-news-agent/`.

Allowed outcomes:

1. remove legacy backend code,
2. move it to an archive/deprecated folder,
3. or convert Streamlit into a thin UI/client that calls FastAPI.

### Requirements

- No duplicate backend source of truth.
- No active independent SQLite backend workflow unless clearly marked deprecated.
- README must explain the final architecture.
- Any remaining legacy code must clearly say it is deprecated or client-only.

### Completion criteria

- Final backend source of truth is clearly `newscraft/`.
- Legacy backend duplication is removed, archived, or deprecated.
- Tests pass.
- `progress.md` is updated.

### Suggested commit message

```text
chore: deprecate legacy Streamlit backend after migration
```

---

## Phase 1.4 — Phase 1 Final Gate

### Required tasks

Before moving to Phase 2:

- Run full test suite.
- Review all Phase 1 progress entries.
- Confirm Phase 1.1 through 1.3 are completed or explicitly blocked.
- If blocked, explain whether Phase 2 can safely proceed.
- Write a Phase 1 final summary in `progress.md`.

### Completion criteria

Phase 1 is complete only when:

- backend ownership is unified under `newscraft/`.
- legacy backend duplication is removed/deprecated/client-only.
- tests have been run.
- final Phase 1 summary exists.

### Suggested commit message

```text
feat: complete FastAPI backend unification
```

Use this broad commit message only if Phase 1 is truly complete.

---

# Phase 2 — High-Quality News Ingestion Foundation

## Objective

Improve the quality and reliability of incoming news/articles before building downstream features.

This is the new Phase 2 because high-quality input is more important than early content generation.

Do not move to Phase 3 until ingestion quality foundations are implemented and tested.

---

## Phase 2.1 — Audit Current Ingestion Quality

### Required tasks

Audit how ingested items are currently collected and stored.

Check:

- title quality
- summary quality
- URL correctness
- source metadata
- source type
- source group
- category
- language
- published date accuracy
- timezone handling
- duplicate behavior
- error handling
- source-level logs
- missing metadata
- low-quality/noisy items

### Required output in progress.md

Document:

- major ingestion quality problems
- missing metadata fields
- unreliable sources
- weak parsing areas
- quality improvement plan

### Completion criteria

- Ingestion quality audit is documented.
- Concrete fixes are identified.

### Suggested commit message

```text
docs: audit ingestion quality issues
```

---

## Phase 2.2 — Standardize Article Normalization

### Required tasks

Create or improve a normalization layer so every connector produces consistent article data.

### Requirements

Normalize:

- title
- URL
- canonical URL if possible
- summary
- source name
- source type
- source group
- category
- language
- published_at
- author/creator if available
- tags/topics if available
- metrics if available
- raw metadata

### Quality rules

- Reject items without usable title or URL unless there is a clear reason to keep them.
- Normalize whitespace.
- Strip broken HTML from summaries.
- Preserve original metadata in a safe metadata field.
- Do not lose source-specific metrics.

### Completion criteria

- Shared normalization logic exists.
- Ingestion uses it.
- Tests cover malformed/partial items.
- `progress.md` is updated.

### Suggested commit message

```text
feat: standardize article normalization
```

---

## Phase 2.3 — Improve Source Configuration and Quality Controls

### Required tasks

Improve source management so sources can be configured, enabled, disabled, grouped, and quality-controlled.

### Requirements

Support or verify:

- source enabled/disabled state
- source type
- source group
- category
- language
- reliability/priority if useful
- per-source fetch limits
- per-source failure tracking
- per-source last successful fetch time
- per-source last error

### Completion criteria

- Sources are configurable enough for high-quality ingestion.
- Source metadata is actually used during ingestion.
- Tests added or updated.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve source configuration for quality ingestion
```

---

## Phase 2.4 — Ingestion Quality Final Gate

### Required tasks

- Run tests.
- Verify at least one ingestion path produces normalized, high-quality article records.
- Confirm source metadata is preserved.
- Confirm malformed items are handled safely.
- Update `progress.md`.

### Completion criteria

- Ingestion foundation produces consistent article data.
- Tests pass or blockers are documented.

### Suggested commit message

```text
feat: complete high-quality ingestion foundation
```

---

# Phase 3 — Connector Quality and Source Coverage

## Objective

Make every important connector reliable, configurable, and useful.

The goal is not just “connectors exist”. The goal is that connectors return high-quality data.

Do not move to Phase 4 until the connector final gate passes.

---

## Phase 3.1 — RSS Connector Quality

### Required tasks

Improve or verify RSS ingestion.

### Requirements

- Parse title, URL, summary, author, published date, tags, enclosures/media if available.
- Preserve feed/source metadata.
- Handle broken feeds gracefully.
- Support date filtering and limits.
- Avoid crashing entire ingestion because one feed fails.

### Completion criteria

- RSS connector works through backend.
- Tests cover success and failed feed behavior.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve RSS connector quality
```

---

## Phase 3.2 — Hacker News Connector Quality

### Required tasks

Improve or verify Hacker News ingestion.

### Requirements

- Fetch top/new/best stories as configured.
- Keep only useful items.
- Preserve HN score, comments, item ID, author if available.
- Filter irrelevant items where appropriate.
- Handle API failures/timeouts.

### Completion criteria

- HN connector works through backend.
- Tests cover useful item filtering and metadata preservation.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve Hacker News connector quality
```

---

## Phase 3.3 — arXiv Connector Quality

### Required tasks

Improve or verify arXiv ingestion.

### Requirements

- Fetch relevant AI/ML/NLP/CV categories.
- Preserve authors, abstract, published date, arXiv ID, category, PDF URL if available.
- Support query/category configuration.
- Handle API failures.
- Avoid duplicate paper records.

### Completion criteria

- arXiv connector works through backend.
- Tests cover metadata preservation.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve arXiv connector quality
```

---

## Phase 3.4 — GitHub Connector Quality

### Required tasks

Improve or verify GitHub repository discovery.

### Requirements

- Support optional `GITHUB_TOKEN`.
- Fetch relevant AI/LLM/RAG/agent repositories.
- Preserve stars, forks, language, topics, open issues, license, owner, updated_at, README snippet if practical.
- Handle rate limits gracefully.
- Avoid low-signal junk repos where possible.

### Completion criteria

- GitHub connector works through backend.
- Tests cover metadata and rate-limit/error handling where practical.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve GitHub discovery connector quality
```

---

## Phase 3.5 — Hugging Face Connector Quality

### Required tasks

Improve or verify Hugging Face model discovery.

### Requirements

- Support optional `HUGGINGFACE_TOKEN`.
- Preserve likes, downloads, tags, model ID, pipeline/task, author if available.
- Filter for useful AI/model updates.
- Handle API failures.

### Completion criteria

- HF connector works through backend.
- Tests cover metadata preservation.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve Hugging Face connector quality
```

---

## Phase 3.6 — YouTube Connector Quality

### Required tasks

Make YouTube ingestion usable and configurable.

### Requirements

- Remove or replace hardcoded `CHANNEL_ID_HERE` placeholders.
- Make YouTube channel IDs configurable.
- Support YouTube RSS channel feeds.
- Validate channel IDs.
- Store title, URL, channel name, published date, summary/description, thumbnail/media metadata if available.
- If `YOUTUBE_API_KEY` is unused, document it as optional/reserved or remove confusing references.

### Completion criteria

- YouTube ingestion works with configured channel IDs.
- Invalid channel IDs return clear errors.
- Tests added or updated.
- `.env.example` and README are updated if needed.
- `progress.md` updated.

### Suggested commit message

```text
fix: complete configurable YouTube connector
```

---

## Phase 3.7 — Telegram Connector Quality

### Required tasks

Support the safest feasible Telegram ingestion path.

### Requirements

If using Telethon:

- support `TELEGRAM_API_ID`
- support `TELEGRAM_API_HASH`
- support session configuration
- never commit session files
- handle missing credentials clearly

If public Telegram parsing exists:

- preserve useful public parsing logic
- extract text, post URL, date, views, forwards, replies if available
- extract media candidates if available

### Completion criteria

- Telegram ingestion works through backend, or is clearly marked blocked with technical reason.
- Session/secrets are ignored by Git.
- Tests added where practical.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve Telegram connector quality
```

---

## Phase 3.8 — Connector Final Gate

### Required tasks

- Run tests.
- Confirm each connector is Completed or Blocked.
- For blocked connectors, document exact reason.
- Confirm connector outputs use shared normalization.
- Update `progress.md`.

### Completion criteria

- Major connectors are reliable, configurable, or honestly blocked.
- No placeholder-only connector remains pretending to work.

### Suggested commit message

```text
feat: complete connector quality improvements
```

---

# Phase 4 — Article Extraction and Enrichment

## Objective

Improve the completeness of article/paper data after initial ingestion.

Many sources only provide a title and short summary. This phase should enrich records where possible before ranking and content workflows.

Do not move to Phase 5 until enrichment final gate passes.

---

## Phase 4.1 — Audit Enrichment Gaps

### Required tasks

Identify where article records are incomplete.

Check:

- missing summaries
- very short summaries
- missing authors
- missing tags/topics
- missing full text
- missing canonical URL
- missing media
- arXiv PDF availability
- GitHub README availability
- Hugging Face model metadata availability

### Completion criteria

- Enrichment gaps documented in `progress.md`.

### Suggested commit message

```text
docs: audit article enrichment gaps
```

---

## Phase 4.2 — Full Article/Text Extraction Strategy

### Required tasks

Implement a safe extraction/enrichment strategy.

### Requirements

- For arXiv: use PDF/full-text asset workflow.
- For GitHub: enrich with README snippet/metadata where available.
- For Hugging Face: enrich with model card/metadata where available.
- For RSS/news: extract improved summaries only when feasible and safe.
- Respect timeouts and network errors.
- Do not scrape aggressively.
- Store enrichment metadata and status.

### Completion criteria

- Enrichment service exists or existing services are improved.
- At least arXiv/GitHub/HF enrichment paths are supported or explicitly blocked.
- Tests added.
- `progress.md` updated.

### Suggested commit message

```text
feat: add article enrichment service
```

---

## Phase 4.3 — arXiv Paper Asset Workflow

### Required tasks

Ensure arXiv paper processing is backend-native and robust.

### Requirements

For arXiv articles:

- extract arXiv ID from multiple URL formats
- download PDF
- extract full text
- clean text
- detect major sections
- generate:
  - `full_text.txt`
  - `research_brief.md`
  - `instagram_brief.md`
  - `podcast_brief.md`
- store asset metadata in PostgreSQL
- use configurable `PAPER_DATA_DIR`
- do not erase existing file paths on metadata-only updates
- handle failed PDF download/extraction gracefully
- ignore generated files in Git

### Completion criteria

- Backend arXiv asset endpoint performs real processing.
- Tests cover success and failure paths.
- `progress.md` updated.

### Suggested commit message

```text
feat: complete backend arXiv paper asset workflow
```

---

## Phase 4.4 — Enrichment Final Gate

### Required tasks

- Run tests.
- Verify enrichment improves article completeness.
- Confirm generated files are ignored.
- Update `progress.md`.

### Completion criteria

- Article records are richer and more useful for ranking/review.

### Suggested commit message

```text
feat: complete article extraction and enrichment
```

---

# Phase 5 — Ranking, Filtering, Deduplication, and Freshness

## Objective

Make the system surface the best and most relevant news, not just the newest or noisiest items.

Do not move to Phase 6 until this phase passes its final gate.

---

## Phase 5.1 — Audit Current Ranking and Dedupe

### Required tasks

Inspect:

- ranking/scoring logic
- categorization logic
- duplicate handling
- source priority
- date/freshness handling
- low-quality filtering
- existing tests

### Completion criteria

- Current ranking/dedupe weaknesses documented.

### Suggested commit message

```text
docs: audit ranking and dedupe behavior
```

---

## Phase 5.2 — Improve Ranking and Categorization

### Required tasks

Implement or improve backend ranking/scoring/categorization.

### Requirements

Rank and categorize consistently across:

- AI
- Tech
- Research
- Tool
- Model
- Video
- General

Preserve source-specific signals:

- Hacker News score/comments
- GitHub stars/forks/recency
- Hugging Face likes/downloads
- Telegram views/forwards
- arXiv category/research relevance
- RSS source priority/reliability

### Completion criteria

- Ranking service exists in backend.
- Ingestion uses backend ranking service.
- Tests cover representative source types.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve ranking and categorization quality
```

---

## Phase 5.3 — Improve Filtering and Noise Reduction

### Required tasks

Add or improve filters to reduce low-quality data.

### Requirements

Handle:

- empty titles
- broken URLs
- spammy/irrelevant items
- too-short summaries
- unrelated HN/GitHub/HF results
- old items outside requested date range
- duplicate or near-duplicate titles where practical

### Completion criteria

- Filtering improves signal-to-noise ratio.
- Tests cover noisy items.
- `progress.md` updated.

### Suggested commit message

```text
feat: add ingestion quality filters
```

---

## Phase 5.4 — Improve Duplicate Handling and Upsert

### Required behavior

When an article with the same URL already exists:

- update title if improved
- update summary if improved
- update score
- update metadata
- update source info if useful
- update `published_at` only if the new value is better
- update `last_seen_at`
- preserve manual review status
- do not overwrite approved/rejected status accidentally

### Tests required

Add tests for:

- insert new article
- update duplicate URL
- preserve approved status
- preserve rejected status
- refresh metadata
- update last_seen_at

### Completion criteria

- Upsert behavior is safe and useful.
- Tests pass.
- `progress.md` updated.

### Suggested commit message

```text
fix: improve duplicate handling and article freshness
```

---

## Phase 5.5 — Ranking/Dedupe Final Gate

### Required tasks

- Run tests.
- Verify repeated ingestion updates existing records safely.
- Verify ranking surfaces better items.
- Verify filtering removes bad items.
- Update `progress.md`.

### Completion criteria

- News quality is materially improved.

### Suggested commit message

```text
feat: complete ranking filtering and dedupe improvements
```

---

# Phase 6 — Diagnostics, Observability, and Source Health

## Objective

Make source health and ingestion reliability visible.

Do not move to Phase 7 until diagnostics are meaningful.

---

## Phase 6.1 — Audit Existing Diagnostics

### Required tasks

Inspect diagnostics services/routes and legacy diagnostics logic.

### Completion criteria

- Placeholder checks and missing diagnostics are documented.

### Suggested commit message

```text
docs: audit backend diagnostics
```

---

## Phase 6.2 — Implement Real Source Diagnostics

### Required checks

Implement diagnostics for:

- RSS
- Hacker News
- arXiv
- GitHub
- Hugging Face
- YouTube
- Telegram if configured
- PostgreSQL

Each check must return:

- check name
- status
- message
- latency if practical
- missing configuration if relevant
- error details if failed

### Completion criteria

- Diagnostics endpoint returns real checks, not placeholder data.
- Tests added where practical.
- `progress.md` updated.

### Suggested commit message

```text
feat: implement real backend diagnostics
```

---

## Phase 6.3 — Improve Ingestion Run Logs

### Required tasks

Ensure ingestion runs record useful operational data:

- total fetched
- total saved
- duplicates
- filtered items
- failed items
- per-source logs
- error messages
- start/end time
- duration

### Completion criteria

- Run logs are useful for debugging ingestion quality.
- Tests added or updated.
- `progress.md` updated.

### Suggested commit message

```text
feat: improve ingestion run logging
```

---

## Phase 6.4 — Diagnostics Final Gate

### Required tasks

- Run tests.
- Verify diagnostics service/endpoint.
- Verify ingestion run logs.
- Update `progress.md`.

### Completion criteria

- Source health and ingestion reliability are observable.

### Suggested commit message

```text
feat: complete diagnostics and source health reporting
```

---

# Phase 7 — Full Ingestion API Configuration

## Objective

Make ingestion fully controllable through the backend API, not through Streamlit.

Do not move to Phase 8 until this phase passes.

---

## Phase 7.1 — Audit Current Ingestion API

### Required tasks

Inspect:

- `POST /ingestion/runs`
- ingestion schemas
- ingestion services
- connector parameter passing
- source configuration APIs

### Completion criteria

- Missing API controls are documented.

### Suggested commit message

```text
docs: audit ingestion API configuration gaps
```

---

## Phase 7.2 — Expand Ingestion Request Schema

### Required supported fields

Add support where applicable for:

- selected sources
- date range
- per-source limits
- GitHub token
- Hugging Face token
- Telegram channels
- Telegram credentials/session settings where feasible
- YouTube channels
- public source groups
- dry-run mode if useful
- quality filters if useful

### Security requirements

- Do not store tokens unless explicitly required.
- Do not return secrets in responses.
- Do not log secrets.
- Mask sensitive values in logs.

### Completion criteria

- Pydantic schema validates supported options.
- Bad payloads return clear validation errors.
- `progress.md` updated.

### Suggested commit message

```text
feat: expand ingestion request schema
```

---

## Phase 7.3 — Wire Expanded Config Into Ingestion Service

### Required tasks

- Pass validated request parameters to connectors/services.
- Support source-level limits and date ranges.
- Support source groups.
- Support dry-run if implemented.
- Store run summary and source-level logs.
- Return clear response summary.

### Completion criteria

- API options actually affect ingestion behavior.
- Source-level errors are persisted or returned.
- Tests cover request handling and service behavior.
- `progress.md` updated.

### Suggested commit message

```text
feat: wire expanded ingestion config into backend service
```

---

## Phase 7.4 — Ingestion API Final Gate

### Required tasks

- Run tests.
- Verify ingestion API with:
  - one RSS source
  - one HN/arXiv source
  - one invalid request
  - dry-run if implemented
- Update `progress.md`.

### Completion criteria

- Backend ingestion can be controlled through API without Streamlit.

### Suggested commit message

```text
feat: complete configurable ingestion API
```

---

# Phase 8 — Media Asset Management

## Objective

Make media first-class data instead of burying it only in raw metadata.

Do not move to Phase 9 until this phase passes.

---

## Phase 8.1 — Audit Current Media Handling

### Required tasks

Inspect:

- RSS media extraction
- Telegram media extraction
- YouTube thumbnail/media extraction
- article metadata media fields
- any asset-related models

### Completion criteria

- Media gaps documented.

### Suggested commit message

```text
docs: audit media asset handling
```

---

## Phase 8.2 — Add Media Asset Model and Migration

### Required fields

Create a model/table such as:

```text
media_assets
```

Suggested fields:

- id
- article_id
- media_type
- source_url
- local_path
- mime_type
- width
- height
- metadata
- created_at

### Requirements

- Add SQLAlchemy model.
- Add Alembic migration if project uses Alembic.
- Add repository/service logic.
- Do not download large media files by default.

### Completion criteria

- Media asset table exists.
- Repository/service exists.
- Tests added.
- `progress.md` updated.

### Suggested commit message

```text
feat: add media asset model
```

---

## Phase 8.3 — Extract and Store Media Assets

### Required sources

Extract media from:

- RSS enclosures/media tags
- Telegram public pages or metadata if available
- YouTube thumbnails
- existing source metadata already parsed

### Completion criteria

- Ingestion stores media assets.
- Article media can be retrieved.
- Tests added.
- `progress.md` updated.

### Suggested commit message

```text
feat: store extracted media assets during ingestion
```

---

## Phase 8.4 — Add Media API

### Required tasks

Add endpoint for:

- listing media for an article

Optional:

- listing all media with filters

### Completion criteria

- API returns article media.
- Tests added.
- `progress.md` updated.

### Suggested commit message

```text
feat: add article media API
```

---

## Phase 8.5 — Media Final Gate

### Required tasks

- Run tests.
- Verify media extraction and API.
- Update `progress.md`.

### Completion criteria

- Media assets are first-class backend data.

### Suggested commit message

```text
feat: complete media asset management
```

---

# Phase 9 — Authentication and Basic Security

## Objective

Protect sensitive backend operations before deployment.

Do not move to Phase 10 until this phase passes.

---

## Phase 9.1 — Audit Security Surface

### Required tasks

List all endpoints and classify them as:

- public read-only
- protected write/admin
- sensitive diagnostics
- sensitive ingestion
- sensitive content generation

### Completion criteria

- Endpoint security classification exists in `progress.md`.

### Suggested commit message

```text
docs: audit backend security surface
```

---

## Phase 9.2 — Implement API Key Authentication

### Required tasks

- Add API key auth at minimum.
- Use environment variable for API key.
- Add dependency/helper for protected routes.
- Return clear 401/403 responses.
- Update `.env.example`.

### Must protect

- ingestion run creation
- source creation/update
- article approve/reject/reset/status update
- diagnostics
- media/admin routes
- future draft generation/update routes
- destructive/admin routes

### Completion criteria

- Protected routes reject missing/invalid API keys.
- Protected routes accept valid API key.
- Tests added.
- `progress.md` updated.

### Suggested commit message

```text
feat: add API key authentication
```

---

## Phase 9.3 — Secret Hygiene and Git Ignore

### Required tasks

- Update `.gitignore`.
- Ensure `.env` and generated/session files are ignored.
- Ensure README explains env variables without exposing secrets.
- Verify no obvious secrets are committed.

### Completion criteria

- Secret hygiene documented.
- `progress.md` updated.

### Suggested commit message

```text
chore: strengthen secret hygiene
```

---

## Phase 9.4 — Security Final Gate

### Required tasks

- Run tests.
- Verify protected endpoints.
- Update `progress.md`.

### Completion criteria

- Backend is not publicly writable without authentication.

### Suggested commit message

```text
feat: complete backend API protection
```

---

# Phase 10 — Content Generation Workflow

## Objective

Only after high-quality ingestion, enrichment, ranking, diagnostics, media, API configuration, and security are in place, add content generation.

Do not start this phase early.

Content generation should turn approved, high-quality articles into usable drafts.

---

## Phase 10.1 — Audit Current Draft System

### Required tasks

Inspect existing:

- draft models
- draft schemas
- draft services
- draft routes
- draft tests

Identify whether drafts are only stored or actually generated.

### Completion criteria

- Current draft workflow is documented.
- Missing generation capabilities are listed.

### Suggested commit message

```text
docs: audit content draft workflow
```

---

## Phase 10.2 — Implement Content Generation Service

### Required draft types

Implement generation for:

- Instagram post
- Instagram caption
- LinkedIn post
- Telegram post
- Podcast script
- Research summary

### Requirements

- Use a dedicated service.
- Design a provider interface so an LLM provider can be plugged in later.
- Provide a safe rule-based fallback when no LLM key exists.
- Use article title, summary, URL, source metadata, category, ranking metadata, and paper assets if available.
- Do not hallucinate unsupported facts.
- Include source attribution or URL where appropriate.
- Store generated draft in PostgreSQL.
- Generate content only from approved articles unless explicitly configured otherwise.

### Completion criteria

- Generation service exists.
- All required draft types are supported.
- Rule-based fallback works.
- Tests cover at least three draft types.
- `progress.md` updated.

### Suggested commit message

```text
feat: add backend content generation service
```

---

## Phase 10.3 — Add/Complete Content Draft API

### Required endpoints

Add or complete endpoints for:

- generate draft from approved article
- list drafts
- get draft detail if useful
- update draft
- approve/mark draft ready if appropriate

### Requirements

- Validate draft type with Pydantic.
- Return clear errors for missing article or unsupported draft type.
- Protect write endpoints with Phase 9 auth.
- Add tests.

### Completion criteria

- API can generate a draft from an approved article.
- API can list and update drafts.
- Tests pass.
- `progress.md` updated.

### Suggested commit message

```text
feat: add content draft generation API
```

---

## Phase 10.4 — Content Generation Final Gate

### Required tasks

- Run tests.
- Verify end-to-end:
  - approved article input
  - draft generated
  - draft stored
  - draft listed
  - draft updated
- Verify all required draft types are supported.
- Update `progress.md`.

### Completion criteria

- Content generation works only after quality pipeline is ready.
- Tests pass or blockers are documented.

### Suggested commit message

```text
feat: complete content generation workflow
```

---

# Phase 11 — Production Readiness and Final Cleanup

## Objective

Prepare the branch for a clean GitHub push and future deployment.

Do not mark this phase complete unless the project is actually ready or remaining blockers are honestly documented.

---

## Phase 11.1 — Test and Dependency Cleanup

### Required tasks

- Verify test command.
- Add or update `pytest.ini` if needed.
- Verify `requirements.txt` or dependency files.
- Remove unused dependencies if obvious.
- Add missing dependencies if tests require them.

### Completion criteria

- Tests run with documented command.
- Dependency issues are resolved or documented.
- `progress.md` updated.

### Suggested commit message

```text
chore: clean up tests and dependencies
```

---

## Phase 11.2 — Docker and Database Readiness

### Required tasks

- Verify Docker Compose configuration.
- Verify PostgreSQL configuration.
- Verify Alembic migrations.
- Confirm app can start with documented environment.
- Document startup blockers if any.

### Completion criteria

- Docker/database setup is verified or blockers documented.
- `progress.md` updated.

### Suggested commit message

```text
chore: verify Docker and database setup
```

---

## Phase 11.3 — README and Documentation Update

### README must include

- project overview
- final architecture
- legacy/deprecated notes if any
- setup instructions
- environment variables
- database setup
- migrations
- running backend
- running tests
- ingestion examples
- authentication usage
- API overview
- generated assets notes
- known limitations

### Completion criteria

- README is accurate.
- No outdated Streamlit-as-main-backend instructions remain.
- `progress.md` updated.

### Suggested commit message

```text
docs: update project documentation
```

---

## Phase 11.4 — Git Hygiene

### Required tasks

- Update `.gitignore`.
- Ensure generated files are ignored.
- Ensure `.env` is ignored.
- Ensure local DB files are ignored.
- Ensure Telegram sessions are ignored.
- Ensure generated paper/media assets are ignored.
- Check for accidental secrets.

### Completion criteria

- Git hygiene is documented.
- No obvious sensitive/generated files are staged.
- `progress.md` updated.

### Suggested commit message

```text
chore: improve git hygiene
```

---

## Phase 11.5 — Final Smoke Test

### Required tasks

Run final checks:

- full test suite
- backend import/startup check if possible
- database migration check if possible
- at least one ingestion path if possible
- at least one protected endpoint check if possible

### Completion criteria

- Final validation summary exists in `progress.md`.
- Failures are documented honestly.
- Recommended commit list exists.
- Exact commands to run backend and tests are documented.

### Suggested commit message

```text
chore: final production readiness cleanup
```

---

# Final Agent Response Required

When all phases are done, provide a final summary with:

1. Completed phases
2. Blocked phases, if any
3. Important files changed
4. Test commands run
5. Test results
6. Remaining limitations
7. Recommended commit list
8. Exact commands to run the backend
9. Exact commands to run tests
10. Confirmation that `progress.md` was updated after each phase

Do not claim the project is production-ready unless the final gate passed.

---

# Final Reminder

Be strict.

A phase is not complete because “some work was done”.

A phase is complete only when:

- checklist is satisfied,
- tests are run,
- behavior is verified,
- `progress.md` is updated,
- and remaining issues are documented.

If you are unsure whether a phase is complete, treat it as incomplete and continue working or mark it as blocked with a clear reason.
