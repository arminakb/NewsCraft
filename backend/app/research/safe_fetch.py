from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.safe_http import (
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    SafeHttpClient,
    SafeHttpError,
)
from app.discovery.article_extractor import extract_article
from app.discovery.models import DiscoveryItem, ExtractedArticle
from app.research.schemas import DiscoveredSourcePayload
from app.stories.evidence import build_evidence_key

type Resolver = Callable[[str], Awaitable[Sequence[str]]]
type ArticleExtractor = Callable[[Any, DiscoveryItem], Awaitable[ExtractedArticle]]


class SafeArticleFetchError(RuntimeError):
    """A typed, fixed-message failure safe to expose outside the fetch boundary."""


class SafeArticleFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        extractor: ArticleExtractor = extract_article,
    ) -> None:
        self._resolver = resolver
        self._transport = transport
        self._extractor = extractor

    async def fetch(self, url: str) -> DiscoveredSourcePayload:
        client_options: dict[str, Any] = {
            "max_redirects": MAX_REDIRECTS,
            "max_response_bytes": MAX_RESPONSE_BYTES,
        }
        if self._resolver is not None:
            client_options["resolver"] = self._resolver
        if self._transport is not None:
            client_options["transport"] = self._transport

        item = DiscoveryItem(
            source_platform="research",
            source_name="",
            external_id=url,
            title="",
            url=url,
            summary="",
            published_at=None,
            image_url=None,
            author=None,
            metadata={},
        )
        try:
            async with SafeHttpClient(**client_options) as client:
                try:
                    article = await self._extractor(client, item)
                except SafeHttpError:
                    raise
                except Exception as exc:
                    raise SafeArticleFetchError("Article extraction failed") from exc
                try:
                    extracted_final_url = article.final_url
                except Exception as exc:
                    raise SafeArticleFetchError("Article materialization failed") from exc
                final_url = await client.validate_public_url(extracted_final_url)
        except SafeArticleFetchError:
            raise
        except SafeHttpError as exc:
            raise _mapped_fetch_error(exc) from exc
        except httpx.HTTPError as exc:
            raise SafeArticleFetchError("Article fetch failed") from exc
        except Exception as exc:
            raise SafeArticleFetchError("Article fetch failed") from exc

        try:
            if article.extraction_status not in {"ok", "fallback"}:
                raise SafeArticleFetchError("Article extraction failed")
            content_text = " ".join(article.content_text.split())
            if not content_text:
                raise SafeArticleFetchError("Article extraction failed")
            content_sha256 = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
            return DiscoveredSourcePayload(
                evidence_key=build_evidence_key(
                    content_item_id=None,
                    source_url=final_url,
                    content_sha256=content_sha256,
                ),
                url=final_url,
                title=" ".join(article.title.split()) or None,
                publisher=None,
                published_at=article.published_at,
                retrieved_at=datetime.now(UTC),
                content_text=content_text,
                content_sha256=content_sha256,
                extraction_status=article.extraction_status,
            )
        except SafeArticleFetchError:
            raise
        except Exception as exc:
            raise SafeArticleFetchError("Article materialization failed") from exc


def _mapped_fetch_error(exc: SafeHttpError) -> SafeArticleFetchError:
    message = str(exc)
    if message == "Manual URL request rejected":
        return SafeArticleFetchError("Article fetch rejected")
    if message == "Too many manual URL redirects":
        return SafeArticleFetchError("Too many article redirects")
    if message == "Manual URL response is too large":
        return SafeArticleFetchError("Article response is too large")
    return SafeArticleFetchError("Article fetch failed")


__all__ = ["SafeArticleFetchError", "SafeArticleFetcher"]
