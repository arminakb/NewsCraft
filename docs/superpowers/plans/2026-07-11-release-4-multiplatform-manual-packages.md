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
- Every package is rendered from one immutable `StoryRevision`, one `BrandProfile`, and immutable prompt versions.
- Every edit/regeneration creates an immutable `PlatformVariantRevision`; approval remains tied to exact revision ID and content hash.
- Manual publication can be marked complete only for an approved, still-current revision. Editing creates a different unapproved revision and never mutates the publication plan.
- JSON, Markdown, HTML, and ZIP exports include a manifest with story revision, variant revision, content hash, approval state, generated time, and evidence URLs.
- Exported HTML is sanitized; filenames never contain user-controlled path separators; media is copied only from validated local `MediaAsset.storage_path` entries.
- All platform limits live in one backend module and every validation result is persisted with the revision.
- Calendar timestamps are stored in UTC and rendered in the chosen timezone, default `Asia/Tehran`.
- Do not add AI image/video generation. Produce source-media selections, carousel/thread assignments, alt text, briefs, and prompts for manual asset work.
- Each task is test-first and ends in a focused commit; never stage credentials, generated export bundles, local media, `.superpowers/`, or unrelated files.

## Dependencies and Exclusions

This plan consumes Release 3 `CanonicalStoryOutput`, `EditorialService`, `ContentPack`, `PlatformVariant`, `PlatformVariantRevision`, `CitationRef`, `editorialQueryKeys`, and exact-revision approval endpoints. It consumes Release 2 `app.generation.telegram_schema.TelegramRewriteOutput`, `app.publishing.telegram.renderer`, `PublishJob`, `Publication`, and `PublishOperationReceipt` without changing their idempotency or remote-delivery behavior.

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
- `app/exports/models.py`: export artifact and manifest value objects persisted in the owning workflow job result.
- `app/exports/service.py`: deterministic JSON/Markdown/HTML/ZIP building.
- `app/exports/handlers.py`: durable export job.
- `app/manual_publication/models.py`: manual plan/checklist state.
- `app/manual_publication/service.py`: exact-revision planning and completion rules.
- `app/manual_publication/calendar.py`: unified manual and Telegram calendar projection.
- `app/api/exports.py`: export creation/status/download endpoints.
- `app/api/calendar.py`: publication plans, checklist, completion, and calendar endpoints.

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
- Modify: `backend/app/generation/telegram_schema.py`
- Create: `backend/tests/generation/test_platform_schemas.py`
- Create: `backend/tests/generation/test_platform_validation.py`

**Interfaces:**
- Consumes: Release 2 `TelegramRewriteOutput` and Release 3 `CitationRef`.
- Produces: `InstagramVariantPayload`, `XVariantPayload`, `BlogVariantPayload`, `PlatformPayload`, `ValidationIssue`, and `validate_platform_payload()`.

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
    value = XVariantPayload(mode="thread", posts=[x_post(1, "a" * 281)], link_strategy="last_post", manual_checklist=[])
    issues = validate_platform_payload("x", value)
    assert issues == [ValidationIssue(code="x_post_too_long", path="posts.0.text", message="Post 1 is 281/280 weighted characters")]


def test_blog_requires_resolved_citations_and_complete_seo_fields():
    value = BlogVariantPayload.model_validate(blog_payload(citations=[]))
    issues = validate_platform_payload("blog", value)
    assert {issue.code for issue in issues} == {"blog_missing_citations"}
```

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


class TelegramVariantPayload(TelegramRewriteOutput):
    attribution_footer: str | None = Field(default=None, max_length=500)
    canonical_url: HttpUrl | None = None
    media: list[MediaAssignment]
    citations: list[CitationRef] = Field(min_length=1)
    manual_checklist: list[str] = Field(min_length=1)


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
    citations: list[CitationRef] = Field(min_length=1)
    tags: list[str] = Field(max_length=20)
    seo_description: str = Field(min_length=50, max_length=160)
    hero_media: MediaAssignment | None
    canonical_sources: list[HttpUrl] = Field(min_length=1)
    manual_checklist: list[str] = Field(min_length=1)


PlatformPayload = TelegramVariantPayload | InstagramVariantPayload | XVariantPayload | BlogVariantPayload
```

- [ ] **Step 4: Implement deterministic validation**

