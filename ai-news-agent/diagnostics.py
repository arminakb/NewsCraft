"""Safe connector diagnostics for the dashboard."""

import requests
from huggingface_hub import HfApi

from connectors import GITHUB_SEARCH_URL, fetch_arxiv_ai, fetch_github_repositories, fetch_hacker_news, fetch_huggingface_models
from utils import clean_token, redact_sensitive_text


def _result(ok, status, message, items_found=0, error=None, http_status=None, raw_items_found=None, token_configured=None):
    return {
        "ok": ok,
        "status": status,
        "message": message,
        "token_configured": token_configured,
        "items_found": items_found,
        "raw_items_found": raw_items_found if raw_items_found is not None else items_found,
        "http_status": http_status,
        "error": redact_sensitive_text(error) if error else None,
    }


def test_github_connection(github_token=None):
    github_token = clean_token(github_token)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    try:
        response = requests.get(
            GITHUB_SEARCH_URL,
            params={"q": "topic:llm", "sort": "stars", "order": "desc", "per_page": 1},
            headers=headers,
            timeout=15,
        )
        data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        return _result(
            response.ok,
            "success" if response.ok else "error",
            "GitHub API reachable" if response.ok else "GitHub API returned an error",
            items_found=len(data.get("items", [])),
            http_status=response.status_code,
            token_configured=bool(github_token),
            error=None if response.ok else data.get("message"),
        )
    except Exception as exc:
        return _result(False, "error", "GitHub API request failed", error=exc, token_configured=bool(github_token))


def test_huggingface_connection(huggingface_token=None):
    huggingface_token = clean_token(huggingface_token)
    try:
        api = HfApi(token=huggingface_token) if huggingface_token else HfApi()
        models = list(api.list_models(sort="likes", limit=1, full=True))
        return _result(True, "success", "Hugging Face API reachable", items_found=len(models), token_configured=bool(huggingface_token))
    except Exception as exc:
        return _result(False, "error", "Hugging Face API request failed", error=exc, token_configured=bool(huggingface_token))


def test_github_connector(start_date=None, end_date=None, github_token=None):
    github_token = clean_token(github_token)
    try:
        diagnostics = {}
        items = fetch_github_repositories(start_date=start_date, end_date=end_date, limit=10, github_token=github_token, diagnostics=diagnostics)
        result = _result(True, "success", "GitHub connector completed", items_found=len(items), token_configured=bool(github_token))
        result["diagnostics"] = diagnostics
        return result
    except Exception as exc:
        return _result(False, "error", "GitHub connector failed", error=exc, token_configured=bool(github_token))


def test_huggingface_connector(start_date=None, end_date=None, huggingface_token=None):
    huggingface_token = clean_token(huggingface_token)
    try:
        items = fetch_huggingface_models(start_date=start_date, end_date=end_date, limit=10, huggingface_token=huggingface_token)
        return _result(True, "success", "Hugging Face connector completed", items_found=len(items), token_configured=bool(huggingface_token))
    except Exception as exc:
        return _result(False, "error", "Hugging Face connector failed", error=exc, token_configured=bool(huggingface_token))


def test_hacker_news_connector(start_date=None, end_date=None):
    try:
        diagnostics = {}
        items = fetch_hacker_news(start_date=start_date, end_date=end_date, limit=10, diagnostics=diagnostics)
        result = _result(True, "success", "Hacker News connector completed", items_found=len(items))
        result["diagnostics"] = diagnostics
        return result
    except Exception as exc:
        return _result(False, "error", "Hacker News connector failed", error=exc)


def test_arxiv_connector(start_date=None, end_date=None):
    try:
        diagnostics = {}
        items = fetch_arxiv_ai(start_date=start_date, end_date=end_date, limit=10, diagnostics=diagnostics)
        result = _result(True, "success", "arXiv connector completed", items_found=len(items))
        result["diagnostics"] = diagnostics
        return result
    except Exception as exc:
        return _result(False, "error", "arXiv connector failed", error=exc)
