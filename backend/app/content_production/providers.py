from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.content_production.enrichment import (
    EnrichmentFinding,
    EnrichmentQuery,
    EnrichmentResponse,
)
from app.content_production.llm import OpenAIResponsesProvider, OpenRouterChatCompletionsProvider
from app.discovery.article_extractor import extract_article_document
from app.discovery.models import DiscoveryItem, ExtractedArticle

PUBLIC_ARTICLE_USER_AGENT = "NewsCraft-ArticleExtractor/1.0 (+https://localhost/newscraft)"
DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
HostResolver = Callable[[str], Awaitable[list[str]]]


@dataclass(frozen=True)
class ArticleFetchPolicy:
    timeout_seconds: float = 15.0
    max_response_bytes: int = 2_000_000
    max_redirects: int = 4


class SafeArticleExtractionProvider:
    provider_name = "http_trafilatura"

    def __init__(
        self,
        *,
        policy: ArticleFetchPolicy | None = None,
        client: httpx.AsyncClient | None = None,
        resolver: HostResolver | None = None,
    ) -> None:
        self.policy = policy or ArticleFetchPolicy()
        self.client = client
        self.resolver = resolver or resolve_host_addresses

    async def extract(self, item: DiscoveryItem) -> ExtractedArticle:
        if not item.url:
            return _failed_article(item, "missing_url")
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(follow_redirects=False)
        try:
            final_url, html = await self._fetch_html(client, item.url)
            return extract_article_document(item, final_url=final_url, html=html)
        except ProviderFetchError as exc:
            return _failed_article(item, exc.reason)
        finally:
            if owns_client:
                await client.aclose()

    async def _fetch_html(self, client: httpx.AsyncClient, initial_url: str) -> tuple[str, str]:
        url = initial_url
        for redirect_count in range(self.policy.max_redirects + 1):
            await validate_public_url(url, self.resolver)
            try:
                async with client.stream(
                    "GET",
                    url,
                    follow_redirects=False,
                    timeout=self.policy.timeout_seconds,
                    headers={"User-Agent": PUBLIC_ARTICLE_USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ProviderFetchError("redirect_missing_location")
                        if redirect_count >= self.policy.max_redirects:
                            raise ProviderFetchError("too_many_redirects")
                        url = urljoin(url, location)
                        continue
                    if response.status_code >= 400:
                        raise ProviderFetchError(f"http_{response.status_code}")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().casefold()
                    if content_type not in {"text/html", "application/xhtml+xml"}:
                        raise ProviderFetchError("unsupported_content_type")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.policy.max_response_bytes:
                            raise ProviderFetchError("response_too_large")
                    encoding = response.encoding or "utf-8"
                    return str(response.url), bytes(body).decode(encoding, errors="replace")
            except httpx.TimeoutException as exc:
                raise ProviderFetchError("timeout") from exc
            except httpx.HTTPError as exc:
                raise ProviderFetchError("network_error") from exc
        raise ProviderFetchError("too_many_redirects")


class DuckDuckGoEnrichmentProvider:
    provider_name = "duckduckgo_html"

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_results: int = 5,
        max_snippet_chars: int = 500,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results
        self.max_snippet_chars = max_snippet_chars
        self.client = client

    async def search(self, query: EnrichmentQuery) -> EnrichmentResponse:
        search_text = build_search_text(query)
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient()
        try:
            response = await client.get(
                DUCKDUCKGO_SEARCH_URL,
                params={"q": search_text},
                timeout=self.timeout_seconds,
                headers={"User-Agent": PUBLIC_ARTICLE_USER_AGENT, "Accept": "text/html"},
            )
            response.raise_for_status()
            return self._parse(response.text, query.source_url)
        except httpx.TimeoutException:
            return EnrichmentResponse(status="failed", error_message="provider_timeout")
        except httpx.HTTPStatusError as exc:
            return EnrichmentResponse(status="failed", error_message=f"provider_http_{exc.response.status_code}")
        except httpx.HTTPError:
            return EnrichmentResponse(status="failed", error_message="provider_network_error")
        finally:
            if owns_client:
                await client.aclose()

    def _parse(self, html: str, original_url: str | None) -> EnrichmentResponse:
        soup = BeautifulSoup(html, "lxml")
        findings: list[EnrichmentFinding] = []
        seen: set[str] = set()
        original = _canonical_result_url(original_url)
        for result in soup.select(".result"):
            link = result.select_one(".result__a")
            if link is None:
                continue
            url = _duckduckgo_result_url(str(link.get("href") or ""))
            canonical = _canonical_result_url(url)
            if not canonical or canonical == original or canonical in seen:
                continue
            seen.add(canonical)
            snippet_node = result.select_one(".result__snippet")
            snippet = _bounded_text(
                snippet_node.get_text(" ", strip=True) if snippet_node else "",
                self.max_snippet_chars,
            )
            title = _bounded_text(link.get_text(" ", strip=True), 300)
            if not title or not snippet:
                continue
            findings.append(
                EnrichmentFinding(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=urlsplit(url).hostname,
                    reliability="unverified_secondary",
                )
            )
            if len(findings) >= self.max_results:
                break
        if not findings:
            return EnrichmentResponse(status="empty", warnings=["no_useful_results"])
        return EnrichmentResponse(status="ok", findings=findings)


class ProviderFetchError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def resolve_host_addresses(hostname: str) -> list[str]:
    loop = asyncio.get_running_loop()
    rows = await loop.run_in_executor(None, socket.getaddrinfo, hostname, None, 0, socket.SOCK_STREAM)
    return list(dict.fromkeys(row[4][0] for row in rows))


async def validate_public_url(url: str, resolver: HostResolver) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ProviderFetchError("unsupported_scheme")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ProviderFetchError("invalid_url")
    try:
        addresses = [str(ipaddress.ip_address(parsed.hostname))]
    except ValueError:
        try:
            addresses = await resolver(parsed.hostname)
        except (OSError, socket.gaierror) as exc:
            raise ProviderFetchError("dns_resolution_failed") from exc
    if not addresses:
        raise ProviderFetchError("dns_resolution_failed")
    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ProviderFetchError("private_address")


def build_search_text(query: EnrichmentQuery) -> str:
    parts = [query.title, query.source_name, query.author, query.published_date]
    return _bounded_text(" ".join(str(value) for value in parts if value), 300)


def _duckduckgo_result_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)
    return value


def _canonical_result_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.casefold()}://{parsed.hostname.casefold()}{path}"


