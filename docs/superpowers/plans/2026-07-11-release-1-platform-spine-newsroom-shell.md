# Release 1 Platform Spine and Newsroom Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace NewsCraft's synchronous, one-shot operations path with a durable PostgreSQL workflow spine, an observable scheduler/worker, safe global controls, deterministic fake AI contracts, and a truthful Newsroom Command Center home and job queue.

**Architecture:** Release 1 establishes application-owned domain records without pretending later editorial or Telegram flows already work. PostgreSQL owns jobs, leases, schedules, controls, attempts, revisions, and append-only events; FastAPI mutations enqueue work; a long-running worker executes registered handlers; a separate scheduler materializes due source collection jobs. The Next.js root becomes a responsive Newsroom shell whose Today and Job Queue views render only live API state, while the proven ingestion/content/media screens remain available as secondary operations pages.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, Pydantic 2, PostgreSQL 18, Alembic, pytest, pytest-asyncio, Ruff, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Testing Library, Playwright, Docker Compose.

## Execution Prerequisite

Release 0 must be fully implemented and verified before starting this plan. Start from its clean final commit in an isolated worktree created with `superpowers:using-git-worktrees`; do not execute Release 1 on top of the pre-Release-0 dirty cleanup tree.

Run before Task 1:

```bash
git status --short --branch
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests -q && .venv/bin/ruff check .
cd ../frontend && npm run test && npm run typecheck && npm run build
cd .. && docker compose config >/tmp/newscraft-release1-prerequisite.yml
```

Expected: the worktree is clean, all Release 0 checks pass, and Compose validation exits `0`.

## Global Constraints

- Product mode remains local and single operator; do not add accounts, authentication, RBAC, billing, Redis, Celery, Kafka, or Kubernetes.
- PostgreSQL is the only durable queue. Queue claiming must use `FOR UPDATE SKIP LOCKED`, worker leases, heartbeats, and deterministic idempotency keys.
- Store timestamps as timezone-aware UTC values. The scheduler computes local due times with `zoneinfo.ZoneInfo`; the default timezone is exactly `Asia/Tehran` and the default daily collection time is exactly `06:00`.
- Job status values are exactly `queued`, `running`, `succeeded`, `failed`, `needs_review`, and `cancelled`.
- Job error classes are exactly `retryable`, `needs_review`, and `permanent`. Job origins are exactly `manual`, `scheduler`, `automation`, and `retry`.
- Global pause holds every queued `pause_sensitive=True` job and prevents the scheduler from materializing new due jobs. Lease recovery and explicitly manual `pause_sensitive=False` jobs continue to work while paused.
- `review_required` remains the default publishing policy. `auto_publish` is only an explicit value on a route; no Release 1 code may publish anything.
- `dry_run` is persisted in the singleton global control and exposed in the UI, but only later publishing handlers consume it.
- Secrets are references such as `OPENROUTER_API_KEY` or `TELEGRAM_DESTINATION_NEWS_TOKEN`; no API, JSONB payload, event, database content field, fixture, or log stores a credential value.
- Event payloads must recursively redact keys matching `authorization`, `cookie`, `token`, `secret`, `password`, or `api_key`, case-insensitively.
- Existing ingestion, normalization, media, classification, scoring, diagnostics, and source behavior must remain green.
- Every behavior change is test-first, every task ends with the named commit, and unrelated files are never staged.

## Explicit Release 1 Exclusions

- Do not implement OpenRouter HTTP calls, `codex exec`, DuckDuckGo search, research completeness evaluation, or source fetching beyond the existing ingestion service.
- Do not implement Telegram Bot API publishing, MTProto sessions, album capture, route polling, bounded backfill, cursor advancement, or media re-upload. Release 2 consumes the contracts defined here.
- Do not implement story grouping, evidence capture behavior, generation orchestration, content-pack editing, approvals, platform rendering, or exports. Their durable records and provider boundary are introduced now; Release 3 and Release 4 activate them.
- Do not add dead navigation links for Automations, Drafts, Review & Publish, or Library. Add those links only in the release that supplies the working screen.
- Do not remove the existing manual approval endpoint in this release; do not connect new work to that overloaded legacy state.
- Do not claim that pause cancels a running job. Pause prevents future claims and schedule materialization; a running job completes or fails normally.

## Locked Cross-Release Contracts

Later plans import these names verbatim. Changing them requires updating every later plan before implementation.

### Backend module map

| Responsibility | Public module and names |
| --- | --- |
| Editorial records | `app.stories.models`: `Story`, `StoryEvidenceSnapshot`, `StoryRevision`, `StoryEvidenceLink` |
| Brand and prompts | `app.generation.models`: `BrandProfile`, `PromptTemplate`, `PromptTemplateVersion`, `AIProviderProfile`, `GenerationRun`, `GenerationAttempt`, `ContentPack`, `PlatformVariant`, `PlatformVariantRevision` |
| Research records | `app.research.models`: `ResearchRun`, `ResearchAttempt`, `ResearchSource` |
| Destination/publication | `app.publishing.models`: `Destination`, `PublishJob`, `PublishAttempt`, `Publication` |
| Automation records | `app.automations.models`: `AutomationRoute` |
| Workflow engine | `app.jobs.models`: `WorkflowJob`, `WorkflowEvent`, `WorkflowSchedule`, `AutomationControl` |
| Queue API | `app.jobs.repository`: `JobRepository`, `EnqueueJobResult` |
| Handler extension | `app.jobs.registry`: `JobContext`, `JobHandler`, `JobHandlerRegistry`, `build_default_registry` |
| Job schemas | `app.jobs.schemas`: `JobAcceptedOut`, `JobOut`, `JobDetailOut`, `JobListOut`, `JobSummaryOut` |
| Provider contract | `app.generation.providers.base`: `ProviderMessage`, `GenerationProviderRequest`, `GenerationProviderResult`, `GenerationProvider` |
| Provider registry | `app.generation.providers.registry`: `ProviderRegistry`, `build_default_provider_registry` |

The queue method signatures are:

```python
@dataclass(frozen=True, slots=True)
class EnqueueJobResult:
    job: WorkflowJob
    created: bool


async def enqueue_job(
    self,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    origin: JobOrigin,
    priority: int = 0,
    scheduled_for: datetime | None = None,
    max_attempts: int = 3,
    pause_sensitive: bool = True,
) -> EnqueueJobResult: ...

async def claim_next_job(
    self,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> WorkflowJob | None: ...

async def heartbeat_job(
    self,
    *,
    job_id: UUID,
    worker_id: str,
    lease_seconds: int,
    progress: int | None = None,
    progress_message: str | None = None,
    now: datetime | None = None,
) -> bool: ...

async def finish_job(
    self,
    *,
    job_id: UUID,
    worker_id: str,
    result: dict[str, Any],
    now: datetime | None = None,
) -> WorkflowJob: ...

async def fail_job(
    self,
    *,
    job_id: UUID,
    worker_id: str,
    error_class: JobErrorClass,
    error_code: str,
    error_message: str,
    retry_at: datetime | None = None,
    now: datetime | None = None,
) -> WorkflowJob: ...

async def retry_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob: ...
async def cancel_job(self, *, job_id: UUID, now: datetime | None = None) -> WorkflowJob: ...
async def requeue_expired_leases(self, *, now: datetime | None = None) -> int: ...
async def get_job(self, job_id: UUID) -> WorkflowJob | None: ...
async def list_jobs(
    self,
    *,
    statuses: tuple[JobStatus, ...] = (),
    job_type: str | None = None,
    error_class: JobErrorClass | None = None,
    limit: int = 100,
) -> list[WorkflowJob]: ...
```

`JobHandler` is `Callable[[WorkflowJob, JobContext], Awaitable[dict[str, Any]]]`. `JobContext` has exactly `session: AsyncSession` and `providers: ProviderRegistry`. `JobHandlerRegistry.register(job_type, handler)` rejects duplicate registrations; `get(job_type)` raises `UnknownJobTypeError` for an unknown type.

