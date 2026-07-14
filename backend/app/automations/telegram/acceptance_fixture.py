from __future__ import annotations

from pathlib import Path

import httpx


class TelegramAcceptanceFixtureTransport(httpx.AsyncBaseTransport):
    """Serve deterministic Telegram HTML and media without outbound requests."""

    def __init__(self, fixture_path: str | Path) -> None:
        self.fixture_path = Path(fixture_path)
        if not self.fixture_path.is_file():
            raise ValueError("Telegram acceptance fixture file is unavailable")
        self._html = self.fixture_path.read_text(encoding="utf-8")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(405, request=request)
        if request.url.host == "t.me" and request.url.path.startswith("/s/"):
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=self._html,
                request=request,
            )
        if request.url.host == "cdn.example":
            content_type = _fixture_content_type(request.url.path)
            content = f"newscraft-acceptance-media:{request.url.path}".encode()
            return httpx.Response(
                200,
                headers={"content-type": content_type},
                content=content,
                request=request,
            )
        return httpx.Response(404, request=request)


def _fixture_content_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")


__all__ = ["TelegramAcceptanceFixtureTransport"]
