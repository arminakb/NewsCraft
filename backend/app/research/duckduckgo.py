from __future__ import annotations

import asyncio
import math
import os
from typing import Any

from ddgs import DDGS
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.core.outbound_proxy import OutboundProxyPolicy, ProxyConfigurationError
from app.normalization.urls import normalize_url


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(max_length=500)
    url: HttpUrl
    snippet: str = Field(max_length=2_000)


class DuckDuckGoSearchClient:
    def __init__(
        self,
        *,
        max_timeout_seconds: float = 30.0,
        proxy_policy: OutboundProxyPolicy | None = None,
    ) -> None:
        self.max_timeout_seconds = _finite_positive_timeout(max_timeout_seconds)
        if os.environ.get("DDGS_PROXY", "").strip():
            raise ProxyConfigurationError("proxy_environment_unsupported")
        self.proxy_policy = proxy_policy or OutboundProxyPolicy.from_environment()

    async def search(
        self,
        query: str,
        *,
        limit: int,
        timeout_seconds: float | None = None,
    ) -> list[SearchResult]:
        normalized_query = " ".join(query.split())
        transport_timeout = self.max_timeout_seconds
        if timeout_seconds is not None:
            transport_timeout = min(
                _finite_positive_timeout(timeout_seconds),
                self.max_timeout_seconds,
            )
        raw_results = await asyncio.to_thread(
            lambda: list(
                DDGS(
                    proxy=self.proxy_policy.explicit_proxy_url("https://duckduckgo.com"),
                    # The runtime accepts fractional seconds; the third-party stub
                    # incorrectly narrows this parameter to int.
                    timeout=transport_timeout,  # type: ignore[arg-type]
                ).text(
                    normalized_query,
                    backend="duckduckgo",
                    max_results=limit,
                )
            )
        )
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for raw in raw_results:
            normalized = _normalize_result(raw)
            if normalized is None:
                continue
            canonical_url = normalize_url(str(normalized.url))
            if canonical_url in seen_urls:
                continue
            seen_urls.add(canonical_url)
            results.append(
                SearchResult.model_validate(
                    {
                        "title": normalized.title,
                        "url": canonical_url,
                        "snippet": normalized.snippet,
                    }
                )
            )
        return results


def _normalize_result(raw: Any) -> SearchResult | None:
    if not isinstance(raw, dict):
        return None
    url = raw.get("href") or raw.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        return SearchResult.model_validate(
            {
                "title": _clean_text(raw.get("title"), limit=500),
                "url": normalize_url(url.strip()),
                "snippet": _clean_text(raw.get("body") or raw.get("snippet"), limit=2_000),
            }
        )
    except TypeError, ValueError:
        return None


def _clean_text(value: Any, *, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _finite_positive_timeout(value: float) -> float:
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("DuckDuckGo timeout must be finite and positive")
    return timeout


__all__ = ["DuckDuckGoSearchClient", "SearchResult"]