The provider value objects are:

```python
@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class GenerationProviderRequest:
    run_id: UUID
    purpose: str
    requested_model: str | None
    messages: tuple[ProviderMessage, ...]
    response_schema: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GenerationProviderResult:
    provider: str
    requested_model: str | None
    resolved_model: str
    output: dict[str, Any]
    raw_text: str
    usage: dict[str, Any]
    finish_reason: str | None


class GenerationProvider(Protocol):
    provider_name: str

    async def generate(self, request: GenerationProviderRequest) -> GenerationProviderResult: ...
```

## Data Contract A: Platform Spine

All IDs are PostgreSQL UUID primary keys created with `uuid.uuid4`; all JSON columns are non-null JSONB with `{}` or `[]` server defaults as shown; every `created_at` is non-null `timestamptz` with `now()`.

| Model / table | Exact columns beyond `id` |
| --- | --- |
| `Story` / `stories` | `title Text`, `status Text='open'`, `primary_language Text='en'`, `created_at`, `updated_at` |
| `StoryEvidenceSnapshot` / `story_evidence_snapshots` | `story_id FK stories`, `content_item_id FK content_items NULL`, `source_url Text`, `title Text NULL`, `content_text Text`, `authors JSONB=[]`, `published_at timestamptz NULL`, `content_sha256 Text`, `snapshot_metadata JSONB={}`, `captured_at` |
| `StoryRevision` / `story_revisions` | `story_id FK stories`, `revision_number Integer`, `narrative Text`, `facts JSONB=[]`, `disagreements JSONB=[]`, `angles JSONB=[]`, `citations JSONB=[]`, `created_by Text`, `created_at`; unique `(story_id, revision_number)` |
| `StoryEvidenceLink` / `story_evidence_links` | `story_revision_id FK story_revisions`, `evidence_snapshot_id FK story_evidence_snapshots`, `claim_key Text`, `relationship Text='supports'`, `created_at`; unique `(story_revision_id, evidence_snapshot_id, claim_key)` |
| `BrandProfile` / `brand_profiles` | `name Text unique`, `output_language Text`, `tone Text`, `editorial_rules JSONB=[]`, `attribution_rules JSONB={}`, `default_hashtags JSONB=[]`, `platform_preferences JSONB={}`, `is_default Boolean=false`, `created_at`, `updated_at` |
| `PromptTemplate` / `prompt_templates` | `purpose_key Text unique`, `name Text`, `description Text NULL`, `created_at`, `updated_at` |
| `PromptTemplateVersion` / `prompt_template_versions` | `prompt_template_id FK prompt_templates`, `version Integer`, `system_template Text`, `user_template Text`, `output_schema_version Text`, `output_schema JSONB={}`, `checksum_sha256 Text`, `is_active Boolean=false`, `created_at`; unique `(prompt_template_id, version)` |
| `AIProviderProfile` / `ai_provider_profiles` | `name Text unique`, `provider_type Text`, `default_model Text NULL`, `secret_ref Text NULL`, `settings JSONB={}`, `enabled Boolean=true`, `created_at`, `updated_at` |
| `ResearchRun` / `research_runs` | `story_id FK stories`, `requested_mode Text`, `provider_profile_id FK ai_provider_profiles NULL`, `status Text`, `query_budget Integer=0`, `page_budget Integer=0`, `time_budget_seconds Integer=0`, `result_story_revision_id FK story_revisions NULL`, `created_at`, `started_at NULL`, `finished_at NULL` |
| `ResearchAttempt` / `research_attempts` | `research_run_id FK research_runs`, `attempt_number Integer`, `queries JSONB=[]`, `status Text`, `usage JSONB={}`, `error_class Text NULL`, `error_code Text NULL`, `error_message Text NULL`, `started_at`, `finished_at NULL`; unique `(research_run_id, attempt_number)` |
| `ResearchSource` / `research_sources` | `research_run_id FK research_runs`, `url Text`, `title Text NULL`, `publisher Text NULL`, `published_at NULL`, `content_sha256 Text NULL`, `extraction_status Text`, `relevance Numeric=0`, `citation_key Text`, `snapshot_metadata JSONB={}`, `created_at`; unique `(research_run_id, url)` |
| `GenerationRun` / `generation_runs` | `story_revision_id FK story_revisions NULL`, `provider_profile_id FK ai_provider_profiles NULL`, `prompt_template_version_id FK prompt_template_versions`, `requested_model Text NULL`, `status Text`, `input_hash Text`, `request_payload JSONB={}`, `output_payload JSONB={}`, `error_class Text NULL`, `error_code Text NULL`, `error_message Text NULL`, `started_at NULL`, `finished_at NULL`, `created_at` |
| `GenerationAttempt` / `generation_attempts` | `generation_run_id FK generation_runs`, `attempt_number Integer`, `provider Text`, `requested_model Text NULL`, `resolved_model Text NULL`, `prompt_snapshot JSONB={}`, `response_payload JSONB={}`, `usage JSONB={}`, `validation_errors JSONB=[]`, `status Text`, `error_class Text NULL`, `error_code Text NULL`, `error_message Text NULL`, `started_at`, `finished_at NULL`; unique `(generation_run_id, attempt_number)` |
| `ContentPack` / `content_packs` | `story_revision_id FK story_revisions`, `brand_profile_id FK brand_profiles`, `status Text='draft'`, `created_at`, `updated_at`; unique `(story_revision_id, brand_profile_id)` |
| `PlatformVariant` / `platform_variants` | `content_pack_id FK content_packs`, `platform Text`, `created_at`; unique `(content_pack_id, platform)` |
| `PlatformVariantRevision` / `platform_variant_revisions` | `platform_variant_id FK platform_variants`, `revision_number Integer`, `content JSONB={}`, `content_hash Text`, `evidence_map JSONB=[]`, `validation_results JSONB=[]`, `approval_state Text='draft'`, `approved_at NULL`, `created_by Text`, `created_at`; unique `(platform_variant_id, revision_number)` |
| `Destination` / `destinations` | `name Text`, `platform Text`, `target_ref Text`, `secret_ref Text`, `enabled Boolean=false`, `health_status Text='unknown'`, `last_health_check_at NULL`, `settings JSONB={}`, `created_at`, `updated_at`; unique `(platform, target_ref)` |
| `AutomationRoute` / `automation_routes` | `name Text`, `source_id FK sources`, `destination_id FK destinations`, `brand_profile_id FK brand_profiles`, `prompt_template_version_id FK prompt_template_versions`, `ai_provider_profile_id FK ai_provider_profiles`, `access_mode Text='public_html'`, `research_mode Text='off'`, `content_filters JSONB={}`, `media_policy Text='preserve'`, `attribution_policy Text='preserve'`, `custom_footer Text NULL`, `publishing_policy Text='review_required'`, `poll_interval_seconds Integer=300`, `quiet_hours JSONB={}`, `retry_policy JSONB={}`, `cursor_state JSONB={}`, `enabled Boolean=false`, `paused_at NULL`, `last_polled_at NULL`, `next_poll_at NULL`, `backfill_limit Integer NULL`, `backfill_since NULL`, `created_at`, `updated_at` |
| `PublishJob` / `publish_jobs` | `workflow_job_id FK workflow_jobs NULL`, `destination_id FK destinations`, `platform_variant_revision_id FK platform_variant_revisions`, `status Text`, `idempotency_key Text unique`, `payload_hash Text`, `scheduled_for NULL`, `created_at`, `updated_at` |
| `PublishAttempt` / `publish_attempts` | `publish_job_id FK publish_jobs`, `attempt_number Integer`, `sanitized_payload JSONB={}`, `payload_hash Text`, `status Text`, `http_status Integer NULL`, `remote_response JSONB={}`, `error_class Text NULL`, `error_code Text NULL`, `error_message Text NULL`, `started_at`, `finished_at NULL`; unique `(publish_job_id, attempt_number)` |
| `Publication` / `publications` | `publish_job_id FK publish_jobs unique`, `destination_id FK destinations`, `platform_variant_revision_id FK platform_variant_revisions`, `remote_message_ids JSONB=[]`, `permalink Text NULL`, `payload_hash Text`, `published_at`, `reconciliation_status Text='confirmed'`; unique `(destination_id, platform_variant_revision_id)` |

