# AI & Tech News Agent Dashboard

A small Streamlit MVP that collects AI and technology news from public sources,
ranks the articles, stores them in SQLite, and displays them for review.

## Features

- RSS feed, Hacker News, and arXiv collection
- Hugging Face model, GitHub repository, and YouTube RSS discovery
- Telegram channel ingestion through a local Telethon user session
- Keyword scoring and category classification
- SQLite storage with duplicate URL protection
- Streamlit dashboard with review statuses
- Latest/recent time ranges, sorting, and display filtering
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

Use **Time range** to run the agent for Last 24 hours, Last 3 days, Last 7 days, or a custom Start Date/End Date. Preset ranges use datetime filtering, so Last 24 hours is not treated as a whole calendar day.

Use **Sort by** in Display Filters to sort by Latest first, Highest score, Most popular, or Source. Cards show relative publish time such as `Published 2 hours ago`.

## Selecting Sources

Use **Collection Controls** to choose which sources the agent should run. Each run creates a new search session, and the dashboard shows the current session by default so old results do not crowd the new run.

Source labels are split into:

- `source`: the publication or API, such as OpenAI News, Hacker News, arXiv, or GitHub.
- `source_type`: the connector type, such as RSS Feed, Hacker News API, arXiv API, or GitHub API.
- `source_group`: Company News, Startup News, AI Industry News, Developer Trends, Research, Model Trends, or Video.

RSS is a connector type, not a single publisher.

## RSS News Sources

Configured RSS feeds include OpenAI News, Anthropic News, NVIDIA AI Blog, Google DeepMind Blog, Microsoft AI Blog, Hugging Face Blog, TechCrunch AI, TechCrunch Startups, VentureBeat AI, The Verge AI, MIT Technology Review AI, and Y Combinator Blog. Broken feeds are skipped and reported without crashing collection.

## Hacker News and arXiv

Hacker News now checks top, new, and best story lists, keeps URL stories with developer/startup/AI relevance, and records HN score and comments. arXiv now searches AI, ML, NLP, CV, and statistical ML categories, stores papers as Research, and keeps author names when available.

## Hugging Face Models

The Hugging Face connector discovers public models, stores likes/downloads as metrics, and creates a concise structured summary from meaningful tags and metadata. Noisy tags such as framework/storage tags, license tags, arXiv IDs, and language codes are hidden from the main card. A Hugging Face token is optional and can be entered in Configuration or provided with `HUGGINGFACE_TOKEN`.

## GitHub Repository Discovery

The GitHub connector searches AI/ML/LLM/agent/RAG topics and keywords, tries pushed-date and created-date queries, falls back to popular AI repositories, and stores stars, forks, open issues, language, topics, and concise structured summaries. It attempts to fetch README snippets safely, but raw README text stays hidden in card details. The collection report includes token configured status, HTTP status, rate-limit remaining, queries used, raw items, date-filtered items, scored items, and returned count. `GITHUB_TOKEN` is optional but recommended for better GitHub API limits.

## YouTube Video Sources

YouTube collection uses RSS channel feeds from `config.py`, not the YouTube Data API. Replace `CHANNEL_ID_HERE` in `YOUTUBE_CHANNEL_FEEDS` with real channel IDs. Search-based YouTube Data API support can be added later if needed.

## Telegram Channel Connector

Telegram ingestion uses Telethon with a local Telegram user session. It is intended for trusted public channels or channels your logged-in account is allowed to access. It does not use the Telegram Bot API for public-channel ingestion.

Install dependencies, then create the local session once:

```bash
python telegram_login.py
```

Then run the dashboard, open **Configuration**, enter Telegram API ID, Telegram API Hash, Session Name, and one channel username per line. Select **Telegram Channels** in Collection Controls and run the agent.

Supported environment variables:

```bash
export TELEGRAM_API_ID="your_api_id"
export TELEGRAM_API_HASH="your_api_hash"
export TELEGRAM_SESSION_NAME="telegram_news_session"
```

Security notes:

- Do not commit `.session` files.
- Do not share your API hash.
- Do not scrape private channels without permission.
- Keep the channel list curated for quality.

## Configuration Popup

Open **Configuration** near the dashboard header to enter optional API credentials and run diagnostics. Manually entered tokens are stripped of leading/trailing whitespace and stored only in Streamlit session state. They are not saved to SQLite, printed, or committed. If the installed Streamlit version does not support popovers, the app uses a compact expander fallback.

## Card Actions and Summaries

Collected cards show one review action: **Approve**. Approving saves a deduplicated copy into `approved_articles.db` and marks the collected row as approved. Reject and reset actions were removed to keep review fast.

GitHub and Hugging Face cards use this concise structure: What it is, Why it matters, Best use cases, and Key signals. Raw summaries, full metadata, and debug details are collapsed under **Raw details**.

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
export TELEGRAM_API_ID="your_telegram_api_id"
export TELEGRAM_API_HASH="your_telegram_api_hash"
export TELEGRAM_SESSION_NAME="telegram_news_session"
```

PowerShell:

```powershell
$env:GITHUB_TOKEN="your_github_token"
$env:HUGGINGFACE_TOKEN="your_huggingface_token"
$env:YOUTUBE_API_KEY="your_youtube_api_key"
$env:TELEGRAM_API_ID="your_telegram_api_id"
$env:TELEGRAM_API_HASH="your_telegram_api_hash"
$env:TELEGRAM_SESSION_NAME="telegram_news_session"
```

## Cleaning Old Data

If old articles still appear, the existing `news.db` may contain old or badly formatted dates from a previous version. Use **Clear Results Database** in the dashboard, or delete `news.db` manually, then run the agent again.

## Troubleshooting GitHub and Hugging Face

Open **Configuration > Debug** and run the GitHub, Hugging Face, Hacker News, arXiv, or Telegram connector tests. The diagnostics show token status, safe HTTP/status details, per-query/per-feed counts, session status, and item counts without exposing token values.

Common causes of empty results:

- Token was entered in a different browser session; enter it again in Configuration or use an environment variable.
- GitHub rate limit, 401, 403, or query validation errors.
- Date range is too narrow; connectors fall back to popular/recent results where useful.
- Hugging Face metadata such as `last_modified`, likes, or downloads is missing.
- Display filters hide results; use Category `All` and Status `All`.
- Old database schema or old rows; use **Clear Results Database**.
- Telegram session is missing; run `python telegram_login.py` with the same session name.

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
summarizer.py
telegram_connector.py
telegram_login.py
utils.py
requirements.txt
README.md
```

## Next steps

- Tune keywords after real-world usage.
- Add scheduling when manual runs are not enough.
