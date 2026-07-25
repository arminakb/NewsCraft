# Articles data and UX contract

Status: Phase 1 architectural proposal
Date: 2026-07-21
Scope: documentation only; no application, API, schema, or navigation changes

## Decisions

1. **Canonical Articles record:** a composed API view anchored on `ContentItem.id`.
2. **Editorial relationship:** zero or more immutable `StoryEvidenceSnapshot` rows connect a content item to stories. Story state and completeness remain story-level data.
3. **Collection persistence:** workspace-global named Collections supersede `ArticleMark`. Story `shortlisted` state remains separate.
4. **API direction:** add summary/detail Articles endpoints rather than turning the existing raw `/content-items` endpoint into the operator contract.
5. **Old routes:** keep Inbox, Content, and Library until replacement workflows pass later visual and behavioral review.

## Why `ContentItem` is canonical

`ContentItem` owns every required article-list property: normalized title, summary/body, canonical URL, publication/sort time, score, content type, taxonomy metadata, language/direction, readiness, source reference, and primary image reference. It exists at ingestion time and is deduplicated using identities.

`Story` is a later editorial aggregate. It groups one or more immutable evidence snapshots, owns editorial state, completeness, research, revisions, and generation. It does not own score, content type, topic, source, or primary image. Using Story as the Articles identity would hide ungrouped content and force article organization to inherit story-level workflow semantics.

`GET /library/originals` is a reduced read-only projection of `ContentItem`; it omits summary, score, classification, language, image, and detail fields. It is unsuitable as the new primary contract.

## Entity relationships

```text
Source 1 ─── * SourceItem * ─── 1 ContentItem
                                      │
                                      ├── primary_image_id ── 0..1 MediaAsset
                                      ├── 1 ─── * ItemMedia * ─── 1 MediaAsset
                                      ├── 0..* StoryEvidenceSnapshot * ─── 1 Story
                                      │                                      │
                                      │                                      ├── StoryRevision
                                      │                                      ├── ResearchRun
                                      │                                      └── ContentPack workflow
                                      └── 0..* ArticleCollectionItem * ─── 1 ArticleCollection
```

Relationship constraints:

- `ContentItem.primary_source_id` points to canonical source metadata.
- `ContentItem.primary_image_id` is a selected media reference; `ItemMedia` preserves all attachments and roles.
- `StoryEvidenceSnapshot.content_item_id` may be null for manual or research evidence.
- Database schema does not enforce one active story per content item. Live data currently has exactly one active story for every one of 3,142 content items, but API design must not assume this remains true.
- Evidence snapshots copy article text and provenance immutably. Article detail should not substitute current `ContentItem` text for historical evidence.

## Current API findings

### `/content-items`

Current list endpoint:

- Returns a plain array, not a page envelope.
- Caps `limit` at 250 and has no cursor, offset, total, or next-page token.
- Returns full `content_text` and `content_html_sanitized` on every list row, producing an unnecessarily large browsing payload.
- Loads `primary_media`.
- Does not join `Source`; current frontend derives source name/platform from denormalized `classification_metadata`.

Supported query parameters:

- `status`
- `content_type`
- `rewrite_bucket`
- `is_rewrite_ready`
- `source_tier`
- `quality_status`
- `sort=latest|score`
- `limit`

### `/stories`

Current endpoint is cursor-paginated and supports title search, editorial state, completeness, and superseded inclusion. Completeness is calculated from Story evidence, not ContentItem readiness.

Story mutations and workflow actions:

- `PATCH /stories/{story_id}/editorial-state`
- `POST /stories/bulk-editorial-state`
- `POST /stories/{story_id}/research-runs`
- `POST /stories/{story_id}/content-packs`
- `POST /stories/group-pending`
- `POST /stories/manual`

### Library

Library is read-only lookup/history:

- Originals: reduced cursor-paginated ContentItem projection.
- Stories: same story projection used by Inbox.
- Evidence: immutable evidence snapshots.
- Research runs: durable historical outcomes and errors.
- Drafts/content packs: generated editorial artifacts.
- Exports and publications: historical handoff/outcome records.

