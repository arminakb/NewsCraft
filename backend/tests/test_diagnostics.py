from httpx import ASGITransport, AsyncClient

from app.api.routes import get_session
from app.main import app


class FakeSession:
    async def execute(self, *_args, **_kwargs):
        return None


async def _override_session():
    yield FakeSession()


async def test_diagnostics_endpoint_reports_database_and_source_support():
    app.dependency_overrides[get_session] = _override_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/diagnostics")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"] == "ok"
    assert payload["checks"]["rss_parser"] == "ok"
    assert payload["checks"]["telegram_public_parser"] == "ok"
