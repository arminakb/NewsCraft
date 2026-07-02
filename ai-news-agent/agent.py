"""News agent pipeline."""

import logging

from connectors import fetch_arxiv_ai, fetch_hacker_news, fetch_rss_articles
from ranker import classify_and_score
from storage import init_db, save_articles


def _safe_fetch(fetcher):
    try:
        return fetcher()
    except Exception as exc:
        logging.warning("%s failed: %s", getattr(fetcher, "__name__", "fetcher"), exc)
        return []


def run_news_agent():
    init_db()
    fetched = []
    for fetcher in (fetch_rss_articles, fetch_hacker_news, fetch_arxiv_ai):
        fetched.extend(_safe_fetch(fetcher))

    processed = []
    for article in fetched:
        if not article.get("title") or not article.get("url"):
            continue
        ranked = classify_and_score(article)
        if ranked["score"] > 0:
            processed.append(ranked)

    save_articles(processed)
    return processed