`PublishJob.workflow_job_id` is declared by migration `0005_job_engine_and_scheduling` after `workflow_jobs` exists. In model code it is nullable from the start; migration `0004_platform_spine` creates `publish_jobs` without that column, and `0005` adds the column plus foreign key.

---

### Task 1: Add the explicit platform-spine models and migration

**Files:**
- Modify: `backend/app/db/base.py`
- Modify: `backend/app/db/models.py`
- Create: `backend/app/db/model_registry.py`
- Create: `backend/app/stories/__init__.py`
- Create: `backend/app/stories/models.py`
- Create: `backend/app/research/__init__.py`
- Create: `backend/app/research/models.py`
- Create: `backend/app/generation/__init__.py`
- Create: `backend/app/generation/models.py`
- Create: `backend/app/automations/__init__.py`
- Create: `backend/app/automations/models.py`
- Create: `backend/app/publishing/__init__.py`
- Create: `backend/app/publishing/models.py`
- Modify: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0004_platform_spine.py`
- Modify: `backend/tests/test_models.py`
- Create: `backend/tests/test_platform_spine_migration.py`

**Interfaces:**
- Consumes: existing `Base`, PostgreSQL UUID/JSONB conventions, `ContentItem`, and `Source`.
- Produces: every model in Data Contract A except the four job-engine models and the deferred `PublishJob.workflow_job_id` column.

- [ ] **Step 1: Write failing metadata tests**

Change `backend/tests/test_models.py` to import `Base` from `app.db.model_registry`. Add one table-driven test whose expected mapping is the table/column list in Data Contract A, excluding `workflow_jobs`, `workflow_events`, `workflow_schedules`, `automation_controls`, and `publish_jobs.workflow_job_id`. Assert every table exists, every named column exists, and the named unique constraints exist.

Add relationship-safety assertions:

```python
def test_platform_spine_keeps_editorial_and_machine_state_separate():
    content_columns = set(Base.metadata.tables["content_items"].columns)
    revision_columns = set(Base.metadata.tables["platform_variant_revisions"].columns)

    assert "approval_state" not in content_columns
    assert {"approval_state", "content_hash", "revision_number"}.issubset(revision_columns)


def test_destination_stores_a_secret_reference_not_a_secret_value():
    columns = set(Base.metadata.tables["destinations"].columns)

    assert "secret_ref" in columns
    assert "token" not in columns
    assert "api_key" not in columns
```

- [ ] **Step 2: Run the model tests and verify failure**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py -q
```

Expected: FAIL because the platform-spine tables are not registered.

- [ ] **Step 3: Move shared mapped-column helpers and implement focused model modules**

Move `uuid_pk()` and `timestamp_now()` from `app/db/models.py` to `app/db/base.py`, re-import them into the existing model module, and keep their behavior unchanged. Implement every mapped class and constraint exactly as Data Contract A specifies. Use `Mapped[...]`, `mapped_column`, PostgreSQL `UUID`, `JSONB`, and `ARRAY`; do not use database enum types or cascade deletion.

Create `app/db/model_registry.py` as the single Alembic metadata import point:

```python
from app.automations.models import AutomationRoute
from app.db.base import Base
from app.db.models import ContentDraft, ContentItem, IngestRun, ItemIdentity, ItemMedia, MediaAsset, RawPayload, RewriteCandidate, Source, SourceItem
from app.generation.models import AIProviderProfile, BrandProfile, ContentPack, GenerationAttempt, GenerationRun, PlatformVariant, PlatformVariantRevision, PromptTemplate, PromptTemplateVersion
from app.publishing.models import Destination, Publication, PublishAttempt, PublishJob
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

__all__ = ["Base"]
```

Format the long imports with Ruff rather than suppressing `E501`. Update Alembic to `from app.db.model_registry import Base`.

- [ ] **Step 4: Write the failing migration-contract test**

Create `backend/tests/test_platform_spine_migration.py`:

```python
from pathlib import Path


def test_platform_spine_migration_has_stable_revision_and_tables():
    migration = Path("alembic/versions/0004_platform_spine.py").read_text(encoding="utf-8")

    assert 'revision = "0004_platform_spine"' in migration
    assert 'down_revision = "0003_content_intelligence_schema"' in migration
    for table in (
        "stories", "story_evidence_snapshots", "story_revisions", "story_evidence_links",
        "brand_profiles", "prompt_templates", "prompt_template_versions", "ai_provider_profiles",
        "research_runs", "research_attempts", "research_sources", "generation_runs",
        "generation_attempts", "content_packs", "platform_variants", "platform_variant_revisions",
        "destinations", "automation_routes", "publish_jobs", "publish_attempts", "publications",
    ):
        assert f'"{table}"' in migration


def test_platform_spine_migration_is_reversible():
    migration = Path("alembic/versions/0004_platform_spine.py").read_text(encoding="utf-8")

    assert "def downgrade() -> None:" in migration
    assert migration.count("op.drop_table(") == 21
```

Run it and expect failure because the migration is absent.

- [ ] **Step 5: Implement migration `0004_platform_spine`**

Create all 21 tables in foreign-key order from Data Contract A. Create indexes on every foreign key used for chronological lookup and these named indexes: `ix_story_revisions_story_created`, `ix_generation_runs_status_created`, `ix_automation_routes_enabled_next_poll`, `ix_publish_jobs_status_scheduled`, and `ix_publications_published_at`. In `downgrade()`, drop those indexes and all tables in exact reverse dependency order. `publish_jobs` omits `workflow_job_id` until migration `0005`.

- [ ] **Step 6: Verify models and migration, then commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_models.py tests/test_platform_spine_migration.py -q
.venv/bin/ruff check app/db app/stories app/research app/generation app/automations app/publishing alembic/versions/0004_platform_spine.py tests/test_models.py tests/test_platform_spine_migration.py
cd ..
git add backend/app/db backend/app/stories backend/app/research backend/app/generation \
  backend/app/automations backend/app/publishing backend/alembic/env.py \
  backend/alembic/versions/0004_platform_spine.py backend/tests/test_models.py \
  backend/tests/test_platform_spine_migration.py
git commit -m "feat: add content platform domain spine"
```

Expected: focused tests and Ruff pass; the commit contains no workflow behavior.

---

### Task 2: Add workflow-job, schedule, event, and global-control persistence

**Files:**
- Create: `backend/app/jobs/__init__.py`
- Create: `backend/app/jobs/types.py`
- Create: `backend/app/jobs/models.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/model_registry.py`
- Modify: `backend/app/publishing/models.py`
- Create: `backend/alembic/versions/0005_job_engine_and_scheduling.py`
- Create: `backend/tests/test_job_models.py`
- Create: `backend/tests/test_job_engine_migration.py`
- Modify: `docker-compose.yml`
- Modify: `backend/tests/test_docker_config.py`

**Interfaces:**
- Consumes: migration head `0004_platform_spine` and Data Contract A.
- Produces: migration head `0005_job_engine_and_scheduling`, the status/error/origin enums, four durable job-engine models, `Source.next_fetch_at`, and `PublishJob.workflow_job_id`.

- [ ] **Step 1: Write failing workflow metadata and enum tests**

Create `backend/tests/test_job_models.py` with exact enum-value assertions and required columns:

```python
from app.db.model_registry import Base
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus


