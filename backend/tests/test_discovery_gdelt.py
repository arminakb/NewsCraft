from datetime import UTC, datetime

import httpx

from app.discovery.gdelt import discover_gdelt


async def test_discover_gdelt_queries_doc_api_and_maps_articles():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "url": "https://example.com/ai",
                        "title": "AI story",
                        "seendate": "20260705120000",
                        "socialimage": "https://example.com/ai.jpg",
                        "domain": "example.com",
                        "sourcecountry": "US",
                        "language": "English",
                    },
                    {"title": "Missing URL"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await discover_gdelt(
            client,
            datetime(2026, 7, 5, tzinfo=UTC),
            datetime(2026, 7, 6, tzinfo=UTC),
            ["AI", "economy"],
            max_records=50,
        )

    assert len(items) == 1
    assert str(requests[0].url).startswith("https://api.gdeltproject.org/api/v2/doc/doc")
    params = dict(requests[0].url.params)
    assert params["mode"] == "ArtList"
    assert params["format"] == "json"
    assert params["startdatetime"] == "20260705000000"
    assert params["enddatetime"] == "20260706000000"
    assert params["maxrecords"] == "50"
    assert "AI" in params["query"]
    assert "OR" in params["query"]
    assert items[0].source_platform == "gdelt"
    assert items[0].external_id == "https://example.com/ai"
    assert items[0].image_url == "https://example.com/ai.jpg"
    assert items[0].metadata["domain"] == "example.com"
