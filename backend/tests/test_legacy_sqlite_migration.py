import sqlite3
from pathlib import Path


def test_legacy_sqlite_migration_reads_basic_article_rows(tmp_path):
    from scripts.migrate_legacy_sqlite import read_legacy_articles

    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("create table articles (title text, url text, source text, summary text)")
        conn.execute(
            "insert into articles (title, url, source, summary) values (?, ?, ?, ?)",
            ("Legacy story", "https://example.com/legacy", "Legacy", "Summary"),
        )

    rows = list(read_legacy_articles(Path(db_path)))

    assert rows == [
        {
            "title": "Legacy story",
            "url": "https://example.com/legacy",
            "source": "Legacy",
            "summary": "Summary",
        }
    ]
