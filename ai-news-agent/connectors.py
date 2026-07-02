"""Free public news source connectors."""

import html
import logging
import base64
from xml.etree import ElementTree

import feedparser
import requests
from huggingface_hub import HfApi

from config import RSS_FEEDS, YOUTUBE_CHANNEL_FEEDS
from utils import is_within_date_range, normalize_date_for_storage, parse_article_date

HN_TOP_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
ARXIV_URL = "http://export.arxiv.org/api/query"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
TIMEOUT = 15
GITHUB_MIN_STARS = 20
HF_TAGS = [
    "text-generation",
    "image-to-text",
    "text-to-image",
    "automatic-speech-recognition",
    "text-to-video",
    "multimodal",
    "agent",
    "llm",
]
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
]


def _text(value):
    return html.unescape(str(value or "")).strip()


def _structured_summary(what_it_is, why_it_matters, best_use_cases, key_signals):
    return {
        "what_it_is": what_it_is,
        "why_it_matters": why_it_matters,
        "best_use_cases": best_use_cases[:4],
        "key_signals": key_signals[:6],
    }


def _entry_date(entry):
    for key in ("published", "updated", "published_parsed", "updated_parsed"):
        parsed = parse_article_date(entry.get(key))
        if parsed:
            return parsed
    return None


def fetch_rss_articles(start_date=None, end_date=None):
    articles = []
    for feed_config in RSS_FEEDS:
        url = feed_config["url"] if isinstance(feed_config, dict) else feed_config
        try:
            feed = feedparser.parse(url)
            source = _text(feed.feed.get("title")) or (feed_config.get("name") if isinstance(feed_config, dict) else url)
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


def fetch_youtube_videos(start_date=None, end_date=None, limit=30, youtube_api_key=None):
    # Future improvement: Add YouTube Data API search connector using API key,
    # query terms, publishedAfter, publishedBefore, order=date/viewCount.
    articles = []
    for feed_config in YOUTUBE_CHANNEL_FEEDS:
        url = feed_config["url"]
        if "CHANNEL_ID_HERE" in url:
            logging.warning("Skipping YouTube placeholder channel feed for %s", feed_config["name"])
            continue
        try:
            feed = feedparser.parse(url)
            entries = feed.entries
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
            articles.append(
                {
                    "source": f"YouTube - {feed_config['name']}",
                    "source_type": "youtube",
                    "title": title,
                    "url": link,
                    "published_at": normalize_date_for_storage(published),
                    "summary": _text(entry.get("summary") or entry.get("description")),
                    "category": "Video",
                    "score": 0,
                    "metrics": {"channel": feed_config["name"]},
                }
            )
            if len(articles) >= limit:
                return articles
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


def _hf_score(model, tags):
    likes = int(getattr(model, "likes", 0) or 0)
    downloads = int(getattr(model, "downloads", 0) or 0)
    tag_score = sum(3 for tag in tags if tag in HF_TAGS)
    return likes + downloads // 100 + tag_score


def _hf_structured_summary(model_id, tags, likes, downloads, published):
    tag_text = ", ".join(tags[:4]) if tags else "general model metadata"
    use_cases = []
    if "text-generation" in tags or "llm" in tags:
        use_cases.extend(["Text generation", "Agent workflows", "RAG experiments"])
    if "text-to-image" in tags:
        use_cases.append("Image generation")
    if "automatic-speech-recognition" in tags:
        use_cases.append("Speech recognition")
    if not use_cases:
        use_cases = ["Model evaluation", "AI prototyping"]
    signals = [f"Tags: {tag_text}", f"Likes: {likes}", f"Downloads: {downloads}"]
    if published:
        signals.append(f"Last modified: {normalize_date_for_storage(published)}")
    return _structured_summary(
        f"{model_id} is a Hugging Face model related to {tag_text}.",
        "It may be worth reviewing because its tags and community metrics indicate current model activity.",
        use_cases,
        signals,
    )


def fetch_huggingface_models(start_date=None, end_date=None, limit=30, huggingface_token=None):
    logging.info("Hugging Face connector started. Token configured: %s", "yes" if huggingface_token else "no")
    try:
        api = HfApi(token=huggingface_token) if huggingface_token else HfApi()
        models = list(api.list_models(sort="likes", limit=limit * 3, full=True))
    except Exception as exc:
        logging.warning("Hugging Face fetch failed: %s", exc)
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
        likes = int(getattr(model, "likes", 0) or 0)
        downloads = int(getattr(model, "downloads", 0) or 0)
        articles.append(
            {
                "source": "Hugging Face",
                "source_type": "huggingface",
                "title": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "published_at": normalize_date_for_storage(published),
                "summary": ", ".join(tags[:12]),
                "category": "Model",
                "score": _hf_score(model, tags),
                "metrics": {"likes": likes, "downloads": downloads},
                "structured_summary": _hf_structured_summary(model_id, tags, likes, downloads, published),
            }
        )
        if len(articles) >= limit:
            break
    if not articles and (start_date or end_date):
        logging.warning("Hugging Face date range returned 0 items; falling back to popular models without date filtering")
        return fetch_huggingface_models(limit=limit, huggingface_token=huggingface_token)
    logging.info("Hugging Face normalized items returned: %s", len(articles))
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
    topic_score = sum(5 for topic in topics if topic in {"llm", "agents", "rag", "generative-ai", "machine-learning"})
    description_score = 5 if repo.get("description") else 0
    return stars + forks * 2 + topic_score + description_score


