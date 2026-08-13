# Articles field map

Status: Historical (2026-08-13) — Phase 1 contract, retained for its
persistence-mapping column, which the shipped API contract does not carry. The
`/articles` surface shipped (`backend/app/api/articles.py`, browser route
`/feed`); for the authoritative request/response shape read
`contracts/openapi.json`, which is drift-gated by
`backend/tests/test_openapi_contract.py`.
Canonical identity: `ContentItem.id`

## List fields

| Articles field | Current persistence | Current API availability | Contract decision |
| --- | --- | --- | --- |
| `id` | `ContentItem.id` | `/content-items` | Stable article ID. |
| `title` | `ContentItem.title` | Yes, nullable | Display `Untitled article` only as UI fallback; preserve null in API. |
| `summary` | `ContentItem.summary` | Yes, nullable | Use short summary. API may provide bounded body excerpt separately when summary is absent; never send full body in list. |
| `source.id` | `ContentItem.primary_source_id` | ID only | Join `Source`; nullable for manual/legacy records. |
| `source.name` | `Source.name` | Only denormalized `classification_metadata.source_name` today | Joined Source is authoritative; metadata is legacy fallback. |
| `source.platform` | `Source.platform` | Only denormalized metadata today | Joined Source is authoritative. |
| `source.url` | `ContentItem.canonical_url`, then Source homepage/feed for context | Canonical URL yes | Article original action uses canonical URL. Source identity link may use Source homepage. Keep meanings separate. |
| `published_at` | `ContentItem.published_at` | Yes, nullable | Preserve exact publication time. |
| `sort_at` | `ContentItem.sort_at` | Yes | Stable ingestion ordering fallback. |
| `display_at` | Derived | No | `published_at ?? sort_at`. |
| `date_basis` | Derived | No | `published` when published time exists; otherwise `collected`. UI must label fallback truthfully. |
| `score` | `ContentItem.score` | Yes | Integer score; expose filter bounds from API rules, not assumed UI range. |
| `content_type` | `ContentItem.content_type` | Yes | Operator-facing classification. Values observed live: article, research, tutorial, tool_update, news, vendor_update, promo, longform, video. Facet dynamically. |
| `topic` | `ContentItem.metrics.classification.category` | Raw metrics only | Normalize into first-class response string. Values observed live: AI, Economy, Tech, News, General. |
| `domain` | `ContentItem.classification_metadata.source_domain` | Raw metadata only | Normalize into first-class response string; lowercase host without credentials/port. |
| `language` | `ContentItem.language_code` | Yes | Preserve nullable value; observed `en` and `fa`. Do not default unknown to English in API. |
| `direction` | `ContentItem.direction` | Yes | Use for isolated title/summary direction boundary. Validate `ltr`, `rtl`, or null. |
| `coverage.state` | Active linked Stories plus computed completeness | Not on ContentItem API | `ungrouped`, `incomplete`, or `complete` using documented aggregate rule. |
| `coverage.stories` | `StoryEvidenceSnapshot.content_item_id` to Story | Separate Story APIs | Return all active story IDs, titles, states, and completeness summaries. |
| `article_readiness` | `is_rewrite_ready`, reason, blockers | Yes | Separate from Story coverage. Show compactly only when action is blocked; full detail under Advanced. |
| `image` | `primary_image_id` to `MediaAsset` | `primary_media` yes | Return ID, URL, kind, dimensions, alt text, fetch status. Reserve aspect-ratio space and provide fallback. |
| `has_image` | Derived from live primary media | No | True only for non-expired primary media with `kind=image`. |
| `saved` | Derived from `ArticleCollectionItem` existence | Yes | True when article belongs to at least one Collection. |
| `saved_collection_ids` | `ArticleCollectionItem.collection_id` | Yes | Deterministic list of every Collection containing article. |

## Detail-only fields

