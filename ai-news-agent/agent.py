"""News agent pipeline."""

import logging

from connectors import (
    fetch_arxiv_ai,
    fetch_github_repositories,
    fetch_hacker_news,
    fetch_huggingface_models,
    fetch_rss_articles,
    fetch_youtube_videos,
)
from ranker import classify_and_score
from storage import create_search_session, init_db, save_articles, update_search_session_count
from telegram_connector import fetch_telegram_posts_sync
from utils import clean_token, is_within_date_range, normalize_date_for_storage

DEFAULT_SOURCES = ["rss", "hacker_news", "arxiv"]
SOURCE_LABELS = {
    "rss": "RSS",
    "hacker_news": "Hacker News",
    "arxiv": "arXiv",
    "huggingface": "Hugging Face",
    "github": "GitHub",
    "youtube": "YouTube",
    "telegram": "Telegram",
}


class AgentResult(list):
    def __init__(self, articles, report, search_session_id=None):
        super().__init__(articles)
        self.report = report
        self.search_session_id = search_session_id


def _safe_fetch(fetcher, **kwargs):
    try:
        return fetcher(**kwargs)
    except Exception as exc:
        logging.warning("%s failed: %s", getattr(fetcher, "__name__", "fetcher"), exc)
        return []


def _source_name(article):
    return article.get("source") or SOURCE_LABELS.get(article.get("source_type"), "Unknown")


def _record_source(report, name, raw_count):
    report["sources"][name] = raw_count
    report["source_details"][name] = {
        "raw": raw_count,
        "after_date_filter": 0,
        "after_scoring": 0,
        "saved": 0,
        "skipped_duplicates": 0,
    }


def _record_items(report, fallback_name, items):
    if not items:
        _record_source(report, fallback_name, 0)
        return
    counts = {}
    for item in items:
        counts[_source_name(item) or fallback_name] = counts.get(_source_name(item) or fallback_name, 0) + 1
    for name, count in counts.items():
        _record_source(report, name, count)


def run_news_agent(
    start_date=None,
    end_date=None,
    selected_sources=None,
    github_token=None,
    huggingface_token=None,
    youtube_api_key=None,
    telegram_api_id=None,
    telegram_api_hash=None,
    telegram_session_name=None,
    telegram_channels=None,
):
    init_db()
    github_token = clean_token(github_token)
    huggingface_token = clean_token(huggingface_token)
    youtube_api_key = clean_token(youtube_api_key)
    telegram_api_id = clean_token(telegram_api_id)
    telegram_api_hash = clean_token(telegram_api_hash)
    telegram_session_name = clean_token(telegram_session_name)
    selected_sources = selected_sources or DEFAULT_SOURCES
    search_session_id = create_search_session(start_date, end_date, selected_sources)
    fetched = []
    report = {
        "search_session": search_session_id,
        "selected_sources": selected_sources,
        "sources": {},
        "source_details": {},
        "diagnostics": {},
        "saved": 0,
        "skipped_by_date": 0,
        "skipped_by_score": 0,
        "errors": 0,
    }
    if "rss" in selected_sources:
        rss_diagnostics = {}
        items = _safe_fetch(fetch_rss_articles, start_date=start_date, end_date=end_date, diagnostics=rss_diagnostics)
        report["diagnostics"]["rss"] = rss_diagnostics
        _record_items(report, "RSS feeds", items)
        fetched.extend(items)
    if "hacker_news" in selected_sources:
        hn_diagnostics = {}
        items = _safe_fetch(fetch_hacker_news, limit=30, start_date=start_date, end_date=end_date, diagnostics=hn_diagnostics)
        report["diagnostics"]["hacker_news"] = hn_diagnostics
        _record_items(report, "Hacker News", items)
        fetched.extend(items)
    if "arxiv" in selected_sources:
        arxiv_diagnostics = {}
        items = _safe_fetch(fetch_arxiv_ai, limit=20, start_date=start_date, end_date=end_date, diagnostics=arxiv_diagnostics)
        report["diagnostics"]["arxiv"] = arxiv_diagnostics
        _record_items(report, "arXiv", items)
        fetched.extend(items)
    if "huggingface" in selected_sources:
        items = _safe_fetch(
            fetch_huggingface_models,
            limit=30,
            start_date=start_date,
            end_date=end_date,
            huggingface_token=huggingface_token,
        )
        _record_items(report, "Hugging Face", items)
        fetched.extend(items)
    if "github" in selected_sources:
        github_diagnostics = {}
        items = _safe_fetch(
            fetch_github_repositories,
            limit=30,
            start_date=start_date,
            end_date=end_date,
            github_token=github_token,
            diagnostics=github_diagnostics,
        )
        report["diagnostics"]["github"] = github_diagnostics
        _record_items(report, "GitHub", items)
        fetched.extend(items)
    if "youtube" in selected_sources:
        items = _safe_fetch(
            fetch_youtube_videos,
            limit=30,
            start_date=start_date,
            end_date=end_date,
            youtube_api_key=youtube_api_key,
        )
        _record_items(report, "YouTube", items)
        fetched.extend(items)
    if "telegram" in selected_sources:
        telegram_diagnostics = {}
        items = _safe_fetch(
            fetch_telegram_posts_sync,
            channels=telegram_channels,
            start_datetime=start_date,
            end_datetime=end_date,
            limit_per_channel=20,
            telegram_api_id=telegram_api_id,
            telegram_api_hash=telegram_api_hash,
            telegram_session_name=telegram_session_name,
            diagnostics=telegram_diagnostics,
        )
        report["diagnostics"]["telegram"] = telegram_diagnostics
        _record_items(report, "Telegram Channels", items)
        fetched.extend(items)

    processed = []
    for article in fetched:
        if not article.get("title") or not article.get("url"):
            continue
        source_name = _source_name(article)
        report["source_details"].setdefault(
            source_name,
            {"raw": 0, "after_date_filter": 0, "after_scoring": 0, "saved": 0, "skipped_duplicates": 0},
        )
        article.setdefault("source_type", "rss")
        article.setdefault("connector", article.get("source_type", "rss"))
        article.setdefault("source_group", "")
        article.setdefault("metrics", {})
        article["search_session_id"] = search_session_id
        if (start_date or end_date) and not is_within_date_range(article.get("published_at"), start_date, end_date):
            report["skipped_by_date"] += 1
            continue
        report["source_details"][source_name]["after_date_filter"] += 1
        article["published_at"] = normalize_date_for_storage(article.get("published_at"))
        ranked = classify_and_score(article)
        if ranked["score"] > 0:
            report["source_details"][source_name]["after_scoring"] += 1
            processed.append(ranked)
        else:
            report["skipped_by_score"] += 1

    for source_name in report["source_details"]:
        source_articles = [article for article in processed if _source_name(article) == source_name]
        if not source_articles:
            continue
        saved = save_articles(source_articles)
        report["source_details"][source_name]["saved"] = saved
        report["source_details"][source_name]["skipped_duplicates"] = max(len(source_articles) - saved, 0)
        report["saved"] += saved

    update_search_session_count(search_session_id, len(processed))
    report["skipped_duplicates"] = sum(detail["skipped_duplicates"] for detail in report["source_details"].values())
    return AgentResult(processed, report, search_session_id)
