"""Safe connector diagnostics for the dashboard."""

import requests
from huggingface_hub import HfApi

from connectors import GITHUB_SEARCH_URL, fetch_github_repositories, fetch_huggingface_models


def _result(ok, status, message, items_found=0, error=None, http_status=None, raw_items_found=None):
    return {
        "ok": ok,
        "status": status,
        "message": message,
        "items_found": items_found,
        "raw_items_found": raw_items_found if raw_items_found is not None else items_found,
        "http_status": http_status,
        "error": str(error) if error else None,
    }


def test_github_connection(github_token=None):
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
            error=None if response.ok else data.get("message"),
        )
    except Exception as exc:
        return _result(False, "error", "GitHub API request failed", error=exc)


def test_huggingface_connection(huggingface_token=None):
    try:
        api = HfApi(token=huggingface_token) if huggingface_token else HfApi()
        models = list(api.list_models(sort="likes", limit=1, full=True))
        return _result(True, "success", "Hugging Face API reachable", items_found=len(models))
    except Exception as exc:
        return _result(False, "error", "Hugging Face API request failed", error=exc)


def test_github_connector(start_date=None, end_date=None, github_token=None):
    try:
        items = fetch_github_repositories(start_date=start_date, end_date=end_date, limit=10, github_token=github_token)
        return _result(True, "success", "GitHub connector completed", items_found=len(items))
    except Exception as exc:
        return _result(False, "error", "GitHub connector failed", error=exc)


def test_huggingface_connector(start_date=None, end_date=None, huggingface_token=None):
    try:
        items = fetch_huggingface_models(start_date=start_date, end_date=end_date, limit=10, huggingface_token=huggingface_token)
        return _result(True, "success", "Hugging Face connector completed", items_found=len(items))
    except Exception as exc:
        return _result(False, "error", "Hugging Face connector failed", error=exc)
