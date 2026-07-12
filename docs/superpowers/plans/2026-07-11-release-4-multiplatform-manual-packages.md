# Release 4 Multi-Platform Manual Packages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate, validate, preview, edit, copy, export, schedule, and manually track complete Telegram, Instagram, X, and blog packages from one approved canonical story revision.

**Architecture:** Each platform owns a strict structured payload and validator, while the existing immutable `PlatformVariantRevision` remains the common storage and approval boundary. Export jobs render one exact revision into deterministic files; a manual publication plan references that same revision and joins reviewed Telegram schedules in one read-only calendar projection.

**Tech Stack:** Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, Markdown/HTML rendering, pytest, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright.

## Global Constraints

- Releases 0–3 are complete and all release gates pass before this plan starts.
- Platforms are exactly `telegram`, `instagram`, `x`, and `blog`.
- Instagram, X, and blog are manual publishing packages; this release does not add their credentials or live connectors.
- Telegram live publishing remains Release 2 behavior; Release 4 adds complete preview, export/copy, checklist, and calendar treatment without bypassing Telegram policy gates.
- Telegram `PlatformVariantRevision.content` remains the exact Release 2 mapping with keys `body`, `parse_mode`, `buttons`, `source_item_id`, `source_url`, `media_policy`, `media_asset_ids`, `direction`, and `dry_run`. The key is always present but `source_item_id` is nullable for grouped/manual Release 3 stories. Release 4 must not wrap, rename, or add fields to that stored mapping; citations, evidence, and manual checklist data travel beside the revision in API/package projections.
- Every package is rendered from one immutable `StoryRevision`, one `BrandProfile`, and immutable prompt versions.
- Manual-text citations may truthfully have `source_url=None`; blog canonical sources are derived only from distinct non-null citation URLs and the platform never invents a link.
- Every edit/regeneration creates an immutable `PlatformVariantRevision`; approval remains tied to exact revision ID and content hash.
- Manual publication can be marked complete only for an approved, still-current revision. Editing creates a different `pending_review` revision and never mutates the publication plan.
- JSON, Markdown, HTML, and ZIP exports include a manifest with story revision, variant revision, content hash, approval state, generated time, and evidence URLs.
- Exported HTML is sanitized; filenames never contain user-controlled path separators; media is copied only from validated local `MediaAsset.storage_path` entries.
- All platform limits live in one backend module and every validation result is persisted with the revision.
- Calendar timestamps are stored in UTC and rendered in the chosen timezone, default `Asia/Tehran`.
- Do not add AI image/video generation. Produce source-media selections, carousel/thread assignments, alt text, briefs, and prompts for manual asset work.
- Each task is test-first and ends in a focused commit; never stage credentials, generated export bundles, local media, `.superpowers/`, or unrelated files.

## Dependencies and Exclusions

This plan consumes Release 3 `CanonicalStoryOutput`, `EditorialService`, `ContentPack`, `PlatformVariant`, `PlatformVariantRevision`, `PromptTemplateVersion`, `CitationRef`, `validate_citations()`, `editorialQueryKeys`, and exact-revision approval endpoints. It consumes Release 2 `app.generation.telegram_schema.TelegramRewriteOutput`, Telegram content assembly/renderer behavior, `PublishJob`, `Publication`, and `PublishOperationReceipt` without changing their idempotency or remote-delivery behavior.

Before Task 1:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
cd ../frontend
npm run test
npm run typecheck
cd ..
git status --short
```

Expected: all gates pass and the worktree contains no unfinished Release 3 changes. This release excludes live Instagram/X/CMS publishing, social OAuth, remote analytics, AI-created images/video, automatic screenshot posting, and arbitrary ZIP file ingestion.

## File and Responsibility Map

### Backend

- `app/generation/platform_schemas.py`: complete structured payloads for all four platforms.
- `app/generation/platform_limits.py`: authoritative validation limits and X weighted-length helper.
- `app/generation/platform_validation.py`: typed validation issues and per-platform validators.
- `app/generation/platform_renderers.py`: deterministic copy/Markdown/HTML representations.
- `app/generation/multiplatform.py`: one canonical story to requested platform revisions.
- `app/generation/default_prompts.py`: idempotent active `instagram_pack`, `x_pack`, and `blog_pack` prompt versions beside Release 3 `telegram_pack`; Release 2 `telegram_rewrite` remains route-only.
- `app/generation/editorial_service.py`: profile/prompt resolution, grounded multi-platform generation, and immutable platform-matched edits.
- `app/exports/models.py`: export artifact and manifest value objects persisted in the owning workflow job result.
- `app/exports/service.py`: deterministic JSON/Markdown/HTML/ZIP building.
- `app/exports/handlers.py`: durable export job.
- `app/core/config.py` and Compose `export_data`: authoritative `/data/exports` storage shared by API downloads and the source-generation worker.
- `app/manual_publication/models.py`: manual plan/checklist state.
- `app/manual_publication/service.py`: exact-revision planning and completion rules.
- `app/manual_publication/calendar.py`: unified manual and Telegram calendar projection.
- `app/publishing/telegram/service.py`: reviewed Telegram scheduling through the existing publish job/idempotency boundary.
- `app/api/exports.py`: export creation/status/download endpoints.
- `app/api/calendar.py`: publication plans, checklist, completion, and calendar endpoints.
- `app/api/telegram_drafts.py`: exact-revision Telegram schedule endpoint beside Release 2 review/publish actions.
- `app/api/library.py`: cursor-paginated Evidence and Research library resources over existing Release 1/3 records.

### Frontend

- `features/packages/types.ts`: platform payload, validation, export, checklist, and calendar types.
- `features/packages/api.ts`: typed package/export/manual-plan requests.
- `features/packages/components/platform-preview.tsx`: Telegram/Instagram/X/blog preview dispatcher.
- `features/packages/components/platform-editor.tsx`: schema-specific immutable revision editor.
- `features/packages/components/copy-export-actions.tsx`: clipboard and export job outcomes.
- `features/packages/components/media-plan.tsx`: source-media selection and manual asset briefs.
- `features/calendar/publication-calendar.tsx`: timezone-aware month/list calendar.
- `app/calendar/page.tsx`: reviewed Telegram plus planned manual posts.

---

### Task 1: Define complete platform payload schemas and validation limits

**Files:**
- Create: `backend/app/generation/platform_schemas.py`
- Create: `backend/app/generation/platform_limits.py`
- Create: `backend/app/generation/platform_validation.py`
- Create: `backend/tests/generation/test_platform_schemas.py`
- Create: `backend/tests/generation/test_platform_validation.py`

**Interfaces:**
- Consumes: Release 2 `TelegramRewriteOutput`, the exact persisted Telegram revision-content mapping, Release 2 Telegram renderer, and Release 3 `CitationRef`.
- Produces: compatibility-only `TelegramVariantPayload`, `InstagramVariantPayload`, `XVariantPayload`, `BlogVariantPayload`, `PlatformPayload`, `ValidationIssue`, and `validate_platform_payload()` without changing Release 2 Telegram storage or rendering.

- [ ] **Step 1: Write failing schema and validation tests**

```python
def test_instagram_package_contains_publishable_copy_carousel_alt_text_and_checklist():
    value = InstagramVariantPayload.model_validate(instagram_payload())
    assert value.caption
    assert value.hook
    assert value.cta
    assert value.hashtags == ["#AI", "#NewsCraft"]
    assert value.alt_text
    assert [slide.order for slide in value.carousel] == [1, 2]
    assert value.manual_checklist


def test_x_validator_reports_exact_segment_and_weighted_length():
    value = XVariantPayload(
        mode="thread",
        posts=[XPost(order=1, text="a" * 281, media=[], citations=[citation_ref()])],
        link_strategy="last_post",
        manual_checklist=["Verify thread order before posting"],
    )
    issues = validate_platform_payload("x", value)
    assert [issue for issue in issues if issue.severity == "error"] == [
        ValidationIssue(code="x_post_too_long", path="posts.0.text", message="Post 1 is 281/280 weighted characters")
    ]
    assert any(issue.code == "x_platform_recheck_required" and issue.severity == "warning" for issue in issues)


