"""Free public news source connectors."""

import html
import logging
from datetime import datetime, timezone
from xml.etree import ElementTree

import feedparser
import requests
from dateutil import parser as date_parser

RSS_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed/",
]

HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
ARXIV_URL = "http://export.arxiv.org/api/query"
TIMEOUT = 15


def _text(value):
    return html.unescape(str(value or "")).strip()


def _date(value):
    if not value:
        return ""
    try:
        return date_parser.parse(value).isoformat()
    except (TypeError, ValueError, OverflowError):
        return _text(value)


def fetch_rss_articles():
    articles = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            source = _text(feed.feed.get("title")) or url
            for entry in feed.entries:
                title = _text(entry.get("title"))
                link = _text(entry.get("link"))
                if not title or not link:
                    continue
                articles.append(
                    {
                        "source": source,
                        "title": title,
                        "url": link,
                        "published_at": _date(entry.get("published") or entry.get("updated")),
                        "summary": _text(entry.get("summary") or entry.get("description")),
                        "category": "General",
                        "score": 0,
                    }
                )
        except Exception as exc:
            logging.warning("RSS fetch failed for %s: %s", url, exc)
    return articles


def fetch_hacker_news(limit=30):
    try:
        response = requests.get(HN_TOP_URL, timeout=TIMEOUT)
        response.raise_for_status()
        story_ids = response.json()[:limit]
    except Exception as exc:
        logging.warning("Hacker News top stories fetch failed: %s", exc)
        return []

    articles = []
    for story_id in story_ids:
        try:
            response = requests.get(HN_ITEM_URL.format(id=story_id), timeout=TIMEOUT)
            response.raise_for_status()
            story = response.json() or {}
            title = _text(story.get("title"))
            url = _text(story.get("url"))
            if not title or not url:
                continue
            published = story.get("time")
            articles.append(
                {
                    "source": "Hacker News",
                    "title": title,
                    "url": url,
                    "published_at": datetime.fromtimestamp(published, timezone.utc).isoformat()
                    if published
                    else "",
                    "summary": _text(story.get("text")),
                    "category": "General",
                    "score": int(story.get("score") or 0),
                }
            )
        except Exception as exc:
            logging.warning("Hacker News story fetch failed for %s: %s", story_id, exc)
    return articles


def fetch_arxiv_ai(limit=20):
    params = {
        "search_query": "cat:cs.AI OR cat:cs.LG OR cat:cs.CL",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": limit,
    }
    try:
        response = requests.get(ARXIV_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
    except Exception as exc:
        logging.warning("arXiv fetch failed: %s", exc)
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    articles = []
    for entry in root.findall("atom:entry", ns):
        title = _text(entry.findtext("atom:title", default="", namespaces=ns)).replace("\n", " ")
        url = _text(entry.findtext("atom:id", default="", namespaces=ns))
        if not title or not url:
            continue
        articles.append(
            {
                "source": "arXiv",
                "title": " ".join(title.split()),
                "url": url,
                "published_at": _date(entry.findtext("atom:published", default="", namespaces=ns)),
                "summary": _text(entry.findtext("atom:summary", default="", namespaces=ns)),
                "category": "AI",
                "score": 0,
            }
        )
    return articles
