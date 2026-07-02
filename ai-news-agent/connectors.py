"""Free public news source connectors."""

import html
import logging
from xml.etree import ElementTree

import feedparser
import requests

from utils import is_within_date_range, normalize_date_for_storage, parse_article_date

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


def _entry_date(entry):
    for key in ("published", "updated", "published_parsed", "updated_parsed"):
        parsed = parse_article_date(entry.get(key))
        if parsed:
            return parsed
    return None


def fetch_rss_articles(start_date=None, end_date=None):
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
                published = _entry_date(entry)
                if not is_within_date_range(published, start_date, end_date):
                    continue
                articles.append(
                    {
                        "source": source,
                        "source_type": "rss",
                        "title": title,
                        "url": link,
                        "published_at": normalize_date_for_storage(published),
                        "summary": _text(entry.get("summary") or entry.get("description")),
                        "category": "General",
                        "score": 0,
                        "metrics": {},
                    }
                )
        except Exception as exc:
            logging.warning("RSS fetch failed for %s: %s", url, exc)
    return articles


def fetch_hacker_news(limit=30, start_date=None, end_date=None):
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
            published = parse_article_date(story.get("time"))
            if not is_within_date_range(published, start_date, end_date):
                continue
            articles.append(
                {
                    "source": "Hacker News",
                    "source_type": "hacker_news",
                    "title": title,
                    "url": url,
                    "published_at": normalize_date_for_storage(published),
                    "summary": _text(story.get("text")),
                    "category": "General",
                    "score": int(story.get("score") or 0),
                    "metrics": {"score": int(story.get("score") or 0)},
                }
            )
        except Exception as exc:
            logging.warning("Hacker News story fetch failed for %s: %s", story_id, exc)
    return articles


def fetch_arxiv_ai(limit=20, start_date=None, end_date=None):
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
        published = parse_article_date(
            entry.findtext("atom:published", default="", namespaces=ns)
            or entry.findtext("atom:updated", default="", namespaces=ns)
        )
        if not is_within_date_range(published, start_date, end_date):
            continue
        articles.append(
            {
                "source": "arXiv",
                "source_type": "arxiv",
                "title": " ".join(title.split()),
                "url": url,
                "published_at": normalize_date_for_storage(published),
                "summary": _text(entry.findtext("atom:summary", default="", namespaces=ns)),
                "category": "AI",
                "score": 0,
                "metrics": {},
            }
        )
    return articles
