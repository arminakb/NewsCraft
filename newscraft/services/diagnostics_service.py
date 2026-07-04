from time import perf_counter

from sqlalchemy import text

from newscraft.connectors import fetchers
from newscraft.core.config import settings
from newscraft.core.security import redact_secret


class DiagnosticsService:
    def __init__(self, db=None):
        self.db = db

    def source_diagnostics(self):
        checks = [
            self._postgresql_check(),
            self._connector_check("rss", fetchers.fetch_rss_articles, diagnostics={}),
            self._connector_check("hacker_news", fetchers.fetch_hacker_news, limit=1, diagnostics={}),
            self._connector_check("arxiv", fetchers.fetch_arxiv_ai, limit=1, diagnostics={}),
            self._connector_check("github", fetchers.fetch_github_repositories, limit=1, github_token=settings.github_token, diagnostics={}),
            self._connector_check("huggingface", fetchers.fetch_huggingface_models, limit=1, huggingface_token=settings.huggingface_token),
            self._connector_check("youtube", fetchers.fetch_youtube_videos, limit=1),
            self._connector_check(
                "telegram",
                fetchers.fetch_telegram_posts_sync,
                channels=[],
                limit_per_channel=1,
                telegram_api_id=settings.telegram_api_id,
                telegram_api_hash=settings.telegram_api_hash,
                telegram_session_name=settings.telegram_session_name,
                diagnostics={},
            ),
        ]
        status = "ok" if all(check["status"] == "ok" for check in checks) else "warning"
        return {"status": status, "checks": checks}

    def _postgresql_check(self):
        start = perf_counter()
        try:
            if self.db is None:
                return self._result("postgresql", "warning", "database session not provided", start)
            self.db.execute(text("SELECT 1"))
            return self._result("postgresql", "ok", "database reachable", start)
        except Exception as exc:
            return self._result("postgresql", "error", "database check failed", start, error=exc)

    def _connector_check(self, name, fetcher, **kwargs):
        start = perf_counter()
        try:
            items = fetcher(**kwargs) or []
            return self._result(name, "ok", f"connector reachable; {len(items)} item(s) returned", start, items_found=len(items))
        except Exception as exc:
            return self._result(name, "error", "connector check failed", start, error=exc)

    def _result(self, name, status, message, start, error=None, **extra):
        result = {"name": name, "status": status, "message": message, "latency_ms": round((perf_counter() - start) * 1000, 2), **extra}
        if error:
            result["error"] = self._redact(error)
        return result

    def _redact(self, error):
        text_value = str(error)
        for secret in (settings.github_token, settings.huggingface_token, settings.telegram_api_hash):
            if secret:
                text_value = text_value.replace(str(secret), redact_secret(secret))
        return fetchers.redact_sensitive_text(text_value)
