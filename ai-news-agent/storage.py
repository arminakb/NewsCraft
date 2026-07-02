"""SQLite storage layer."""

import os
import sqlite3

from utils import normalize_date_for_storage

DB_PATH = "news.db"
VALID_STATUSES = {"new", "approved", "rejected"}


def _db_path():
    return os.environ.get("NEWS_DB_PATH", DB_PATH)


def _connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                published_at TEXT,
                summary TEXT,
                category TEXT,
                score INTEGER DEFAULT 0,
                status TEXT DEFAULT 'new',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def save_articles(articles):
    if not articles:
        return 0

    with _connect() as conn:
        before = conn.total_changes
        conn.executemany(
            """
            INSERT OR IGNORE INTO articles
            (source, title, url, published_at, summary, category, score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    article.get("source", ""),
                    article.get("title", ""),
                    article.get("url", ""),
                    normalize_date_for_storage(article.get("published_at")),
                    article.get("summary", ""),
                    article.get("category", "General"),
                    int(article.get("score", 0)),
                )
                for article in articles
            ],
        )
        return conn.total_changes - before


def get_articles(limit=100, start_date=None, end_date=None, category=None, status=None):
    where = []
    params = []
    if start_date:
        where.append("date(published_at) >= date(?)")
        params.append(normalize_date_for_storage(start_date))
    if end_date:
        where.append("date(published_at) <= date(?)")
        params.append(normalize_date_for_storage(end_date))
    if category and category != "All":
        where.append("category = ?")
        params.append(category)
    if status and status != "All":
        where.append("status = ?")
        params.append(status)
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, source, title, url, published_at, summary, category, score, status, created_at
            FROM articles
            {"WHERE " + " AND ".join(where) if where else ""}
            ORDER BY published_at DESC, score DESC, created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def update_article_status(article_id, status):
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}")

    with _connect() as conn:
        conn.execute(
            "UPDATE articles SET status = ? WHERE id = ?",
            (status, article_id),
        )


def clear_articles():
    with _connect() as conn:
        conn.execute("DELETE FROM articles")