def test_job_enum_values_are_stable_cross_release_contracts():
    assert [value.value for value in JobStatus] == ["queued", "running", "succeeded", "failed", "needs_review", "cancelled"]
    assert [value.value for value in JobErrorClass] == ["retryable", "needs_review", "permanent"]
    assert [value.value for value in JobOrigin] == ["manual", "scheduler", "automation", "retry"]


def test_workflow_job_columns_support_leases_retries_progress_and_attention():
    columns = set(Base.metadata.tables["workflow_jobs"].columns)
    assert {
        "job_type", "status", "payload", "result", "priority", "idempotency_key", "origin",
        "pause_sensitive", "scheduled_for", "attempt_count", "max_attempts", "lease_owner",
        "lease_expires_at", "heartbeat_at", "progress", "progress_message", "error_class",
        "error_code", "error_message", "started_at", "finished_at", "created_at", "updated_at",
    } == columns - {"id"}


def test_source_and_publish_models_link_to_scheduler_and_queue():
    assert "next_fetch_at" in Base.metadata.tables["sources"].columns
    assert "workflow_job_id" in Base.metadata.tables["publish_jobs"].columns
```

Run the file and expect import/table failures.

- [ ] **Step 2: Implement exact enums and job-engine models**

Use `StrEnum` in `app/jobs/types.py`. Define:

- `WorkflowJob` exactly as the test above, with JSONB defaults `{}`, `priority=0`, `pause_sensitive=true`, `attempt_count=0`, `max_attempts=3`, `progress=0`, `status='queued'`, unique `idempotency_key`, and a check constraint `progress >= 0 AND progress <= 100`.
- `WorkflowEvent`: `id`, nullable `workflow_job_id` FK, `event_type Text`, `actor Text`, `event_data JSONB={}`, and `created_at`.
- `WorkflowSchedule`: `id`, `schedule_key Text unique`, nullable `source_id` FK, `name Text`, `job_type Text`, `payload JSONB={}`, `schedule_kind Text`, `timezone Text='Asia/Tehran'`, nullable `local_time Text`, nullable `interval_minutes Integer`, nullable `next_run_at`, `enabled Boolean=true`, `pause_sensitive Boolean=true`, nullable `last_enqueued_at`, `created_at`, `updated_at`.
- `AutomationControl`: text primary key `id`, `global_pause Boolean=false`, `dry_run Boolean=false`, nullable `pause_reason`, nullable `paused_at`, and `updated_at`.

Add `Source.next_fetch_at: datetime | None`. Add nullable `PublishJob.workflow_job_id` with an index.

Create indexes exactly named `ix_workflow_jobs_claim`, `ix_workflow_jobs_lease_expiry`, `ix_workflow_jobs_attention`, `ix_workflow_events_job_created`, `ix_workflow_events_created`, `ix_workflow_schedules_due`, and `ix_sources_next_fetch_at`.

- [ ] **Step 3: Write the migration and Compose contract tests**

Create `backend/tests/test_job_engine_migration.py` to assert revision `0005_job_engine_and_scheduling`, down revision `0004_platform_spine`, all four job tables, `next_fetch_at`, `workflow_job_id`, every named index, and a downgrade that removes the added columns before dropping tables.

Extend `backend/tests/test_docker_config.py` with:

```python
def test_compose_has_ephemeral_postgres_test_profile():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service = compose["services"]["postgres-test"]

    assert service["image"] == "postgres:18"
    assert service["profiles"] == ["test"]
    assert service["environment"]["POSTGRES_DB"] == "newscraft_test"
    assert service["ports"] == ["127.0.0.1:55432:5432"]
    assert "/var/lib/postgresql" in service["tmpfs"]
```

Run both files and expect failure.

- [ ] **Step 4: Implement migration `0005` and isolated test PostgreSQL**

Create the four job tables and named indexes, add both deferred columns/FKs, and insert exactly one singleton control row with `id='global'`, `global_pause=false`, and `dry_run=false`. Downgrade removes the singleton with its table.

Add this Compose service without changing normal startup:

```yaml
postgres-test:
  image: postgres:18
  profiles: ["test"]
  environment:
    POSTGRES_USER: newscraft
    POSTGRES_PASSWORD: newscraft
    POSTGRES_DB: newscraft_test
  ports:
    - "127.0.0.1:55432:5432"
  tmpfs:
    - /var/lib/postgresql
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U newscraft -d newscraft_test"]
    interval: 2s
    timeout: 2s
    retries: 30
```

- [ ] **Step 5: Verify migration order and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_job_models.py tests/test_job_engine_migration.py tests/test_docker_config.py -q
PYTHONPATH=. .venv/bin/alembic upgrade head --sql >/tmp/newscraft-release1-spine.sql
.venv/bin/ruff check app/jobs app/db app/publishing alembic/versions/0005_job_engine_and_scheduling.py tests/test_job_models.py tests/test_job_engine_migration.py
cd ..
docker compose --profile test config >/tmp/newscraft-release1-test-compose.yml
git add backend/app/jobs backend/app/db backend/app/publishing \
  backend/alembic/versions/0005_job_engine_and_scheduling.py backend/tests/test_job_models.py \
  backend/tests/test_job_engine_migration.py backend/tests/test_docker_config.py docker-compose.yml
git commit -m "feat: persist workflow jobs schedules and controls"
```

Expected: focused tests, offline migration SQL, Ruff, and Compose validation pass.

---

### Task 3: Implement and prove the PostgreSQL job repository

**Files:**
- Create: `backend/app/jobs/events.py`
- Create: `backend/app/jobs/errors.py`
- Create: `backend/app/jobs/repository.py`
- Create: `backend/tests/postgres/__init__.py`
- Create: `backend/tests/postgres/conftest.py`
- Create: `backend/tests/postgres/test_job_repository.py`
- Create: `backend/tests/test_job_event_redaction.py`

**Interfaces:**
- Consumes: `WorkflowJob`, `WorkflowEvent`, `AutomationControl`, and the locked repository signatures.
- Produces: atomic enqueue/claim/lease/heartbeat/completion/failure/retry/cancel/recovery operations and sanitized append-only events.

- [ ] **Step 1: Add a guarded PostgreSQL test fixture**

In `backend/tests/postgres/conftest.py`, read `TEST_DATABASE_URL`; skip the module when absent; parse the database name and raise before connecting unless it ends in `_test`. Create all `app.db.model_registry.Base.metadata` tables at session start, truncate them between tests with `TRUNCATE ... RESTART IDENTITY CASCADE`, insert `AutomationControl(id="global", global_pause=False, dry_run=False)` after every truncate, and dispose the engine after the session. Never call `drop_all` against a non-test database.

The exact local test command is:

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests/postgres/test_job_repository.py -q
```

- [ ] **Step 2: Write failing idempotency and SKIP LOCKED tests**

Create two tests that call the locked `enqueue_job` signature. The first enqueues the same key twice and asserts `created` is `True` then `False` and both results share one job ID. The second enqueues two jobs, claims one in session A without committing, claims in session B, and asserts the IDs differ; compile the claim statement with the PostgreSQL dialect and assert `FOR UPDATE SKIP LOCKED` appears.

- [ ] **Step 3: Write failing transition, lease, pause, and attention tests**

Add focused cases proving:

- claim order is priority descending, then `scheduled_for`, then `created_at`;
- a future job is not claimed;
- global pause holds a pause-sensitive job but still allows a manual non-sensitive job;
- claim changes `queued -> running`, increments `attempt_count`, and fills lease/heartbeat/start fields;
- heartbeat succeeds only for the current lease owner and updates progress;
- finish requires the lease owner, stores result, clears lease fields, and emits `job.succeeded`;
- `retryable` failure with attempts remaining requeues at the explicit `retry_at` and emits `job.retry_scheduled`;
- exhausted retryable and `permanent` failures become `failed`;
- `needs_review` becomes `needs_review`;
- retry accepts only `failed` or `needs_review`; cancel accepts only `queued`; invalid transitions raise `InvalidJobTransition`;
- expired running leases return to `queued`, clear ownership, and emit `job.lease_expired`;
- listing attention returns only `failed` and `needs_review` in newest-first order.

- [ ] **Step 4: Write failing recursive event-redaction tests**

Create `backend/tests/test_job_event_redaction.py`:

```python
from app.jobs.events import redact_event_data


