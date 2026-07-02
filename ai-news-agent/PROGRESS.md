# Project Progress

## Overall Progress

Progress: [████████████████████] 200%

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
- Live authenticated validation should be run from the dashboard Configuration panel so tokens stay in session state only.

**Next step:**
Use Configuration > Debug to test authenticated GitHub and Hugging Face connectors.

---

## Phase 18 Completed: Dashboard UX cleanup, search sessions, approved articles, and better source enrichment

**What was changed:**
- Renamed Settings to Configuration and moved token/debug controls into a popover-style panel.
- Removed the duplicate Source Type display filter.
- Added structured summaries for GitHub repositories and Hugging Face models.
- Moved Clear Results Database next to the run button with a confirmation checkbox.
- Added search sessions so new runs show current-session results by default.
- Added `approved_articles.db` storage and an Approved Articles dashboard tab.
- Improved GitHub discovery with created/pushed date queries, README snippets, and quality filtering.
- Expanded the collection report with selected sources, per-source raw counts, saved counts, duplicate skips, date skips, and score skips.

**What was broken before:**
- New searches mixed with old database rows unless the user manually cleared the database.
- Approved status only changed the collected row and did not save reusable approved articles separately.
- GitHub and Hugging Face cards mostly showed names and sparse metadata.
- Settings and cleanup controls took too much dashboard space.

**What was fixed:**
- Each agent run now creates a search session and tags collected articles with it.
- Duplicate URLs are still protected, but repeated discoveries move into the latest search session.
- Approved articles are copied into a separate SQLite database with URL deduplication.
- GitHub/Hugging Face results now display rule-based structured explanations.

**Files changed:**
- `app.py`
- `agent.py`
- `approved_storage.py`
- `connectors.py`
- `diagnostics.py`
- `storage.py`
- `test_news_agent.py`
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Testing performed:**
- `.venv/bin/python -m unittest test_news_agent`
- `.venv/bin/python -m compileall app.py agent.py approved_storage.py config.py connectors.py diagnostics.py storage.py ranker.py utils.py test_news_agent.py`

**Remaining issues, if any:**
- Tokens pasted into chat should be rotated.
- Live authenticated GitHub and Hugging Face checks should be run from Configuration > Debug so tokens stay in session state.

**Updated progress bar:**
Progress: [██████████████████] 180%

**Next step:**
Run the Streamlit dashboard and test GitHub/Hugging Face collection with Configuration > Debug.

---

## Phase 19 Completed: Configuration UX cleanup, token sanitization, card action simplification, and useful summaries

**What was changed:**
- Moved Configuration into a wider right header column and enabled container-width popover behavior where Streamlit supports it.
- Added token cleanup for dashboard inputs, environment fallback, agent calls, connectors, and diagnostics.
- Redacted token-like values from diagnostic errors.
- Removed Reject and Reset to New from article cards.
- Kept Approve saving to `approved_articles.db` and marking collected rows approved.
- Added rule-based summary utilities for concise GitHub and Hugging Face summaries.
- Filtered noisy tags and hid raw metadata under collapsed Raw details.

**What was fixed:**
- Hugging Face tokens with trailing spaces no longer reach `HfApi(token=...)`.
- GitHub tokens with trailing spaces no longer reach the Authorization header.
- Cards no longer dump long tag lists or repeat visible metrics under the structured summary.
- Configuration placement is less likely to overflow at the right edge.

**Files changed:**
- `app.py`
- `agent.py`
- `connectors.py`
- `diagnostics.py`
- `summarizer.py`
- `utils.py`
- `test_news_agent.py`
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Testing performed:**
- `.venv/bin/python -m unittest test_news_agent`
- `.venv/bin/python -m compileall app.py agent.py approved_storage.py config.py connectors.py diagnostics.py storage.py ranker.py utils.py summarizer.py test_news_agent.py`

**Remaining issues, if any:**
- Configuration popover direction is limited by Streamlit; the layout workaround gives it more room inside the page.
- Tokens pasted into chat should still be rotated.

**Updated progress bar:**
Progress: [███████████████████] 190%

**Next step:**
Run the dashboard and verify a GitHub/Hugging Face run with tokens entered in Configuration.

---

## Phase 20 Completed: Source logic audit, GitHub repair, latest sorting, and expanded AI news sources

