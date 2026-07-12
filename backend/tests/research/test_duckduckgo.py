from __future__ import annotations

import asyncio


def test_duckduckgo_client_forces_backend_and_deduplicates_normalized_urls(monkeypatch):
    from app.research.duckduckgo import DuckDuckGoSearchClient

    calls: list[dict[str, object]] = []
    constructor_calls: list[dict[str, object]] = []

    class FakeDDGS:
        def __init__(self, **kwargs):
            constructor_calls.append(kwargs)

        def text(self, query: str, **kwargs):
            calls.append({"query": query, **kwargs})
            return [
                {"title": " Result ", "href": "HTTPS://Example.com/report/", "body": " Snippet "},
                {"title": "Duplicate", "href": "https://example.com/report", "body": "Other"},
                {"title": "Missing URL", "body": "ignored"},
            ]

    monkeypatch.setattr("app.research.duckduckgo.DDGS", FakeDDGS)

    results = asyncio.run(DuckDuckGoSearchClient().search(" agent release ", limit=5))

    assert constructor_calls == [{"timeout": 30.0}]
    assert calls == [{"query": "agent release", "backend": "duckduckgo", "max_results": 5}]
    assert [result.model_dump(mode="json") for result in results] == [
        {
            "title": "Result",
            "url": "https://example.com/report",
            "snippet": "Snippet",
        }
    ]


def test_duckduckgo_client_propagates_finite_remaining_timeout_to_transport(monkeypatch):
    from app.research.duckduckgo import DuckDuckGoSearchClient

    constructor_calls: list[dict[str, object]] = []
    text_calls: list[dict[str, object]] = []

    class FakeDDGS:
        def __init__(self, **kwargs):
            constructor_calls.append(kwargs)

        def text(self, query: str, **kwargs):
            text_calls.append({"query": query, **kwargs})
            return []

    monkeypatch.setattr("app.research.duckduckgo.DDGS", FakeDDGS)

    asyncio.run(
        DuckDuckGoSearchClient(max_timeout_seconds=30).search(
            "agent release",
            limit=5,
            timeout_seconds=2.75,
        )
    )

    assert constructor_calls == [{"timeout": 2.75}]
    assert text_calls == [
        {"query": "agent release", "backend": "duckduckgo", "max_results": 5}
    ]


def test_duckduckgo_client_caps_timeout_and_rejects_unbounded_values(monkeypatch):
    from app.research.duckduckgo import DuckDuckGoSearchClient

    constructor_calls: list[dict[str, object]] = []

    class FakeDDGS:
        def __init__(self, **kwargs):
            constructor_calls.append(kwargs)

        def text(self, query: str, **kwargs):
            return []

    monkeypatch.setattr("app.research.duckduckgo.DDGS", FakeDDGS)
    client = DuckDuckGoSearchClient(max_timeout_seconds=7)

    asyncio.run(client.search("agent release", limit=5, timeout_seconds=20))

    assert constructor_calls == [{"timeout": 7.0}]
    for invalid in (0, -1, float("inf"), float("nan")):
        with __import__("pytest").raises(ValueError, match="finite and positive"):
            asyncio.run(client.search("agent release", limit=5, timeout_seconds=invalid))
