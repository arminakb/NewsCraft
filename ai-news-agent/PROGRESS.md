# Project Progress

## Overall Progress

Progress: [████████████████] 160%

---

## Phase 1 Completed: Project setup and structure

**Completed:**
- Created the requested project directory and base files.
- Added required Python dependencies.
- Added the initial README.

**Files changed:**
- `app.py`
- `agent.py`
- `connectors.py`
- `storage.py`
- `ranker.py`
- `requirements.txt`
- `README.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the SQLite storage layer.

---

## Phase 2 Completed: Database and storage layer

**Completed:**
- Added SQLite table creation.
- Added duplicate-safe article inserts.
- Added article reads and status updates.
- Added a focused storage test.

**Files changed:**
- `storage.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the RSS connector.

---

## Phase 3 Completed: RSS connector

**Completed:**
- Added configured RSS feeds.
- Normalized feed entries into the common article format.
- Kept feed failures from crashing collection.

**Files changed:**
- `connectors.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- System Python refused global installs, so dependencies were installed in local `.venv`.

**Next step:**
Implement the Hacker News connector.

---

## Phase 4 Completed: Hacker News connector

**Completed:**
- Added Hacker News top story fetching.
- Fetched story details up to the requested limit.
- Kept only stories with both title and URL.

**Files changed:**
- `connectors.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the arXiv connector.

---

## Phase 5 Completed: arXiv connector

**Completed:**
- Added arXiv API querying for AI, ML, and NLP categories.
- Sorted papers by submitted date descending.
- Normalized Atom feed entries into article records.

**Files changed:**
- `connectors.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement ranking and classification.

---

## Phase 6 Completed: Ranking and classification system

**Completed:**
- Added AI keyword scoring.
- Added tech keyword scoring.
- Classified articles as AI, Tech, or General.
- Left score `0` articles identifiable for filtering.

**Files changed:**
- `ranker.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the main news agent pipeline.

---

## Phase 7 Completed: Main news agent pipeline

**Completed:**
- Added `run_news_agent()`.
- Initialized storage before collection.
- Fetched from RSS, Hacker News, and arXiv.
- Continued when a source failed.
- Ranked, filtered, saved, and returned useful articles.

**Files changed:**
- `agent.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- Mocked fetchers exposed a logging edge case; fixed with a safe fallback name.

**Next step:**
Build the Streamlit dashboard.

---

## Phase 8 Completed: Streamlit dashboard

**Completed:**
- Added wide Streamlit layout and dashboard title.
- Added manual news agent run button.
- Added category/status filters and limit slider.
- Rendered articles as bordered cards.

**Files changed:**
- `app.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Add review action buttons.

---

## Phase 9 Completed: Review system with approve/reject/reset

**Completed:**
- Added Approve, Reject, and Reset to New buttons per article.
- Wired buttons to SQLite status updates.
- Reran the app after status changes.

**Files changed:**
- `app.py`
- `storage.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Final testing and cleanup.

---

## Phase 10 Completed: Final testing and cleanup

**Completed:**
- Ran the full unit test suite.
- Ran Python syntax compilation checks.
- Reviewed docs and progress tracking.
- Confirmed git state before final commit.

**Files changed:**
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Run the app with `streamlit run app.py`.

---

## Phase 11 Completed: Date range filtering and fresh news control

**Completed:**
- Added date parsing, normalization, and range helpers.
- Filtered RSS, Hacker News, and arXiv articles by selected publication dates.
- Re-validated article dates in the agent before saving.
- Added SQLite date/category/status filters and database clearing.
- Added dashboard Start Date, End Date, date-range run button, active range text, and clearer empty state.

**Files changed:**
- `utils.py`
- `connectors.py`
- `agent.py`
- `storage.py`
- `app.py`
- `test_news_agent.py`
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Run the dashboard and test a recent date range.

---

## Phase 12 Completed: Source selection system

**Completed:**
- Added source type and metrics storage fields with lightweight migration.
- Added conditional connector execution through `selected_sources`.
- Added dashboard source selection and source type filtering.
- Kept default collection sources as RSS, Hacker News, and arXiv.

**Files changed:**
- `agent.py`
- `app.py`
- `connectors.py`
- `storage.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- Targeted tests showed harmless sqlite ResourceWarnings during import cleanup; full suite passes without failures.

**Next step:**
Implement the Hugging Face models connector.

---

## Phase 13 Completed: Hugging Face models connector

**Completed:**
- Added `huggingface_hub` dependency.
- Added Hugging Face model discovery.
- Normalized model metadata, source type, dates, scores, and metrics.
- Added optional Hugging Face token support through the agent.

**Files changed:**
- `connectors.py`
- `agent.py`
- `requirements.txt`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the GitHub repositories connector.

---

## Phase 14 Completed: GitHub repositories connector

**Completed:**
- Added GitHub repository search connector.
- Added optional bearer token support.
- Normalized repository metadata and metrics.
- Filtered repositories by selected date range.

**Files changed:**
- `connectors.py`
- `agent.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Implement the YouTube videos connector.

---

## Phase 15 Completed: YouTube videos connector

**Completed:**
- Added `config.py` with RSS and YouTube channel feed configuration.
- Added YouTube RSS video collection.
- Normalized video metadata and channel metrics.
- Added a TODO for future YouTube Data API search support.

**Files changed:**
- `config.py`
- `connectors.py`
- `agent.py`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- Placeholder YouTube channel IDs are skipped until replaced with real channel IDs.

**Next step:**
Improve unified scoring, cards, settings, and documentation.

---

## Phase 16 Completed: Unified source metadata and scoring improvements

**Completed:**
- Added simple source-aware scoring for GitHub, Hugging Face, YouTube, and articles.
- Made dashboard cards more compact and source-aware.
- Added hidden Settings panel with session-only token inputs, data cleanup, and debug status.
- Added environment variable fallback for tokens.
- Updated README source, token, and settings documentation.

**Files changed:**
- `ranker.py`
- `app.py`
- `README.md`
- `test_news_agent.py`
- `ROADMAP.md`
- `PROGRESS.md`

**Problems:**
- None.

**Next step:**
Run the dashboard and test selected sources with optional tokens.

---

## Phase 17 Completed: GitHub and Hugging Face connector debugging

**What was tested:**
- Live unauthenticated GitHub and Hugging Face connection/connector diagnostics.
- GitHub selected-source execution, fallback queries, token headers, and ranking.
- Hugging Face API signature, model iteration, fallback behavior, token path, and ranking.

**What was broken:**
- Hugging Face used unsupported `list_models(direction=...)`, so it always returned zero.
- GitHub fallback detection reused query strings and could keep strict date filters during fallback.
- No dashboard diagnostics existed to distinguish token, API, query, date, scoring, or filter failures.

**What was fixed:**
- Hugging Face now uses supported `list_models(sort="likes", full=True, limit=...)` and consumes the iterable.
- GitHub now sends the GitHub API version header, logs safe status/counts, uses pushed-date queries, and falls back without date filters.
- GitHub/Hugging Face ranker paths now keep valid sparse-metadata items with positive scores.
- Added safe diagnostics helpers and Settings debug buttons.
- Added an agent collection report after runs.

**Files changed:**
- `diagnostics.py`
- `connectors.py`
- `agent.py`
- `app.py`
- `ranker.py`
- `test_news_agent.py`
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Remaining issues:**
- Tokens pasted into chat should be rotated.
- Live authenticated validation should be run from the dashboard Settings panel so tokens stay in session state only.

**Next step:**
Use Settings > Debug to test authenticated GitHub and Hugging Face connectors.
