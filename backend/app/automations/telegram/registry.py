from __future__ import annotations

from app.automations.telegram.contracts import TelegramSourceAdapter


class TelegramSourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TelegramSourceAdapter] = {}

    def register(self, access_mode: str, adapter: TelegramSourceAdapter) -> None:
        self._adapters[access_mode] = adapter

    def get(self, access_mode: str) -> TelegramSourceAdapter:
        try:
            return self._adapters[access_mode]
        except KeyError as exc:
            raise LookupError(f"unsupported Telegram access mode: {access_mode}") from exc