Set `INSTAGRAM_CAPTION_MAX = 2200`, `INSTAGRAM_HASHTAG_MAX = 30`, `INSTAGRAM_CAROUSEL_MAX = 20`, `X_POST_WEIGHT_MAX = 280`, `X_MEDIA_PER_POST_MAX = 4`, and `BLOG_SEO_DESCRIPTION_MAX = 160`. `x_weighted_length()` counts every normalized URL as 23 and every other Unicode code point as one; persist a warning code `x_platform_recheck_required` because final manual posting remains authoritative. Validators also enforce sequential order values, unique media assignments, at least one citation per factual post/section, non-empty alt text for assigned media, and exact platform/type agreement.

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
git add backend/app/generation/platform_schemas.py backend/app/generation/platform_limits.py backend/app/generation/platform_validation.py backend/app/generation/telegram_schema.py backend/tests/generation/test_platform_schemas.py backend/tests/generation/test_platform_validation.py
git commit -m "feat: define complete platform package schemas"
```

Expected: schema and validator tests pass.

---

### Task 2: Generate one validated multi-platform content pack

**Files:**
- Create: `backend/app/generation/multiplatform.py`
- Create: `backend/app/generation/platform_renderers.py`
- Modify: `backend/app/generation/editorial_service.py`
- Modify: `backend/app/generation/handlers.py`
- Modify: `backend/app/api/content_packs.py`
- Create: `backend/tests/generation/test_multiplatform.py`
- Modify: `backend/tests/api/test_content_pack_routes.py`

**Interfaces:**
- Consumes: Task 1 schemas/validators, Release 3 canonical revision/provider/pack services, Release 2 Telegram renderer.
- Produces: `MultiPlatformPackRequest`, `generate_platform_variants()`, persisted validation results, and requested-platform regeneration.

- [ ] **Step 1: Write failing generation tests**

```python
async def test_pack_generation_creates_four_variants_from_one_story_revision(editorial_service, canonical_revision, brand):
    result = await editorial_service.generate_pack(
        MultiPlatformPackRequest(
            story_revision_id=canonical_revision.id,
            brand_profile_id=brand.id,
            platforms=["telegram", "instagram", "x", "blog"],
            provider="fake",
        )
    )
    assert {revision.platform for revision in result.revisions} == {"telegram", "instagram", "x", "blog"}
    assert {revision.story_revision_id for revision in result.revisions} == {canonical_revision.id}
    assert all(revision.validation_errors == [] for revision in result.revisions)


async def test_schema_invalid_platform_output_becomes_needs_review_and_does_not_auto_approve(editorial_service, invalid_provider):
    result = await editorial_service.generate_pack(request_for("instagram"), provider=invalid_provider)
    revision = result.revisions[0]
    assert revision.approval_state == "unapproved"
    assert revision.validation_errors[0]["code"] == "instagram_caption_too_long"
    assert result.job_status == "needs_review"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation/test_multiplatform.py tests/api/test_content_pack_routes.py -q
```

Expected: failure because `MultiPlatformPackRequest` and renderer registry are absent.

- [ ] **Step 3: Implement requested-platform generation and rendering**

```python
class MultiPlatformPackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_revision_id: UUID
    brand_profile_id: UUID
    platforms: list[Literal["telegram", "instagram", "x", "blog"]] = Field(min_length=1)
    provider: Literal["fake", "openrouter", "codex"]


async def generate_platform_variants(request: MultiPlatformPackRequest, context: GenerationContext) -> GeneratedPack:
    revisions: list[PlatformVariantRevision] = []
    for platform in deduplicate_preserving_order(request.platforms):
        output = await context.provider.generate(context.request_for(platform))
        payload = PLATFORM_ADAPTERS[platform].validate_python(output.payload)
        issues = validate_platform_payload(platform, payload)
        revisions.append(await context.repository.create_revision(platform, payload, issues, output.attempt_id))
    return GeneratedPack(revisions=revisions)
```

Generation input includes canonical facts/citations, brand tone/language, source media, platform limits, and the relevant prompt version. It does not ask one platform to infer another platform's structure. Persist all error/warning issues. Any error moves the job to `needs_review`; warnings do not block human approval but remain visible.

- [ ] **Step 4: Expand API contracts**

`POST /stories/{story_id}/content-packs` accepts `platforms` instead of the Release 3 singular platform and returns one job. `POST /platform-variants/{variant_id}/regenerate` accepts provider plus optional operator instruction and creates a child revision for only that platform. `GET /content-packs/{pack_id}` returns variants ordered `telegram`, `instagram`, `x`, `blog` with current revision, all validation issues, media plan, and approval state.

```python
class RegenerateVariantRequest(BaseModel):
    provider: Literal["fake", "openrouter", "codex"]
    instruction: str | None = Field(default=None, max_length=1_000)
```

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation tests/api/test_content_pack_routes.py -q
.venv/bin/ruff check app/generation app/api/content_packs.py tests/generation tests/api/test_content_pack_routes.py
git diff --check
cd ..
git add backend/app/generation backend/app/api/content_packs.py backend/tests/generation backend/tests/api/test_content_pack_routes.py
git commit -m "feat: generate validated multi-platform packs"
```

