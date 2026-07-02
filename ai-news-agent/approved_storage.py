"""Separate SQLite storage for approved articles."""

import json
import os
import sqlite3
from contextlib import contextmanager

from utils import normalize_date_for_storage

APPROVED_DB_PATH = "approved_articles.db"


def _db_path():
    return os.environ.get("APPROVED_DB_PATH", APPROVED_DB_PATH)


@contextmanager
def _connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_approved_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS approved_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_article_id INTEGER,
                source TEXT,
                source_type TEXT,
                title TEXT,
                url TEXT UNIQUE,
                published_at TEXT,
                summary TEXT,
                structured_summary_json TEXT DEFAULT '{}',
                category TEXT,
                score INTEGER DEFAULT 0,
                metrics_json TEXT DEFAULT '{}',
                thumbnail_url TEXT,
                approved_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'approved',
                notes TEXT
            )
            """
        )
        _ensure_column(conn, "connector", "TEXT")
        _ensure_column(conn, "source_group", "TEXT")


def _ensure_column(conn, name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(approved_articles)")}
    if name not in columns:
        conn.execute(f"ALTER TABLE approved_articles ADD COLUMN {name} {definition}")


def save_approved_article(article):
    init_approved_db()
    with _connect() as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO approved_articles
            (original_article_id, source, source_type, title, url, published_at, summary, structured_summary_json,
             category, score, metrics_json, thumbnail_url, notes, connector, source_group)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.get("id"),
                article.get("source", ""),
                article.get("source_type", ""),
                article.get("title", ""),
                article.get("url", ""),
                normalize_date_for_storage(article.get("published_at")),
                article.get("summary", ""),
                json.dumps(article.get("structured_summary", {})),
                article.get("category", "General"),
                int(article.get("score", 0)),
                json.dumps(article.get("metrics", {})),
                article.get("thumbnail_url", ""),
                article.get("notes", ""),
                article.get("connector", article.get("source_type", "")),
                article.get("source_group", ""),
            ),
        )
        return conn.total_changes - before


def get_approved_articles(limit=100, category=None, source_type=None):
    init_approved_db()
    where = []
    params = []
    if category and category != "All":
        where.append("category = ?")
        params.append(category)
    if source_type and source_type != "All":
        where.append("source_type = ?")
        params.append(source_type)
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, original_article_id, source, source_type, title, url, published_at, summary,
                   structured_summary_json, category, score, metrics_json, thumbnail_url, approved_at, status, notes,
                   connector, source_group
            FROM approved_articles
            {"WHERE " + " AND ".join(where) if where else ""}
            ORDER BY approved_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    articles = []
    for row in rows:
        article = dict(row)
        try:
            article["metrics"] = json.loads(article.pop("metrics_json") or "{}")
        except json.JSONDecodeError:
            article["metrics"] = {}
        try:
            article["structured_summary"] = json.loads(article.pop("structured_summary_json") or "{}")
        except json.JSONDecodeError:
            article["structured_summary"] = {}
        articles.append(article)
    return articles


def delete_approved_article(approved_id):
    init_approved_db()
    with _connect() as conn:
        conn.execute("DELETE FROM approved_articles WHERE id = ?", (approved_id,))
