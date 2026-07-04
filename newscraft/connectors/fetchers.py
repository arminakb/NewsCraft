"""Backend-owned news source fetchers."""

import asyncio
import base64
import html
import logging
import os
import re
from datetime import date, datetime, timezone
from time import struct_time
from urllib.parse import urlparse
from xml.etree import ElementTree

import feedparser
import requests
from dateutil import parser as date_parser
from huggingface_hub import HfApi

HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_NEW_URL = "https://hacker-news.firebaseio.com/v0/newstories.json"
HN_BEST_URL = "https://hacker-news.firebaseio.com/v0/beststories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
ARXIV_URL = "http://export.arxiv.org/api/query"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
TIMEOUT = 15
GITHUB_MIN_STARS = 20

RSS_FEEDS = [
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "source_group": "company_news"},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/news/rss.xml", "source_group": "company_news"},
    {"name": "NVIDIA AI Blog", "url": "https://developer.nvidia.com/blog/category/artificial-intelligence/feed/", "source_group": "company_news"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/discover/blog/rss.xml", "source_group": "company_news"},
    {"name": "Microsoft AI Blog", "url": "https://blogs.microsoft.com/ai/feed/", "source_group": "company_news"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "source_group": "company_news"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "source_group": "startup_news"},
    {"name": "TechCrunch Startups", "url": "https://techcrunch.com/category/startups/feed/", "source_group": "startup_news"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "source_group": "ai_industry_news"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "source_group": "ai_industry_news"},
    {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed/", "source_group": "ai_industry_news"},
    {"name": "Y Combinator Blog", "url": "https://www.ycombinator.com/blog/rss", "source_group": "startup_news"},
]

YOUTUBE_CHANNEL_FEEDS = []
TELEGRAM_CHANNELS = []
HF_TAGS = {"text-generation", "image-to-text", "text-to-image", "automatic-speech-recognition", "text-to-video", "multimodal", "agent", "llm"}
USEFUL_TAGS = HF_TAGS | {"speech", "agents", "rag", "reasoning", "coding", "vision", "robotics", "embedding", "embeddings", "reranker", "audio", "computer-vision", "conversational", "chat", "machine-learning", "generative-ai", "artificial-intelligence"}
NOISY_TAGS = {"safetensors", "transformers", "pytorch", "tensorflow", "endpoints_compatible", "eval-results", "onnx"}
NOISY_PREFIXES = ("license:", "arxiv:", "region:", "base_model:", "dataset:")
HN_KEYWORDS = {"ai", "artificial intelligence", "openai", "anthropic", "llm", "machine learning", "startup", "developer", "programming", "software", "github", "api", "security", "nvidia", "agent", "database"}
GITHUB_QUERIES = [
    "topic:artificial-intelligence",
    "topic:machine-learning",
    "topic:llm",
    "topic:agents",
    "topic:rag",
    "topic:ai",
    "topic:generative-ai",
    "topic:artificial-intelligence created:{date_range}",
    "topic:llm created:{date_range}",
    "topic:agents created:{date_range}",
    "topic:rag created:{date_range}",
    '"ai agent"',
    '"llm agent"',
    '"generative ai"',
]
GITHUB_FALLBACK_QUERIES = [
    "topic:artificial-intelligence",
    "topic:machine-learning",
    "topic:llm",
    "topic:agents",
    "topic:rag",
    "topic:generative-ai",
    "ai agent",
    "llm agent",
    "rag framework",
    "multimodal ai",
    "generative ai",
]

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError, RPCError, SessionPasswordNeededError
except ImportError:  # pragma: no cover
    TelegramClient = None
    FloodWaitError = RPCError = SessionPasswordNeededError = Exception


def clean_token(value):
    if not value:
        return None
    value = str(value).strip()
    return value or None


def redact_sensitive_text(value):
    text = str(value or "")
    text = re.sub(r"(github_pat_|ghp_|hf_)[A-Za-z0-9_]+", "[redacted-token]", text)
    return re.sub(r"Bearer\s+[^'\"\s]+", "Bearer [redacted-token]", text)


def parse_article_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, struct_time) or (isinstance(value, tuple) and len(value) >= 6):
        return datetime(*value[:6])
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        return date_parser.parse(str(value)).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def is_within_date_range(date_value, start_date=None, end_date=None):
    parsed = parse_article_date(date_value)
    if parsed is None:
        return start_date is None and end_date is None
    start = parse_article_date(start_date) if start_date else None
    end = parse_article_date(end_date) if end_date else None
    if isinstance(start_date, datetime) or isinstance(end_date, datetime):
        return not ((start and parsed < start) or (end and parsed > end))
    article_date = parsed.date()
    return not ((start and article_date < start.date()) or (end and article_date > end.date()))