def test_redact_event_data_masks_nested_secret_like_keys_without_mutating_input():
    source = {
        "Authorization": "Bearer real-token",
        "nested": {"api_key": "real-key", "safe": "visible"},
        "items": [{"cookie": "session=value"}, "plain"],
    }

    assert redact_event_data(source) == {
        "Authorization": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "safe": "visible"},
        "items": [{"cookie": "[REDACTED]"}, "plain"],
    }
    assert source["Authorization"] == "Bearer real-token"
```

- [ ] **Step 5: Implement repository transitions and sanitized event creation**

Use `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(WorkflowJob.id)` for enqueue. Use one transaction for every state transition and its event. `claim_next_job` must read the singleton pause state in the claim query and call `.with_for_update(skip_locked=True)`. Never commit inside the repository; flush and let API/worker boundaries commit.

Use the exact event names `job.enqueued`, `job.claimed`, `job.heartbeat`, `job.succeeded`, `job.retry_scheduled`, `job.failed`, `job.needs_review`, `job.retried`, `job.cancelled`, and `job.lease_expired`. Persist only `redact_event_data(event_data)`.

- [ ] **Step 6: Run PostgreSQL and unit verification, then commit**

Run:

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests/postgres/test_job_repository.py -q
PYTHONPATH=. .venv/bin/python -m pytest tests/test_job_event_redaction.py -q
.venv/bin/ruff check app/jobs tests/postgres tests/test_job_event_redaction.py
cd ..
git add backend/app/jobs backend/tests/postgres backend/tests/test_job_event_redaction.py
git commit -m "feat: add leased PostgreSQL workflow queue"
```

Expected: concurrency, transition, pause, recovery, and redaction tests pass.

---

### Task 4: Add deterministic provider and job-handler extension contracts

**Files:**
- Create: `backend/app/generation/providers/__init__.py`
- Create: `backend/app/generation/providers/base.py`
- Create: `backend/app/generation/providers/fake.py`
- Create: `backend/app/generation/providers/registry.py`
- Create: `backend/app/jobs/registry.py`
- Create: `backend/tests/test_generation_provider_contract.py`
- Create: `backend/tests/test_job_handler_registry.py`

**Interfaces:**
- Consumes: locked provider and handler types.
- Produces: a deterministic fake provider, provider lookup, duplicate-safe handler registration, and stable extension points for Releases 2–4.

- [ ] **Step 1: Write failing provider contract tests**

Create tests that instantiate `DeterministicFakeProvider(output={"text": "rewritten"}, resolved_model="fake-v1")`, call `generate()` twice with the same locked request object, and assert equal `GenerationProviderResult` values with provider `fake`, raw text as canonical sorted JSON, zero token/cost usage, and finish reason `stop`. Assert constructor input is deep-copied so later caller mutation cannot change output.

Add registry tests:

```python
def test_provider_registry_rejects_duplicate_names():
    registry = ProviderRegistry()
    registry.register(DeterministicFakeProvider())

    with pytest.raises(DuplicateProviderError):
        registry.register(DeterministicFakeProvider())


def test_provider_registry_reports_unknown_provider():
    with pytest.raises(UnknownProviderError):
        ProviderRegistry().get("openrouter")


def test_default_provider_registry_contains_only_the_fake_provider():
    registry = build_default_provider_registry()

    assert registry.names() == ("fake",)
```

- [ ] **Step 2: Implement provider values, protocol, fake, and registry**

Implement the locked dataclasses and protocol exactly. `DeterministicFakeProvider` accepts keyword-only `output: Mapping[str, Any] | None = None` and `resolved_model: str = "fake-v1"`; default output is `{"status": "ok"}`. `build_default_provider_registry()` returns a new registry containing exactly that default fake. It never reads environment variables, sleeps, performs I/O, or inspects Telegram settings.

- [ ] **Step 3: Write failing job-handler registry tests**

Assert exact registration and lookup, duplicate rejection, and unknown-type rejection. Assert `build_default_registry()` contains only `ingest.collect` in Release 1.

- [ ] **Step 4: Implement handler registry contracts**

Define the exact `JobContext`, `JobHandler`, and `JobHandlerRegistry` contracts from the locked section. Define `UnknownJobTypeError` and `DuplicateJobHandlerError` in `app/jobs/errors.py`. Defer the body of `build_default_registry()` to import `handle_ingest_collect` locally, avoiding import cycles.

- [ ] **Step 5: Verify and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_generation_provider_contract.py tests/test_job_handler_registry.py -q
.venv/bin/ruff check app/generation/providers app/jobs/registry.py tests/test_generation_provider_contract.py tests/test_job_handler_registry.py
cd ..
git add backend/app/generation/providers backend/app/jobs/registry.py backend/app/jobs/errors.py \
  backend/tests/test_generation_provider_contract.py backend/tests/test_job_handler_registry.py
git commit -m "feat: define deterministic generation provider contracts"
```

---

### Task 5: Add scheduling, pause semantics, and a long-running worker

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/jobs/control.py`
- Create: `backend/app/jobs/scheduler.py`
- Create: `backend/app/jobs/handlers.py`
- Create: `backend/app/jobs/worker.py`
- Modify: `backend/app/jobs/registry.py`
- Replace: `backend/app/worker.py`
- Create: `backend/tests/test_automation_control.py`
- Create: `backend/tests/test_scheduler.py`
- Create: `backend/tests/test_job_worker.py`

**Interfaces:**
- Consumes: `JobRepository`, `IngestionService.run_once(platforms, source_ids, trigger)`, provider/handler registries, source intervals, and global control.
- Produces: `AutomationControlService`, `SchedulerService.tick()`, registered `ingest.collect`, `WorkerRunner.run_once()`, and long-running scheduler/worker entry points.

- [ ] **Step 1: Write failing control tests**

Test `AutomationControlService.get_control()` always returns the `global` singleton and `update_control(global_pause, dry_run, pause_reason, now)` obeys these rules: pausing sets `paused_at`; resuming clears `paused_at` and `pause_reason`; omitted fields retain prior values; every actual change emits `automation.control_updated`; a no-op patch emits no event.

- [ ] **Step 2: Write failing deterministic scheduler tests**

Use a fake clock and fake repository to prove:

- an active source with `fetch_interval_minutes=1440` gets schedule key `source:{source_id}`, kind `daily`, timezone `Asia/Tehran`, local time `06:00`, and a correct next UTC instant across Tehran date boundaries;
- a source with `fetch_interval_minutes=30` gets kind `interval`, interval `30`, and next run based on the latest of last fetch and scheduler observation;
- a disabled source's schedule is disabled;
- a due schedule enqueues `ingest.collect` with payload `{"source_ids": [str(source_id)], "platforms": None}`, origin `scheduler`, and key `schedule:{schedule_id}:{due_time.isoformat()}`;
- enqueue and advancing `next_run_at`, `last_enqueued_at`, and `Source.next_fetch_at` happen in one transaction;
- a second tick at the same instant deduplicates rather than creating another job;
- global pause still calls `requeue_expired_leases()` but enqueues no due schedules;
- malformed timezone/local-time values disable that schedule and emit `schedule.invalid` instead of crashing the loop.

- [ ] **Step 3: Implement settings, control, and scheduler**