Evidence, research runs, exports, and publications remain archive/history capabilities. Library Originals overlap Articles and can eventually become a link or redirect only after Articles is validated. Library must retain historical records unavailable from an article row.

## Proposed Articles API

Add a dedicated composed read model. Keep existing endpoints unchanged for compatibility.

### List

```http
GET /articles?q=&source_id=&date_from=&date_to=&score_min=&score_max=
  &content_type=&topic=&domain=&language=&coverage=&has_image=
  &collection_id=&sort=newest|score|relevance&cursor=&limit=
```

Response:

```json
{
  "items": [],
  "next_cursor": null,
  "result_count": 0
}
```

Rules:

- Identity is `ContentItem.id`.
- List rows exclude full body and sanitized HTML.
- Source fields come from joined `Source`; classification metadata is fallback only for legacy/null-source records.
- `display_at` is `published_at` when present, otherwise `sort_at`; `date_basis` states `published` or `collected`.
- Date filters use the same `display_at` expression, inclusive start and exclusive end, with timezone-aware ISO-8601 input.
- `has_image=true` means a non-expired primary media row whose kind is `image`; `remote_only` is usable.
- Topic is normalized taxonomy category currently stored at `metrics.classification.category`.
- Domain is source domain currently stored at `classification_metadata.source_domain`.
- Coverage is explicit, not overloaded:
  - `ungrouped`: no active linked Story.
  - `incomplete`: at least one active linked Story and none complete.
  - `complete`: at least one active linked Story is complete.
- Return every active Story link. Never select an arbitrary single Story when schema permits several.
- `sort=relevance` is valid only with non-empty `q`.
- Cursor encodes every sort key plus `ContentItem.id`; filter changes invalidate cursor.
- `result_count` must use same predicates as page query. It may be computed separately but cannot be an estimate presented as exact.

### Detail

```http
GET /articles/{content_item_id}
```

Detail adds:

- full `content_text`
- sanitized body representation when needed
- authors and tags
- canonical/original URL
- primary and attached media
- article readiness details
- all active and historical Story links
- immutable evidence identifiers and focused evidence links
- current research/generation state reachable through existing Story APIs
- technical metadata under an `advanced` object, not mixed into primary fields

### Facets

Phase 3 needs valid filter choices. Add either `GET /articles/facets` or a `facets` block on the first page. Values must come from persisted data and use the same base visibility rules as `/articles`. Do not hard-code category, language, content-type, source, or domain options in the browser.

## Filter support matrix

| Desired filter/sort | Current server support | Required change |
| --- | --- | --- |
| Search | Story title only; not ContentItem | Add server-side title/summary/body search and relevance rank. Use multilingual-safe PostgreSQL strategy; do not client-filter. |
| Source | No ContentItem filter | Join/filter `primary_source_id`; expose source facets. |
| Date range | No | Filter `coalesce(published_at, sort_at)` with explicit bounds. |
| Score | Sort only | Add validated `score_min` and `score_max`. |
| Content type | Yes | Carry into Articles contract and facet values. |
| Topic | No | Filter normalized taxonomy category; avoid raw JSON contract leaking to client. |
| Domain | No | Filter normalized source domain; define canonical casing. |
| Language | No | Filter `language_code`; include null/unknown behavior explicitly. |
| Coverage/completeness | Story endpoint only | Join all active Story links and calculate aggregate coverage as defined above. Keep ContentItem rewrite readiness separate. |
| Has image | No | Filter usable primary image existence. |
| Newest | Yes, but no cursor | Add stable keyset pagination on `display_at`, then ID. |
| Score | Yes, but no cursor | Add stable keyset pagination on score, `display_at`, then ID. |
| Relevance | No | Add ranked search; reject relevance without query. |
| Collection | No | Filter by `collection_id`; unknown collection returns 404. |

## Article detail data sources