def test_blog_requires_resolved_citations_and_complete_seo_fields():
    value = BlogVariantPayload.model_validate(blog_payload(citations=[], canonical_sources=[]))
    issues = validate_platform_payload("blog", value)
    assert {issue.code for issue in issues} == {"blog_missing_citations"}


def test_blog_canonical_sources_equal_distinct_non_null_citation_urls():
    citations = [
        citation_ref(source_url=None),
        citation_ref(source_url="https://example.com/report"),
        citation_ref(source_url="https://example.com/report"),
    ]
    valid = BlogVariantPayload.model_validate(
        blog_payload(citations=citations, canonical_sources=["https://example.com/report"])
    )
    assert "blog_canonical_sources_mismatch" not in {
        issue.code for issue in validate_platform_payload("blog", valid)
    }

    missing = BlogVariantPayload.model_validate(blog_payload(citations=citations, canonical_sources=[]))
    assert "blog_canonical_sources_mismatch" in {
        issue.code for issue in validate_platform_payload("blog", missing)
    }


def test_blog_with_only_manual_text_citations_keeps_canonical_sources_empty():
    value = BlogVariantPayload.model_validate(
        blog_payload(citations=[citation_ref(source_url=None)], canonical_sources=[])
    )
    assert "blog_canonical_sources_mismatch" not in {
        issue.code for issue in validate_platform_payload("blog", value)
    }


def test_telegram_payload_round_trips_release_two_content_and_renderer_plan():
    stored = release_two_telegram_revision_content()
    payload = TelegramVariantPayload.model_validate(stored)

    assert payload.model_dump(mode="json") == stored
    assert render_telegram_variant(payload.model_dump(mode="json")) == render_release_two_telegram(stored)
```

`blog_payload(citations=[], canonical_sources=[])` must remain valid at the Pydantic shape layer: all non-citation fields satisfy their field constraints, both lists are empty, and `validate_platform_payload("blog", value)` owns the `blog_missing_citations` issue. The canonical-source fixtures must otherwise satisfy every blog rule so they isolate `blog_canonical_sources_mismatch`. The X fixture must likewise satisfy post citations, checklist, media, order, and link strategy so the 281-character branch is the only failing rule.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation/test_platform_schemas.py tests/generation/test_platform_validation.py -q
```

Expected: import failures for platform schemas and validation.

- [ ] **Step 3: Implement exact payload contracts**

```python
class MediaAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    media_asset_id: UUID | None
    role: Literal["hero", "slide", "post", "inline"]
    order: int = Field(ge=1)
    alt_text: str = Field(min_length=1, max_length=1_000)
    manual_brief: str | None = Field(default=None, max_length=2_000)
    image_prompt: str | None = Field(default=None, max_length=2_000)


class InstagramSlide(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: int = Field(ge=1, le=20)
    headline: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=500)
    media: MediaAssignment


class TelegramVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4096)
    parse_mode: Literal["HTML"] = "HTML"
    buttons: list[TelegramButton] = Field(default_factory=list, max_length=8)
    source_item_id: UUID | None
    source_url: str | None
    media_policy: Literal["preserve", "omit", "replace_manually"]
    media_asset_ids: list[UUID]
    direction: Literal["ltr", "rtl"]
    dry_run: bool


class InstagramVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hook: str = Field(min_length=1, max_length=180)
    caption: str = Field(min_length=1, max_length=2_200)
    cta: str = Field(min_length=1, max_length=300)
    hashtags: list[str] = Field(max_length=30)
    alt_text: str = Field(min_length=1, max_length=1_000)
    carousel: list[InstagramSlide] = Field(max_length=20)
    citations: list[CitationRef] = Field(min_length=1)
    manual_checklist: list[str] = Field(min_length=1)


class XPost(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: int = Field(ge=1, le=25)
    text: str = Field(min_length=1)
    media: list[MediaAssignment] = Field(max_length=4)
    citations: list[CitationRef] = Field(min_length=1)


class XVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["single", "thread"]
    posts: list[XPost] = Field(min_length=1, max_length=25)
    link_strategy: Literal["first_post", "last_post", "each_post", "no_link"]
    manual_checklist: list[str] = Field(min_length=1)


class BlogVariantPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)
    excerpt: str = Field(min_length=1, max_length=300)
    body_markdown: str = Field(min_length=200)
    headings: list[str] = Field(min_length=1)
    citations: list[CitationRef] = Field(default_factory=list)
    tags: list[str] = Field(max_length=20)
    seo_description: str = Field(min_length=50, max_length=160)
    hero_media: MediaAssignment | None
    canonical_sources: list[HttpUrl] = Field(default_factory=list)
    manual_checklist: list[str] = Field(min_length=1)


PlatformPayload = TelegramVariantPayload | InstagramVariantPayload | XVariantPayload | BlogVariantPayload
```

- [ ] **Step 4: Implement deterministic validation**

Set `INSTAGRAM_CAPTION_MAX = 2200`, `INSTAGRAM_HASHTAG_MAX = 30`, `INSTAGRAM_CAROUSEL_MAX = 20`, `X_POST_WEIGHT_MAX = 280`, `X_MEDIA_PER_POST_MAX = 4`, and `BLOG_SEO_DESCRIPTION_MAX = 160`. `x_weighted_length()` counts every normalized URL as 23 and every other Unicode code point as one; persist a warning code `x_platform_recheck_required` because final manual posting remains authoritative. Validators also enforce sequential order values, unique media assignments, at least one citation per factual post/section, non-empty alt text for assigned media, and exact platform/type agreement. For blog, `canonical_sources` must equal the ordered distinct non-null `CitationRef.source_url` values, preserving first citation appearance. An empty list is valid only when every citation has `source_url=None`; a missing URL is never fabricated from an evidence key, title, or operator text. Telegram validation delegates HTML/button/body/media checks to the Release 2 schema and renderer and never builds a second renderer. `TelegramVariantPayload` is only a strict validator for the already persisted Release 2 mapping; evidence citations and manual checklist projections are not serialized into `PlatformVariantRevision.content`.

```python
class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    path: str
    message: str
    severity: Literal["error", "warning"] = "error"


def validate_platform_payload(platform: Platform, payload: PlatformPayload) -> list[ValidationIssue]:
    validator = PLATFORM_VALIDATORS[platform]
    return validator(payload)
```

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation/test_platform_schemas.py tests/generation/test_platform_validation.py -q
.venv/bin/ruff check app/generation tests/generation
git diff --check
cd ..
git add backend/app/generation/platform_schemas.py backend/app/generation/platform_limits.py backend/app/generation/platform_validation.py backend/tests/generation/test_platform_schemas.py backend/tests/generation/test_platform_validation.py
git commit -m "feat: define complete platform package schemas"
```

Expected: schema and validator tests pass.

---

### Task 2: Generate one validated multi-platform content pack

**Files:**
- Modify: `backend/app/generation/platform_schemas.py`
- Create: `backend/app/generation/multiplatform.py`
- Create: `backend/app/generation/platform_renderers.py`
- Modify: `backend/app/generation/default_prompts.py`
- Modify: `backend/app/generation/editorial_service.py`
- Modify: `backend/app/generation/handlers.py`
- Modify: `backend/app/api/content_packs.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/generation/test_multiplatform.py`
- Create: `backend/tests/generation/test_multiplatform_edits.py`
- Create: `backend/tests/generation/test_platform_prompts.py`
- Modify: `backend/tests/api/test_content_pack_routes.py`

**Interfaces:**
- Consumes: Task 1 schemas/validators, Release 3 canonical revision/provider/pack services and `validate_citations()`, Release 2 Telegram content assembly/renderer, and immutable prompt-version selection.
- Produces: `MultiPlatformPackRequest`, `generate_platform_variants()`, active manual-platform prompt defaults, grounded persisted validation results, immutable Instagram/X/blog edit requests, and requested-platform regeneration.

- [ ] **Step 1: Write failing generation, prompt, citation, and immutable-edit tests**

```python
async def test_pack_generation_creates_four_variants_from_one_story_revision(
    editorial_service,
    canonical_revision,
    brand,
    fake_generation_provider_profile,
):
    result = await editorial_service.generate_pack(
        MultiPlatformPackRequest(
            story_revision_id=canonical_revision.id,
            brand_profile_id=brand.id,
            platforms=["telegram", "instagram", "x", "blog"],
            generation_provider_profile_id=fake_generation_provider_profile.id,
        )
    )
    assert {revision.platform for revision in result.revisions} == {"telegram", "instagram", "x", "blog"}
    assert {revision.story_revision_id for revision in result.revisions} == {canonical_revision.id}
    assert all(revision.validation_errors == [] for revision in result.revisions)


