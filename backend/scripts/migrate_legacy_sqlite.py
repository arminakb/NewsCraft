from __future__ import annotations

import sqlite3
from pathlib import Path


def read_legacy_articles(db_path: Path):
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("select title, url, source, summary from articles").fetchall()
    return [dict(row) for row in rows]
