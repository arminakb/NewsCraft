Before writing code, first create `ROADMAP.md` and divide the project into clear implementation phases. Then implement the project phase by phase. After completing each phase, update `PROGRESS.md` with a short report and a text-based progress bar. Do not continue to the next phase without updating the progress file.



You are a senior full-stack Python engineer and AI product builder.

I want you to build an MVP project called **AI & Tech News Agent Dashboard**.

The goal is to create a simple working system that collects daily AI and technology news from free public sources, ranks them, stores them, and displays them in a dashboard.

Do not over-engineer the project. Build a clean, working MVP first.

## Main Requirements

Build a Python project with this structure:

```text
ai-news-agent/
  app.py
  agent.py
  connectors.py
  storage.py
  ranker.py
  requirements.txt
  README.md
```

The app should use:

```text
Python
Streamlit
SQLite
feedparser
requests
python-dateutil
```

No paid APIs.
No OpenAI API for this version.
No authentication system.
No Docker for now unless necessary.
No complex frontend framework.

## What the app should do

The system should collect AI and tech news from these sources:

1. RSS feeds
2. Hacker News API
3. arXiv API

Use free public sources only.

The agent should:

1. Fetch articles from RSS feeds.
2. Fetch top stories from Hacker News.
3. Fetch recent AI/ML/NLP papers from arXiv.
4. Normalize all articles into one common format.
5. Score each article based on AI and technology keywords.
6. Classify each article as:

   * AI
   * Tech
   * General
7. Store articles in SQLite.
8. Avoid duplicate articles using the article URL.
9. Display the articles in a Streamlit dashboard.
10. Allow the user to manually run the news agent from the dashboard.

## Data format

Every article should be normalized into this format:

```json
{
  "source": "Source name",
  "title": "Article title",
  "url": "https://...",
  "published_at": "Publication date if available",
  "summary": "Short summary or excerpt",
  "category": "AI / Tech / General",
  "score": 0
}
```

## Files to implement

### 1. `requirements.txt`

Include all required packages.

### 2. `storage.py`

Implement SQLite database logic.

Functions needed:

```python
init_db()
save_articles(articles)
get_articles(limit=100)
update_article_status(article_id, status)
```

Create a table called `articles` with these fields:

```text
id
source
title
url
published_at
summary
category
score
status
created_at
```

The `status` field should default to `"new"`.

Valid statuses:

```text
new
approved
rejected
```

Use `INSERT OR IGNORE` to avoid duplicate URLs.

### 3. `ranker.py`

Implement simple keyword-based ranking.

Use AI keywords like:

```text
ai
artificial intelligence
openai
anthropic
google deepmind
llm
large language model
chatgpt
claude
gemini
machine learning
deep learning
neural
agent
agents
automation
robotics
computer vision
generative ai
multimodal
model
```

Use tech keywords like:

```text
startup
github
developer
software
api
cloud
cybersecurity
security
chip
nvidia
apple
meta
microsoft
google
database
framework
open source
```

Implement:

```python
classify_and_score(article)
```

The function should add:

```python
article["score"]
article["category"]
```

Only keep useful and relevant articles.

### 4. `connectors.py`

Implement these functions:

```python
fetch_rss_articles()
fetch_hacker_news(limit=30)
fetch_arxiv_ai(limit=20)
```

For RSS, use these feeds:

```text
https://openai.com/news/rss.xml
https://techcrunch.com/category/artificial-intelligence/feed/
https://www.theverge.com/rss/ai-artificial-intelligence/index.xml
https://www.technologyreview.com/topic/artificial-intelligence/feed/
```

If a feed fails, the app should not crash. Log the error and continue.

For Hacker News:

Use:

```text
https://hacker-news.firebaseio.com/v0/topstories.json
https://hacker-news.firebaseio.com/v0/item/{id}.json
```

Only include stories that have both title and URL.

For arXiv:

Use:

```text
http://export.arxiv.org/api/query
```

Query categories:

```text
cat:cs.AI OR cat:cs.LG OR cat:cs.CL
```

Sort by submitted date descending.

### 5. `agent.py`

Implement:

```python
run_news_agent()
```

It should:

1. Initialize DB.
2. Fetch from all connectors.
3. Score and classify articles.
4. Remove articles with score 0.
5. Save articles.
6. Return the processed articles.

The agent should not crash if one source fails.

### 6. `app.py`

Build a Streamlit dashboard.

Dashboard features:

1. Page title:
   **AI & Tech News Agent Dashboard**

2. Button:
   **Run News Agent**

