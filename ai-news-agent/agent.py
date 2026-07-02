"""News agent pipeline."""

import logging

from connectors import fetch_arxiv_ai, fetch_hacker_news, fetch_rss_articles
from ranker import classify_and_score
from storage import init_db, save_articles
from utils import is_within_date_range, normalize_date_for_storage

DEFAULT_SOURCES = ["rss", "hacker_news", "arxiv"]


def _safe_fetch(fetcher, **kwargs):
    try:
        return fetcher(**kwargs)
    except Exception as exc:
        logging.warning("%s failed: %s", getattr(fetcher, "__name__", "fetcher"), exc)
        return []


def run_news_agent(start_date=None, end_date=None, selected_sources=None):
    init_db()
    selected_sources = selected_sources or DEFAULT_SOURCES
    fetched = []
    if "rss" in selected_sources:
        fetched.extend(_safe_fetch(fetch_rss_articles, start_date=start_date, end_date=end_date))
    if "hacker_news" in selected_sources:
        fetched.extend(_safe_fetch(fetch_hacker_news, limit=30, start_date=start_date, end_date=end_date))
    if "arxiv" in selected_sources:
        fetched.extend(_safe_fetch(fetch_arxiv_ai, limit=20, start_date=start_date, end_date=end_date))

    processed = []
    for article in fetched:
        if not article.get("title") or not article.get("url"):
            continue
        article.setdefault("source_type", "rss")
        article.setdefault("metrics", {})
        if (start_date or end_date) and not is_within_date_range(article.get("published_at"), start_date, end_date):
            continue
        article["published_at"] = normalize_date_for_storage(article.get("published_at"))
        ranked = classify_and_score(article)
        if ranked["score"] > 0:
            processed.append(ranked)

    save_articles(processed)
    return processed