async def test_schema_invalid_platform_output_becomes_needs_review_and_does_not_auto_approve(
    editorial_service,
    invalid_generation_provider_profile,
):
    result = await editorial_service.generate_pack(
        request_for(
            "instagram",
            generation_provider_profile_id=invalid_generation_provider_profile.id,
        )
    )
    revision = result.revisions[0]
    assert revision.approval_state == "pending_review"
    assert revision.validation_errors[0]["code"] == "instagram_caption_too_long"
    assert result.job_status == "needs_review"


async def test_telegram_generation_persists_release_two_content_and_keeps_renderer_compatible(
    editorial_service,
    canonical_revision,
    brand,
    fake_generation_provider_profile,
):
    result = await editorial_service.generate_pack(
        MultiPlatformPackRequest(
            story_revision_id=canonical_revision.id,
            brand_profile_id=brand.id,
            platforms=["telegram"],
            generation_provider_profile_id=fake_generation_provider_profile.id,
        )
    )
    content = result.revisions[0].content
    assert set(content) == {
        "body", "parse_mode", "buttons", "source_item_id", "source_url",
        "media_policy", "media_asset_ids", "direction", "dry_run",
    }
    assert render_telegram_variant(content) == render_release_two_telegram(content)


async def test_manual_grouped_story_keeps_nullable_telegram_source_item_id(
    editorial_service,
    manual_story_revision,
    brand,
    fake_generation_provider_profile,
):
    result = await editorial_service.generate_pack(
        MultiPlatformPackRequest(
            story_revision_id=manual_story_revision.id,
            brand_profile_id=brand.id,
            platforms=["telegram"],
            generation_provider_profile_id=fake_generation_provider_profile.id,
        )
    )
    assert result.revisions[0].content["source_item_id"] is None


async def test_fabricated_but_well_shaped_platform_citation_never_creates_a_revision(
    editorial_service,
    instagram_provider_profile_with_unknown_evidence_uuid,
):
    result = await editorial_service.generate_pack(
        request_for(
            "instagram",
            generation_provider_profile_id=instagram_provider_profile_with_unknown_evidence_uuid.id,
        )
    )
    assert result.job_status == "needs_review"
    assert result.revisions == []
    assert stored_attempt().validation_errors[0]["code"] == "citation_integrity"


async def test_each_platform_run_uses_its_active_non_null_prompt_version(
    editorial_service,
    four_platform_request,
    active_platform_prompt_versions,
):
    result = await editorial_service.generate_pack(four_platform_request)
    for revision in result.revisions:
        run = await generation_run_for_attempt(revision.generation_attempt_id)
        assert run.prompt_template_version_id == active_platform_prompt_versions[revision.platform].id
        assert run.prompt_template_version_id is not None


async def test_manual_platform_edit_creates_pending_review_child_and_preserves_parent(
    editorial_service,
    approved_instagram_revision,
    grounded_instagram_payload,
):
    edited = await editorial_service.edit_manual_platform_variant(
        approved_instagram_revision.platform_variant_id,
        ManualPlatformEditRequest(
            base_revision_id=approved_instagram_revision.id,
            base_content_hash=approved_instagram_revision.content_hash,
            payload=InstagramEditPayload(platform="instagram", content=grounded_instagram_payload),
            evidence_map=ordered_distinct_citations(grounded_instagram_payload),
            edit_note="Shorten the caption",
        ),
    )
    assert edited.parent_revision_id == approved_instagram_revision.id
    assert edited.approval_state == "pending_review"
    assert edited.generation_attempt_id is None
    assert approved_instagram_revision.approval_state == "approved"
```

Also add API/service cases proving a platform discriminator that differs from the target `PlatformVariant.platform` is rejected, stale base revision ID/hash returns HTTP 409, syntactically valid citations with an unknown snapshot ID/key, altered URL, invalid locator, or altered excerpt hash create no child revision, and approval re-runs the same integrity checks rather than approving legacy/fabricated evidence. Assert the default prompt seed is idempotent and yields one active version for each purpose key `instagram_pack`, `x_pack`, and `blog_pack` without replacing Release 3 `telegram_pack` or Release 2 route-only `telegram_rewrite`. Seed an inactive higher-numbered fixture and prove generation selects the explicitly active version rather than the newest version number.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation/test_multiplatform.py \
  tests/generation/test_multiplatform_edits.py tests/generation/test_platform_prompts.py \
  tests/api/test_content_pack_routes.py -q
```

Expected: failures for the multi-platform request/renderer, manual edit union, citation-integrity enforcement, and prompt defaults.

- [ ] **Step 3: Implement grounded platform generation, prompt resolution, rendering, and immutable edits**

```python
class MultiPlatformPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_revision_id: UUID
    brand_profile_id: UUID
    platforms: list[Literal["telegram", "instagram", "x", "blog"]] = Field(min_length=1)
    generation_provider_profile_id: UUID


async def generate_platform_variants(request: MultiPlatformPackRequest, context: GenerationContext) -> GeneratedPack:
    revisions: list[PlatformVariantRevision] = []
    for platform in deduplicate_preserving_order(request.platforms):
        prompt_version = await context.require_active_prompt_version(PLATFORM_PROMPT_PURPOSE[platform])
        run = await context.start_generation_run(platform, prompt_template_version_id=prompt_version.id)
        provider_result = await context.provider.generate(
            context.request_for(platform, prompt_version=prompt_version)
        )
        attempt = await context.record_attempt(run, provider_result)

        if platform == "telegram":
            rewrite = TelegramRewriteOutput.model_validate(provider_result.output)
            stored_content = context.release_two_telegram_content(rewrite)
            payload = TelegramVariantPayload.model_validate(stored_content)
            evidence_map = await context.validated_telegram_evidence_map()
        else:
            payload = MANUAL_PLATFORM_ADAPTERS[platform].validate_python(provider_result.output)
            await context.validate_manual_platform_citations(platform, payload)
            stored_content = payload.model_dump(mode="json")
            evidence_map = ordered_distinct_citations(payload)

        issues = validate_platform_payload(platform, payload)
        revisions.append(
            await context.repository.create_revision(
                platform, stored_content, evidence_map, issues, attempt.id
            )
        )
    return GeneratedPack(revisions=revisions)
```

`PLATFORM_PROMPT_PURPOSE` is exactly `telegram -> telegram_pack`, `instagram -> instagram_pack`, `x -> x_pack`, and `blog -> blog_pack`. Extend the existing default-prompt bootstrap to seed immutable version 1 for the three manual-platform purposes idempotently, with their strict output schemas; reuse Release 3's active `telegram_pack` version for editorial Telegram generation. Resolve one active version before every platform provider call. Each platform gets its own `GenerationRun`/`GenerationAttempt`, and every run stores a non-null `prompt_template_version_id`; the prompt snapshot and input hash include that version's schema/checksum. A missing or multiply-active platform prompt is a permanent configuration failure before provider dispatch. Never place prompt text/version choices in the public request, use route-only `telegram_rewrite` for editorial packs, or reuse one platform's prompt for another.