3. When the button is clicked:

   * Run `run_news_agent()`
   * Show success message with number of collected articles

4. Filters:

   * Category filter: All / AI / Tech / General
   * Status filter: All / new / approved / rejected
   * Limit slider: 10 to 100

5. Display articles as cards.

Each article card should show:

```text
Title as clickable link
Source
Category
Score
Status
Published date
Summary preview
```

6. Add three action buttons per article:

```text
Approve
Reject
Reset to New
```

These buttons should update article status in the database.

Use Streamlit session rerun after updating status.

## Important UX Requirements

The dashboard should look clean and simple.

Use wide layout.

Use Streamlit containers or bordered cards if available.

Do not show huge raw HTML summaries. Clean summaries if needed.

Long summaries should be trimmed to around 500 characters.

## Error handling

The app should handle:

```text
RSS feed errors
Network errors
Missing article title
Missing article URL
Duplicate URLs
Empty result lists
```

The app should not crash if one source fails.

## README.md

Create a simple README with:

1. Project description
2. Features
3. Installation
4. How to run
5. Project structure
6. Next steps

Installation should be:

```bash
pip install -r requirements.txt
```

Run command:

```bash
streamlit run app.py
```

## Coding Style

Write clean, readable Python.

Use functions, not one giant script.

Add comments only where useful.

Keep the MVP simple.

Do not add unnecessary frameworks.

Do not add LLM rewriting yet.

Do not add Instagram video generation yet.

This version is only for collecting, ranking, storing, and reviewing AI/tech news.

## Project Planning and Progress Tracking

In addition to building the project, create two documentation files:

```text
ROADMAP.md
PROGRESS.md
```

### ROADMAP.md

Create a file called `ROADMAP.md`.

In this file, divide the project into clear development phases.

Suggested phases:

```text
Phase 1: Project setup and structure
Phase 2: Database and storage layer
Phase 3: RSS connector
Phase 4: Hacker News connector
Phase 5: arXiv connector
Phase 6: Ranking and classification system
Phase 7: Main news agent pipeline
Phase 8: Streamlit dashboard
Phase 9: Review system with approve/reject/reset
Phase 10: Final testing and cleanup
```

For each phase, include:

```text
Goal
Tasks
Expected output
Completion status
```

Use checkboxes for tasks.

Example format:

```md
## Phase 1: Project setup and structure

**Goal:** Create the base project structure.

### Tasks
- [ ] Create project files
- [ ] Add requirements.txt
- [ ] Prepare README.md

### Expected Output
A clean Python project structure ready for development.

### Status
Not started
```

### PROGRESS.md

Create a file called `PROGRESS.md`.

After finishing each phase, update this file with a short progress report.

Each progress update should include:

```text
Phase name
What was completed
Files changed or created
Problems encountered, if any
Next step
Progress bar
```

Use a simple text-based progress bar.

Example:

```md
# Project Progress

## Overall Progress

Progress: [███-------] 30%

---

## Phase 1 Completed: Project setup and structure

**Completed:**
- Created the main project files.
- Added initial requirements.
- Prepared base README.

**Files changed:**
- app.py
- agent.py
- connectors.py
- storage.py
- ranker.py
- requirements.txt
- README.md

**Problems:**
- None.

**Next step:**
Implement the SQLite storage layer.
```

The progress bar should be updated after every completed phase.

Use this progress format:

```text
Phase 1 complete: 10%
Phase 2 complete: 20%
Phase 3 complete: 30%
Phase 4 complete: 40%
Phase 5 complete: 50%
Phase 6 complete: 60%
Phase 7 complete: 70%
Phase 8 complete: 80%
Phase 9 complete: 90%
Phase 10 complete: 100%
```

Important:

* Do not skip documentation.
* Do not only create the files at the end.
* Update `PROGRESS.md` after each completed phase.
* Keep each progress report short and useful.
* If something fails, write it clearly in `PROGRESS.md`.
* At the end of the project, `PROGRESS.md` should show 100% completion.
* At the end of the project, `ROADMAP.md` should show all phases as completed.




## Acceptance Criteria

The project is complete when:

1. I can run:

```bash
streamlit run app.py
```

2. The dashboard opens successfully.

3. I can click **Run News Agent**.

4. News from RSS, Hacker News, and arXiv is collected.

5. Articles are saved into SQLite.

6. Duplicate URLs are ignored.

7. Articles appear in the dashboard.

8. I can filter by category and status.

9. I can approve, reject, or reset articles.

10. The app still works even if one data source fails.

After building the project, briefly explain how to run it and what files were created.