| Detail section | Source |
| --- | --- |
| Identity, title, summary, body, URL, authors, tags, language/direction | `ContentItem` |
| Source name/platform/group/homepage | joined `Source` via `primary_source_id` |
| Primary image | `ContentItem.primary_image_id` joined to `MediaAsset` |
| Other images/media | `ItemMedia` joined to `MediaAsset`, ordered by role and `sort_order` |
| Score and operator classification | `ContentItem.score`, `content_type`, normalized topic/domain |
| Item readiness | `is_rewrite_ready`, reason, blockers |
| Story coverage and editorial state | all active linked `Story` rows plus computed story summaries |
| Immutable source evidence | `StoryEvidenceSnapshot`; never regenerated from current item body |
| Research status/results | Story-scoped `ResearchRun`, attempts, and sources |
| Generated work | Story revisions, content packs, variants, exact revision APIs |
| Saved state | `ArticleCollectionItem` memberships keyed by ContentItem ID |

## Inbox capabilities to preserve

Articles/detail must keep these reachable once Inbox is eventually retired:

- Add manual URL/text.
- Group pending content through durable job.
- See active Story association and completeness.
- Change Story editorial state, including reject.
- Start standard/deep research with available provider.
- Bind completed research run to generation.
- Generate content pack with explicit brand/provider/prompt versions.
- Open existing editorial studio/draft.
- Preserve bulk Story-state changes only where selected rows resolve unambiguously to active stories.

Collection membership does not replace Reject and does not automatically shortlist a Story.

## Operator-facing versus diagnostic fields

Primary operator fields:

- title, summary, source, date/date basis, score
- content type, topic, domain, language
- primary image
- coverage and saved collection state
- original link, authors/tags where useful

Advanced/diagnostic fields:

- raw ContentItem status and item type
- rewrite bucket, source tier, freshness bucket, quality status
- rewrite reasons/blockers and classification reasons
- score breakdown, raw metrics, raw classification metadata
- media confidence, fetch status, extraction role/source
- hashes, internal IDs, evidence keys, timestamps used for audit
- sanitized HTML representation

Diagnostic fields remain available in Content or Article detail Advanced disclosure. They should not dominate list rows.

## Required future backend work

Not implemented in Phase 1:

1. Composed `/articles` summary and detail endpoints.
2. Keyset pagination, exact result count, facets, search, desired filters, and stable sorting.
3. Explicit response schemas that avoid raw JSON metadata as frontend contract.
4. Named Collection migration/model/API and retention protection. Implemented in Session 4A.
5. Efficient bulk Story completeness projection for article pages.
6. Tests for filtering, cursor stability, source joins, multi-story links, missing dates/images, Persian search, Collection membership idempotency, and retention.

## Risks and unknowns

- Search implementation must support Persian and English. Existing indexes do not establish a search strategy; benchmark PostgreSQL full-text/trigram options before choosing.
- Current topic/domain values live inside JSON. Query performance may need expression indexes or normalized columns after measuring real plans.
- Schema permits multiple active stories per content item even though live data currently has one. Product must define action selection if this occurs; API must expose all links now.
- Some content items may have no source, publication time, summary, image, or Story. Empty values need truthful fallbacks, not fabricated metadata.
- `normalized_url` may be remote-only. Frontend image policy, SSR behavior, and failure fallback need Phase 2 browser verification.
- Exact result counts can become costly at large scale; current requirement says result count, but performance threshold needs measurement.
- Multi-user identity/authorization is absent from current product model. Collections are workspace-global until user accounts exist.
- Retention behavior protects saved content and referenced primary media.
- Whether ContentItem approval remains a daily action or advanced ingestion/recovery action needs operator confirmation. It remains available on `/content` meanwhile.

## Evidence inspected

- `backend/app/db/models.py`
- `backend/app/stories/models.py`
- `backend/app/research/models.py`
- `backend/app/api/content.py`
- `backend/app/api/stories.py`
- `backend/app/api/content_packs.py`
- `backend/app/api/library.py`
- `backend/app/api/media.py`
- `backend/app/api/schemas.py`
- `backend/app/ingestion/repository.py`
- `frontend/lib/api-client.ts`
- `frontend/lib/editorial-api.ts`
- `frontend/features/library/api.ts`
- `frontend/components/dashboard/pages/content-items-page.tsx`
- `frontend/components/editorial/story-inbox.tsx`
- Live local API payloads and read-only PostgreSQL counts on 2026-07-21.