def _github_is_relevant(repo, use_date):
    stars = int(repo.get("stargazers_count") or 0)
    text = f"{repo.get('full_name', '')} {repo.get('description', '')} {' '.join(repo.get('topics') or [])}".lower()
    strong_match = any(term in text for term in ("ai", "llm", "agent", "rag", "machine-learning", "generative"))
    return stars >= GITHUB_MIN_STARS or (use_date and stars >= 5) or strong_match


def _github_readme_snippet(full_name, headers):
    try:
        response = requests.get(f"https://api.github.com/repos/{full_name}/readme", headers=headers, timeout=TIMEOUT)
        if not response.ok:
            return ""
        content = response.json().get("content", "")
        return base64.b64decode(content).decode("utf-8", errors="ignore")[:600]
    except Exception:
        return ""


def _github_structured_summary(repo, summary, readme_snippet, published):
    topics = [str(topic) for topic in repo.get("topics") or []]
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    language = repo.get("language") or "unspecified language"
    description = summary or readme_snippet[:180] or "No description provided."
    use_cases = ["AI development", "Developer tooling"]
    topic_text = " ".join(topics).lower()
    if "agent" in topic_text:
        use_cases.append("Agentic workflows")
    if "rag" in topic_text:
        use_cases.append("RAG experiments")
    signals = [f"{stars} stars", f"{forks} forks", f"Language: {language}"]
    if topics:
        signals.append(f"Topics: {', '.join(topics[:5])}")
    if published:
        signals.append(f"Recently pushed: {normalize_date_for_storage(published)}")
    return _structured_summary(
        description,
        "It is relevant because it is AI-related, recently active or popular, and has developer interest signals.",
        use_cases,
        signals,
    )


def fetch_github_repositories(start_date=None, end_date=None, limit=30, github_token=None):
    logging.info("GitHub connector started. Token configured: %s", "yes" if github_token else "no")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    articles = []
    seen = set()
    queries = [(query, True) for query in GITHUB_QUERIES] + [(query, False) for query in GITHUB_FALLBACK_QUERIES]
    for query, use_date in queries:
        try:
            full_query = _github_query(query, start_date, end_date) if use_date else query
            response = requests.get(
                GITHUB_SEARCH_URL,
                params={"q": full_query, "sort": "stars", "order": "desc", "per_page": limit},
                headers=headers,
                timeout=TIMEOUT,
            )
            logging.info("GitHub query used: %s HTTP status: %s", full_query, response.status_code)
            response.raise_for_status()
            repos = response.json().get("items", [])
            logging.info("GitHub raw items found: %s", len(repos))
        except Exception as exc:
            logging.warning("GitHub fetch failed for %s: %s", query, exc)
            continue

        for repo in repos:
            url = _text(repo.get("html_url"))
            title = _text(repo.get("full_name"))
            if not title or not url or url in seen:
                continue
            published = parse_article_date(repo.get("pushed_at") or repo.get("updated_at") or repo.get("created_at"))
            if use_date and not is_within_date_range(published, start_date, end_date):
                continue
            if not _github_is_relevant(repo, use_date):
                continue
            metrics = {
                "stars": int(repo.get("stargazers_count") or 0),
                "forks": int(repo.get("forks_count") or 0),
                "open_issues": int(repo.get("open_issues_count") or 0),
                "language": repo.get("language") or "",
            }
            topics = repo.get("topics") or []
            readme = _github_readme_snippet(title, headers)
            summary = _text(repo.get("description")) or ", ".join(topics) or readme[:180]
            articles.append(
                {
                    "source": "GitHub",
                    "source_type": "github",
                    "title": title,
                    "url": url,
                    "published_at": normalize_date_for_storage(published),
                    "summary": summary,
                    "category": "Tool",
                    "score": _github_score(repo),
                    "metrics": metrics,
                    "structured_summary": _github_structured_summary(repo, summary, readme, published),
                }
            )
            seen.add(url)
            if len(articles) >= limit:
                logging.info("GitHub normalized items returned: %s", len(articles))
                return articles
    logging.info("GitHub normalized items returned: %s", len(articles))
    return articles