| Detail field | Persistence/API source | Presentation |
| --- | --- | --- |
| Full text | `ContentItem.content_text` | Primary readable body when available. Preserve direction. |
| Sanitized HTML | `ContentItem.content_html_sanitized` | Render only through existing safe HTML boundary; do not expose as default list field. |
| Authors | `ContentItem.authors` | Human-readable metadata. |
| Tags | `ContentItem.tags` | Secondary metadata; collapse long lists. |
| Original link | `ContentItem.canonical_url` | External link with safe protocol and new-tab disclosure. |
| All media | `ItemMedia` plus `MediaAsset` | Ordered gallery/attachments; roles and diagnostics under Advanced. |
| Active Story links | Evidence snapshot join to active Stories | Show editorial state, completeness, research/generation actions. |
| Historical Story links | Evidence snapshot join including superseded Stories | Advanced/history section. |
| Evidence | `StoryEvidenceSnapshot` | Immutable title/text/source/hash/captured time. Link to focused evidence. |
| Research | Story-scoped research APIs | Status, provider, budget, sources, resulting revision. |
| Generated work | Content pack/revision APIs | Open existing draft/studio/review routes. |
| Technical metadata | ContentItem scoring/classification/readiness fields | Advanced disclosure, collapsed by default. |

## Fields not to conflate

| Pair | Difference |
| --- | --- |
| ContentItem vs Story | Collected normalized item versus editorial grouping/workflow aggregate. |
| `status` vs editorial state | ContentItem ingestion approval (`new`/`approved`) versus Story workflow (`inbox`/`shortlisted`/`rejected`/`drafted`). |
| Article readiness vs Story completeness | Suitability for rewrite based on one item versus coverage across immutable Story evidence. |
| Collections vs Shortlist | ContentItem organization versus editorial state transition on Story. |
| Source URL vs source homepage | Original article location versus publisher/source identity location. |
| Primary image vs any media | Selected image for list/detail hero versus all attached images/video. |
| Current body vs evidence snapshot | Mutable normalized ContentItem body versus immutable evidence captured for a Story. |

## Proposed summary response shape

```json
{
  "id": "uuid",
  "title": "string or null",
  "summary": "string or null",
  "excerpt": "bounded string or null",
  "source": {
    "id": "uuid or null",
    "name": "string or null",
    "platform": "string or null",
    "homepage_url": "https URL or null"
  },
  "canonical_url": "https URL or null",
  "published_at": "timestamp or null",
  "sort_at": "timestamp",
  "display_at": "timestamp",
  "date_basis": "published",
  "score": 59,
  "content_type": "article",
  "topic": "AI",
  "domain": "example.com",
  "language": "en",
  "direction": "ltr",
  "coverage": {
    "state": "incomplete",
    "stories": [
      {
        "id": "uuid",
        "title": "string",
        "editorial_state": "inbox",
        "complete": false,
        "score": 25
      }
    ]
  },
  "article_readiness": {
    "ready": true
  },
  "image": {
    "id": "uuid",
    "url": "https URL",
    "kind": "image",
    "width": 1152,
    "height": 648,
    "alt_text": "string or null",
    "fetch_status": "remote_only"
  },
  "has_image": true,
  "saved": false,
  "saved_collection_ids": []
}
```

`date_basis` may also be `collected`. `source`, `image`, topic/domain, and coverage Story list may contain null/empty values. Response schema must define exact keys and reject accidental raw metadata expansion.

## Existing Content fields kept out of primary list

- `item_type`
- raw ContentItem `status`
- `rewrite_bucket`
- `rewrite_ready_reason`
- `rewrite_blockers`
- `classification_reasons`
- `source_tier`
- `freshness_bucket`
- `quality_status`
- `score_breakdown`
- raw `metrics`
- raw `classification_metadata`
- `content_html_sanitized`
- media confidence, quality, storage path, extraction source, and role

These stay available through Content or Article detail Advanced disclosure. A blocking readiness state may surface contextually when operator attempts Research/Generate.
