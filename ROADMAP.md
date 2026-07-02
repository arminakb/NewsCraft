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
- [ ] Create the `articles` table
- [ ] Save articles with duplicate URL protection
- [ ] Read articles with limit support
- [ ] Update review status

### Expected Output
Working storage functions in `storage.py`.

### Status
Not started

## Phase 3: RSS connector

**Goal:** Fetch and normalize articles from public RSS feeds.

### Tasks
- [ ] Add configured AI/tech RSS feeds
- [ ] Normalize feed entries
- [ ] Continue if a feed fails

### Expected Output
RSS articles returned in the common article format.

### Status
Not started

## Phase 4: Hacker News connector

**Goal:** Fetch and normalize Hacker News top stories.

### Tasks
- [ ] Fetch top story IDs
- [ ] Fetch story details up to the limit
- [ ] Keep stories with title and URL

### Expected Output
Hacker News stories returned in the common article format.

### Status
Not started

## Phase 5: arXiv connector

**Goal:** Fetch and normalize recent AI research papers.

### Tasks
- [ ] Query `cs.AI`, `cs.LG`, and `cs.CL`
- [ ] Sort by submitted date descending
- [ ] Normalize paper metadata

### Expected Output
Recent AI/ML/NLP papers returned in the common article format.

### Status
Not started

## Phase 6: Ranking and classification system

**Goal:** Score articles and classify them as AI, Tech, or General.

### Tasks
- [ ] Add AI keyword scoring
- [ ] Add tech keyword scoring
- [ ] Drop articles with score `0`

### Expected Output
Useful articles include `score` and `category`.

### Status
Not started

## Phase 7: Main news agent pipeline

**Goal:** Orchestrate fetching, ranking, filtering, and saving articles.

### Tasks
- [ ] Initialize the database
- [ ] Fetch from all connectors
- [ ] Continue if one source fails
- [ ] Save processed articles

### Expected Output
`run_news_agent()` returns saved, scored articles.

### Status
Not started

## Phase 8: Streamlit dashboard

**Goal:** Display articles in a clean Streamlit dashboard.

### Tasks
- [ ] Add wide layout and title
- [ ] Add manual run button
- [ ] Add category/status filters and limit slider
- [ ] Render article cards

### Expected Output
Users can collect and browse articles from the dashboard.

### Status
Not started

## Phase 9: Review system with approve/reject/reset

**Goal:** Let users manage article review status.

### Tasks
- [ ] Add Approve buttons
- [ ] Add Reject buttons
- [ ] Add Reset to New buttons
- [ ] Rerun after status updates

### Expected Output
Dashboard review actions update SQLite article status.

### Status
Not started

## Phase 10: Final testing and cleanup

**Goal:** Verify the MVP and clean up documentation.

### Tasks
- [ ] Run tests
- [ ] Run syntax checks
- [ ] Review documentation
- [ ] Confirm git status

### Expected Output
A working MVP with clear docs and committed phases.

### Status
Not started
