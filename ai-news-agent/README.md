# AI & Tech News Agent Dashboard

A small Streamlit MVP that collects AI and technology news from public sources,
ranks the articles, stores them in SQLite, and displays them for review.

## Features

- RSS, Hacker News, and arXiv collection
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

## Cleaning Old Data

If old articles still appear, the existing `news.db` may contain old or badly formatted dates from the previous version. Use the **Clear Old Database** button in the dashboard, or delete `news.db` manually, then run the agent again.

## Project structure

```text
app.py
agent.py
connectors.py
storage.py
ranker.py
utils.py
requirements.txt
README.md
```

## Next steps

- Tune keywords after real-world usage.
- Add scheduling when manual runs are not enough.
