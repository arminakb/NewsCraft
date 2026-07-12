from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from app.content_production.evidence import evaluate_enrichment_relevance, relevant_enrichment_findings
from app.content_production.idempotency import artifact_id, create_or_get_artifact
from app.content_production.repository import ContentProductionRepository
from app.content_production.states import WorkflowState
from app.db.models import ArticleExtractionResult, ContentItem, ContentProductionRun, WebEnrichmentResult
from app.discovery.article_extractor import extract_article
from app.discovery.models import DiscoveryItem


@dataclass(frozen=True)
class EnrichmentQuery:
    title: str | None
    source_name: str | None
    source_url: str | None
    source_domain: str | None
    published_date: str | None
    author: str | None = None

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "published_date": self.published_date,
            "author": self.author,
        }


@dataclass(frozen=True)
class EnrichmentFinding:
    title: str
    url: str
    snippet: str
    source_name: str | None = None
    published_at: str | None = None
    reliability: str = "unverified"

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "source_name": self.source_name,
            "published_at": self.published_at,
            "reliability": self.reliability,
        }


@dataclass(frozen=True)
class EnrichmentResponse:
    status: str
    findings: list[EnrichmentFinding] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error_message: str | None = None


class WebEnrichmentProvider(Protocol):
    provider_name: str

    async def search(self, query: EnrichmentQuery) -> EnrichmentResponse:
        ...


class ArticleExtractionProvider(Protocol):
    provider_name: str

    async def extract(self, item: DiscoveryItem):
        ...


class NullWebEnrichmentProvider:
    provider_name = "none"

    async def search(self, query: EnrichmentQuery) -> EnrichmentResponse:
        return EnrichmentResponse(
            status="skipped",
            warnings=["no_enrichment_provider_configured"],
        )


class ArticleExtractionService:
    def __init__(
        self,
        session,
        client: httpx.AsyncClient | None = None,
        provider: ArticleExtractionProvider | None = None,
    ):
        self.session = session
        self.client = client
        self.provider = provider

    async def extract_for_run(
        self,
        run: ContentProductionRun,
        item: ContentItem,
        *,
        command_id: uuid.UUID | None = None,
    ) -> ArticleExtractionResult:
        result_id = artifact_id(command_id or run.id, "article_extraction_result")

        async def create() -> ArticleExtractionResult:
            repository = ContentProductionRepository(self.session)
            if run.state in {WorkflowState.SUFFICIENCY_PARTIAL.value, WorkflowState.SUFFICIENCY_INSUFFICIENT.value}:
                await repository.transition_run(
                    run,
                    WorkflowState.ARTICLE_EXTRACTING,
                    current_step="article_extraction",
                )

            if not item.canonical_url:
                result = _failed_extraction_result(run, item, "missing_source_url", result_id=result_id)
                self.session.add(result)
                await self.session.flush()
                return result

            if self.provider is not None:
                article = await self.provider.extract(_to_discovery_item(item))
            elif self.client is not None:
                article = await extract_article(self.client, _to_discovery_item(item))
            else:
                from app.content_production.providers import SafeArticleExtractionProvider

                article = await SafeArticleExtractionProvider().extract(_to_discovery_item(item))

            result = ArticleExtractionResult(
                id=result_id,
                production_run_id=run.id,
                content_item_id=item.id,
                status=article.extraction_status,
                source_url=article.url,
                final_url=article.final_url,
                title=article.title,
                summary=article.summary,
                content_text=article.content_text,
                author=article.author,
                published_at=article.published_at,
                image_url=article.image_url,
                warnings_json=article.extraction_warnings,
                metadata_json={"truth_priority": "original_source_url"},
                error_message=(
                    None if article.extraction_status != "failed" else ", ".join(article.extraction_warnings)
                ),
            )
            self.session.add(result)
            await self.session.flush()
            if result.status in {"ok", "fallback"}:
                await repository.transition_run(run, WorkflowState.ARTICLE_EXTRACTED, current_step="article_extraction")
            return result

        return await create_or_get_artifact(self.session, ArticleExtractionResult, result_id, create)