def normalize_date_for_storage(date_value):
    parsed = parse_article_date(date_value)
    return parsed.isoformat(timespec="seconds") if parsed else ""


def truncate_text(text, max_chars):
    text = " ".join(str(text or "").split())
    return text if len(text) <= max_chars else text[: max_chars - 3].rstrip() + "..."


def filter_useful_tags(tags, source_type):
    useful = []
    for tag in tags or []:
        tag = str(tag).strip().lower()
        if not tag or tag in useful or tag in NOISY_TAGS or tag.startswith(NOISY_PREFIXES) or len(tag) <= 2:
            continue
        if source_type == "huggingface" and (tag in USEFUL_TAGS or any(word in tag for word in ("agent", "rag", "vision", "audio", "speech", "coding"))):
            useful.append(tag)
        elif source_type == "github" and (tag in USEFUL_TAGS or any(word in tag for word in ("agent", "rag", "llm", "ai"))):
            useful.append(tag)
        if len(useful) >= 5:
            break
    return useful


def _text(value):
    return html.unescape(str(value or "")).strip()


def _entry_date(entry):
    for key in ("published", "updated", "published_parsed", "updated_parsed"):
        parsed = parse_article_date(entry.get(key))
        if parsed:
            return parsed
    return None


def _number(value):
    return f"{int(value or 0):,}"


def _use_cases(tags, default):
    tags = set(tags or [])
    cases = []
    if tags & {"text-generation", "conversational", "chat", "llm"}:
        cases.extend(["Chatbot experiments", "Text generation"])
    if tags & {"agent", "agents"}:
        cases.append("Agentic workflows")
    if "rag" in tags:
        cases.append("RAG applications")
    if tags & {"text-to-image", "vision", "computer-vision", "image-to-text"}:
        cases.append("Vision or image workflows")
    if tags & {"audio", "speech", "automatic-speech-recognition"}:
        cases.append("Speech or audio workflows")
    return (cases or default)[:3]


def build_huggingface_structured_summary(model_data):
    tags = filter_useful_tags(model_data.get("tags", []), "huggingface")
    task = model_data.get("pipeline_tag") or (tags[0] if tags else "AI model")
    signals = []
    if model_data.get("likes"):
        signals.append(f"{_number(model_data['likes'])} likes")
    if model_data.get("downloads"):
        signals.append(f"{_number(model_data['downloads'])} downloads")
    if model_data.get("last_modified"):
        signals.append("Recently modified")
    if task:
        signals.append(f"Task: {task}")
    if tags:
        signals.append("Tags: " + ", ".join(tags[:3]))
    return {
        "what_it_is": truncate_text(model_data.get("description") or f"A {task} model hosted on Hugging Face.", 180),
        "why_it_matters": "It has useful community or freshness signals, making it worth checking for AI experiments.",
        "best_use_cases": _use_cases(tags + [task], ["Model evaluation", "AI prototyping"]),
        "key_signals": signals[:4],
        "visible_tags": tags[:5],
    }


