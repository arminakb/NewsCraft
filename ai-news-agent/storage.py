"""SQLite storage layer."""

import os
import json
import sqlite3
import uuid
from contextlib import contextmanager

from utils import normalize_date_for_storage

DB_PATH = "news.db"
VALID_STATUSES = {"new", "approved", "rejected"}


def _db_path():
    return os.environ.get("NEWS_DB_PATH", DB_PATH)


@contextmanager
def _connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


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
        _ensure_column(conn, "source_type", "TEXT DEFAULT 'rss'")
        _ensure_column(conn, "metrics_json", "TEXT DEFAULT '{}'")
        _ensure_column(conn, "thumbnail_url", "TEXT")
        _ensure_column(conn, "structured_summary_json", "TEXT DEFAULT '{}'")
        _ensure_column(conn, "search_session_id", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                start_date TEXT,
                end_date TEXT,
                selected_sources_json TEXT,
                item_count INTEGER DEFAULT 0,
                notes TEXT
            )
            """
        )


def _ensure_column(conn, name, definition):
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    if name not in columns:
        conn.execute(f"ALTER TABLE articles ADD COLUMN {name} {definition}")


def save_articles(articles):
    if not articles:
        return 0

    with _connect() as conn:
        inserted = 0
        for article in articles:
            values = (
                article.get("source", ""),
                article.get("source_type", "rss"),
                article.get("title", ""),
                article.get("url", ""),
                normalize_date_for_storage(article.get("published_at")),
                article.get("summary", ""),
                article.get("category", "General"),
                int(article.get("score", 0)),
                json.dumps(article.get("metrics", {})),
                article.get("thumbnail_url", ""),
                json.dumps(article.get("structured_summary", {})),
                article.get("search_session_id"),
            )
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO articles
                (source, source_type, title, url, published_at, summary, category, score, metrics_json, thumbnail_url,
                 structured_summary_json, search_session_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            inserted += cursor.rowcount
            if cursor.rowcount == 0 and article.get("search_session_id"):
                conn.execute(
                    """
                    UPDATE articles
                    SET source = ?, source_type = ?, title = ?, published_at = ?, summary = ?, category = ?,
                        score = ?, metrics_json = ?, thumbnail_url = ?, structured_summary_json = ?,
                        search_session_id = ?
                    WHERE url = ?
                    """,
                    (
                        values[0],
                        values[1],
                        values[2],
                        values[4],
                        values[5],
                        values[6],
                        values[7],
                        values[8],
                        values[9],
                        values[10],
                        values[11],
                        values[3],
                    ),
                )
        return inserted


def get_articles(limit=100, start_date=None, end_date=None, category=None, status=None, source_type=None, search_session_id=None):
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
    if source_type and source_type != "All":
        where.append("source_type = ?")
        params.append(source_type)
    if search_session_id and search_session_id != "All":
        where.append("search_session_id = ?")
        params.append(search_session_id)
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT id, source, source_type, title, url, published_at, summary, category, score, status,
                   created_at, metrics_json, thumbnail_url, structured_summary_json, search_session_id
            FROM articles
            {"WHERE " + " AND ".join(where) if where else ""}
            ORDER BY published_at DESC, score DESC, created_at DESC
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
        conn.execute("DELETE FROM search_sessions")


def create_search_session(start_date=None, end_date=None, selected_sources=None, notes=""):
    session_id = uuid.uuid4().hex
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO search_sessions (session_id, start_date, end_date, selected_sources_json, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                normalize_date_for_storage(start_date),
                normalize_date_for_storage(end_date),
                json.dumps(selected_sources or []),
                notes,
            ),
        )
    return session_id


def update_search_session_count(search_session_id, item_count):
    with _connect() as conn:
        conn.execute("UPDATE search_sessions SET item_count = ? WHERE session_id = ?", (item_count, search_session_id))


def get_search_sessions(limit=20):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT session_id, created_at, start_date, end_date, selected_sources_json, item_count, notes
            FROM search_sessions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