class WebEnrichmentService:
    def __init__(self, session, provider: WebEnrichmentProvider | None = None):
        self.session = session
        self.provider = provider or NullWebEnrichmentProvider()

    async def enrich_run(
        self,
        run: ContentProductionRun,
        item: ContentItem,
        *,
        command_id: uuid.UUID | None = None,
    ) -> WebEnrichmentResult:
        result_id = artifact_id(command_id or run.id, "web_enrichment_result")

        async def create() -> WebEnrichmentResult:
            repository = ContentProductionRepository(self.session)
            if run.state in {
                WorkflowState.SUFFICIENCY_PARTIAL.value,
                WorkflowState.SUFFICIENCY_INSUFFICIENT.value,
                WorkflowState.ARTICLE_EXTRACTED.value,
            }:
                await repository.transition_run(run, WorkflowState.ENRICHING, current_step="web_enrichment")

            query = build_enrichment_query(item)
            response = await self.provider.search(query)
            assessed_findings = evaluate_enrichment_relevance(
                title=item.title,
                source_url=item.canonical_url,
                source_name=(item.classification_metadata or {}).get("source_name"),
                findings=[finding.as_dict() for finding in response.findings],
            )
            accepted_findings = relevant_enrichment_findings(assessed_findings)
            warnings = list(response.warnings)
            if response.status == "ok" and not accepted_findings:
                warnings.append("no_relevant_findings")
            result = WebEnrichmentResult(
                id=result_id,
                production_run_id=run.id,
                content_item_id=item.id,
                provider_name=self.provider.provider_name,
                status=response.status,
                query_json=query.as_dict(),
                findings_json=assessed_findings,
                source_attribution_json=[
                    {
                        "url": finding.url,
                        "source_name": finding.source_name,
                        "truth_priority": "web_enrichment_secondary",
                    }
                    for finding in response.findings
                ],
                warnings_json=warnings,
                error_message=response.error_message,
            )
            self.session.add(result)
            await self.session.flush()
            if response.status == "ok":
                await repository.transition_run(run, WorkflowState.ENRICHED, current_step="web_enrichment")
            return result

        return await create_or_get_artifact(self.session, WebEnrichmentResult, result_id, create)


def build_enrichment_query(item: ContentItem) -> EnrichmentQuery:
    source_url = item.canonical_url
    return EnrichmentQuery(
        title=item.title,
        source_name=(item.classification_metadata or {}).get("source_name"),
        source_url=source_url,
        source_domain=_domain(source_url),
        published_date=item.published_at.date().isoformat() if item.published_at else None,
        author=(item.authors or [None])[0] if item.authors else None,
    )


def _to_discovery_item(item: ContentItem) -> DiscoveryItem:
    return DiscoveryItem(
        source_platform=item.item_type,
        source_name=(item.classification_metadata or {}).get("source_name") or "content_item",
        external_id=item.canonical_url or str(item.id),
        title=item.title or "",
        url=item.canonical_url,
        summary=item.summary or "",
        published_at=item.published_at,
        image_url=None,
        author=(item.authors or [None])[0] if item.authors else None,
        categories=list(item.tags or []),
        metadata={"content_item_id": str(item.id)},
    )


def _failed_extraction_result(
    run: ContentProductionRun,
    item: ContentItem,
    warning: str,
    *,
    result_id: uuid.UUID | None = None,
) -> ArticleExtractionResult:
    return ArticleExtractionResult(
        id=result_id or uuid.uuid4(),
        production_run_id=run.id,
        content_item_id=item.id,
        status="failed",
        source_url=item.canonical_url,
        final_url=item.canonical_url,
        title=item.title,
        summary=item.summary,
        content_text=item.summary or item.title,
        author=(item.authors or [None])[0] if item.authors else None,
        published_at=item.published_at,
        image_url=None,
        warnings_json=[warning],
        metadata_json={"truth_priority": "original_source_url"},
        error_message=warning,
    )


def _domain(value: str | None) -> str | None:
    if not value or "://" not in value:
        return None
    return value.split("://", 1)[1].split("/", 1)[0].removeprefix("www.").casefold()
