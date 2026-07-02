# AI & Tech News Agent Dashboard

A small Streamlit MVP that collects AI and technology news from public sources,
ranks the articles, stores them in SQLite, and displays them for review.

## Features

- RSS, Hacker News, and arXiv collection
- Keyword scoring and category classification
- SQLite storage with duplicate URL protection
- Streamlit dashboard with review statuses

## Installation

```bash
pip install -r requirements.txt
```

## How to run

```bash
streamlit run app.py
```

## Project structure

```text
app.py
agent.py
connectors.py
storage.py
ranker.py
requirements.txt
README.md
```

## Next steps

- Tune keywords after real-world usage.
- Add scheduling when manual runs are not enough.