Add exact settings with validation:

```python
scheduler_timezone: str = "Asia/Tehran"
daily_collection_time: str = "06:00"
scheduler_poll_seconds: float = Field(default=15.0, gt=0)
worker_poll_seconds: float = Field(default=1.0, gt=0)
worker_lease_seconds: int = Field(default=120, ge=30)
worker_heartbeat_seconds: int = Field(default=30, ge=5)
```

Parse `daily_collection_time` once as `%H:%M`; validate the timezone through `ZoneInfo`. `SchedulerService.tick(now)` first requeues expired leases, then reconciles source schedules, then returns without materialization when paused, otherwise locks due schedules with `SKIP LOCKED`, enqueues, and advances them. The scheduler module's `main()` loops until SIGINT/SIGTERM and logs counts without payload bodies.

- [ ] **Step 4: Write failing worker and ingestion-handler tests**

Prove `handle_ingest_collect()` passes only `platforms`, `source_ids`, and trigger `workflow_job` to `IngestionService.run_once`. Prove it raises `RetryableJobError(code="ingest_partial")` when the returned stats contain failures, and returns stats on success.

For `WorkerRunner.run_once()` assert: no job returns `False`; one job returns `True`; claim is committed before handler execution; heartbeat uses an independent session; success calls `finish_job`; known `RetryableJobError`, `NeedsReviewJobError`, and `PermanentJobError` map to exact error classes; an unknown handler becomes permanent `unknown_job_type`; an unexpected exception becomes retryable `unhandled_exception`; cancellation of the process stops after the active handler boundary.

- [ ] **Step 5: Implement typed handler failures and worker lifecycle**

Add exception classes with exact `code` and sanitized `message` properties. Build a default provider registry containing `DeterministicFakeProvider`; build the default handler registry containing only `ingest.collect`. Replace `app/worker.py` with a compatibility entry point that calls `app.jobs.worker.main`, so old local commands become long-running rather than one-shot.

Use a background heartbeat task while the handler runs. The heartbeat task opens its own `async_session`, commits each successful heartbeat, and stops before finish/fail is recorded. Worker logs may include job ID, job type, state, attempt, and error code; never log payload or result dictionaries.

- [ ] **Step 6: Verify and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_automation_control.py tests/test_scheduler.py tests/test_job_worker.py tests/test_ingestion_service.py -q
.venv/bin/ruff check app/core/config.py app/jobs app/worker.py tests/test_automation_control.py tests/test_scheduler.py tests/test_job_worker.py
cd ..
git add backend/app/core/config.py backend/app/jobs backend/app/worker.py \
  backend/tests/test_automation_control.py backend/tests/test_scheduler.py backend/tests/test_job_worker.py
git commit -m "feat: run scheduled work with pause-safe workers"
```

---

### Task 6: Replace synchronous mutations with job and control APIs

**Files:**
- Create: `backend/app/jobs/schemas.py`
- Create: `backend/app/api/jobs.py`
- Create: `backend/app/api/control.py`
- Create: `backend/app/api/ingest.py`
- Create: `backend/app/api/sources.py`
- Create: `backend/app/api/content.py`
- Create: `backend/app/api/media.py`
- Create: `backend/app/api/diagnostics.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/api/schemas.py`
- Create: `backend/tests/test_api_jobs.py`
- Create: `backend/tests/test_api_control.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: queue/control services and all existing read APIs.
- Produces: resource-split FastAPI routers; `POST /ingest/run` returning `202`; job list/detail/summary/retry/cancel APIs; global control API.

- [ ] **Step 1: Write failing asynchronous-ingest API tests**

Change `IngestRunRequest` to require `request_id: UUID` and retain optional `platforms` and `source_ids`. Test two posts with the same request ID return the same job ID, first with `deduplicated=false` and second with `deduplicated=true`. Assert status `202`, no network ingestion service is constructed, and the job has type `ingest.collect`, origin `manual`, `pause_sensitive=false`, and idempotency key `manual:ingest:{request_id}`.

`JobAcceptedOut` is exactly:

```python
class JobAcceptedOut(BaseModel):
    job_id: UUID
    status: JobStatus
    deduplicated: bool
```

- [ ] **Step 2: Write failing job API tests**

Cover:

- `GET /jobs` filters repeated `status`, `job_type`, `error_class`, and `limit`;
- `GET /jobs/summary` returns `queued`, `running`, `attention`, and `succeeded_today` counts;
- `GET /jobs/{id}` includes its append-only `events` newest-first;
- missing job returns `404`;
- retry returns the updated job and `409` for an invalid state;
- cancel returns the updated job and `409` for running/completed jobs.

Expose all truthful fields from `WorkflowJob`; never expose lease owner in `JobOut`. `JobDetailOut` extends `JobOut` with sanitized `payload`, `result`, and events.

- [ ] **Step 3: Write failing control API tests**

Test `GET /automation-control` and `PATCH /automation-control` with body fields `global_pause`, `dry_run`, and `pause_reason`. Assert a pause response includes real `paused_at`, resume clears it, an empty body is `422`, and a reason longer than 500 characters is `422`.

- [ ] **Step 4: Implement resource routers and aggregate them**

Move existing handlers without behavioral changes into resource routers. `app/api/routes.py` must contain only an `APIRouter` plus `include_router(...)` calls; preserve every current URL. Declare `/jobs/summary` before `/jobs/{job_id}`. API boundaries commit after enqueue/control/transition and roll back through FastAPI's request lifecycle on exceptions.

Use these response shapes:

```python
class JobOut(BaseModel):
    id: UUID
    job_type: str
    status: JobStatus
    origin: JobOrigin
    priority: int
    pause_sensitive: bool
    scheduled_for: datetime
    attempt_count: int
    max_attempts: int
    progress: int
    progress_message: str | None
    error_class: JobErrorClass | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class JobListOut(BaseModel):
    items: list[JobOut]


class JobSummaryOut(BaseModel):
    queued: int
    running: int
    attention: int
    succeeded_today: int
```

- [ ] **Step 5: Verify API compatibility and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_api.py tests/test_api_jobs.py tests/test_api_control.py tests/test_api_content_intelligence.py -q
.venv/bin/ruff check app/api app/jobs/schemas.py tests/test_api.py tests/test_api_jobs.py tests/test_api_control.py
cd ..
git add backend/app/api backend/app/jobs/schemas.py backend/tests/test_api.py \
  backend/tests/test_api_jobs.py backend/tests/test_api_control.py
git commit -m "feat: expose durable job and automation control APIs"
```

Expected: ingestion returns jobs rather than doing network I/O, all prior read routes remain compatible, and API tests pass.

---

### Task 7: Add typed frontend job and control clients

**Files:**
- Create: `frontend/lib/http.ts`
- Modify: `frontend/lib/api-client.ts`
- Modify: `frontend/lib/query-keys.ts`
- Create: `frontend/features/jobs/types.ts`
- Create: `frontend/features/jobs/api.ts`
- Create: `frontend/features/control/types.ts`
- Create: `frontend/features/control/api.ts`
- Create: `frontend/tests/job-api.test.ts`
- Create: `frontend/tests/control-api.test.ts`
- Modify: `frontend/tests/api-client.test.ts`

**Interfaces:**
- Consumes: exact Release 1 API schemas.
- Produces: camel-case `WorkflowJob`, `JobSummary`, `AutomationControl` types and feature-owned request functions.

- [ ] **Step 1: Write failing client mapping tests**

Add fixtures containing every backend field and assert exact camel-case mapping. Assert `getJobs({ statuses: ["failed", "needs_review"], limit: 25 })` sends two `status` parameters; retry/cancel use `POST`; control patch uses `PATCH`; and `enqueueIngest()` sends a caller-provided UUID as `request_id`.

The public frontend types are:

```tsx
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "needs_review" | "cancelled"
export type JobErrorClass = "retryable" | "needs_review" | "permanent"
export type JobOrigin = "manual" | "scheduler" | "automation" | "retry"

