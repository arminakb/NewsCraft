# AI & Tech News Agent Dashboard

A small Streamlit MVP that collects AI and technology news from public sources,
ranks the articles, stores them in SQLite, and displays them for review.

## Features

- RSS, Hacker News, and arXiv collection
- Hugging Face model, GitHub repository, and YouTube RSS discovery
- Keyword scoring and category classification
- SQLite storage with duplicate URL protection
- Streamlit dashboard with review statuses
- Date range collection and display filtering
- Current search sessions and separate approved-articles storage

## Installation

```bash
pip install -r requirements.txt
```

On systems that block global Python package installs, use a virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## How to run

```bash
streamlit run app.py
```

With the local virtual environment:

```bash
.venv/bin/streamlit run app.py
```

## Date Range Filtering

Use the Start Date and End Date controls to collect and display news from a specific period. The selected range is applied during source collection and when reading saved articles from SQLite.

## Selecting Sources

Use **Collection Controls** to choose which sources the agent should run. Each run creates a new search session, and the dashboard shows the current session by default so old results do not crowd the new run.

## Hugging Face Models

The Hugging Face connector discovers public models, stores likes/downloads as metrics, and creates a structured summary from tags and metadata. A Hugging Face token is optional and can be entered in Configuration or provided with `HUGGINGFACE_TOKEN`.

## GitHub Repository Discovery

The GitHub connector searches AI/ML/LLM/agent/RAG topics and keywords, tries pushed-date and created-date queries, falls back to popular AI repositories, and stores stars, forks, open issues, language, and structured summaries. It also attempts to fetch README snippets safely. `GITHUB_TOKEN` is optional but recommended for better GitHub API limits.

## YouTube Video Sources

YouTube collection uses RSS channel feeds from `config.py`, not the YouTube Data API. Replace `CHANNEL_ID_HERE` in `YOUTUBE_CHANNEL_FEEDS` with real channel IDs. Search-based YouTube Data API support can be added later if needed.

## Configuration Popup

Open **Configuration** near the dashboard header to enter optional API credentials and run diagnostics. Manually entered tokens are stored only in Streamlit session state. They are not saved to SQLite, printed, or committed. If the installed Streamlit version does not support popovers, the app uses a compact expander fallback.

## Search Sessions

Every **Run Agent** click creates a new search session and tags collected articles with that session ID. The dashboard shows current-session results by default, while older collected rows remain in `news.db` for later use or cleanup.

## Approved Articles Database

Click **Approve** on an article to save a copy into `approved_articles.db` and mark the original collected row as approved. Approved URLs are deduplicated and survive new searches and normal results cleanup. Use the **Approved Articles** tab to review or delete approved items.

## Clearing Results Database

Use **Clear Results Database** next to the run button to clear collected results and search sessions from `news.db`. This does not delete `approved_articles.db`.

## Environment Variables

```bash
export GITHUB_TOKEN="your_github_token"
export HUGGINGFACE_TOKEN="your_huggingface_token"
export YOUTUBE_API_KEY="your_youtube_api_key"
```

PowerShell:

```powershell
$env:GITHUB_TOKEN="your_github_token"
$env:HUGGINGFACE_TOKEN="your_huggingface_token"
$env:YOUTUBE_API_KEY="your_youtube_api_key"
```

## Cleaning Old Data

If old articles still appear, the existing `news.db` may contain old or badly formatted dates from a previous version. Use **Clear Results Database** in the dashboard, or delete `news.db` manually, then run the agent again.

## Troubleshooting GitHub and Hugging Face

Open **Configuration > Debug** and run the GitHub/Hugging Face connection and connector tests. The diagnostics show token status, safe HTTP/status details, and item counts without exposing token values.

Common causes of empty results:

- Token was entered in a different browser session; enter it again in Configuration or use an environment variable.
- GitHub rate limit, 401, 403, or query validation errors.
- Date range is too narrow; connectors fall back to popular/recent results where useful.
- Hugging Face metadata such as `last_modified`, likes, or downloads is missing.
- Display filters hide results; use Category `All` and Status `All`.
- Old database schema or old rows; use **Clear Results Database**.

## Project structure

```text
app.py
agent.py
diagnostics.py
connectors.py
config.py
approved_storage.py
storage.py
ranker.py
utils.py
requirements.txt
README.md
```

## Next steps

- Tune keywords after real-world usage.
- Add scheduling when manual runs are not enough.
