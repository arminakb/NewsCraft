"""Backend-owned connector registry."""

from newscraft.connectors.fetchers import (
    fetch_arxiv_ai,
    fetch_github_repositories,
    fetch_hacker_news,
    fetch_huggingface_models,
    fetch_rss_articles,
    fetch_telegram_posts_sync,
    fetch_youtube_videos,
    get_connector_fetchers,
)

__all__ = [
    "fetch_arxiv_ai",
    "fetch_github_repositories",
    "fetch_hacker_news",
    "fetch_huggingface_models",
    "fetch_rss_articles",
    "fetch_telegram_posts_sync",
    "fetch_youtube_videos",
    "get_connector_fetchers",
]