Generation input includes canonical facts/citations, brand tone/language, source media, platform limits, and that platform's resolved active prompt version. Resolve `generation_provider_profile_id` through the Release 3 enabled/available `AIProviderProfile` boundary, persist that UUID on every `GenerationRun.provider_profile_id`, and resolve provider type/model/secret server-side; no request or job payload carries a provider-type literal. Provider calls remain outside database transactions. It does not ask one platform to infer another platform's structure. Persist all ordinary schema/platform validation issues. Any such error moves the job to `needs_review`; warnings do not block human approval but remain visible.

The branch above is mandatory. For `telegram`, validate only the provider-authored `body`/`parse_mode`/`buttons` as `TelegramRewriteOutput`, then call the existing Release 2 assembly helper with trusted story/route context to produce all nine stored keys: `body`, `parse_mode`, `buttons`, nullable `source_item_id`, `source_url`, `media_policy`, `media_asset_ids`, `direction`, and `dry_run`. The provider may not supply or override the latter six provenance/policy values. Pass the assembled mapping to `TelegramVariantPayload` and the existing Release 2 renderer compatibility test. Build the nonempty evidence map from the exact resolved citations on the selected canonical `StoryRevision`, validate it through the shared Release 2/3 citation contract, and pass it explicitly to revision persistence. Return evidence as an adjacent API field; never insert `citations`, `manual_checklist`, `media`, `canonical_url`, or `attribution_footer` into Telegram `content`. Instagram, X, and blog instead validate their complete provider outputs through their own full DTOs, derive the ordered evidence map from those validated citations, and store those DTOs as content.

Before persisting an Instagram/X/blog provider result, convert it to Release 3 `Claim` values and call `validate_citations()` against the exact immutable evidence snapshot set linked to the selected `StoryRevision`: Instagram maps its combined hook/caption/carousel factual copy to its `citations`; X maps every post separately to that post's citations; blog maps its body/headings to its `citations`. Empty citations on any non-empty factual mapping are invalid. Reject unknown snapshot UUIDs, evidence keys, source URLs, locators, or excerpt hashes, including well-shaped fabricated `CitationRef` objects. `PlatformVariantRevision.evidence_map` must equal the ordered distinct citations embedded in the platform DTO. Citation-integrity failure finishes the attempt/job as `needs_review` with sanitized error code `citation_integrity` and creates no `PlatformVariantRevision`; it is not downgraded to an approvable warning.

Add the immutable manual-platform edit contract to `platform_schemas.py`:

```python
class InstagramEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["instagram"]
    content: InstagramVariantPayload


class XEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["x"]
    content: XVariantPayload


class BlogEditPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: Literal["blog"]
    content: BlogVariantPayload


ManualPlatformEditPayload = Annotated[
    InstagramEditPayload | XEditPayload | BlogEditPayload,
    Field(discriminator="platform"),
]


class ManualPlatformEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: ManualPlatformEditPayload
    evidence_map: list[CitationRef] = Field(min_length=1)
    edit_note: str = Field(min_length=1, max_length=500)
```

`edit_manual_platform_variant()` locks the target `PlatformVariant` plus current revision, requires the discriminator to equal the persisted variant platform, and returns HTTP 409 when either base ID or hash is stale. It requires `evidence_map` to equal the ordered distinct citations embedded in `payload.content`, runs platform validation and Release 3 citation integrity against the pack's exact `StoryRevision` evidence, and creates revision `N+1` with `parent_revision_id=base_revision_id`, `generation_attempt_id=None`, canonical hash over `{content, evidence_map}`, and `approval_state="pending_review"`; it never mutates the parent. A citation/platform failure creates no child. Before approving any Instagram/X/blog revision, reload and revalidate its stored content/evidence against that same immutable evidence set; reject integrity failure instead of approving it. Keep both the Release 3 Telegram edit model and Release 2 `/telegram/drafts/{revision_id}/revisions` request/assembly behavior unchanged.

- [ ] **Step 4: Expand API contracts**

`POST /stories/{story_id}/content-packs` accepts `platforms` instead of the Release 3 singular platform and returns one job. `POST /platform-variants/{variant_id}/regenerate` accepts `generation_provider_profile_id` plus an optional operator instruction and creates a child revision for only that platform, using the target platform's current active prompt version and the same citation-integrity gate. `GET /content-packs/{pack_id}` returns variants ordered `telegram`, `instagram`, `x`, `blog` with current revision, all validation issues, media plan, approval state, and safe prompt-version identity/checksum.

```python
class RegenerateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_provider_profile_id: UUID
    instruction: str | None = Field(default=None, max_length=1_000)
```

Extend the existing `POST /platform-variants/{variant_id}/revisions` route without replacing its Release 3 Telegram request. After loading the target variant, dispatch Instagram/X/blog bodies through `ManualPlatformEditRequest`; Telegram continues through the existing `EditVariantRequest` and Release 2 draft-edit endpoint. Return HTTP 422 with code `citation_integrity` for fabricated/mismatched evidence, HTTP 409 for stale ID/hash or platform conflict, and HTTP 201 only after the immutable child commits. `POST /platform-variant-revisions/{revision_id}/approve` re-runs stored platform schema, platform validation, evidence-map equality, and citation integrity before the exact hash-matching approval transition.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation tests/api/test_content_pack_routes.py -q
.venv/bin/ruff check app/generation app/api/content_packs.py app/main.py tests/generation tests/api/test_content_pack_routes.py
git diff --check
cd ..
git add backend/app/generation backend/app/api/content_packs.py backend/app/main.py \
  backend/tests/generation backend/tests/api/test_content_pack_routes.py
git commit -m "feat: generate validated multi-platform packs"
```

Expected: platform-specific generation, active prompt selection, grounded citations, immutable edits, approval revalidation, Telegram compatibility, and API tests pass.

---

### Task 3: Build deterministic JSON, Markdown, HTML, and media-bundle exports

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/exports/__init__.py`
- Create: `backend/app/exports/models.py`
- Create: `backend/app/exports/service.py`
- Create: `backend/app/exports/handlers.py`
- Create: `backend/app/api/exports.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/routes.py`
- Modify: `docker-compose.yml`
- Modify: `backend/tests/test_docker_config.py`
- Create: `backend/tests/exports/test_service.py`
- Create: `backend/tests/exports/test_handlers.py`
- Create: `backend/tests/api/test_export_routes.py`

**Interfaces:**
- Consumes: exact platform revisions and local validated media.
- Produces: `ExportRequest`, `ExportArtifact`, job type `build_export`, export status/download endpoints, deterministic checksummed bundles, and one persistent `export_data` volume mounted at `/data/exports` in API and `worker-source-generation`.

- [ ] **Step 1: Add and install the rendering dependencies before importing export modules**

Add to the runtime dependency list in `backend/pyproject.toml`:

```toml
"markdown>=3.8",
"nh3>=0.3",
```

Install the edited project before running an export test:

```bash
cd backend
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip show markdown nh3
```

Expected: both packages are installed into `backend/.venv`; no test imports an undeclared package.

- [ ] **Step 2: Write failing export, storage, and capability tests**

```python
async def test_export_manifest_binds_every_file_to_exact_revision_and_hash(export_service, approved_pack):
    artifact = await export_service.build(ExportRequest(content_pack_id=approved_pack.id, formats=["json", "markdown", "html", "zip"], include_media=True))
    manifest = artifact.manifest
    assert manifest["content_pack_id"] == str(approved_pack.id)
    assert {item["revision_id"] for item in manifest["variants"]} == {str(value.id) for value in approved_pack.current_revisions}
    assert all(item["sha256"] for item in manifest["files"])


def test_blog_html_is_sanitized_and_keeps_resolved_citation_links(export_service, blog_revision):
    html = export_service.render_html(blog_revision_with_body(blog_revision, '<script>alert(1)</script> [Source](https://example.com/report)'))
    assert "<script" not in html
    assert 'href="https://example.com/report"' in html
```

