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

Use **Collection Controls** to choose which sources the agent should run. Source selection affects collection only; previously stored items remain visible unless hidden by the Source Type filter.

## Hugging Face Models

The Hugging Face connector discovers recently updated public models and stores likes/downloads as metrics. A Hugging Face token is optional and can be entered in Settings or provided with `HUGGINGFACE_TOKEN`.

## GitHub Repository Discovery

The GitHub connector searches AI/ML repository topics and keywords, then stores stars, forks, and open issues. `GITHUB_TOKEN` is optional but recommended for better GitHub API limits.

## YouTube Video Sources

YouTube collection uses RSS channel feeds from `config.py`, not the YouTube Data API. Replace `CHANNEL_ID_HERE` in `YOUTUBE_CHANNEL_FEEDS` with real channel IDs. Search-based YouTube Data API support can be added later if needed.

## Settings Panel

Click **Settings** in the dashboard to open API token, data cleanup, and debug controls. Manually entered tokens are stored only in Streamlit session state. They are not saved to SQLite, printed, or committed.

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

If old articles still appear, the existing `news.db` may contain old or badly formatted dates from the previous version. Use the **Clear Old Database** button in the dashboard, or delete `news.db` manually, then run the agent again.

## Troubleshooting GitHub and Hugging Face

Open **Settings > Debug** and run the GitHub/Hugging Face connection and connector tests. The diagnostics show token status, safe HTTP/status details, and item counts without exposing token values.

Common causes of empty results:

- Token was entered but not saved in Settings.
- GitHub rate limit, 401, 403, or query validation errors.
- Date range is too narrow; connectors fall back to popular/recent results where useful.
- Hugging Face metadata such as `last_modified`, likes, or downloads is missing.
- Display filters hide results; use Source Type `All`, Category `All`, Status `All`.
- Old database schema or old rows; use **Clear Old Database**.

## Project structure

```text
app.py
agent.py
diagnostics.py
connectors.py
config.py
storage.py
ranker.py
utils.py
requirements.txt
README.md
```

## Next steps

- Tune keywords after real-world usage.
- Add scheduling when manual runs are not enough.
