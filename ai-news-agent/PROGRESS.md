# Project Progress

## Overall Progress

Progress: [██████----] 60%

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
