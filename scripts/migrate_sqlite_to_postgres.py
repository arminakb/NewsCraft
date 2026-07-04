import argparse
import json
import sqlite3
from pathlib import Path

from newscraft.db.session import SessionLocal
from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.approved_article_repository import ApprovedArticleRepository


def migrate(db, news_db_path="news.db", approved_db_path="approved_articles.db"):
    summary = {"articles_seen": 0, "articles_inserted": 0, "approved_seen": 0, "approved_inserted": 0}
    article_repo = ArticleRepository(db)
    approved_repo = ApprovedArticleRepository(db)

    for row in _rows(news_db_path, "articles"):
        summary["articles_seen"] += 1
        existing = article_repo._find_existing({"url": row.get("url"), "source": row.get("source"), "external_id": None})
        article = article_repo.upsert(_article(row))
        if not existing and article:
            summary["articles_inserted"] += 1

    for row in _rows(approved_db_path, "approved_articles"):
        summary["approved_seen"] += 1
        article = article_repo.upsert(_article(row))
        before = len(approved_repo.list(limit=100000))
        approved_repo.create_from_article(article, notes=row.get("notes"))
        if len(approved_repo.list(limit=100000)) > before:
            summary["approved_inserted"] += 1

    return summary


def _rows(path, table):
    path = Path(path)
    if not path.exists():
        return []
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            return [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        except sqlite3.Error:
            return []


def _article(row):
    metrics = _json(row.get("metrics_json"))
    structured = _json(row.get("structured_summary_json"))
    return {
        "title": row.get("title") or "",
        "url": row.get("url"),
        "source": row.get("source") or "Unknown",
        "source_type": row.get("source_type"),
        "connector": row.get("connector") or row.get("source_type"),
        "source_group": row.get("source_group"),
        "summary": row.get("summary"),
        "published_at": row.get("published_at"),
        "category": row.get("category"),
        "score": row.get("score") or 0,
        "status": row.get("status") or ("approved" if row.get("approved_at") else "new"),
        "metadata": {"metrics": metrics, "structured_summary": structured},
        "raw_data": row,
    }


def _json(value):
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--news-db", default="news.db")
    parser.add_argument("--approved-db", default="approved_articles.db")
    args = parser.parse_args()

    with SessionLocal() as db:
        summary = migrate(db, args.news_db, args.approved_db)
    print(summary)


if __name__ == "__main__":
    main()