Expected: generation and API tests pass.

---

### Task 3: Build deterministic JSON, Markdown, HTML, and media-bundle exports

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/exports/__init__.py`
- Create: `backend/app/exports/models.py`
- Create: `backend/app/exports/service.py`
- Create: `backend/app/exports/handlers.py`
- Create: `backend/app/api/exports.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/exports/test_service.py`
- Create: `backend/tests/exports/test_handlers.py`
- Create: `backend/tests/api/test_export_routes.py`

**Interfaces:**
- Consumes: exact platform revisions and local validated media.
- Produces: `ExportRequest`, `ExportArtifact`, job type `build_export`, export status/download endpoints, and deterministic checksummed bundles.

- [ ] **Step 1: Write failing export tests**

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

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/exports tests/api/test_export_routes.py -q
```

Expected: import failures for export modules.

- [ ] **Step 3: Implement exact artifact contracts and safe rendering**

Add these runtime dependencies:

```toml
"markdown>=3.8",
"nh3>=0.3",
```

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

- [ ] **Step 4: Add durable export endpoints**

```text
POST /content-packs/{pack_id}/exports             -> 202 JobAcceptedOut
GET  /exports/{export_id}                         -> ExportArtifactOut
GET  /exports/{export_id}/download/{file_name}    -> application/octet-stream
```

The POST creates `build_export:{pack_id}:{sorted_revision_hashes}:{request_hash}`. GET loads the durable workflow job and validates its typed artifact result. Download resolves only filenames listed in that job's artifact manifest and sets `Content-Disposition: attachment`. Export generation is a worker job; no route copies media inline.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/exports tests/api/test_export_routes.py tests/jobs -q
.venv/bin/ruff check app/exports app/api/exports.py tests/exports tests/api/test_export_routes.py
git diff --check
cd ..
git add backend/pyproject.toml backend/app/exports backend/app/api/exports.py backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/exports backend/tests/api/test_export_routes.py
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
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/manual_publication/test_service.py`
- Create: `backend/tests/manual_publication/test_calendar.py`
- Create: `backend/tests/api/test_calendar_routes.py`
- Create: `backend/tests/test_manual_publication_migration.py`

**Interfaces:**
- Consumes: approved variant revisions and Release 2 scheduled `PublishJob`/`Publication` rows.
- Produces: `ManualPublicationPlan`, `ManualPublicationService`, `CalendarEvent`, plan/checklist/completion APIs, and `GET /calendar`.

- [ ] **Step 1: Write failing migration and exact-revision tests**

```python
def test_manual_publication_migration_has_revision_and_schedule_constraints():
    migration = Path("alembic/versions/0007_manual_publication_plans.py").read_text()
    assert 'revision = "0007_manual_publication_plans"' in migration
    assert 'down_revision = "0006_telegram_automation_vertical"' in migration
    assert "manual_publication_plans" in migration
    assert "platform_variant_revision_id" in migration
    assert "scheduled_for" in migration


async def test_plan_requires_exact_approved_revision(db_session, unapproved_revision):
    with pytest.raises(ManualPublicationError, match="revision is not approved"):
        await ManualPublicationService(db_session).create_plan(unapproved_revision.id, scheduled_for(), "Asia/Tehran")


async def test_completion_preserves_revision_identity_and_operator_evidence(db_session, approved_instagram_revision):
    plan = await ManualPublicationService(db_session).create_plan(approved_instagram_revision.id, scheduled_for(), "Asia/Tehran")
    completed = await ManualPublicationService(db_session).mark_published(plan.id, external_url="https://instagram.com/p/abc", note="Posted from mobile")
    assert completed.platform_variant_revision_id == approved_instagram_revision.id
    assert completed.status == "manual_published"
    assert completed.completed_at is not None
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/manual_publication tests/api/test_calendar_routes.py tests/test_manual_publication_migration.py -q
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

`GET /calendar?start=<UTC>&end=<UTC>&timezone=Asia/Tehran` validates a maximum 93-day window, returns manual plans plus scheduled Telegram publish jobs, and performs no timezone-naive comparisons. Add `POST /manual-publication-plans`, `PATCH /manual-publication-plans/{id}/checklist`, `POST /manual-publication-plans/{id}/mark-published`, and `POST /manual-publication-plans/{id}/cancel`. Every mutation records a `WorkflowEvent`.