export type WorkflowJob = {
  id: string
  jobType: string
  status: JobStatus
  origin: JobOrigin
  priority: number
  pauseSensitive: boolean
  scheduledFor: string
  attemptCount: number
  maxAttempts: number
  progress: number
  progressMessage: string | null
  errorClass: JobErrorClass | null
  errorCode: string | null
  errorMessage: string | null
  startedAt: string | null
  finishedAt: string | null
  createdAt: string
  updatedAt: string
}

export type JobSummary = { queued: number; running: number; attention: number; succeededToday: number }
export type AutomationControl = {
  globalPause: boolean
  dryRun: boolean
  pauseReason: string | null
  pausedAt: string | null
  updatedAt: string
}
```

- [ ] **Step 2: Extract one shared HTTP boundary**

Move `ApiError`, `API_BASE_URL`, and private `request` from `lib/api-client.ts` to `lib/http.ts`; export `apiRequest<T>`. Update the legacy client to import it without changing paths or mappings. Do not create a second fetch wrapper.

- [ ] **Step 3: Implement feature API modules and query keys**

Implement `getJobs`, `getJob`, `getJobSummary`, `retryJob`, `cancelJob`, `enqueueIngest`, `getAutomationControl`, and `updateAutomationControl`. Extend query keys with `jobs(filters)`, `job(id)`, `jobSummary`, and `automationControl`. Keep filters serializable and stable. Replace the legacy `runIngest` helper with a thin call to `enqueueIngest` that supplies `crypto.randomUUID()`; no second fetch implementation is allowed.

- [ ] **Step 4: Verify and commit**

Run:

```bash
cd frontend
npx vitest run tests/job-api.test.ts tests/control-api.test.ts tests/api-client.test.ts
npm run typecheck
cd ..
git add frontend/lib/http.ts frontend/lib/api-client.ts frontend/lib/query-keys.ts \
  frontend/features/jobs frontend/features/control frontend/tests/job-api.test.ts \
  frontend/tests/control-api.test.ts frontend/tests/api-client.test.ts
git commit -m "feat: add typed job and control clients"
```

---

### Task 8: Introduce the responsive Newsroom Command Center shell

**Files:**
- Create: `frontend/components/newsroom/newsroom-shell.tsx`
- Create: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Create: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/components/newsroom/newsroom-header.tsx`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/dashboard/dashboard-shell.tsx`
- Modify: `frontend/components/dashboard/pages/operations-page-frame.tsx`
- Delete: `frontend/components/dashboard/app-sidebar.tsx`
- Modify: `frontend/tests/navigation.test.tsx`
- Create: `frontend/tests/newsroom-shell.test.tsx`
- Modify: `frontend/tests/dashboard-shell.test.tsx`
- Modify: `frontend/tests/operation-pages.test.tsx`

**Interfaces:**
- Consumes: existing working route pages plus the job summary and global control queries.
- Produces: one application shell, truthful live navigation, mobile access, and no nested/duplicate sidebars.

- [ ] **Step 1: Write failing navigation and shell tests**

Assert desktop navigation has active links for `Today` (`/`) and `Job Queue` (`/jobs`), plus secondary links `Sources`, `Content`, `Ingestion Runs`, `Media`, and `Diagnostics`. Assert there are no links named Automations, Drafts, Review & Publish, or Library yet. Assert the current path uses `aria-current="page"`.

At a mobile container width, assert a button named `Open navigation` is keyboard reachable, has `aria-expanded=false`, opens a labeled navigation panel, moves focus to the first link, closes on Escape, and restores focus. Assert no 440px blank third column exists.

- [ ] **Step 2: Implement one shell in the root layout**

Set metadata title to `NewsCraft` and description to `Local content operations command center`. Wrap routed children once with `NewsroomShell` inside the existing providers. Remove sidebar/grid wrappers from `DashboardShell` and `OperationsPageFrame`; they become focused page regions only. Delete `AppSidebar` after all imports are removed.

The shell header shows `Automation paused` only when the live control says so and `Checking controls` while first loading. A request error renders `Control state unavailable`; it must never infer that automations are running. Set content containers to `min-w-0`; apply `dir="auto"` to job/error text, not the whole English interface.

- [ ] **Step 3: Add responsive and accessible styling**

Desktop uses a 248px sidebar and fluid content. Below `768px`, hide the sidebar, show a sticky header and bottom navigation, keep 44px minimum interactive targets, and prevent horizontal page overflow. The mobile menu is stateful React with documented focus behavior; do not add a UI dependency.

- [ ] **Step 4: Verify shell tests and commit**

Run:

```bash
cd frontend
npx vitest run tests/navigation.test.tsx tests/newsroom-shell.test.tsx tests/dashboard-shell.test.tsx tests/operation-pages.test.tsx
npm run typecheck
cd ..
git add frontend/app/layout.tsx frontend/app/globals.css frontend/components/newsroom \
  frontend/components/dashboard/dashboard-shell.tsx frontend/components/dashboard/pages/operations-page-frame.tsx \
  frontend/components/dashboard/app-sidebar.tsx frontend/tests/navigation.test.tsx \
  frontend/tests/newsroom-shell.test.tsx frontend/tests/dashboard-shell.test.tsx frontend/tests/operation-pages.test.tsx
git commit -m "feat: introduce the Newsroom command center shell"
```

---

### Task 9: Build truthful Today, attention, pause, and job-queue views

**Files:**
- Create: `frontend/components/providers/notice-provider.tsx`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/page.tsx`
- Create: `frontend/app/jobs/page.tsx`
- Create: `frontend/features/control/global-controls.tsx`
- Create: `frontend/features/jobs/job-status-badge.tsx`
- Create: `frontend/features/jobs/job-table.tsx`
- Create: `frontend/features/jobs/job-detail-panel.tsx`
- Create: `frontend/features/jobs/attention-queue.tsx`
- Create: `frontend/features/jobs/jobs-page.tsx`
- Create: `frontend/features/today/today-page.tsx`
- Create: `frontend/tests/global-controls.test.tsx`
- Create: `frontend/tests/today-page.test.tsx`
- Create: `frontend/tests/jobs-page.test.tsx`
- Delete: `frontend/components/dashboard/dashboard-shell.tsx`
- Delete: `frontend/components/dashboard/top-status-bar.tsx`
- Delete: `frontend/components/dashboard/content-queue-panel.tsx`
- Delete: `frontend/components/dashboard/ingestion-runs-panel.tsx`
- Delete: `frontend/components/dashboard/media-strip.tsx`
- Delete: `frontend/tests/dashboard-shell.test.tsx`
- Delete: `frontend/tests/dashboard-panels.test.tsx`
- Modify: `frontend/e2e/dashboard.spec.ts`

**Interfaces:**
- Consumes: live job/control clients, query keys, and Newsroom shell.
- Produces: default Today command center, durable attention queue, global pause/dry-run controls, complete job list/detail/retry/cancel UI, and visible mutation outcomes.

- [ ] **Step 1: Write failing global-control tests**

Cover checking, error, active, paused, and mutation-pending states. Clicking `Pause automations` sends `{global_pause: true, pause_reason: "Paused from Newsroom"}`; clicking `Resume automations` sends `{global_pause: false}`. Dry run is a separate switch with its current value in its accessible name. Disable controls during mutation. On success, invalidate control, summary, and job queries; show both an `aria-live` toast and an inline timestamped outcome. On error, leave the server-derived state unchanged and show the API error.

- [ ] **Step 2: Write failing Today view tests**

Assert the page heading is `Today`. Test loading skeletons; API error with retry; all-zero empty copy `No workflow jobs yet`; live count cards; attention jobs from only `failed`/`needs_review`; running jobs with real progress; and recent successes. Assert error messages and progress labels use API text and `dir="auto"`.

