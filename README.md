# NewsCraft

NewsCraft is a Streamlit dashboard for collecting, ranking, reviewing, and preparing AI and technology news from public sources.

The app lives in `ai-news-agent/` and uses Python, Streamlit, SQLite, RSS feeds, Hacker News, arXiv, GitHub, Hugging Face, YouTube RSS, and optional Telegram ingestion.

## Features

- Collects AI and tech news from RSS, Hacker News, arXiv, GitHub, Hugging Face, YouTube RSS, and Telegram channels.
- Scores and classifies articles with simple keyword-based ranking.
- Stores collected and approved articles in local SQLite databases.
- Provides a Streamlit review dashboard with source, status, date, and category filters.
- Supports optional session-only API tokens for higher connector limits.
- Prepares selected arXiv papers into local PDF, full-text, research brief, Instagram brief, and podcast brief assets.

## Tech Stack

- Python
- Streamlit
- SQLite
- feedparser
- requests
- python-dateutil
- huggingface_hub
- Telethon
- PyMuPDF

## Installation

```bash
cd ai-news-agent
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Environment Variables

The app reads environment variables from the running shell, or you can enter optional tokens in the dashboard Configuration panel. Copy the example file as a local reference if useful:

```bash
cp ai-news-agent/.env.example ai-news-agent/.env
```

Supported optional variables:

```bash
GITHUB_TOKEN=
HUGGINGFACE_TOKEN=
YOUTUBE_API_KEY=
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_NAME=telegram_news_session
```

## Run Locally

```bash
cd ai-news-agent
.venv/bin/streamlit run app.py
```

Then open the URL printed by Streamlit.

## Backend Ingestion Service

The new backend lives in `backend/`. It provides a FastAPI API, PostgreSQL schema, RSS and public Telegram parsers, ingestion worker, and media downloader.

Run the backend stack with Docker Compose:

```bash
docker compose build
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
docker compose up api
```

Then check:

```bash
curl http://localhost:8000/health
```

Run one manual ingestion pass:

```bash
docker compose run --rm worker
```

If your network needs a proxy, export it before running Compose:

```bash
export ALL_PROXY=socks5h://127.0.0.1:10808
```

## Basic Usage

1. Open the dashboard.
2. Choose a time range and source connectors.
3. Click **Run Agent**.
4. Review collected articles and approve useful items.
5. For arXiv articles, click **Prepare Paper Asset** to generate local paper files.

## Project Structure

```text
.
├── README.md
├── ROADMAP.md
├── ai-news-agent/
│   ├── app.py
│   ├── agent.py
│   ├── connectors.py
│   ├── storage.py
│   ├── approved_storage.py
│   ├── paper_fetcher.py
│   ├── paper_extractor.py
│   ├── paper_storage.py
│   ├── research_brief.py
│   ├── ranker.py
│   ├── summarizer.py
│   ├── telegram_connector.py
│   ├── telegram_login.py
│   ├── test_news_agent.py
│   ├── requirements.txt
│   ├── README.md
│   └── PROGRESS.md
└── .env.example
```

## Notes

- Local databases, virtual environments, Telegram sessions, generated paper assets, and `.env` files are ignored by Git.
- Paper briefs are rule-based and should be reviewed before publishing.