**What was investigated:**
- GitHub token path from Configuration to agent, connector, scoring, storage, and dashboard.
- Hacker News top-story-only collection, URL filtering, date filtering, scoring, and display.
- arXiv query categories, Atom parsing, date filtering, scoring, and display.
- RSS source labels, per-feed handling, source groups, and failed-feed behavior.
- SQLite date filtering, sort order, duplicate URL/session updates, and approved storage independence.
- Dashboard source labels, current-session filtering, time ranges, sorting, and card timestamps.

**What was broken:**
- Hacker News and arXiv could return valid items but then be dropped because scoring could stay at zero.
- Hacker News only used top stories, so useful new/best developer stories were missed.
- arXiv searched only AI/LG/CL and did not preserve authors or Research category.
- RSS source reporting was grouped as RSS instead of showing real feed names.
- Date filtering was date-only, so Last 24 hours could not work correctly.
- GitHub diagnostics did not expose enough per-query HTTP/rate-limit/raw/filter counts to explain empty runs.
- Storage had no connector/source-group columns and no user-selectable sort mode.

**What was fixed:**
- Added connector/source_group metadata through collection, storage, approved storage, and dashboard display.
- Added Last 24 hours, Last 3 days, Last 7 days, and Custom range support.
- Added Sort by: Latest first, Highest score, Most popular, and Source.
- Added relative publish time on cards.
- Expanded RSS sources to OpenAI, Anthropic, NVIDIA, DeepMind, Microsoft, Hugging Face, TechCrunch, VentureBeat, The Verge, MIT Tech Review, and Y Combinator.
- Hacker News now checks top/new/best stories and reports raw IDs, loaded items, URL items, date-filtered items, and scored items.
- arXiv now searches AI/LG/CL/CV/stat.ML, stores authors, and scores Research items positively.
- GitHub connector now reports token status, query list, HTTP status, rate limit remaining, raw count, date-filtered count, scored count, and returned count.

**Files changed:**
- `app.py`
- `agent.py`
- `approved_storage.py`
- `config.py`
- `connectors.py`
- `diagnostics.py`
- `ranker.py`
- `storage.py`
- `test_news_agent.py`
- `utils.py`
- `README.md`
- `ROADMAP.md`
- `PROGRESS.md`

**Tests performed:**
- `.venv/bin/python -m unittest test_news_agent`
- `.venv/bin/python -m compileall app.py agent.py approved_storage.py config.py connectors.py diagnostics.py storage.py ranker.py utils.py summarizer.py test_news_agent.py`

**Remaining issues, if any:**
- Some RSS feeds may fail or change URLs; failed feeds are reported and skipped.
- GitHub can still be rate-limited or return zero for narrow ranges, but diagnostics now show why.
- Tokens pasted into chat should still be rotated.

**Updated progress bar:**
Progress: [████████████████████] 200%

**Next step:**
Run each source from the dashboard with Last 7 days and review the collection report diagnostics.

---

## Phase 21 Completed: Telegram channel connector

**What was added:**
- Added a Telethon-based Telegram connector for manually configured trusted channels.
- Added `telegram_login.py` to create a local user session outside Streamlit.
- Added Telegram API ID, API Hash, session name, and channel username fields in Configuration.
- Added Telegram Channels to source selection, diagnostics, agent collection, ranking, and card metrics.
- Added `.session` and `.session-journal` git ignores.

**What was tested:**
- Telegram username parsing and message normalization.
- Missing Telegram API/session configuration diagnostics.
- Agent config passing from selected Telegram source into the connector.
- Telegram ranking with views, forwards, links, and AI/tech keywords.
- Dashboard token/environment resolution for Telegram settings.

**Files changed:**
- `.gitignore`
- `ROADMAP.md`
- `app.py`
- `agent.py`
- `config.py`
- `diagnostics.py`
- `ranker.py`
- `telegram_connector.py`
- `telegram_login.py`
- `test_news_agent.py`
- `requirements.txt`
- `README.md`
- `PROGRESS.md`

**Known limitations:**
- Telegram requires a local Telethon user session; the Streamlit app does not perform first-time login.
- Channel discovery is manual by design.
- Private channels only work when the logged-in account has legitimate access.
- Live Telegram collection was not run because it requires user login/session credentials.

**Updated progress bar:**
Progress: [█████████████████████] 210%

**Next step:**
Run `python telegram_login.py`, add trusted channel usernames in Configuration, and test Telegram Channels from the dashboard Debug panel.