def build_github_structured_summary(repo_data):
    topics = filter_useful_tags(repo_data.get("topics", []), "github")
    signals = []
    if repo_data.get("stars"):
        signals.append(f"{_number(repo_data['stars'])} stars")
    if repo_data.get("forks"):
        signals.append(f"{_number(repo_data['forks'])} forks")
    if repo_data.get("published_at"):
        signals.append("Recently pushed")
    if topics:
        signals.append("Topics: " + ", ".join(topics[:3]))
    if repo_data.get("language"):
        signals.append(repo_data["language"])
    return {
        "what_it_is": truncate_text(repo_data.get("description") or repo_data.get("readme_snippet") or "An AI-related repository worth reviewing.", 180),
        "why_it_matters": "It has GitHub traction, relevant AI topics, or recent activity, suggesting active developer interest.",
        "best_use_cases": _use_cases(topics, ["AI development", "Developer tooling", "Automation prototypes"]),
        "key_signals": signals[:4],
        "visible_tags": topics[:5],
        "last_modified": normalize_date_for_storage(repo_data.get("published_at")),
    }


def fetch_rss_articles(start_date=None, end_date=None, diagnostics=None):
    articles = []
    for feed_config in RSS_FEEDS:
        url = feed_config["url"] if isinstance(feed_config, dict) else feed_config
        configured_name = feed_config.get("name", url) if isinstance(feed_config, dict) else ""
        source_group = feed_config.get("source_group", "ai_industry_news") if isinstance(feed_config, dict) else "ai_industry_news"
        raw_count = kept_count = 0
        try:
            feed = feedparser.parse(url)
            source = configured_name or _text(feed.feed.get("title")) or url
            raw_count = len(feed.entries)
            for entry in feed.entries:
                title = _text(entry.get("title"))
                link = _text(entry.get("link"))
                if not title or not link:
                    continue
                published = _entry_date(entry)
                if not is_within_date_range(published, start_date, end_date):
                    continue
                articles.append({"source": source, "source_type": "rss", "connector": "rss", "source_group": source_group, "title": title, "url": link, "published_at": normalize_date_for_storage(published), "summary": _text(entry.get("summary") or entry.get("description")), "category": "General", "score": 0, "metrics": {}})
                kept_count += 1
        except Exception as exc:
            logging.warning("RSS fetch failed for %s: %s", url, exc)
            if diagnostics is not None:
                diagnostics.setdefault("failed_feeds", []).append({"source": configured_name or url, "url": url, "error": redact_sensitive_text(exc)})
        if diagnostics is not None:
            diagnostics.setdefault("feeds", {})[configured_name or url] = {"raw": raw_count, "returned": kept_count, "source_group": source_group}
    return articles


def fetch_youtube_videos(start_date=None, end_date=None, limit=30, youtube_api_key=None, channel_feeds=None):
    articles = []
    for feed_config in channel_feeds or YOUTUBE_CHANNEL_FEEDS:
        url = feed_config["url"]
        if "channel_id=" in url and url.rsplit("channel_id=", 1)[-1].strip().upper().endswith("_HERE"):
            logging.warning("Skipping YouTube placeholder channel feed for %s", feed_config["name"])
            continue
        try:
            entries = feedparser.parse(url).entries
        except Exception as exc:
            logging.warning("YouTube feed failed for %s: %s", feed_config["name"], exc)
            continue
        for entry in entries:
            title = _text(entry.get("title"))
            link = _text(entry.get("link"))
            if not title or not link:
                continue
            published = _entry_date(entry)
            if not is_within_date_range(published, start_date, end_date):
                continue
            articles.append({"source": f"YouTube - {feed_config['name']}", "source_type": "youtube", "connector": "youtube", "source_group": "video", "title": title, "url": link, "published_at": normalize_date_for_storage(published), "summary": _text(entry.get("summary") or entry.get("description")), "category": "Video", "score": 0, "metrics": {"channel": feed_config["name"]}})
            if len(articles) >= limit:
                return articles
    return articles


def _hn_relevant(story):
    text = f"{story.get('title', '')} {story.get('text', '')}".lower()
    return int(story.get("score") or 0) >= 20 or any(keyword in text for keyword in HN_KEYWORDS)


