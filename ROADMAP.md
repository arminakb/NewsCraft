# AI & Tech News Agent Dashboard Roadmap

## Phase 1: Project setup and structure

**Goal:** Create the base Python project structure.

### Tasks
- [x] Create project files
- [x] Add `requirements.txt`
- [x] Prepare base `README.md`

### Expected Output
A clean Python project structure ready for development.

### Status
Complete

## Phase 2: Database and storage layer

**Goal:** Add SQLite persistence for normalized articles.

### Tasks
- [x] Create the `articles` table
- [x] Save articles with duplicate URL protection
- [x] Read articles with limit support
- [x] Update review status

### Expected Output
Working storage functions in `storage.py`.

### Status
Complete

## Phase 3: RSS connector

**Goal:** Fetch and normalize articles from public RSS feeds.

### Tasks
- [x] Add configured AI/tech RSS feeds
- [x] Normalize feed entries
- [x] Continue if a feed fails

### Expected Output
RSS articles returned in the common article format.

### Status
Complete

## Phase 4: Hacker News connector

**Goal:** Fetch and normalize Hacker News top stories.

### Tasks
- [x] Fetch top story IDs
- [x] Fetch story details up to the limit
- [x] Keep stories with title and URL

### Expected Output
Hacker News stories returned in the common article format.

### Status
Complete

## Phase 5: arXiv connector

**Goal:** Fetch and normalize recent AI research papers.

### Tasks
- [x] Query `cs.AI`, `cs.LG`, and `cs.CL`
- [x] Sort by submitted date descending
- [x] Normalize paper metadata

### Expected Output
Recent AI/ML/NLP papers returned in the common article format.

### Status
Complete

## Phase 6: Ranking and classification system

**Goal:** Score articles and classify them as AI, Tech, or General.

### Tasks
- [x] Add AI keyword scoring
- [x] Add tech keyword scoring
- [x] Drop articles with score `0`

### Expected Output
Useful articles include `score` and `category`.

### Status
Complete

## Phase 7: Main news agent pipeline

**Goal:** Orchestrate fetching, ranking, filtering, and saving articles.

### Tasks
- [x] Initialize the database
- [x] Fetch from all connectors
- [x] Continue if one source fails
- [x] Save processed articles

### Expected Output
`run_news_agent()` returns saved, scored articles.

### Status
Complete

## Phase 8: Streamlit dashboard

**Goal:** Display articles in a clean Streamlit dashboard.

### Tasks
- [x] Add wide layout and title
- [x] Add manual run button
- [x] Add category/status filters and limit slider
- [x] Render article cards

### Expected Output
Users can collect and browse articles from the dashboard.

### Status
Complete

## Phase 9: Review system with approve/reject/reset

**Goal:** Let users manage article review status.

### Tasks
- [x] Add Approve buttons
- [x] Add Reject buttons
- [x] Add Reset to New buttons
- [x] Rerun after status updates

### Expected Output
Dashboard review actions update SQLite article status.

### Status
Complete

## Phase 10: Final testing and cleanup

**Goal:** Verify the MVP and clean up documentation.

### Tasks
- [x] Run tests
- [x] Run syntax checks
- [x] Review documentation
- [x] Confirm git status

### Expected Output
A working MVP with clear docs and committed phases.

### Status
Complete

## Phase 11: Date range filtering and fresh news control

**Goal:** Let users collect and display only articles inside a selected date range.

### Tasks
- [x] Add date parsing and range helpers
- [x] Filter RSS, Hacker News, and arXiv by publication date
- [x] Re-validate article dates in the agent before saving
- [x] Filter SQLite reads by date, category, and status
- [x] Add dashboard date inputs and database clearing
- [x] Update documentation and tests

### Expected Output
Fresh, dated articles are collected and displayed only for the selected date range.

### Status
Complete

## Phase 12: Source selection system

**Goal:** Let users choose which source connectors run and filter stored items by source type.

