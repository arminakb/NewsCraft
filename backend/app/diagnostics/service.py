from __future__ import annotations

from sqlalchemy import select, text

from app.db.models import Source

SOURCE_HEALTH_STATUSES = ("healthy", "degraded", "broken", "disabled", "unknown")


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
                "counts": _empty_counts(total=0),
                "problem_sources": [],
            }
        counts = _empty_counts(total=len(sources))
        problem_sources = []
        for source in sources:
            status = _source_health_status(source)
            counts[status] += 1
            if status in {"degraded", "broken", "disabled", "unknown"}:
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
        status = "ok" if counts["broken"] == 0 and counts["degraded"] == 0 and counts["unknown"] == 0 else "degraded"
        return {"status": status, "counts": counts, "problem_sources": problem_sources}


def _empty_counts(total: int) -> dict[str, int]:
    return {**{status: 0 for status in SOURCE_HEALTH_STATUSES}, "total": total}


def _source_health_status(source: Source) -> str:
    if not source.active or source.disabled_reason:
        return "disabled"
    status = source.health_status or "unknown"
    if status == "healthy" and not _has_health_history(source):
        return "unknown"
    if status not in SOURCE_HEALTH_STATUSES:
        return "degraded"
    return status


def _has_health_history(source: Source) -> bool:
    if any(
        getattr(source, field) is not None
        for field in ("last_fetch_at", "last_success_at", "last_failure_at", "last_http_status")
    ):
        return True
    return any(
        int(getattr(source, field) or 0) > 0
        for field in ("last_parse_count", "last_suitable_count", "last_media_count", "failure_count")
    )


def _health_sort_key(status: str, name: str) -> tuple[int, str]:
    return {"broken": 0, "degraded": 1, "unknown": 2, "disabled": 3}.get(status, 4), name
