import sys
from pathlib import Path


LEGACY_DIR = Path(__file__).resolve().parents[2] / "ai-news-agent"
if str(LEGACY_DIR) not in sys.path:
    sys.path.insert(0, str(LEGACY_DIR))


def get_connector_fetchers():
    from newscraft.connectors.public import fetch_public_rss_sources, fetch_public_telegram_channels
    from connectors import (
        fetch_arxiv_ai,
        fetch_github_repositories,
        fetch_hacker_news,
        fetch_huggingface_models,
        fetch_rss_articles,
        fetch_youtube_videos,
    )
    from telegram_connector import fetch_telegram_posts_sync

    return {
        "rss": fetch_rss_articles,
        "hacker_news": fetch_hacker_news,
        "arxiv": fetch_arxiv_ai,
        "github": fetch_github_repositories,
        "huggingface": fetch_huggingface_models,
        "youtube": fetch_youtube_videos,
        "telegram": fetch_telegram_posts_sync,
        "rss_public": fetch_public_rss_sources,
        "telegram_public": fetch_public_telegram_channels,
    }


def classify_and_score(article):
    from ranker import classify_and_score as legacy_classify

    return legacy_classify(article)