Add an API test proving export listing is stable under cursor pagination and never returns a storage path outside the safe download endpoint.

Add `backend/tests/test_docker_config.py` coverage that parses Compose and asserts:

```python
def test_export_storage_is_persistent_and_shared_only_with_the_builder_and_api():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert "export_data:/data/exports" in compose["services"]["api"]["volumes"]
    assert "export_data:/data/exports" in compose["services"]["worker-source-generation"]["volumes"]
    assert compose["services"]["api"]["environment"]["EXPORT_ROOT"] == "/data/exports"
    assert compose["services"]["worker-source-generation"]["environment"]["EXPORT_ROOT"] == "/data/exports"
    assert "export_data:/data/exports" not in compose["services"]["worker-publishing"].get("volumes", [])
    assert "export_data" in compose["volumes"]
```

Add handler-registry/worker tests proving `build_export` is registered in the source-generation registry when existing capability `generation` is enabled, appears in `registry.job_types()`, is passed to `claim_next_job(allowed_job_types=...)`, and is absent from the publishing-only registry. Do not add a fifth CLI capability or a second queue.

- [ ] **Step 3: Run tests and verify the missing export/storage behavior**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/exports tests/api/test_export_routes.py tests/test_docker_config.py tests/test_job_handler_registry.py tests/test_job_worker.py -q
```

Expected: export module/storage/registry assertions fail; dependency imports succeed.

- [ ] **Step 4: Implement exact artifact, storage, and worker-capability contracts**

Add `export_root: str = "/data/exports"` to `backend/app/core/config.py`. Export service constructors receive `Path(settings.export_root)` from the API/handler composition boundary; they never read an arbitrary root from job payloads.

In `docker-compose.yml`, set `EXPORT_ROOT: /data/exports` and mount `export_data:/data/exports` on `api` and `worker-source-generation`. Declare top-level `export_data:` beside the existing named volumes. Do not mount it on `worker-publishing`; that process neither builds nor serves exports.

Register `build_export` only in the handler bundle selected by existing capability `generation`, which is hosted by `worker-source-generation`. The publishing bundle must not resolve the export root or register the handler. Release 1 atomic claim filtering then claims `build_export` only from `registry.job_types()` of the source-generation worker.

```python
class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_pack_id: UUID
    revision_ids: list[UUID] | None = None
    formats: list[Literal["json", "markdown", "html", "zip"]] = Field(min_length=1)
    include_media: bool = False


class ExportManifest(BaseModel):
    schema_version: Literal["newscraft-export-v1"] = "newscraft-export-v1"
    content_pack_id: UUID
    story_revision_id: UUID
    created_at: datetime
    variants: list[ExportVariantIdentity]
    files: list[ExportFileIdentity]
```

JSON uses sorted keys and UTF-8; Markdown uses deterministic heading templates per platform; blog HTML converts only the stored Markdown and sanitizes tags/attributes; ZIP entry names use `{platform}/{revision_id}/{safe_filename}`. Reject `..`, absolute paths, symlinks, missing storage files, and media whose resolved path escapes `MEDIA_ROOT`. Compute SHA-256 for every exported file and write `manifest.json` last. Store artifacts under `EXPORT_ROOT/{job_id}` outside Git.

`ExportArtifact` is a Pydantic value object, not a second queue or an undeclared ORM table. The `build_export` handler stores its serialized artifact identity, manifest path, checksums, and completion state in the owning `WorkflowJob.result`; the job UUID is the public `export_id`.

- [ ] **Step 5: Add durable export endpoints**

```text
POST /content-packs/{pack_id}/exports             -> 202 JobAcceptedOut
GET  /exports?cursor=<cursor>&limit=50             -> ExportArtifactListOut
GET  /exports/{export_id}                         -> ExportArtifactOut
GET  /exports/{export_id}/download/{file_name}    -> application/octet-stream
```

The POST creates `build_export:{pack_id}:{sorted_revision_hashes}:{request_hash}`. List uses stable `(finished_at, job_id)` cursor pagination over completed/failed `build_export` workflow jobs. Detail loads the durable workflow job and validates its typed artifact result. Download resolves only filenames listed in that job's artifact manifest and sets `Content-Disposition: attachment`. Export generation is a worker job; no route copies media inline.

- [ ] **Step 6: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/exports tests/api/test_export_routes.py tests/test_docker_config.py tests/test_job_handler_registry.py tests/test_job_worker.py tests/postgres/test_job_repository.py -q
.venv/bin/ruff check app/exports app/api/exports.py tests/exports tests/api/test_export_routes.py
git diff --check
cd ..
git add backend/pyproject.toml backend/app/exports backend/app/api/exports.py backend/app/core/config.py \
  backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/exports \
  backend/tests/api/test_export_routes.py backend/tests/test_docker_config.py docker-compose.yml
git commit -m "feat: export deterministic content packages"
```

Expected: export, API, and job tests pass.

---

### Task 4: Persist manual publishing plans, checklists, and one calendar projection

**Files:**
- Create: `backend/alembic/versions/0007_manual_publication_plans.py`
- Modify: `backend/app/db/model_registry.py`
- Create: `backend/app/manual_publication/__init__.py`
- Create: `backend/app/manual_publication/models.py`
- Create: `backend/app/manual_publication/service.py`
- Create: `backend/app/manual_publication/calendar.py`
- Create: `backend/app/api/calendar.py`
- Modify: `backend/app/api/telegram_drafts.py`
- Modify: `backend/app/publishing/telegram/service.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/manual_publication/test_service.py`
- Create: `backend/tests/manual_publication/test_calendar.py`
- Create: `backend/tests/api/test_calendar_routes.py`
- Create: `backend/tests/test_manual_publication_migration.py`
- Modify: `backend/tests/test_telegram_draft_api.py`
- Modify: `backend/tests/test_telegram_publish_service.py`

**Interfaces:**
- Consumes: approved variant revisions and Release 2 scheduled `PublishJob`/`Publication` rows.
- Produces: `ManualPublicationPlan`, `ManualPublicationService`, `schedule_reviewed_telegram()`, reviewed Telegram scheduling API, `CalendarEvent`, plan/checklist/completion APIs, and `GET /calendar`.

- [ ] **Step 1: Write failing migration and exact-revision tests**

```python
def test_manual_publication_migration_has_revision_and_schedule_constraints():
    migration = Path("alembic/versions/0007_manual_publication_plans.py").read_text()
    assert 'revision = "0007_manual_publication_plans"' in migration
    assert 'down_revision = "0006_telegram_automation_vertical"' in migration
    assert "manual_publication_plans" in migration
    assert "platform_variant_revision_id" in migration
    assert "scheduled_for" in migration


async def test_plan_requires_exact_approved_revision(db_session, pending_review_revision):
    with pytest.raises(ManualPublicationError, match="revision is not approved"):
        await ManualPublicationService(db_session).create_plan(pending_review_revision.id, scheduled_for(), "Asia/Tehran")


async def test_completion_preserves_revision_identity_and_operator_evidence(db_session, approved_instagram_revision):
    plan = await ManualPublicationService(db_session).create_plan(approved_instagram_revision.id, scheduled_for(), "Asia/Tehran")
    completed = await ManualPublicationService(db_session).mark_published(plan.id, external_url="https://instagram.com/p/abc", note="Posted from mobile")
    assert completed.platform_variant_revision_id == approved_instagram_revision.id
    assert completed.status == "manual_published"
    assert completed.completed_at is not None


async def test_reviewed_telegram_schedule_sets_domain_and_workflow_due_times(client, approved_telegram_revision):
    due = "2026-07-13T05:30:00Z"
    response = await client.post(
        f"/telegram/drafts/{approved_telegram_revision.id}/schedule",
        json={
            "content_hash": approved_telegram_revision.content_hash,
            "destination_id": str(TELEGRAM_DESTINATION_ID),
            "scheduled_for": due,
        },
    )
    assert response.status_code == 202
    assert stored_publish_job().scheduled_for.isoformat() == "2026-07-13T05:30:00+00:00"
    assert enqueued_workflow_job().scheduled_for.isoformat() == "2026-07-13T05:30:00+00:00"
    assert enqueued_workflow_job().job_type == "telegram.publish"
    assert enqueued_workflow_job().pause_sensitive is True
```