def _bounded_text(value: str, limit: int) -> str:
    return " ".join(value.split())[:limit]


def _failed_article(item: DiscoveryItem, reason: str) -> ExtractedArticle:
    return ExtractedArticle(
        url=item.url or item.external_id,
        final_url=item.url or item.external_id,
        title=item.title,
        summary=item.summary,
        content_text=item.summary or item.title,
        content_html=None,
        author=item.author,
        published_at=item.published_at,
        image_url=item.image_url,
        extraction_status="failed",
        extraction_warnings=[reason],
    )


def build_production_provider_options(config) -> dict:
    extraction = SafeArticleExtractionProvider(
        policy=ArticleFetchPolicy(
            timeout_seconds=config.article_fetch_timeout_seconds,
            max_response_bytes=config.article_fetch_max_bytes,
            max_redirects=config.article_fetch_max_redirects,
        )
    )
    enrichment = None
    if config.enrichment_provider == "duckduckgo":
        enrichment = DuckDuckGoEnrichmentProvider(
            timeout_seconds=config.enrichment_timeout_seconds,
            max_results=config.enrichment_max_results,
            max_snippet_chars=config.enrichment_max_snippet_chars,
        )
    llm = None
    if config.llm_provider == "openai":
        llm = OpenAIResponsesProvider(
            api_key=config.openai_api_key.get_secret_value(),
            model=config.llm_model,
            base_url=config.llm_base_url,
        )
    elif config.llm_provider == "openrouter":
        llm = OpenRouterChatCompletionsProvider(
            api_key=config.openrouter_api_key.get_secret_value(),
            model=config.llm_model,
            base_url=config.llm_base_url,
        )
    return {
        "extraction_provider": extraction,
        "enrichment_provider": enrichment,
        "llm_provider": llm,
        "llm_timeout_seconds": config.llm_request_timeout_seconds,
        "llm_max_output_tokens": config.llm_max_output_tokens,
    }