def fetch_hacker_news(limit=30, start_date=None, end_date=None, diagnostics=None):
    story_ids = []
    for name, url in (("topstories", HN_TOP_URL), ("newstories", HN_NEW_URL), ("beststories", HN_BEST_URL)):
        try:
            response = requests.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            ids = response.json()[: max(limit, 30)]
            story_ids.extend(ids)
            if diagnostics is not None:
                diagnostics.setdefault("lists", {})[name] = len(ids)
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.setdefault("errors", []).append(f"{name}: {redact_sensitive_text(exc)}")
    story_ids = list(dict.fromkeys(story_ids))
    if diagnostics is not None:
        diagnostics["raw_ids"] = len(story_ids)

    articles = []
    loaded = with_url = after_date = after_score = 0
    for story_id in story_ids:
        try:
            response = requests.get(HN_ITEM_URL.format(id=story_id), timeout=TIMEOUT)
            response.raise_for_status()
            story = response.json() or {}
            loaded += 1
            title = _text(story.get("title"))
            url = _text(story.get("url"))
            if not title or not url:
                continue
            with_url += 1
            published = parse_article_date(story.get("time"))
            if not is_within_date_range(published, start_date, end_date):
                continue
            after_date += 1
            if not _hn_relevant(story):
                continue
            after_score += 1
            hn_score = int(story.get("score") or 0)
            articles.append({"source": "Hacker News", "source_type": "hacker_news", "connector": "hacker_news", "source_group": "developer_trends", "title": title, "url": url, "published_at": normalize_date_for_storage(published), "summary": _text(story.get("text")), "category": "General", "score": hn_score, "metrics": {"hn_score": hn_score, "comments": int(story.get("descendants") or 0)}})
            if len(articles) >= limit:
                break
        except Exception as exc:
            if diagnostics is not None:
                diagnostics.setdefault("errors", []).append(f"item {story_id}: {redact_sensitive_text(exc)}")
    if diagnostics is not None:
        diagnostics.update({"loaded": loaded, "with_url": with_url, "after_date_filter": after_date, "after_scoring": after_score, "returned": len(articles)})
    return articles