Add schedule rejection cases for a `pending_review`/stale-hash/dry-run revision, non-Telegram or disabled destination, a timestamp not strictly in the future, an already running/published publish job, and a conflicting second schedule time. Replaying the exact destination/revision/hash/time returns the existing `JobAcceptedOut` rather than a second `PublishJob` or `WorkflowJob`.

Add calendar API coverage proving scheduled reviewed Telegram jobs appear at `PublishJob.scheduled_for`, publication pagination includes confirmed Telegram and `manual_published` records, merely planned manual work does not appear as published, and exact revision IDs are preserved.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/manual_publication tests/api/test_calendar_routes.py \
  tests/test_manual_publication_migration.py tests/test_telegram_draft_api.py tests/test_telegram_publish_service.py -q
```

Expected: missing migration/module failures.

- [ ] **Step 3: Create the schema and service contracts**

Migration `0007_manual_publication_plans` revises Release 2 head `0006_telegram_automation_vertical` and creates:

```python
class ManualPublicationPlan(Base):
    __tablename__ = "manual_publication_plans"
    id: Mapped[UUID] = uuid_pk()
    platform_variant_revision_id: Mapped[UUID] = mapped_column(ForeignKey("platform_variant_revisions.id"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    display_timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Asia/Tehran")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="planned")
    checklist_state: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    external_url: Mapped[str | None] = mapped_column(Text)
    operator_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
```

Add a unique partial index allowing one active (`planned` or `ready`) plan per revision. Platform must match the variant and be one of `instagram`, `x`, or `blog`; Telegram scheduling continues through `PublishJob`. Checklist keys are stable IDs returned by `manual_checklist_for(platform)` and values are booleans. `ready` requires every item checked.

- [ ] **Step 4: Build a unified calendar projection and API**

```python
class CalendarEvent(BaseModel):
    id: str
    kind: Literal["telegram_publish", "manual_publication"]
    platform: Literal["telegram", "instagram", "x", "blog"]
    revision_id: UUID
    title: str
    starts_at: datetime
    status: str
    action_url: str
```

Add this compatible extension to `backend/app/api/telegram_drafts.py`:

```python
class ScheduleTelegramIn(BaseModel):
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    destination_id: UUID
    scheduled_for: datetime


@router.post("/drafts/{revision_id}/schedule", response_model=JobAcceptedOut, status_code=202)
async def schedule_telegram_revision(revision_id: UUID, payload: ScheduleTelegramIn, session: AsyncSession = SessionDependency):
    result = await schedule_reviewed_telegram(session, revision_id=revision_id, request=payload)
    await session.commit()
    return JobAcceptedOut(job_id=result.workflow_job.id, status=result.workflow_job.status, deduplicated=not result.created)
```

`schedule_reviewed_telegram()` locks the exact `PlatformVariantRevision`, verifies platform `telegram`, approval/hash, `dry_run=false`, future aware UTC timestamp, and an enabled Telegram destination. It creates or reuses the Release 2 `PublishJob` using idempotency key `telegram-publish:{destination_id}:{revision.id}:{revision.content_hash}`, sets `PublishJob.status="scheduled"` and `PublishJob.scheduled_for=request.scheduled_for`, and enqueues the matching `telegram.publish` `WorkflowJob` with the same `scheduled_for`, origin `manual`, and `pause_sensitive=True` in the same transaction. Exact replay is deduplicated; a different due time for an existing nonterminal job is HTTP 409 rather than silently moving it. The existing Telegram publish handler remains the only network boundary and re-evaluates pause/destination/validation gates at execution.

`GET /calendar?start=<UTC>&end=<UTC>&timezone=Asia/Tehran` validates a maximum 93-day window, returns manual plans plus scheduled Telegram publish jobs, and performs no timezone-naive comparisons. `GET /publications?cursor=<cursor>&platform=<optional>&limit=50` returns a stable chronological union of real Telegram `Publication` rows and completed manual plans with explicit `kind`; it never treats a planned manual item as published. Add `POST /manual-publication-plans`, `PATCH /manual-publication-plans/{id}/checklist`, `POST /manual-publication-plans/{id}/mark-published`, and `POST /manual-publication-plans/{id}/cancel`. Every mutation records a `WorkflowEvent`.

- [ ] **Step 5: Run migration, tests, and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/manual_publication tests/api/test_calendar_routes.py \
  tests/test_manual_publication_migration.py tests/test_telegram_draft_api.py tests/test_telegram_publish_service.py -q
.venv/bin/ruff check app/manual_publication app/api/calendar.py tests/manual_publication tests/api/test_calendar_routes.py
git diff --check
cd ..
docker compose --profile test rm -sf postgres-test
docker compose --profile test up -d --wait postgres-test
cd backend
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic downgrade 0006_telegram_automation_vertical
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
cd ..
git add backend/alembic/versions/0007_manual_publication_plans.py backend/app/db/model_registry.py \
  backend/app/manual_publication backend/app/api/calendar.py backend/app/api/telegram_drafts.py \
  backend/app/publishing/telegram/service.py backend/app/api/routes.py backend/tests/manual_publication \
  backend/tests/api/test_calendar_routes.py backend/tests/test_manual_publication_migration.py \
  backend/tests/test_telegram_draft_api.py backend/tests/test_telegram_publish_service.py
git commit -m "feat: add manual publication calendar"
```

Expected: migration round trip and focused tests pass.

---

### Task 5: Add typed platform editors, faithful previews, and media plans

**Files:**
- Create: `frontend/features/packages/types.ts`
- Create: `frontend/features/packages/api.ts`
- Create: `frontend/features/packages/components/platform-preview.tsx`
- Create: `frontend/features/packages/components/telegram-preview.tsx`
- Create: `frontend/features/packages/components/instagram-preview.tsx`
- Create: `frontend/features/packages/components/x-preview.tsx`
- Create: `frontend/features/packages/components/blog-preview.tsx`
- Create: `frontend/features/packages/components/platform-editor.tsx`
- Create: `frontend/features/packages/components/media-plan.tsx`
- Modify: `frontend/app/drafts/[packId]/page.tsx`
- Modify: `frontend/app/review/[revisionId]/page.tsx`
- Create: `frontend/tests/platform-previews.test.tsx`
- Create: `frontend/tests/platform-editor.test.tsx`
- Create: `frontend/tests/media-plan.test.tsx`

**Interfaces:**
- Consumes: Task 1/2 payloads, the discriminated manual-platform immutable edit contract, and the compatible Release 3/Release 2 Telegram editor contracts.
- Produces: discriminated `PlatformPayload`, exact base-ID/hash/evidence edit requests, preview/editor dispatch, and accessible validation/media displays.

- [ ] **Step 1: Write failing preview/editor tests**

```tsx
it.each([
  ["telegram", telegramRevision, "Telegram preview"],
  ["instagram", instagramRevision, "Instagram preview"],
  ["x", xRevision, "X thread preview"],
  ["blog", blogRevision, "Blog preview"],
])("renders a truthful %s preview", (_platform, revision, label) => {
  render(<PlatformPreview revision={revision} />)
  expect(screen.getByRole("region", { name: label })).toBeInTheDocument()
  expect(screen.getByText(revision.evidenceCitations[0].sourceUrl)).toBeInTheDocument()
})

it("shows backend validation and creates a new revision instead of mutating", async () => {
  const onSave = vi.fn()
  render(<PlatformEditor revision={instagramRevisionWithError} onSave={onSave} />)
  expect(screen.getByText("Caption is 2240/2200 characters")).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText("Caption"))
  await userEvent.type(screen.getByLabelText("Caption"), "Short caption")
  await userEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
    baseRevisionId: instagramRevisionWithError.id,
    baseContentHash: instagramRevisionWithError.contentHash,
    payload: expect.objectContaining({ platform: "instagram" }),
    evidenceMap: instagramRevisionWithError.evidenceCitations,
  }))
})
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/platform-previews.test.tsx tests/platform-editor.test.tsx tests/media-plan.test.tsx
```

Expected: import failures for package components.

- [ ] **Step 3: Implement exact discriminated frontend types**

```tsx
export type PlatformRevision =
  | { platform: "telegram"; id: string; contentHash: string; payload: TelegramPayload; validation: ValidationIssue[]; evidenceCitations: CitationRef[]; manualChecklist: string[] }
  | { platform: "instagram"; id: string; contentHash: string; payload: InstagramPayload; validation: ValidationIssue[]; evidenceCitations: CitationRef[]; manualChecklist: string[] }
  | { platform: "x"; id: string; contentHash: string; payload: XPayload; validation: ValidationIssue[]; evidenceCitations: CitationRef[]; manualChecklist: string[] }
  | { platform: "blog"; id: string; contentHash: string; payload: BlogPayload; validation: ValidationIssue[]; evidenceCitations: CitationRef[]; manualChecklist: string[] }
```

`TelegramPayload` has only the exact nine Release 2 content keys, including nullable `source_item_id`; Telegram evidence citations and manual checklist are adjacent projection fields and are never merged into `payload`. The dispatcher uses exhaustive `switch (revision.platform)` with a `never` assertion. Previews label themselves as approximations, render actual copy/media/order/alt text/citations, handle a null citation URL without inventing a link, and never claim pixel parity with external apps.

Instagram/X/blog editors build the backend `ManualPlatformEditRequest` exactly: current base revision ID/hash, discriminated `{platform, content}`, and an `evidenceMap` equal to ordered distinct citations embedded in that content. They preserve complete citation objects while editing copy/media, show character counts and backend issues, and POST to the existing immutable revision API; stale conflicts refresh without losing the operator's local text, and citation-integrity errors remain visible without treating the edit as saved. Telegram edits continue to submit the Release 3 Telegram edit request or the Release 2 `{content: TelegramRewriteOutput, media_asset_ids}` draft contract as appropriate; they are never coerced through the Instagram/X/blog union.

- [ ] **Step 4: Implement the media plan**

`MediaPlan` lists ordered source assets, dimensions/type/availability, assignment per slide/post/hero, alt text, manual brief, and image prompt. Missing/unsupported media appears as an explicit required manual asset; it is never silently hidden. Drag/reorder sends a new revision payload. All controls have labels and keyboard move-up/move-down actions.

- [ ] **Step 5: Run tests, type check, and commit**

```bash
cd frontend
npm run test -- tests/platform-previews.test.tsx tests/platform-editor.test.tsx tests/media-plan.test.tsx
npm run typecheck
git diff --check
cd ..
git add frontend/features/packages frontend/app/drafts frontend/app/review frontend/tests/platform-previews.test.tsx frontend/tests/platform-editor.test.tsx frontend/tests/media-plan.test.tsx
git commit -m "feat: add multi-platform editors and previews"
```

Expected: focused tests and TypeScript pass.

---

### Task 6: Add copy/export actions, manual checklists, and publication calendar UI

**Files:**
- Create: `frontend/features/packages/components/copy-export-actions.tsx`
- Create: `frontend/features/packages/components/manual-publishing-checklist.tsx`
- Create: `frontend/features/calendar/types.ts`
- Create: `frontend/features/calendar/api.ts`
- Create: `frontend/features/calendar/publication-calendar.tsx`
- Create: `frontend/features/library/api.ts`
- Create: `frontend/features/library/library-page.tsx`
- Create: `backend/app/api/library.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/api/test_library_routes.py`
- Create: `frontend/app/calendar/page.tsx`
- Create: `frontend/app/library/page.tsx`
- Modify: `frontend/lib/query-keys.ts`
- Modify: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Modify: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/tests/copy-export-actions.test.tsx`
- Create: `frontend/tests/manual-publishing-checklist.test.tsx`
- Create: `frontend/tests/publication-calendar.test.tsx`
- Create: `frontend/tests/library-page.test.tsx`
- Modify: `frontend/tests/navigation.test.tsx`

**Interfaces:**
- Consumes: Task 3 exports, Task 4 plans/calendar, Task 5 current revisions.
- Produces: copy formats, durable export job outcomes, persisted checklists, manual completion, calendar navigation, cursor-paginated Evidence/Research APIs, and a unified truthful Library.

- [ ] **Step 1: Write failing interaction tests**

```tsx
it("copies the selected representation and announces success accessibly", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.assign(navigator, { clipboard: { writeText } })
  render(<CopyExportActions revision={xRevision} />)
  await userEvent.click(screen.getByRole("button", { name: "Copy full X thread" }))
  expect(writeText).toHaveBeenCalledWith("1/2 First post\n\n2/2 Second post")
  expect(screen.getByRole("status")).toHaveTextContent("Copied X thread")
})

it("persists checklist progress and enables manual completion only when ready", async () => {
  render(<ManualPublishingChecklist plan={plannedInstagram} />)
  expect(screen.getByRole("button", { name: "Mark as published" })).toBeDisabled()
  for (const checkbox of screen.getAllByRole("checkbox")) await userEvent.click(checkbox)
  expect(screen.getByRole("button", { name: "Mark as published" })).toBeEnabled()
})

it("shows Telegram and manual events in the operator timezone", () => {
  render(<PublicationCalendar events={[telegramEvent, instagramEvent]} timezone="Asia/Tehran" />)
  expect(screen.getByText("Telegram: Daily update")).toBeInTheDocument()
  expect(screen.getByText("Instagram: Daily update")).toBeInTheDocument()
})

it("browses originals, stories, evidence, research, drafts, exports, and publications without mixing their states", async () => {
  render(<LibraryPage />)
  for (const tab of ["Originals", "Stories", "Evidence", "Research", "Drafts", "Exports", "Publications"]) {
    await userEvent.click(screen.getByRole("tab", { name: tab }))
    expect(screen.getByRole("tabpanel", { name: tab })).toBeInTheDocument()
  }
})
```

Create `backend/tests/api/test_library_routes.py` with cursor-stability and truthfulness cases for:

```text
GET /library/evidence?cursor=&story_id=&source_id=&limit=50
GET /library/research-runs?cursor=&story_id=&status=&backend=&limit=50
```

Evidence rows must expose snapshot ID, story/content-item IDs, title, nullable source URL, authors, published/captured timestamps, content hash, and a bounded excerpt; they must not return full raw payloads by default. Research rows expose run ID, story ID, requested mode/backend, status, budgets, started/finished timestamps, attempt count, source count, result revision ID, and sanitized error summary. Add tests proving a newly inserted row between pages does not duplicate/skip older rows, filters use persisted values, and no provider secret reference or response body is returned.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/copy-export-actions.test.tsx tests/manual-publishing-checklist.test.tsx tests/publication-calendar.test.tsx tests/library-page.test.tsx
cd ../backend
PYTHONPATH=. .venv/bin/python -m pytest tests/api/test_library_routes.py -q
```

Expected: import failures for the new components and Library.

- [ ] **Step 3: Implement copy/export/checklist behavior**

Copy actions are exact per platform: Telegram formatted message, Instagram caption plus hashtags, full X thread plus individual post buttons, blog Markdown, and blog HTML. Clipboard failure leaves content selected and shows a durable error. Export action submits formats/media choice, shows returned job, polls artifact state, and exposes download only after success.

```tsx
export const packageQueryKeys = {
  export: (id: string) => ["exports", id] as const,
  manualPlan: (id: string) => ["manual-publication-plans", id] as const,
  calendar: (start: string, end: string, timezone: string) => ["calendar", start, end, timezone] as const,
}
```

Checklist updates are optimistic only after storing a rollback snapshot; on failure restore the server state and show the error. Mark-published requires an optional external URL and note, then invalidates the plan, pack, and calendar queries.

- [ ] **Step 4: Implement calendar route and navigation**

Calendar provides month and chronological list views, platform/status filters, timezone selector, previous/today/next controls, and deep links to exact review revisions or Telegram publication history. Loading/error/empty states are explicit. On view change, request an inclusive start and exclusive end in UTC; never derive event truth locally.

Implement `backend/app/api/library.py` as read-only projections over existing tables. Evidence pagination orders `(captured_at DESC, id DESC)` and encodes both in the cursor. Research pagination orders `(created_at DESC, id DESC)` and likewise uses both values. Clamp excerpts to 500 characters after whitespace normalization, pass errors through shared redaction, and never trigger extraction, research, generation, retries, or health checks from GET. Include the router from `backend/app/api/routes.py`.

Library composes the existing paginated content-item, story, content-pack, export, calendar/publication APIs plus the two new Evidence/Research endpoints. Each of the seven tabs owns distinct loading/error/empty/data state and deep-links to the exact source, story, evidence snapshot, research run, revision, export, or publication; it does not copy records into a new table or infer live status. Add the now-working `Calendar` and `Library` routes to desktop/mobile Newsroom navigation and extend `frontend/tests/navigation.test.tsx` to assert `/calendar` and `/library` targets.

- [ ] **Step 5: Run tests, type check, and commit**

```bash
cd frontend
npm run test -- tests/copy-export-actions.test.tsx tests/manual-publishing-checklist.test.tsx tests/publication-calendar.test.tsx tests/library-page.test.tsx
npm run typecheck
cd ../backend
PYTHONPATH=. .venv/bin/python -m pytest tests/api/test_library_routes.py -q
.venv/bin/ruff check app/api/library.py tests/api/test_library_routes.py
git diff --check
cd ..
git add backend/app/api/library.py backend/app/api/routes.py backend/tests/api/test_library_routes.py \
  frontend/features/packages/components/copy-export-actions.tsx frontend/features/packages/components/manual-publishing-checklist.tsx \
  frontend/features/calendar frontend/features/library frontend/app/calendar/page.tsx frontend/app/library/page.tsx \
  frontend/lib/query-keys.ts frontend/components/newsroom/newsroom-sidebar.tsx \
  frontend/components/newsroom/mobile-newsroom-nav.tsx frontend/tests/copy-export-actions.test.tsx \
  frontend/tests/manual-publishing-checklist.test.tsx frontend/tests/publication-calendar.test.tsx \
  frontend/tests/library-page.test.tsx frontend/tests/navigation.test.tsx
git commit -m "feat: add manual publishing tools and calendar"
```

Expected: focused tests and TypeScript pass.

---

### Task 7: Prove complete manual packages in browser and document the workflow

**Files:**
- Create: `frontend/e2e/multiplatform-packages.spec.ts`
- Create: `backend/tests/integration/test_multiplatform_export_flow.py`
- Create: `docs/operations/manual-publishing-packages.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: all Release 4 functionality.
- Produces: deterministic generation→review→approve→export→plan→manual-complete acceptance coverage.

- [ ] **Step 1: Add backend integration coverage**

```python
async def test_four_platform_pack_exports_and_manual_completion(app_harness, researched_story):
    job = await app_harness.request_pack(researched_story.id, platforms=["telegram", "instagram", "x", "blog"])
    await app_harness.worker.run_until_idle()
    pack = await app_harness.pack_for_job(job.id)
    assert {item.platform for item in pack.current_revisions} == {"telegram", "instagram", "x", "blog"}
    for revision in pack.current_revisions:
        await app_harness.approve(revision.id, revision.content_hash)
    export_job = await app_harness.request_export(pack.id, formats=["json", "markdown", "html", "zip"], include_media=False)
    await app_harness.worker.run_until_idle()
    assert (await app_harness.export_for_job(export_job.id)).manifest["schema_version"] == "newscraft-export-v1"
    plan = await app_harness.create_manual_plan(pack.revision("instagram").id)
    completed = await app_harness.complete_all_checks_and_mark_published(plan.id)
    assert completed.status == "manual_published"
```

- [ ] **Step 2: Add desktop and mobile browser flow**

```ts
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`multi-platform manual package ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto("/drafts/pack-1")
    for (const platform of ["Telegram", "Instagram", "X", "Blog"]) {
      await page.getByRole("tab", { name: platform }).click()
      await expect(page.getByRole("region", { name: new RegExp(`${platform}.*preview`, "i") })).toBeVisible()
    }
    await page.getByRole("button", { name: "Export package" }).click()
    await expect(page.getByText("Export ready")).toBeVisible()
    await page.getByRole("link", { name: "Calendar" }).click()
    await expect(page.getByText("Instagram: Agent release")).toBeVisible()
  })
}
```

- [ ] **Step 3: Document exact operator flow and limitations**

Document: generate all platforms; review citations and media; edit/save a new revision; approve exact revision; copy or export; schedule a manual plan; complete the platform-specific checklist; record external URL/note. State clearly that Instagram/X/blog are not automatically posted and previews are approximations.

- [ ] **Step 4: Run the Release 4 gate**

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
cd ..
docker compose --profile test rm -sf postgres-test
docker compose --profile test up -d --wait postgres-test
cd backend
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic downgrade 0006_telegram_automation_vertical
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
cd ../frontend
npm run test
npm run typecheck
npm run build
npx playwright test --project=chromium
cd ..
docker compose config >/tmp/newscraft-release4-compose.yml
git diff --check
```

Expected: complete backend/frontend, migration, browser, build, and Compose gates pass.

- [ ] **Step 5: Commit acceptance coverage and docs**

```bash
git add frontend/e2e/multiplatform-packages.spec.ts backend/tests/integration/test_multiplatform_export_flow.py docs/operations/manual-publishing-packages.md README.md
git commit -m "test: prove multi-platform manual packages"
git status --short
```

Expected: no Release 4 changes remain uncommitted.

## Release 4 Exit Criteria

- Telegram, Instagram, X, and blog revisions have strict payloads, visible validation, citations, media plans, alt text, and checklists.
- One content pack can generate all four variants without mixing their schemas.
- Telegram generation accepts nullable `source_item_id`, validates provider output only as `TelegramRewriteOutput`, and assembles the exact nine-key stored content through the Release 2 boundary.
- Instagram/X/blog generation, edit, regeneration, and approval reject fabricated or mismatched citations against the exact selected story evidence before an approvable revision is created.
- Instagram/X/blog edits use the platform-matched immutable base-ID/hash contract and create only `pending_review` children; Telegram edit request shapes remain compatible.
- Every platform generation run stores the active non-null prompt-template-version ID for `telegram_pack`, `instagram_pack`, `x_pack`, or `blog_pack`; Telegram route rewriting continues to use `telegram_rewrite` only in Release 2.
- Every preview/editor uses an exact immutable revision and never implies live external state.
- Copy actions work per platform and report success/failure accessibly.
- JSON, Markdown, HTML, and ZIP exports are deterministic, sanitized, checksummed, and revision-bound.
- Export artifacts survive container replacement in `export_data`, are built only by `worker-source-generation`, and are downloaded only through the API manifest boundary.
- Instagram/X/blog manual plans require approval and preserve completion evidence.
- Reviewed Telegram revisions can be scheduled through the existing Telegram publishing boundary; both `PublishJob.scheduled_for` and its durable workflow job carry the exact UTC due time.
- The calendar combines real reviewed Telegram schedules and manual plans in the configured timezone.
- Library browses originals, stories, evidence, research runs, drafts, exports, and actual publications with separate truthful states and exact-record links.
- Desktop/mobile acceptance passes without Instagram, X, CMS, Telegram, or AI credentials.