- [ ] **Step 5: Run migration, tests, and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/manual_publication tests/api/test_calendar_routes.py tests/test_manual_publication_migration.py -q
.venv/bin/ruff check app/manual_publication app/api/calendar.py tests/manual_publication tests/api/test_calendar_routes.py
alembic upgrade head
alembic downgrade 0006_telegram_automation_vertical
alembic upgrade head
git diff --check
cd ..
git add backend/alembic/versions/0007_manual_publication_plans.py backend/app/db/model_registry.py backend/app/manual_publication backend/app/api/calendar.py backend/app/api/routes.py backend/tests/manual_publication backend/tests/api/test_calendar_routes.py backend/tests/test_manual_publication_migration.py
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
- Modify: `frontend/app/review/[variantId]/page.tsx`
- Create: `frontend/tests/platform-previews.test.tsx`
- Create: `frontend/tests/platform-editor.test.tsx`
- Create: `frontend/tests/media-plan.test.tsx`

**Interfaces:**
- Consumes: Task 1/2 payloads and Release 3 revision editor contract.
- Produces: discriminated `PlatformPayload`, preview/editor dispatch, and accessible validation/media displays.

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
  expect(screen.getByText(revision.payload.citations[0].sourceUrl)).toBeInTheDocument()
})

it("shows backend validation and creates a new revision instead of mutating", async () => {
  const onSave = vi.fn()
  render(<PlatformEditor revision={instagramRevisionWithError} onSave={onSave} />)
  expect(screen.getByText("Caption is 2240/2200 characters")).toBeInTheDocument()
  await userEvent.clear(screen.getByLabelText("Caption"))
  await userEvent.type(screen.getByLabelText("Caption"), "Short caption")
  await userEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ baseRevisionId: instagramRevisionWithError.id }))
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
  | { platform: "telegram"; id: string; contentHash: string; payload: TelegramPayload; validation: ValidationIssue[] }
  | { platform: "instagram"; id: string; contentHash: string; payload: InstagramPayload; validation: ValidationIssue[] }
  | { platform: "x"; id: string; contentHash: string; payload: XPayload; validation: ValidationIssue[] }
  | { platform: "blog"; id: string; contentHash: string; payload: BlogPayload; validation: ValidationIssue[] }
```

The dispatcher uses exhaustive `switch (revision.platform)` with a `never` assertion. Previews label themselves as approximations, render actual copy/media/order/alt text/citations, and never claim pixel parity with external apps. Editors expose every schema field, preserve citation objects, show character counts and backend issues, and save through the Release 3 immutable revision API.

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
- Create: `frontend/app/calendar/page.tsx`
- Modify: `frontend/lib/query-keys.ts`
- Modify: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Modify: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/tests/copy-export-actions.test.tsx`
- Create: `frontend/tests/manual-publishing-checklist.test.tsx`
- Create: `frontend/tests/publication-calendar.test.tsx`
- Modify: `frontend/tests/navigation.test.tsx`

**Interfaces:**
- Consumes: Task 3 exports, Task 4 plans/calendar, Task 5 current revisions.
- Produces: copy formats, durable export job outcomes, persisted checklists, manual completion, and calendar navigation.

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
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/copy-export-actions.test.tsx tests/manual-publishing-checklist.test.tsx tests/publication-calendar.test.tsx
```

Expected: import failures for the new components.

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
Add the now-working `Calendar` route to desktop and mobile Newsroom navigation and extend `frontend/tests/navigation.test.tsx` to assert both links target `/calendar`.

- [ ] **Step 5: Run tests, type check, and commit**

```bash
cd frontend
npm run test -- tests/copy-export-actions.test.tsx tests/manual-publishing-checklist.test.tsx tests/publication-calendar.test.tsx
npm run typecheck
git diff --check
cd ..
git add frontend/features/packages/components/copy-export-actions.tsx frontend/features/packages/components/manual-publishing-checklist.tsx frontend/features/calendar frontend/app/calendar/page.tsx frontend/lib/query-keys.ts frontend/components/newsroom/newsroom-sidebar.tsx frontend/components/newsroom/mobile-newsroom-nav.tsx frontend/tests/copy-export-actions.test.tsx frontend/tests/manual-publishing-checklist.test.tsx frontend/tests/publication-calendar.test.tsx frontend/tests/navigation.test.tsx
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
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
alembic upgrade head
alembic downgrade 0006_telegram_automation_vertical
alembic upgrade head
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
- Every preview/editor uses an exact immutable revision and never implies live external state.
- Copy actions work per platform and report success/failure accessibly.
- JSON, Markdown, HTML, and ZIP exports are deterministic, sanitized, checksummed, and revision-bound.
- Instagram/X/blog manual plans require approval and preserve completion evidence.
- The calendar combines real Telegram schedules and manual plans in the configured timezone.
- Desktop/mobile acceptance passes without Instagram, X, CMS, Telegram, or AI credentials.