def fetch_arxiv_ai(limit=20, start_date=None, end_date=None, diagnostics=None):
    params = {"search_query": "(cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:stat.ML)", "sortBy": "submittedDate", "sortOrder": "descending", "start": 0, "max_results": limit}
    try:
        response = requests.get(ARXIV_URL, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
    except Exception as exc:
        if diagnostics is not None:
            diagnostics.setdefault("errors", []).append(redact_sensitive_text(exc))
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall("atom:entry", ns)
    if diagnostics is not None:
        diagnostics["raw_entries"] = len(entries)
    articles = []
    after_date = 0
    for entry in entries:
        title = _text(entry.findtext("atom:title", default="", namespaces=ns)).replace("\n", " ")
        url = _text(entry.findtext("atom:id", default="", namespaces=ns))
        if not title or not url:
            continue
        published = parse_article_date(entry.findtext("atom:published", default="", namespaces=ns) or entry.findtext("atom:updated", default="", namespaces=ns))
        if not is_within_date_range(published, start_date, end_date):
            continue
        after_date += 1
        authors = [_text(author.findtext("atom:name", default="", namespaces=ns)) for author in entry.findall("atom:author", ns)]
        articles.append({"source": "arXiv", "source_type": "arxiv", "connector": "arxiv", "source_group": "research", "title": " ".join(title.split()), "url": url, "published_at": normalize_date_for_storage(published), "summary": _text(entry.findtext("atom:summary", default="", namespaces=ns)), "category": "Research", "score": 0, "metrics": {"authors": [author for author in authors if author][:5]}})
    if diagnostics is not None:
        diagnostics.update({"after_date_filter": after_date, "returned": len(articles)})
    return articles


def _hf_score(model, tags):
    return int(getattr(model, "likes", 0) or 0) + int(getattr(model, "downloads", 0) or 0) // 100 + sum(3 for tag in tags if tag in HF_TAGS)


def fetch_huggingface_models(start_date=None, end_date=None, limit=30, huggingface_token=None):
    huggingface_token = clean_token(huggingface_token)
    try:
        models = list((HfApi(token=huggingface_token) if huggingface_token else HfApi()).list_models(sort="likes", limit=limit * 3, full=True))
    except Exception as exc:
        logging.warning("Hugging Face fetch failed: %s", redact_sensitive_text(exc))
        return []

    articles = []
    for model in models:
        model_id = _text(getattr(model, "modelId", ""))
        if not model_id:
            continue
        published = parse_article_date(getattr(model, "last_modified", None))
        if published and not is_within_date_range(published, start_date, end_date):
            continue
        if (start_date or end_date) and not published:
            continue
        tags = [str(tag).lower() for tag in (getattr(model, "tags", None) or [])]
        useful_tags = filter_useful_tags(tags, "huggingface")
        likes = int(getattr(model, "likes", 0) or 0)
        downloads = int(getattr(model, "downloads", 0) or 0)
        pipeline_tag = getattr(model, "pipeline_tag", "") if isinstance(getattr(model, "pipeline_tag", ""), str) else ""
        structured_summary = build_huggingface_structured_summary({"model_id": model_id, "pipeline_tag": pipeline_tag, "tags": tags, "likes": likes, "downloads": downloads, "last_modified": published})
        articles.append({"source": "Hugging Face", "source_type": "huggingface", "connector": "huggingface", "source_group": "model_trends", "title": model_id, "url": f"https://huggingface.co/{model_id}", "published_at": normalize_date_for_storage(published), "summary": ", ".join(useful_tags), "category": "Model", "score": _hf_score(model, tags), "metrics": {"likes": likes, "downloads": downloads, "task": pipeline_tag or "", "useful_tags": useful_tags}, "structured_summary": structured_summary})
        if len(articles) >= limit:
            break
    if not articles and (start_date or end_date):
        return fetch_huggingface_models(limit=limit, huggingface_token=huggingface_token)
    return articles


def _github_query(base_query, start_date, end_date):
    parts = [base_query]
    if "{date_range}" in base_query and not (start_date and end_date):
        return base_query.split(" created:")[0]
    if start_date and end_date:
        date_range = f"{parse_article_date(start_date).date()}..{parse_article_date(end_date).date()}"
        if "{date_range}" in base_query:
            return base_query.format(date_range=date_range)
        parts.append(f"pushed:{date_range}")
    return " ".join(parts)


def _github_score(repo):
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    topics = [str(topic).lower() for topic in repo.get("topics") or []]
    return stars + forks * 2 + sum(5 for topic in topics if topic in {"llm", "agents", "rag", "generative-ai", "machine-learning"}) + (5 if repo.get("description") else 0)


def _github_is_relevant(repo, use_date):
    stars = int(repo.get("stargazers_count") or 0)
    text = f"{repo.get('full_name', '')} {repo.get('description', '')} {' '.join(repo.get('topics') or [])}".lower()
    return stars >= GITHUB_MIN_STARS or (use_date and stars >= 5) or any(term in text for term in ("ai", "llm", "agent", "rag", "machine-learning", "generative"))


def _github_readme_snippet(full_name, headers):
    try:
        response = requests.get(f"https://api.github.com/repos/{full_name}/readme", headers=headers, timeout=TIMEOUT)
        if not response.ok:
            return ""
        return base64.b64decode(response.json().get("content", "")).decode("utf-8", errors="ignore")[:600]
    except Exception:
        return ""


def fetch_github_repositories(start_date=None, end_date=None, limit=30, github_token=None, diagnostics=None):
    github_token = clean_token(github_token)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    if diagnostics is not None:
        diagnostics.update({"token_configured": bool(github_token), "queries": [], "raw_items": 0, "after_date_filter": 0, "after_scoring": 0})

    articles = []
    seen = set()
    for query, use_date in [(q, True) for q in GITHUB_QUERIES] + [(q, False) for q in GITHUB_FALLBACK_QUERIES]:
        query_info = {"query": query, "used_date_filter": use_date, "http_status": None, "rate_limit_remaining": None, "raw": 0, "kept": 0, "error": None}
        try:
            full_query = _github_query(query, start_date, end_date) if use_date else query
            query_info["query"] = full_query
            response = requests.get(GITHUB_SEARCH_URL, params={"q": full_query, "sort": "stars", "order": "desc", "per_page": limit}, headers=headers, timeout=TIMEOUT)
            query_info["http_status"] = response.status_code
            query_info["rate_limit_remaining"] = response.headers.get("X-RateLimit-Remaining")
            response.raise_for_status()
            repos = response.json().get("items", [])
            query_info["raw"] = len(repos)
            if diagnostics is not None:
                diagnostics["raw_items"] += len(repos)
        except Exception as exc:
            query_info["error"] = redact_sensitive_text(exc)
            if diagnostics is not None:
                diagnostics["queries"].append(query_info)
            continue

        for repo in repos:
            url = _text(repo.get("html_url"))
            title = _text(repo.get("full_name"))
            if not title or not url or url in seen:
                continue
            published = parse_article_date(repo.get("pushed_at") or repo.get("updated_at") or repo.get("created_at"))
            if use_date and not is_within_date_range(published, start_date, end_date):
                continue
            if diagnostics is not None:
                diagnostics["after_date_filter"] += 1
            if not _github_is_relevant(repo, use_date):
                continue
            if diagnostics is not None:
                diagnostics["after_scoring"] += 1
            metrics = {"stars": int(repo.get("stargazers_count") or 0), "forks": int(repo.get("forks_count") or 0), "open_issues": int(repo.get("open_issues_count") or 0), "language": repo.get("language") or ""}
            topics = repo.get("topics") or []
            useful_topics = filter_useful_tags(topics, "github")
            readme = _github_readme_snippet(title, headers)
            summary = _text(repo.get("description")) or ", ".join(useful_topics) or readme[:180]
            articles.append({"source": "GitHub", "source_type": "github", "connector": "github", "source_group": "developer_trends", "title": title, "url": url, "published_at": normalize_date_for_storage(published), "summary": summary, "category": "Tool", "score": _github_score(repo), "metrics": {**metrics, "useful_topics": useful_topics}, "structured_summary": build_github_structured_summary({"description": summary, "readme_snippet": readme, "topics": topics, "stars": metrics["stars"], "forks": metrics["forks"], "language": metrics["language"], "published_at": published})})
            seen.add(url)
            query_info["kept"] += 1
            if len(articles) >= limit:
                if diagnostics is not None:
                    diagnostics["queries"].append(query_info)
                    diagnostics["returned"] = len(articles)
                return articles
        if diagnostics is not None:
            diagnostics["queries"].append(query_info)
    if diagnostics is not None:
        diagnostics["returned"] = len(articles)
    return articles


def _clean_username(username):
    return str(username or "").strip().lstrip("@")


def parse_channel_usernames(text):
    return [_clean_username(line) for line in str(text or "").splitlines() if _clean_username(line)]


def _channel_configs(channels):
    configs = []
    for item in TELEGRAM_CHANNELS if channels is None else channels:
        if isinstance(item, dict):
            username = _clean_username(item.get("username"))
            if username:
                configs.append({**item, "username": username})
        else:
            username = _clean_username(item)
            if username:
                configs.append({"name": username, "username": username, "source_group": "social_news", "quality_weight": 1.0})
    return configs


def _session_exists(session_name):
    return bool(session_name and (os.path.exists(session_name) or os.path.exists(f"{session_name}.session")))


def _clean_message_text(text):
    text = re.sub(r"[\U00010000-\U0010ffff]", "", str(text or ""))
    text = re.sub(r"\butm_[A-Za-z0-9_=-]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _title_from_text(text):
    for line in str(text or "").splitlines():
        line = _clean_message_text(line)
        if line:
            return line[:120]
    return "Telegram post"


def _normalize_message(message, channel):
    text = _clean_message_text(getattr(message, "message", "") or getattr(message, "text", ""))
    if not text:
        return None
    username = channel["username"]
    replies = getattr(getattr(message, "replies", None), "replies", 0) or 0
    return {"source": f"Telegram - {channel.get('name') or username}", "source_type": "telegram", "connector": "telegram", "source_group": channel.get("source_group", "social_news"), "title": _title_from_text(text), "url": f"https://t.me/{username}/{getattr(message, 'id', '')}", "published_at": normalize_date_for_storage(parse_article_date(getattr(message, "date", None))), "summary": text, "category": "General", "score": 0, "metrics": {"views": int(getattr(message, "views", 0) or 0), "forwards": int(getattr(message, "forwards", 0) or 0), "replies": int(replies), "quality_weight": float(channel.get("quality_weight", 1.0) or 1.0)}}


async def fetch_telegram_channel_posts(channels, start_datetime=None, end_datetime=None, limit_per_channel=20, telegram_api_id=None, telegram_api_hash=None, telegram_session_name="telegram_news_session", diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else {}
    telegram_api_id = clean_token(telegram_api_id)
    telegram_api_hash = clean_token(telegram_api_hash)
    telegram_session_name = clean_token(telegram_session_name) or "telegram_news_session"
    channel_configs = _channel_configs(channels)
    diagnostics.update({"session_exists": _session_exists(telegram_session_name), "api_id_configured": bool(telegram_api_id), "api_hash_configured": bool(telegram_api_hash), "channels_configured": len(channel_configs), "channels_reachable": 0, "raw_messages_found": 0, "after_date_filter": 0, "normalized": 0, "errors": []})
    if not telegram_api_id or not telegram_api_hash:
        diagnostics["errors"].append("Telegram API ID/API Hash are required.")
        return []
    if TelegramClient is None:
        diagnostics["errors"].append("Telethon is not installed. Run pip install -r requirements.txt.")
        return []
    if not _session_exists(telegram_session_name):
        diagnostics["errors"].append("Telegram session file not found. Run python telegram_login.py first.")
        return []

    articles = []
    try:
        async with TelegramClient(telegram_session_name, int(telegram_api_id), telegram_api_hash) as client:
            if not await client.is_user_authorized():
                diagnostics["errors"].append("Telegram login required. Run python telegram_login.py.")
                return []
            for channel in channel_configs:
                try:
                    entity = await client.get_entity(channel["username"])
                    diagnostics["channels_reachable"] += 1
                    async for message in client.iter_messages(entity, limit=limit_per_channel):
                        diagnostics["raw_messages_found"] += 1
                        published = parse_article_date(getattr(message, "date", None))
                        if not is_within_date_range(published, start_datetime, end_datetime):
                            continue
                        diagnostics["after_date_filter"] += 1
                        article = _normalize_message(message, channel)
                        if article:
                            articles.append(article)
                            diagnostics["normalized"] += 1
                except FloodWaitError as exc:
                    diagnostics["errors"].append(f"{channel['username']}: flood wait {getattr(exc, 'seconds', '?')}s")
                except (RPCError, ValueError, TypeError) as exc:
                    diagnostics["errors"].append(f"{channel['username']}: {redact_sensitive_text(exc)}")
    except SessionPasswordNeededError:
        diagnostics["errors"].append("Telegram two-factor password required. Run python telegram_login.py.")
    except Exception as exc:
        diagnostics["errors"].append(redact_sensitive_text(exc))
    return articles


def fetch_telegram_posts_sync(channels=None, start_datetime=None, end_datetime=None, limit_per_channel=20, telegram_api_id=None, telegram_api_hash=None, telegram_session_name="telegram_news_session", diagnostics=None):
    return asyncio.run(fetch_telegram_channel_posts(TELEGRAM_CHANNELS if channels is None else channels, start_datetime=start_datetime, end_datetime=end_datetime, limit_per_channel=limit_per_channel, telegram_api_id=telegram_api_id, telegram_api_hash=telegram_api_hash, telegram_session_name=telegram_session_name, diagnostics=diagnostics))


def get_connector_fetchers():
    return {
        "rss": fetch_rss_articles,
        "hacker_news": fetch_hacker_news,
        "arxiv": fetch_arxiv_ai,
        "github": fetch_github_repositories,
        "huggingface": fetch_huggingface_models,
        "youtube": fetch_youtube_videos,
        "telegram": fetch_telegram_posts_sync,
    }
