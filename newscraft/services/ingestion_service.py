from newscraft.connectors import get_connector_fetchers
from newscraft.repositories.article_repository import ArticleRepository
from newscraft.repositories.ingestion_run_repository import IngestionRunRepository
from newscraft.services.normalization_service import normalize_article
from newscraft.services.ranking_service import classify_and_score


DEFAULT_SOURCES = ["rss", "hacker_news", "arxiv"]


class IngestionService:
    def __init__(self, db, connector_fetchers=None, article_repo=None, run_repo=None):
        self.db = db
        self.connector_fetchers = connector_fetchers or get_connector_fetchers()
        self.article_repo = article_repo or ArticleRepository(db)
        self.run_repo = run_repo or IngestionRunRepository(db)

    def run(self, selected_sources=None, **kwargs):
        selected_sources = selected_sources or DEFAULT_SOURCES
        run = self.run_repo.create(selected_sources)
        fetched_total = saved_total = duplicate_total = failed_total = 0
        errors = []

        for source in selected_sources:
            fetcher = self.connector_fetchers.get(source)
            if not fetcher:
                failed_total += 1
                errors.append(f"unknown source: {source}")
                continue
            try:
                items = fetcher(**self._fetch_kwargs(source, kwargs)) or []
            except Exception as exc:
                failed_total += 1
                errors.append(f"{source}: {exc}")
                self.run_repo.log_source(run.id, source_name=source, status="failed", error_message=str(exc), failed_count=1)
                continue

            fetched_total += len(items)
            saved = 0
            skipped_malformed = 0
            for item in items:
                normalized = normalize_article(item)
                if not normalized:
                    skipped_malformed += 1
                    continue
                normalized["connector"] = normalized.get("connector") or source
                normalized["source_type"] = normalized.get("source_type") or source
                ranked = classify_and_score(normalized)
                before_id = self.article_repo._find_existing(self.article_repo._values(ranked))
                self.article_repo.upsert(ranked)
                if before_id:
                    duplicate_total += 1
                else:
                    saved += 1
            saved_total += saved
            self.run_repo.log_source(
                run.id,
                source_name=source,
                status="succeeded",
                fetched_count=len(items),
                saved_count=saved,
                log_metadata={"skipped_malformed": skipped_malformed},
            )

        return self.run_repo.finish(
            run,
            status="failed" if errors and not saved_total else "succeeded",
            total_fetched=fetched_total,
            total_saved=saved_total,
            total_duplicates=duplicate_total,
            total_failed=failed_total,
            error_message="; ".join(errors) or None,
        )

    def list_runs(self, limit=50):
        return self.run_repo.list(limit=limit)

    def get_run(self, run_id: int):
        return self.run_repo.get(run_id)

    def _fetch_kwargs(self, source, values):
        allowed = {
            "rss": {"start_date", "end_date", "diagnostics"},
            "hacker_news": {"start_date", "end_date", "limit", "diagnostics"},
            "arxiv": {"start_date", "end_date", "limit", "diagnostics"},
            "github": {"start_date", "end_date", "limit", "github_token", "diagnostics"},
            "huggingface": {"start_date", "end_date", "limit", "huggingface_token"},
            "youtube": {"start_date", "end_date", "limit", "youtube_api_key"},
            "telegram": {
                "channels",
                "start_datetime",
                "end_datetime",
                "limit_per_channel",
                "telegram_api_id",
                "telegram_api_hash",
                "telegram_session_name",
                "diagnostics",
            },
        }.get(source, set(values))
        return {key: value for key, value in values.items() if key in allowed}
