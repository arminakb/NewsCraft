from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.content_production.enrichment import EnrichmentQuery
from app.content_production.providers import (
    ArticleFetchPolicy,
    DuckDuckGoEnrichmentProvider,
    SafeArticleExtractionProvider,
    build_production_provider_options,
)
from app.core.config import Settings
from app.discovery.models import DiscoveryItem


async def public_resolver(hostname: str) -> list[str]:
    return ["93.184.216.34"]


def item(url: str = "https://publisher.test/story") -> DiscoveryItem:
    return DiscoveryItem(
        source_platform="rss",
        source_name="Publisher",
        external_id=url,
        title="A useful source title",
        url=url,
        summary="A short source excerpt",
        published_at=None,
        image_url=None,
        author="Reporter",
        categories=["AI"],
        metadata={},
    )


async def test_safe_extractor_extracts_html_metadata_and_main_text():
    html = """
    <html><head><meta property="og:title" content="Exact title"><meta name="author" content="Author"></head>
    <body><nav>Navigation</nav><article>
      <p>Useful article body with enough detailed public evidence.</p>
    </article></body></html>
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=html, headers={"content-type": "text/html; charset=utf-8"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        result = await SafeArticleExtractionProvider(client=client, resolver=public_resolver).extract(item())

    assert result.extraction_status == "ok"
    assert result.title == "Exact title"
    assert result.author == "Author"
    assert "Useful article body" in result.content_text
    assert "Navigation" not in result.content_text
    assert result.content_html is None


async def test_safe_extractor_revalidates_redirect_and_rejects_private_target():
    requests = []

    async def resolver(hostname: str) -> list[str]:
        return ["127.0.0.1"] if hostname == "internal.test" else ["93.184.216.34"]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://internal.test/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SafeArticleExtractionProvider(client=client, resolver=resolver).extract(item())

    assert result.extraction_status == "failed"
    assert result.extraction_warnings == ["private_address"]
    assert requests == ["https://publisher.test/story"]


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("file:///etc/passwd", "unsupported_scheme"),
        ("http://127.0.0.1/private", "private_address"),
        ("http://169.254.169.254/latest/meta-data", "private_address"),
    ],
)
async def test_safe_extractor_rejects_unsafe_urls(url: str, reason: str):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("request sent"))) as client:
        result = await SafeArticleExtractionProvider(client=client, resolver=public_resolver).extract(item(url))
    assert result.extraction_warnings == [reason]


@pytest.mark.parametrize(
    ("response", "policy", "reason"),
    [
        (
            httpx.Response(200, content=b"binary", headers={"content-type": "application/pdf"}),
            None,
            "unsupported_content_type",
        ),
        (
            httpx.Response(200, content=b"x" * 101, headers={"content-type": "text/html"}),
            ArticleFetchPolicy(max_response_bytes=100),
            "response_too_large",
        ),
    ],
)
async def test_safe_extractor_enforces_content_type_and_size(response, policy, reason):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        result = await SafeArticleExtractionProvider(
            client=client, resolver=public_resolver, policy=policy
        ).extract(item())
    assert result.extraction_warnings == [reason]


async def test_safe_extractor_returns_structured_timeout_without_secret():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret-token=should-not-leak", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await SafeArticleExtractionProvider(client=client, resolver=public_resolver).extract(item())
    assert result.extraction_warnings == ["timeout"]
    assert "secret" not in " ".join(result.extraction_warnings)


async def test_duckduckgo_provider_bounds_deduplicates_and_excludes_original():
    long_snippet = "supporting " * 100
    html = f"""
    <div class="result">
      <a class="result__a" href="https://publisher.test/story">Original</a>
      <div class="result__snippet">same</div>
    </div>
    <div class="result">
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsource.test%2Fa">One</a>
      <div class="result__snippet">{long_snippet}</div>
    </div>
    <div class="result">
      <a class="result__a" href="https://source.test/a?tracking=1">Duplicate</a>
      <div class="result__snippet">duplicate</div>
    </div>
    <div class="result">
      <a class="result__a" href="https://second.test/b">Two</a>
      <div class="result__snippet">Second useful result</div>
    </div>
    """
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await DuckDuckGoEnrichmentProvider(
            client=client, max_results=2, max_snippet_chars=80
        ).search(query())

    assert response.status == "ok"
    assert [finding.url for finding in response.findings] == ["https://source.test/a", "https://second.test/b"]
    assert len(response.findings[0].snippet) == 80


async def test_duckduckgo_provider_distinguishes_empty_and_failure():
    empty = httpx.MockTransport(lambda request: httpx.Response(200, text="<html></html>"))
    async with httpx.AsyncClient(transport=empty) as client:
        response = await DuckDuckGoEnrichmentProvider(client=client).search(query())
    assert response.status == "empty"
    assert response.error_message is None

    def timeout(request):
        raise httpx.ReadTimeout("credential=do-not-leak", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        response = await DuckDuckGoEnrichmentProvider(client=client).search(query())
    assert response.status == "failed"
    assert response.error_message == "provider_timeout"


def test_provider_configuration_defaults_to_no_live_search_and_validates_bounds():
    config = Settings(_env_file=None)
    options = build_production_provider_options(config)
    assert options["extraction_provider"].provider_name == "http_trafilatura"
    assert options["enrichment_provider"] is None

    configured = Settings(_env_file=None, enrichment_provider="duckduckgo", enrichment_max_results=3)
    assert build_production_provider_options(configured)["enrichment_provider"].provider_name == "duckduckgo_html"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, article_fetch_timeout_seconds=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, enrichment_max_results=50)


def test_openrouter_provider_configuration_builds_chat_completions_adapter():
    config = Settings(
        _env_file=None,
        llm_provider="openrouter",
        llm_model="openai/gpt-5-mini",
        llm_base_url="https://openrouter.ai/api/v1",
        openrouter_api_key="test-key",
    )

    provider = build_production_provider_options(config)["llm_provider"]

    assert provider.provider_name == "openrouter"
    assert provider.base_url == "https://openrouter.ai/api/v1"


def test_example_configuration_contains_no_provider_credentials():
    lines = Path("../.env.example").read_text().splitlines()
    text = "\n".join(lines).casefold()
    credential_lines = [line for line in lines if line.startswith(("OPENAI_API_KEY=", "OPENROUTER_API_KEY="))]
    assert credential_lines == ["OPENAI_API_KEY=", "OPENROUTER_API_KEY="]
    assert "token=" not in text


def query() -> EnrichmentQuery:
    return EnrichmentQuery(
        title="AI research announcement",
        source_name="Publisher",
        source_url="https://publisher.test/story",
        source_domain="publisher.test",
        published_date="2026-07-11",
        author=None,
    )
