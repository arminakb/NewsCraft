"""SQLite storage for generated paper assets."""

import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = "paper_assets.db"


def _db_path():
    return os.environ.get("PAPER_ASSETS_DB_PATH", DB_PATH)


@contextmanager
def _connect():
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_paper_assets_db():
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arxiv_id TEXT NOT NULL UNIQUE,
                article_id INTEGER,
                title TEXT,
                authors_json TEXT DEFAULT '[]',
                abstract TEXT,
                pdf_url TEXT,
                local_pdf_path TEXT,
                full_text_path TEXT,
                research_brief_path TEXT,
                instagram_brief_path TEXT,
                podcast_brief_path TEXT,
                sections_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'ready'
            )
            """
        )


def _json_value(asset, json_key, plain_key, default):
    if json_key in asset:
        return asset.get(json_key) or default
    return json.dumps(asset.get(plain_key, default))


def save_paper_asset(asset):
    init_paper_assets_db()
    authors_json = _json_value(asset, "authors_json", "authors", [])
    sections_json = _json_value(asset, "sections_json", "sections", {})
    values = (
        asset["arxiv_id"],
        asset.get("article_id"),
        asset.get("title", ""),
        authors_json,
        asset.get("abstract", ""),
        asset.get("pdf_url", ""),
        asset.get("local_pdf_path", ""),
        asset.get("full_text_path", ""),
        asset.get("research_brief_path", ""),
        asset.get("instagram_brief_path", ""),
        asset.get("podcast_brief_path", ""),
        sections_json,
        asset.get("status", "ready"),
    )
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO paper_assets (
                arxiv_id, article_id, title, authors_json, abstract, pdf_url, local_pdf_path,
                full_text_path, research_brief_path, instagram_brief_path, podcast_brief_path,
                sections_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(arxiv_id) DO UPDATE SET
                article_id = COALESCE(excluded.article_id, paper_assets.article_id),
                title = excluded.title,
                authors_json = excluded.authors_json,
                abstract = excluded.abstract,
                pdf_url = excluded.pdf_url,
                local_pdf_path = excluded.local_pdf_path,
                full_text_path = excluded.full_text_path,
                research_brief_path = excluded.research_brief_path,
                instagram_brief_path = excluded.instagram_brief_path,
                podcast_brief_path = excluded.podcast_brief_path,
                sections_json = excluded.sections_json,
                status = excluded.status
            """,
            values,
        )
        return cursor.rowcount


def _row_to_asset(row):
    if row is None:
        return None
    asset = dict(row)
    try:
        asset["authors"] = json.loads(asset.get("authors_json") or "[]")
    except json.JSONDecodeError:
        asset["authors"] = []
    try:
        asset["sections"] = json.loads(asset.get("sections_json") or "{}")
    except json.JSONDecodeError:
        asset["sections"] = {}
    return asset


def get_paper_asset(arxiv_id):
    init_paper_assets_db()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM paper_assets WHERE arxiv_id = ?", (arxiv_id,)).fetchone()
        return _row_to_asset(row)


def list_paper_assets(limit=100):
    init_paper_assets_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM paper_assets ORDER BY datetime(created_at) DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_asset(row) for row in rows]
