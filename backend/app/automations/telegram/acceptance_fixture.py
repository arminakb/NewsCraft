from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.publishing.telegram.client import TelegramBotClient
from app.publishing.telegram.contracts import TelegramOperationResult, TelegramPublishOperation


class AcceptanceFixtureMisconfigured(RuntimeError):
    """Raised when the fixture-backed Bot API double is built outside a test run."""


class AcceptanceTelegramBotClient(TelegramBotClient):
    """Deterministic Bot API boundary used only by fixture-backed acceptance runs.

    This client reports every publish as succeeded without touching the Telegram
    Bot API, so it must never be reachable from a real deployment. The
    constructor therefore refuses to build unless the process is explicitly a
    fixture-backed test run: a mis-set ``APP_ENV`` fails loudly here instead of
    silently no-opping live publishes.
    """

    def __init__(self, *, config: Settings = settings) -> None:
        if config.app_env != "test" or config.telegram_acceptance_fixture_path is None:
            raise AcceptanceFixtureMisconfigured(
                "AcceptanceTelegramBotClient requires APP_ENV=test with "
                "TELEGRAM_ACCEPTANCE_FIXTURE_PATH configured"
            )
        self.config = config

    async def execute(self, operation: TelegramPublishOperation, token: str) -> TelegramOperationResult:
        del token
        return TelegramOperationResult(
            remote_message_ids=(9_001 + operation.index,),
            response_metadata={"ok": True, "test_transport": True},
        )

    async def get_me(self, token: str) -> dict[str, Any]:
        del token
        return {"id": 9_001, "username": "newscraft_test_bot"}

    async def get_chat(self, target_ref: str, token: str) -> dict[str, Any]:
        del token
        return {
            "id": -1_009_001,
            "type": "channel",
            "username": target_ref.removeprefix("@"),
            "title": "NewsCraft test channel",
        }

    async def get_chat_member(self, target_ref: str, user_id: int, token: str) -> dict[str, Any]:
        del target_ref, user_id, token
        return {"status": "administrator", "administrator": True}


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


__all__ = [
    "AcceptanceFixtureMisconfigured",
    "AcceptanceTelegramBotClient",
    "TelegramAcceptanceFixtureTransport",
]
