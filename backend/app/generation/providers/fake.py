from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from app.generation.providers.base import GenerationProviderRequest, GenerationProviderResult


class DeterministicFakeProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        output: Mapping[str, Any] | None = None,
        resolved_model: str | None = None,
    ) -> None:
        self._output = deepcopy(dict(output)) if output is not None else None
        self._resolved_model = resolved_model

    async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult:
        output = deepcopy(self._output)
        if output is None:
            output = _default_output(request)
        return GenerationProviderResult(
            provider=self.provider_name,
            requested_model=request.requested_model,
            resolved_model=self._resolved_model or request.requested_model or "fake-v1",
            output=output,
            raw_text=json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            usage={"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
            finish_reason="stop",
        )


def _default_output(request: GenerationProviderRequest) -> dict[str, Any]:
    if request.purpose == "canonical_story":
        evidence = _input_json(
            request,
            input_key="evidence_json",
            fallback_marker="Persisted evidence JSON: ",
        )
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("fake canonical generation requires persisted evidence")
        source = next(
            (item for item in evidence if isinstance(item, dict) and str(item.get("content_text") or "")),
            None,
        )
        if source is None:
            raise ValueError("fake canonical evidence content is missing")
        content = str(source["content_text"])
        citation = {
            "evidence_key": source["evidence_key"],
            "evidence_snapshot_id": source["evidence_snapshot_id"],
            "source_url": source.get("source_url"),
            "locator": f"chars:0-{len(content)}",
            "excerpt_sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
        return {
            "headline": "Deterministic acceptance story",
            "narrative": (
                "The supplied immutable evidence confirms this deterministic NewsCraft "
                "acceptance story and keeps every generated platform package source-bound."
            ),
            "facts": [
                {
                    "text": "The supplied source confirms the deterministic acceptance story.",
                    "citations": [citation],
                }
            ],
            "disagreements": [],
            "angles": ["Explain the verified source-backed acceptance flow."],
            "missing_information": [],
        }
    if request.purpose in {"telegram_rewrite", "telegram_pack"}:
        return {"body": "Deterministic Telegram rewrite", "parse_mode": "HTML", "buttons": []}
    if request.purpose in {"instagram_pack", "x_pack", "blog_pack"}:
        canonical = _input_json(
            request,
            input_key="canonical_story_json",
            fallback_marker="Canonical story JSON: ",
        )
        citation = _canonical_citation(canonical)
        return _manual_platform_output(request.purpose, citation)
    return {"status": "ok"}


def _input_json(
    request: GenerationProviderRequest,
    *,
    input_key: str,
    fallback_marker: str,
) -> object:
    input_payload = request.metadata.get("input_payload")
    if isinstance(input_payload, dict) and input_key in input_payload:
        raw = input_payload[input_key]
        if not isinstance(raw, str):
            return deepcopy(raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"fake provider could not parse structured {input_key}") from exc
    return _message_json(request, fallback_marker)


def _message_json(request: GenerationProviderRequest, marker: str) -> object:
    for message in request.messages:
        if marker not in message.content:
            continue
        tail = message.content.split(marker, 1)[1].lstrip()
        try:
            value, _end = json.JSONDecoder().raw_decode(tail)
        except json.JSONDecodeError as exc:
            raise ValueError(f"fake provider could not parse {marker.strip()}") from exc
        return value
    raise ValueError(f"fake provider input is missing {marker.strip()}")


def _canonical_citation(canonical: object) -> dict[str, Any]:
    if not isinstance(canonical, dict):
        raise ValueError("fake platform generation requires a canonical story")
    facts = canonical.get("facts")
    if not isinstance(facts, list) or not facts or not isinstance(facts[0], dict):
        raise ValueError("fake platform generation requires canonical facts")
    citations = facts[0].get("citations")
    if not isinstance(citations, list) or not citations or not isinstance(citations[0], dict):
        raise ValueError("fake platform generation requires a canonical citation")
    return deepcopy(citations[0])


def _manual_platform_output(purpose: str, citation: dict[str, Any]) -> dict[str, Any]:
    if purpose == "instagram_pack":
        return {
            "hook": "The verified acceptance story is confirmed",
            "caption": (
                "The immutable source snapshot confirms the deterministic acceptance story "
                "and keeps this package grounded in reviewed evidence."
            ),
            "cta": "Review the cited source before publishing.",
            "hashtags": ["#NewsCraft", "#VerifiedNews"],
            "alt_text": "A summary card describing the verified acceptance story.",
            "carousel": [
                {
                    "order": 1,
                    "headline": "Acceptance story confirmed",
                    "body": "The cited source confirms the deterministic acceptance story.",
                    "media": {
                        "media_asset_id": None,
                        "role": "slide",
                        "order": 1,
                        "alt_text": "A text card stating that the acceptance story is confirmed.",
                        "manual_brief": "Create a simple source-backed summary card.",
                        "image_prompt": None,
                    },
                }
            ],
            "citations": [citation],
            "manual_checklist": ["Verify carousel order and source attribution before publishing"],
        }
    if purpose == "x_pack":
        return {
            "mode": "single",
            "posts": [
                {
                    "order": 1,
                    "text": (
                        "The immutable source confirms the deterministic acceptance story. "
                        "Review the cited evidence before publishing."
                    ),
                    "media": [],
                    "citations": [citation],
                }
            ],
            "link_strategy": "last_post",
            "manual_checklist": ["Verify the post and source link before publishing"],
        }
    if purpose == "blog_pack":
        source_url = citation.get("source_url")
        return {
            "title": "The verified acceptance story and its source evidence",
            "slug": "verified-acceptance-story-source-evidence",
            "excerpt": "A concise source-backed account of the deterministic acceptance story.",
            "body_markdown": (
                "## What the source confirms\n\n"
                + "The immutable source snapshot confirms the deterministic acceptance story. " * 8
            ),
            "headings": ["What the source confirms"],
            "citations": [citation],
            "tags": ["acceptance", "verification"],
            "seo_description": (
                "A verified account of the deterministic acceptance story, grounded in an "
                "immutable source snapshot and prepared for manual publication."
            ),
            "hero_media": None,
            "canonical_sources": [source_url] if source_url is not None else [],
            "manual_checklist": ["Verify the article, canonical source, and SEO fields"],
        }
    raise ValueError(f"unsupported fake platform purpose: {purpose}")
