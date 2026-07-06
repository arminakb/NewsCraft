from __future__ import annotations

from sqlalchemy import select, text

from app.db.models import Source


class DiagnosticsService:
    def __init__(self, session):
        self.session = session

    async def check(self) -> dict:
        source_health = await self._source_health()
        checks = {
            "database": await self._database_status(),
            "rss_parser": "ok",
            "telegram_public_parser": "ok",
            "media_storage": "configured",
            "source_health": source_health["status"],
        }
        status = "ok" if all(value in {"ok", "configured"} for value in checks.values()) else "degraded"
        return {
            "status": status,
            "checks": checks,
            "source_health": source_health["counts"],
            "problem_sources": source_health["problem_sources"],
        }

    async def _database_status(self) -> str:
        try:
            await self.session.execute(text("select 1"))
        except Exception:
            return "failed"
        return "ok"

    async def _source_health(self) -> dict:
        try:
            sources = list(await self.session.scalars(select(Source).order_by(Source.name)))
        except Exception:
            return {
                "status": "failed",
                "counts": {"healthy": 0, "degraded": 0, "broken": 0, "disabled": 0, "total": 0},
                "problem_sources": [],
            }
        counts = {"healthy": 0, "degraded": 0, "broken": 0, "disabled": 0, "total": len(sources)}
        problem_sources = []
        for source in sources:
            status = source.health_status or ("disabled" if not source.active else "healthy")
            if status not in counts:
                status = "degraded"
            counts[status] += 1
            if status in {"degraded", "broken", "disabled"}:
                problem_sources.append(
                    {
                        "id": str(source.id),
                        "name": source.name,
                        "platform": source.platform,
                        "health_status": status,
                        "failure_count": source.failure_count,
                        "last_http_status": source.last_http_status,
                        "last_error_type": source.last_error_type,
                        "last_error_message": source.last_error_message,
                        "disabled_reason": source.disabled_reason,
                    }
                )

        problem_sources.sort(key=lambda source: _health_sort_key(source["health_status"], source["name"]))
        status = "ok" if counts["broken"] == 0 and counts["degraded"] == 0 else "degraded"
        return {"status": status, "counts": counts, "problem_sources": problem_sources}


def _health_sort_key(status: str, name: str) -> tuple[int, str]:
    return {"broken": 0, "degraded": 1, "disabled": 2}.get(status, 3), name