- [ ] **Step 3: Write failing Job Queue tests**

Cover filters for All, Queued, Running, Attention, Succeeded, and Cancelled; empty/error/loading states; selecting a row; detail payload/event rendering; retry only for failed/needs-review; cancel only for queued; mutation pending; query invalidation; and sanitized payload display. Assert the UI never exposes `lease_owner` because the API contract omits it.

- [ ] **Step 4: Implement shared notices and global controls**

`NoticeProvider` exposes `pushNotice({ tone: "success" | "error", title: string, message: string })`; notices have generated IDs, render in a fixed `aria-live="polite"` region, and expire after 5 seconds. Fake timers in tests prove expiry. Every control mutation also leaves a durable inline outcome until the next action.

- [ ] **Step 5: Implement Today and Job Queue with live queries**

Use 5-second refetch intervals for summary, running jobs, and attention jobs; do not poll detail for terminal jobs. Count cards read only `JobSummary`. Attention actions call the exact retry/cancel mutations. The detail panel is a labeled right-side `aside role="dialog"`, closes by button or Escape, traps focus while open, and returns focus to the selected row.

Replace the root's ingestion dashboard with `TodayPage`; keep source/content/media/runs/diagnostics routes as secondary operations. `app/jobs/page.tsx` renders `JobsPage`. Delete the now-unreachable dashboard shell, top status bar, dashboard-only panels, and their tests after `rg` confirms no remaining imports; do not leave the ingestion-monitor home hidden as dead code.

- [ ] **Step 6: Add deterministic desktop/mobile browser coverage**

Update `frontend/e2e/dashboard.spec.ts` to intercept `/api/backend/automation-control`, `/api/backend/jobs/summary`, and `/api/backend/jobs*` with fixed JSON. Verify desktop Today counts and pause state. Add a mobile viewport case that opens navigation, visits Job Queue, selects a failed job, and sees Retry. Do not require a live backend for browser tests.

- [ ] **Step 7: Verify and commit**

Run:

```bash
cd frontend
npx vitest run tests/global-controls.test.tsx tests/today-page.test.tsx tests/jobs-page.test.tsx tests/newsroom-shell.test.tsx
npm run test
npm run typecheck
npm run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/wingman/.cache/puppeteer/chrome-headless-shell/linux-150.0.7871.24/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npm run test:e2e
cd ..
git add frontend/components/providers/notice-provider.tsx frontend/app/layout.tsx frontend/app/page.tsx \
  frontend/app/jobs frontend/features/control frontend/features/jobs frontend/features/today \
  frontend/components/dashboard/dashboard-shell.tsx frontend/components/dashboard/top-status-bar.tsx \
  frontend/components/dashboard/content-queue-panel.tsx frontend/components/dashboard/ingestion-runs-panel.tsx \
  frontend/components/dashboard/media-strip.tsx frontend/tests/dashboard-shell.test.tsx frontend/tests/dashboard-panels.test.tsx \
  frontend/tests/global-controls.test.tsx frontend/tests/today-page.test.tsx frontend/tests/jobs-page.test.tsx \
  frontend/e2e/dashboard.spec.ts
git commit -m "feat: add truthful Today and job attention views"
```

---

### Task 10: Wire long-running runtime services and prove Release 1

**Files:**
- Modify: `docker-compose.yml`
- Modify: `backend/tests/test_docker_config.py`
- Modify: `README.md`
- Create: `backend/tests/postgres/test_scheduler_worker_integration.py`

**Interfaces:**
- Consumes: durable scheduler, worker, API, Newsroom UI, and test PostgreSQL.
- Produces: four normal runtime processes, crash-recovery proof, documented operations, and full Release 1 verification evidence.

- [ ] **Step 1: Write failing Compose runtime tests**

Replace the old one-shot assertion with parsed YAML assertions that normal services are exactly `postgres`, `api`, `frontend`, `worker`, and `scheduler` (the profiled `postgres-test` is additional), worker command is `python -m app.jobs.worker`, scheduler command is `python -m app.jobs.scheduler`, both share `DATABASE_URL`, both depend on healthy PostgreSQL, and neither publishes host ports. Assert the worker no longer has `--trigger manual` or `--download-media`.

- [ ] **Step 2: Write a failing crash-recovery integration test**

Against `TEST_DATABASE_URL`, enqueue a pause-sensitive job, claim it with a 1-second lease, advance the supplied clock beyond expiry, call `requeue_expired_leases`, claim with a second worker, finish it, and assert one job row plus event sequence `job.enqueued`, `job.claimed`, `job.lease_expired`, `job.claimed`, `job.succeeded`. Add a second test proving scheduler double ticks produce one `ingest.collect` job for one due source.

- [ ] **Step 3: Wire worker and scheduler services**

Give both services the API's database/proxy/media settings. Worker and scheduler use the same backend image and media volume; scheduler does not receive publishing secrets. Keep API/frontend/PostgreSQL host bindings on `127.0.0.1` from Release 0.

- [ ] **Step 4: Document actual Release 1 operations**

Update README with:

````markdown
## Workflow runtime

`docker compose up --build` starts PostgreSQL, API, frontend, a long-running leased worker, and a scheduler. The scheduler creates source collection jobs; API mutation endpoints enqueue jobs and return immediately.

- Newsroom: http://127.0.0.1:3000
- API: http://127.0.0.1:8000
- Global pause holds scheduled/automation work; manual Run ingest remains available.
- Dry run is persisted for future publishing flows. Release 1 does not publish externally.

Run the PostgreSQL queue contract suite:

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests/postgres -q
```
````

Use a four-backtick outer Markdown fence when editing README so the nested shell fence remains valid.

- [ ] **Step 5: Run complete Release 1 verification**

Run:

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
PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/alembic upgrade head
PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/alembic downgrade 0004_platform_spine
PYTHONPATH=. DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/alembic upgrade head
cd ../frontend
npm run test
npm run typecheck
npm run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/wingman/.cache/puppeteer/chrome-headless-shell/linux-150.0.7871.24/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npm run test:e2e
cd ..
docker compose config >/tmp/newscraft-release1-compose.yml
git diff --check
git status --short --branch
```

Expected: all backend/unit/PostgreSQL tests, Ruff, upgrade-downgrade-upgrade, frontend tests/typecheck/build/browser checks, Compose config, and diff checks pass.

- [ ] **Step 6: Commit runtime wiring and documentation**

Run:

```bash
git add docker-compose.yml backend/tests/test_docker_config.py \
  backend/tests/postgres/test_scheduler_worker_integration.py README.md
git commit -m "chore: run and verify the NewsCraft workflow platform"
git status --short --branch
git log --oneline -10
```

Expected: the Release 1 worktree is clean and the ten task commits are visible.

## Release 1 Acceptance Gate

Release 1 is complete only when all statements below are demonstrated by the commands above:

- `POST /ingest/run` returns a durable job immediately and performs no network fetch inside the request.
- Two concurrent PostgreSQL claimers cannot claim the same job; lease expiry makes abandoned work claimable again.
- Repeating one idempotency key cannot create a duplicate job.
- Global pause prevents schedule materialization and pause-sensitive claims while preserving lease recovery and manual work.
- The scheduler computes `06:00 Asia/Tehran` daily work and configurable per-source intervals without relying on process-local memory.
- Fake generation is deterministic and later providers/handlers have one stable application-owned interface.
- Job failures are classified, events are append-only and redacted, and failed/needs-review work is recoverable from the API.
- Today is the default route; live job counts, pause state, running work, attention, and outcomes are visible without invented data.
- Desktop and mobile navigation reach every working Release 1 screen, with no dead future-feature links.
- Worker and scheduler are separate long-running Compose services and Release 0 ingestion/read behavior remains green.