### Tasks
- [x] Add source type and metrics storage fields
- [x] Add conditional agent connector execution
- [x] Add source selector and source type filter in the dashboard
- [x] Keep default sources as RSS, Hacker News, and arXiv

### Expected Output
The dashboard can run selected sources only and filter displayed items by source type.

### Status
Complete

## Phase 13: Hugging Face models connector

**Goal:** Discover and store relevant Hugging Face models.

### Tasks
- [x] Add `huggingface_hub` dependency
- [x] Fetch recently updated interesting models
- [x] Normalize model metadata and metrics
- [x] Support optional Hugging Face token

### Expected Output
Hugging Face models can be collected and displayed.

### Status
Complete

## Phase 14: GitHub repositories connector

**Goal:** Discover and store relevant AI/ML GitHub repositories.

### Tasks
- [x] Query GitHub repository search
- [x] Support optional `GITHUB_TOKEN`
- [x] Normalize repository metadata and metrics
- [x] Filter by selected date range

### Expected Output
GitHub repositories can be collected and displayed.

### Status
Complete

## Phase 15: YouTube videos connector

**Goal:** Collect videos from configured YouTube RSS channel feeds.

### Tasks
- [x] Add YouTube channel feed config
- [x] Fetch videos via RSS
- [x] Normalize video metadata
- [x] Keep Data API support as a future TODO

### Expected Output
YouTube RSS videos can be collected and displayed.

### Status
Complete

## Phase 16: Unified source metadata and scoring improvements

**Goal:** Improve scoring, metadata display, settings, and documentation for all source types.

### Tasks
- [x] Score all source types with simple explainable logic
- [x] Add compact source-aware dashboard cards
- [x] Add settings panel and session-only token inputs
- [x] Update README and progress docs

### Expected Output
All source types have useful scores, metadata, and a cleaner dashboard UI.

### Status
Complete

## Phase 17: GitHub and Hugging Face connector debugging

**Goal:** Diagnose and fix empty GitHub and Hugging Face discovery results.

### Tasks
- [x] Test current GitHub and Hugging Face connector behavior
- [x] Add safe diagnostics helpers and Settings debug buttons
- [x] Fix GitHub token handling, queries, fallback, and logging
- [x] Fix Hugging Face API usage, iterable handling, fallback, and logging
- [x] Ensure ranking and date filtering do not drop valid items
- [x] Update README, progress docs, and tests

### Expected Output
GitHub and Hugging Face connectors return useful items and expose safe diagnostics.

### Status
Complete

## Phase 18: Dashboard UX cleanup, search sessions, approved articles, and better source enrichment

**Goal:** Clean up the dashboard UX, add current search sessions, save approved articles separately, and enrich GitHub/Hugging Face cards.

### Tasks
- [x] Rename Settings to Configuration and use a compact popover-style panel
- [x] Remove duplicate source type controls
- [x] Add structured summaries for GitHub and Hugging Face results
- [x] Move results database clearing to the main page with confirmation
- [x] Add separate approved articles storage and dashboard tab
- [x] Add search sessions and show current session results by default
- [x] Improve GitHub discovery quality and README documentation

### Expected Output
The dashboard shows cleaner current-session results, stores approved articles separately, and displays richer GitHub/Hugging Face explanations.

### Status
Complete

## Phase 19: Configuration UX cleanup, token sanitization, card action simplification, and useful summaries

**Goal:** Keep Configuration inside the page, sanitize tokens, simplify card actions, and make GitHub/Hugging Face summaries concise and useful.

### Tasks
- [x] Improve Configuration placement so the popover stays inside the dashboard width
- [x] Strip whitespace from API tokens and redact token-like error text
- [x] Remove Reject and Reset to New card buttons
- [x] Keep Approve saving to `approved_articles.db`
- [x] Filter noisy Hugging Face/GitHub tags and metadata
- [x] Render concise structured summary sections and compact raw details
- [x] Update README, tests, and progress docs

### Expected Output
The dashboard has cleaner cards, safer token handling, better summaries, and a less fragile Configuration popup.

### Status
Complete
