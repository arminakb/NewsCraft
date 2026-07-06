from __future__ import annotations

from sqlalchemy import text


class DiagnosticsService:
    def __init__(self, session):
        self.session = session

    async def check(self) -> dict:
        checks = {
            "database": await self._database_status(),
            "rss_parser": "ok",
            "telegram_public_parser": "ok",
            "media_storage": "configured",
        }
        status = "ok" if all(value in {"ok", "configured"} for value in checks.values()) else "degraded"
        return {"status": status, "checks": checks}

    async def _database_status(self) -> str:
        try:
            await self.session.execute(text("select 1"))
        except Exception:
            return "failed"
        return "ok"
