# Release 2 Telegram Automation Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one complete Telegram-to-Telegram automation flow that configures a source and destination, captures only new posts and albums by default, rewrites through a versioned OpenRouter prompt, routes the exact immutable revision through review or explicit auto-publish, re-uploads source media, and records idempotent publication receipts and recoverable failures.

**Architecture:** Release 2 consumes the Release 1 PostgreSQL job engine, immutable prompt/revision models, provider registry, publication spine, global controls, and Newsroom shell. Telegram-specific adapters fetch and stage data before a short capture transaction persists source evidence, an automation dispatch, a follow-up job, and the route cursor together; generation and publishing are separate leased jobs. Publication is rendered into deterministic operations before dispatch, and every operation is durably recorded so a retry resumes safely while ambiguous outcomes stop for reconciliation.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2 async, PostgreSQL 18, Alembic, Pydantic 2, httpx, BeautifulSoup/lxml, Telethon 1.x, OpenRouter Chat Completions with JSON Schema, Telegram Bot API, pytest, Ruff, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright, Docker Compose.

## Global Constraints

- Execute Release 0 and Release 1 first. This plan starts from Alembic head `0005_job_engine_and_scheduling` and must not recreate the Release 1 spine.
- Import Release 1 models from their locked public modules: editorial records from `app.stories.models`, prompt/generation records from `app.generation.models`, destination/publication records from `app.publishing.models`, routes from `app.automations.models`, and workflow records from `app.jobs.models`.
- Use Release 1 `JobRepository.enqueue_job`, `claim_next_job`, `heartbeat_job`, `finish_job`, `fail_job`, `retry_job`, `cancel_job`, and `requeue_expired_leases`; do not introduce a second queue.
- Register `telegram.route.initialize`, `telegram.route.poll`, `telegram.route.backfill`, `telegram.route.dry_run`, `telegram.route.process`, `telegram.destination.check`, and `telegram.publish` through `JobHandlerRegistry.register()` and `build_default_registry()`.
- Handlers accept `JobContext(session, providers)` plus one `WorkflowJob` and return a JSON-serializable `dict`; provider implementations use Release 1 `GenerationProviderRequest`, `GenerationProviderResult`, `GenerationProvider.generate()`, and `ProviderRegistry.register/get`.
- `JobContext` remains exactly the Release 1 contract. Telegram source clients, media staging, secret resolution, and Bot API clients are injected into handler closures when the worker builds its registry; never add credentials or transport objects to `JobContext` or job payloads.
- `review_required` is the default route policy. `auto_publish` requires an explicit route choice, a destination that permits auto-publish, a healthy destination, all validation gates, and `AutomationControl.global_pause == false` and `AutomationControl.dry_run == false` at dispatch time.
- New-post-only is the route activation default. Backfill always supplies exactly one bound: `count` in `1..100` or an ISO-8601 `since` timestamp no more than 30 days old. Backfill never moves the live cursor.
- Media policy is exactly `preserve`, `omit`, or `replace_manually`; `preserve` is the default. Albums remain one `AutomationDispatch` and one platform revision even if Telegram requires multiple deterministic Bot API operations.
- `public_html` is credential-free and best-effort. `mtproto_user` may read private or reliable channel history, but stores only three environment-secret references (API ID, API hash, and session); resolved credential material never enters PostgreSQL, events, provider input, or Git.
- OpenRouter is the only live AI backend added in this release. Research mode remains `off`; manual and automatic research arrive in Release 3.
- `AutomationRoute.ai_provider_profile_id` is executable configuration, not display metadata. Provider resolution honors the selected profile's type, secret reference, base URL/settings, default model, and enabled/configured state for every generation attempt.
- No API request performs Telegram or OpenRouter network work inline. Mutations persist configuration or state, enqueue a job transactionally, and return HTTP 202 with the Release 1 `JobAcceptedOut` shape.
- Network, OpenRouter, media-download, and Telegram Bot API calls happen outside database transactions. Short transactions surround durable state transitions and receipts.
- Source text may be Persian and must preserve an explicit `rtl` direction. Application chrome remains LTR and all forms, dialogs, and actions remain keyboard accessible.
- Tokens and session material come from environment variables named by validated secret references. Recursive redaction applies to errors, response metadata, events, headers, query strings, and URLs.
- Default tests use fake providers, fake Telegram source clients, `httpx.MockTransport`, and temporary media directories. Credentialed Telegram/OpenRouter checks are opt-in and never part of `pytest`, Vitest, or Playwright defaults.
- Every task is test-first, ends in one independently reviewable commit, and is followed by requirement and code-quality review before the next task starts.

## Release 1 Contracts Consumed Without Redefinition

| Release 1 contract | Release 2 use |
|---|---|
| `WorkflowJob` plus `JobRepository` | initialization, polling, bounded backfill, dry run, rewrite, destination check, and publish jobs |
| `JobHandlerRegistry` and `build_default_registry()` | Telegram handler registration in the long-running worker |
| `WorkflowSchedule` and scheduler materialization | due route polling without an in-process timer |
| `AutomationControl(id="global")` | global pause and dry-run override at poll, process, and publish boundaries |
| `PromptTemplateVersion` | exact immutable `telegram_rewrite` instructions and output schema version |
| `GenerationProviderRequest/Result` and `ProviderRegistry` | fake/OpenRouter interchangeability |
| `GenerationRun` and `GenerationAttempt` | model resolution, prompt/input hashes, output, usage, validation failure, and retries |
| `PlatformVariant` and `PlatformVariantRevision` | immutable Telegram body, media assignments, validation, editing, and exact-revision approval |
| `Destination` | Telegram target metadata, bot secret reference, enabled/health/auto settings |
| `AutomationRoute` | source/destination/prompt/provider/policy/filter/schedule configuration |
| `PublishJob`, `PublishAttempt`, and `Publication` | exact approved revision, payload hash, attempt trail, and final remote receipt |
| `WorkflowEvent` | append-only operator-visible route, generation, review, retry, pause, and publication history |
| `frontend/features/jobs`, `features/control`, `features/today`, and `components/newsroom` | job status, global controls, Today outcomes, and shared shell |

## File and Responsibility Map

### Backend files created

- `backend/alembic/versions/0006_telegram_automation_vertical.py`: Telegram source config, automation dispatch, and operation-receipt schema.
- `backend/app/automations/telegram/contracts.py`: transport-neutral source envelopes, media references, fetch bounds, and adapter protocol.
- `backend/app/automations/telegram/public_html.py`: best-effort public page fetcher and parser bridge.
- `backend/app/automations/telegram/mtproto.py`: injected Telethon client adapter and album grouping.
- `backend/app/automations/telegram/media.py`: bounded staging and content-addressed media persistence.
- `backend/app/automations/telegram/repository.py`: source config, cursor, dispatch, and capture persistence.
- `backend/app/automations/telegram/handlers.py`: initialize, poll, backfill, dry-run, and process job handlers.
- `backend/app/automations/telegram/route_policy.py`: typed content filters, quiet-hours scheduling, retry policy, and source-edit fingerprints.
- `backend/app/automations/telegram/policy.py`: review/auto/pause/media/destination gate evaluation.
- `backend/app/generation/telegram_schema.py`: validated rewrite request/output plus shared stored Telegram content and evidence-citation contracts.
- `backend/app/generation/provider_settings.py`: provider-specific safe HTTP, pricing, and standard/deep research-budget settings shared by API and resolvers.
- `backend/app/generation/default_prompts.py`: idempotent immutable default `telegram_rewrite` prompt version.
- `backend/app/generation/providers/openrouter.py`: OpenRouter structured-output adapter.
- `backend/app/generation/providers/profiles.py`: selected `AIProviderProfile` validation and per-profile provider/model resolution.
- `backend/app/core/redaction.py`: shared recursive redaction for provider, source, and publishing boundaries.
- `backend/app/publishing/telegram/contracts.py`: deterministic publish plans, operations, results, and classified errors.
- `backend/app/publishing/telegram/renderer.py`: exact text/caption/media operation planning.
- `backend/app/publishing/telegram/client.py`: Bot API transport with multipart upload and error classification.
- `backend/app/publishing/telegram/service.py`: publish-job creation, operation receipts, safe resume, and publication finalization.
- `backend/app/publishing/telegram/handlers.py`: destination health and publish job handlers.
- `backend/app/api/telegram_sources.py`: source configuration API.
- `backend/app/api/telegram_automations.py`: route lifecycle, dry-run, and bounded-backfill API.
- `backend/app/api/telegram_destinations.py`: destination configuration and health-check API.
- `backend/app/api/telegram_drafts.py`: revision detail/edit/approve/publish and reconciliation API.
- `backend/app/api/telegram_schemas.py`: exact request/response validation for the four Telegram resources.

### Backend files modified

- `backend/pyproject.toml`: add Telethon 1.x.
- `backend/app/automations/models.py`: register `TelegramSourceConfig` and `AutomationDispatch` beside `AutomationRoute`.
- `backend/app/publishing/models.py`: register `PublishOperationReceipt` beside the Release 1 publication spine.
- `backend/app/sources/base.py`: carry locally stored media metadata without weakening existing parser contracts.
- `backend/app/ingestion/repository.py`: persist staged Telegram media as already-downloaded assets.
- `backend/app/core/config.py`: OpenRouter, Telegram, staging, and conservative media limits.
- `backend/app/jobs/types.py`: add seven Telegram job-type strings.
- `backend/app/jobs/registry.py`: register Release 2 handlers in `build_default_registry()`.
- `backend/app/jobs/scheduler.py`: materialize due enabled Telegram route polls.
- `backend/app/api/routes.py`: include the four Telegram routers.
- `backend/app/main.py`: seed the default prompt through the existing application bootstrap boundary.
- `.env.example`, `docker-compose.yml`, `README.md`: document secret references and run the real long-running worker/scheduler stack.

### Frontend files created

- `frontend/features/automations/telegram-types.ts`: route/source/destination/draft/publication API types.
- `frontend/features/automations/telegram-api.ts`: Telegram resource requests and mutations.
- `frontend/features/automations/route-builder.tsx`: safe-default route wizard.
- `frontend/features/automations/route-list.tsx`: policy, cursor, pause, health, history, and action summary.
- `frontend/features/automations/route-detail.tsx`: dry run, bounded backfill, failure, and dispatch history.
- `frontend/features/drafts/telegram-draft-list.tsx`: pending Telegram revisions.
- `frontend/features/review/telegram-review-workspace.tsx`: evidence, source media, editor, exact revision approval, and publish action.
- `frontend/features/today/telegram-outcomes.tsx`: waiting review, publishing, published, failed, and reconciliation cards.
- `frontend/features/settings/content-settings-page.tsx`: safe brand, immutable prompt-version, provider, and destination configuration.
- `frontend/app/automations/page.tsx`, `frontend/app/automations/new/page.tsx`, `frontend/app/automations/[routeId]/page.tsx`, `frontend/app/drafts/page.tsx`, and `frontend/app/review/[revisionId]/page.tsx`: Release 2 page entrypoints (Release 1 intentionally does not create the Automations or Drafts pages).
- `frontend/app/settings/content/page.tsx`: content configuration entrypoint.
- `frontend/tests/telegram-api.test.ts`, `frontend/tests/telegram-route-builder.test.tsx`, `frontend/tests/telegram-route-detail.test.tsx`, `frontend/tests/telegram-review-workspace.test.tsx`, `frontend/tests/content-settings-page.test.tsx`, and `frontend/e2e/telegram-automation.spec.ts`: deterministic UI and complete vertical-flow coverage.

### Frontend files modified

- `frontend/app/page.tsx`: add Telegram outcomes to the Release 1 Today entrypoint.
- `frontend/features/today/today-page.tsx`: include Telegram outcomes.
- `frontend/lib/query-keys.ts`: route, source, destination, draft, dispatch, and publication keys.
- `frontend/components/newsroom/newsroom-sidebar.tsx` and `frontend/components/newsroom/mobile-newsroom-nav.tsx`: expose working Automations, Drafts, Review, and content-settings navigation.

---

### Task 1: Add Telegram-specific persistence extensions on the Release 1 spine

**Files:**
- Create: `backend/alembic/versions/0006_telegram_automation_vertical.py`
- Modify: `backend/app/automations/models.py`
- Modify: `backend/app/publishing/models.py`
- Create: `backend/tests/test_telegram_automation_migration.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: Alembic head `0005_job_engine_and_scheduling`; Release 1 `StoryRevision`, `AutomationRoute`, `WorkflowJob`, `GenerationRun`, `PlatformVariantRevision`, `PublishJob`, and `Destination` primary keys.
- Produces: `TelegramSourceConfig`, `AutomationDispatch`, and `PublishOperationReceipt` SQLAlchemy models and tables with the exact constraints below. Route cursor state continues to use Release 1 `AutomationRoute.cursor_state`.

- [ ] **Step 1: Write failing migration and metadata tests**

Create `backend/tests/test_telegram_automation_migration.py`:

```python
from pathlib import Path


def test_telegram_vertical_migration_extends_release_one_head():
    migration = Path("alembic/versions/0006_telegram_automation_vertical.py").read_text(encoding="utf-8")

    assert 'revision: str = "0006_telegram_automation_vertical"' in migration
    assert 'down_revision: str | None = "0005_job_engine_and_scheduling"' in migration
    for table in (
        "telegram_source_configs",
        "automation_dispatches",
        "publish_operation_receipts",
    ):
        assert f'"{table}"' in migration
    assert "uq_automation_dispatch_route_source" in migration
    assert "uq_publish_operation_job_key" in migration
    assert "ck_telegram_source_access_mode" in migration


def test_telegram_vertical_migration_downgrades_only_release_two_tables():
    migration = Path("alembic/versions/0006_telegram_automation_vertical.py").read_text(encoding="utf-8")

    for table in (
        "publish_operation_receipts",
        "automation_dispatches",
        "telegram_source_configs",
    ):
        assert f'op.drop_table("{table}")' in migration
```

Add to `backend/tests/test_models.py`:

```python
def test_telegram_automation_tables_are_registered_with_idempotency_constraints():
    tables = Base.metadata.tables

    assert {
        "telegram_source_configs",
        "automation_dispatches",
        "publish_operation_receipts",
    }.issubset(tables)
    dispatch_names = {constraint.name for constraint in tables["automation_dispatches"].constraints}
    operation_names = {constraint.name for constraint in tables["publish_operation_receipts"].constraints}
    assert "uq_automation_dispatch_route_source" in dispatch_names
    assert "uq_publish_operation_job_key" in operation_names
```

- [ ] **Step 2: Run the tests and verify the missing-schema failure**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_automation_migration.py tests/test_models.py -q
```

Expected: FAIL because migration `0006_telegram_automation_vertical.py` and the three models do not exist.

- [ ] **Step 3: Add the exact extension models and migration**

Add `TelegramSourceConfig` and `AutomationDispatch` to `backend/app/automations/models.py`, and add `PublishOperationReceipt` to `backend/app/publishing/models.py`, following the Release 1 UUID/timestamp column pattern:

```python
class TelegramSourceConfig(Base):
    __tablename__ = "telegram_source_configs"

    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    access_mode: Mapped[str] = mapped_column(Text, nullable=False)
    channel_ref: Mapped[str] = mapped_column(Text, nullable=False)
    peer_id: Mapped[str | None] = mapped_column(Text)
    api_id_secret_ref: Mapped[str | None] = mapped_column(Text)
    api_hash_secret_ref: Mapped[str | None] = mapped_column(Text)
    session_secret_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("access_mode IN ('public_html', 'mtproto_user')", name="ck_telegram_source_access_mode"),
        CheckConstraint(
            "(access_mode = 'public_html' AND api_id_secret_ref IS NULL AND api_hash_secret_ref IS NULL "
            "AND session_secret_ref IS NULL) OR "
            "(access_mode = 'mtproto_user' AND api_id_secret_ref IS NOT NULL AND api_hash_secret_ref IS NOT NULL "
            "AND session_secret_ref IS NOT NULL)",
            name="ck_telegram_source_secret_mode",
        ),
        UniqueConstraint("access_mode", "channel_ref", name="uq_telegram_source_mode_channel"),
    )


class AutomationDispatch(Base):
    __tablename__ = "automation_dispatches"

    id: Mapped[uuid.UUID] = uuid_pk()
    route_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("automation_routes.id", ondelete="CASCADE"))
    source_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_items.id", ondelete="RESTRICT"))
    story_revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_revisions.id", ondelete="RESTRICT"))
    source_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    dispatch_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="captured")
    generation_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_runs.id"))
    variant_revision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("platform_variant_revisions.id"))
    publish_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("publish_jobs.id"))
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("route_id", "source_key", name="uq_automation_dispatch_route_source"),
        CheckConstraint(
            "dispatch_kind IN ('live', 'backfill', 'dry_run', 'source_edit')",
            name="ck_automation_dispatch_kind",
        ),
        Index("ix_automation_dispatch_route_created", "route_id", created_at.desc()),
    )


class PublishOperationReceipt(Base):
    __tablename__ = "publish_operation_receipts"

    id: Mapped[uuid.UUID] = uuid_pk()
    publish_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("publish_jobs.id", ondelete="CASCADE"))
    operation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    operation_key: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    remote_message_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False, server_default=text("'{}'::bigint[]"))
    response_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ambiguous_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = timestamp_now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("publish_job_id", "operation_key", name="uq_publish_operation_job_key"),
        UniqueConstraint("publish_job_id", "operation_index", name="uq_publish_operation_job_index"),
        Index("ix_publish_operation_retry", "status", "next_attempt_at"),
    )
```

Add `CheckConstraint` to the SQLAlchemy imports. Create the matching migration with the same columns, foreign-key delete behavior, constraints, and indexes. `downgrade()` must drop the three tables in reverse dependency order and must not alter any Release 1 table.

- [ ] **Step 4: Run model, migration, and offline Alembic checks**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_automation_migration.py tests/test_models.py -q
PYTHONPATH=. .venv/bin/alembic upgrade head --sql >/tmp/newscraft-release2-upgrade.sql
.venv/bin/ruff check app/automations/models.py app/publishing/models.py alembic/versions/0006_telegram_automation_vertical.py tests/test_telegram_automation_migration.py tests/test_models.py
```

Expected: all tests and Ruff pass; the offline SQL ends at revision `0006_telegram_automation_vertical`.

- [ ] **Step 5: Commit the persistence extension**

```bash
git add backend/alembic/versions/0006_telegram_automation_vertical.py \
  backend/app/automations/models.py backend/app/publishing/models.py \
  backend/tests/test_telegram_automation_migration.py backend/tests/test_models.py
git commit -m "feat: add Telegram automation persistence"
```

---

### Task 2: Define Telegram source envelopes and implement public/MTProto adapters

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/automations/telegram/__init__.py`
- Create: `backend/app/automations/telegram/contracts.py`
- Create: `backend/app/automations/telegram/public_html.py`
- Create: `backend/app/automations/telegram/mtproto.py`
- Create: `backend/app/automations/telegram/registry.py`
- Modify: `backend/app/sources/telegram_public.py`
- Create: `backend/tests/fixtures/telegram_public_album.html`
- Create: `backend/tests/test_telegram_source_adapters.py`
- Modify: `backend/tests/test_telegram_public_parser.py`

**Interfaces:**
- Consumes: current `parse_public_telegram_page()` and Release 1 environment-backed `SecretResolver`.
- Produces: `TelegramSourceAdapter.fetch(request) -> TelegramFetchResult`, `TelegramEnvelope`, `TelegramMediaReference`, `PublicHtmlTelegramAdapter`, `MtprotoTelegramAdapter`, and `TelegramSourceRegistry.get(access_mode)`.

- [ ] **Step 1: Write failing contract, album, bound, and credential-isolation tests**

Create `backend/tests/test_telegram_source_adapters.py` with these cases:

```python
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx

from app.automations.telegram.contracts import TelegramFetchRequest
from app.automations.telegram.mtproto import group_mtproto_messages
from app.automations.telegram.public_html import PublicHtmlTelegramAdapter


async def test_public_html_adapter_returns_ordered_album_and_respects_after_id(tmp_path):
    html = Path("tests/fixtures/telegram_public_album.html").read_text(encoding="utf-8")
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=html)))
    adapter = PublicHtmlTelegramAdapter(client)

    result = await adapter.fetch(
        TelegramFetchRequest(channel_ref="example_channel", after_id=40, before_id=None, limit=20)
    )

    assert [envelope.anchor_message_id for envelope in result.envelopes] == [41, 44]
    assert result.envelopes[1].message_ids == (42, 43, 44)
    assert [media.position for media in result.envelopes[1].media] == [0, 1, 2]
    assert all(media.kind in {"photo", "video", "document"} for media in result.envelopes[1].media)


def test_mtproto_grouping_uses_grouped_id_and_keeps_single_posts_separate():
    messages = [
        SimpleNamespace(id=10, grouped_id=None, date=datetime(2026, 7, 11, tzinfo=UTC), edit_date=None, message="one", media=None),
        SimpleNamespace(id=11, grouped_id=700, date=datetime(2026, 7, 11, tzinfo=UTC), edit_date=None, message="album", media=object()),
        SimpleNamespace(id=12, grouped_id=700, date=datetime(2026, 7, 11, tzinfo=UTC), edit_date=None, message="", media=object()),
    ]

    grouped = group_mtproto_messages(messages, peer_id="-100900")

    assert [envelope.message_ids for envelope in grouped] == [(10,), (11, 12)]
    assert grouped[1].source_key == "-100900:album:700"
    assert grouped[1].text == "album"


async def test_mtproto_adapter_resolves_complete_credential_bundle_without_exposing_it(monkeypatch):
    values = {
        "TELEGRAM_EDITOR_API_ID": "123456",
        "TELEGRAM_EDITOR_API_HASH": "api-hash",
        "TELEGRAM_EDITOR_SESSION": "session-material",
    }
    resolved = []
    secret_resolver = SimpleNamespace(resolve=lambda name: resolved.append(name) or values[name])
    client_factory = FakeTelegramClientFactory()
    adapter = MtprotoTelegramAdapter(secret_resolver=secret_resolver, client_factory=client_factory)

    result = await adapter.fetch(
        TelegramFetchRequest(
            channel_ref="private-channel",
            after_id=50,
            before_id=None,
            limit=10,
            api_id_secret_ref="TELEGRAM_EDITOR_API_ID",
            api_hash_secret_ref="TELEGRAM_EDITOR_API_HASH",
            session_secret_ref="TELEGRAM_EDITOR_SESSION",
        )
    )

    assert resolved == ["TELEGRAM_EDITOR_API_ID", "TELEGRAM_EDITOR_API_HASH", "TELEGRAM_EDITOR_SESSION"]
    assert client_factory.credentials == (123456, "api-hash", "session-material")
    assert all(value not in repr(result) for value in values.values())
    assert client_factory.last_min_id == 50
```

The file must include a tiny `FakeTelegramClientFactory`/client that records `min_id`, returns two `SimpleNamespace` messages, and never performs network I/O.

Extend `backend/tests/test_telegram_public_parser.py` with an album fixture assertion that parser metadata contains integer `message_ids`, an optional `grouped_id`, ordered media, and extracted link/text entities; keep the existing single-post test passing.

- [ ] **Step 2: Run the source-adapter tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_source_adapters.py tests/test_telegram_public_parser.py -q
```

Expected: FAIL because the Telegram adapter package, album fixture, and expanded parser metadata do not exist.

- [ ] **Step 3: Add the transport-neutral contracts**

Create `backend/app/automations/telegram/contracts.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol


TelegramAccessMode = Literal["public_html", "mtproto_user"]
TelegramMediaKind = Literal["photo", "video", "document"]


@dataclass(frozen=True, slots=True)
class TelegramMediaReference:
    key: str
    position: int
    kind: TelegramMediaKind
    source_url: str | None
    remote_ref: str | None
    file_name: str | None
    mime_type: str | None


@dataclass(frozen=True, slots=True)
class TelegramEnvelope:
    source_key: str
    peer_id: str
    channel_ref: str
    anchor_message_id: int
    message_ids: tuple[int, ...]
    grouped_id: str | None
    text: str
    html: str | None
    entities: tuple[dict, ...]
    published_at: datetime
    edited_at: datetime | None
    source_url: str | None
    media: tuple[TelegramMediaReference, ...] = ()


@dataclass(frozen=True, slots=True)
class TelegramFetchRequest:
    channel_ref: str
    after_id: int | None
    before_id: int | None
    limit: int
    since: datetime | None = None
    activation_boundary_at: datetime | None = None
    snapshot_token: str | None = None
    page_token: str | None = None
    api_id_secret_ref: str | None = None
    api_hash_secret_ref: str | None = None
    session_secret_ref: str | None = None


@dataclass(frozen=True, slots=True)
class TelegramFetchResult:
    peer_id: str
    envelopes: tuple[TelegramEnvelope, ...]
    fetched_at: datetime
    snapshot_token: str
    next_page_token: str | None
    complete: bool


@dataclass(frozen=True, slots=True)
class MaterializedTelegramMedia:
    reference: TelegramMediaReference
    path: Path
    byte_length: int
    checksum_sha256: str
    mime_type: str


class TelegramSourceAdapter(Protocol):
    async def fetch(self, request: TelegramFetchRequest) -> TelegramFetchResult: ...

    async def materialize_media(
        self, envelope: TelegramEnvelope, staging_dir: Path
    ) -> tuple[MaterializedTelegramMedia, ...]: ...
```

`snapshot_token` pins the first observed remote head for all later pages (the head ID is sufficient when the transport has no native snapshot token); `page_token` is opaque adapter state. With `activation_boundary_at`, adapters page newest-to-oldest and return `complete=True` only after seeing an envelope at/below the boundary or proving the channel has no older envelope. For forward reads, `complete=True` means every envelope through the pinned head has been returned. An empty result is not a catch-up proof unless `complete=True`.

Also define `telegram_envelope_fingerprint(envelope) -> str` as SHA-256 of canonical JSON containing `peer_id`, ordered `message_ids`, text, HTML, normalized entities, and ordered media keys/kinds. Exclude views, reactions, fetch time, and `edited_at` so a metadata-only poll does not create a false edit revision; a real text/entity/media change does. Task 5 imports this function rather than creating a second fingerprint implementation.

- [ ] **Step 4: Implement both adapters and registry with injected transports**

Add `telethon>=1.40,<2` to backend dependencies. `PublicHtmlTelegramAdapter` must accept an injected `httpx.AsyncClient`, fetch only `https://t.me/s/{validated_username}` (using Telegram's supported `before` pagination parameter), convert current parser items to envelopes, filter `after_id`, `before_id`, `since`, and `activation_boundary_at`, sort ascending, and truncate only after complete album grouping. On the first page, pin `snapshot_token` to the highest complete anchor ID; later pages exclude anything above it. Emit an opaque next-page token and set `complete` only under the contract above. Its materializer downloads each `source_url` to the provided staging directory with bounded streaming and returns checksum/size/MIME metadata.

Extend `parse_public_telegram_page()` so every parsed item has these exact `parser_meta` keys:

```python
{
    "channel": channel,
    "message_id": int(message_id),
    "message_ids": [int(message_id)],
    "grouped_id": grouped_id,
    "views": views,
    "reactions": reactions,
    "entities": entities,
    "direction": infer_direction(content_text),
}
```

When one public HTML message block contains a grouped wrapper, extract every photo/video/document in DOM order into the same parsed item. The new fixture must contain post `41`, then one grouped post whose members are `42`, `43`, and `44`, with photo/video/document order visible in the HTML attributes used by the parser.

`MtprotoTelegramAdapter` must accept the Release 1 `SecretResolver` and an injected `client_factory`. Immediately before client creation, resolve all three references; parse `api_id` as a positive integer and call `client_factory(api_id=api_id, api_hash=api_hash, session=session)`. Missing, empty, or non-numeric values are permanent configuration errors containing reference names only. Call the client with `min_id=after_id or 0`, `max_id=before_id or 0`, the timestamp boundary, pinned head ID, and requested limit; encode offsets in the opaque page token, group by `grouped_id`, normalize to ascending envelopes, and set `complete` truthfully. Expose no API hash/session string in results or exceptions. `materialize_media()` calls the injected client's download boundary into `staging_dir`; no Telethon object crosses the adapter boundary.

Create `TelegramSourceRegistry` with:

```python
class TelegramSourceRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, TelegramSourceAdapter] = {}

    def register(self, access_mode: str, adapter: TelegramSourceAdapter) -> None:
        self._adapters[access_mode] = adapter

    def get(self, access_mode: str) -> TelegramSourceAdapter:
        try:
            return self._adapters[access_mode]
        except KeyError as exc:
            raise LookupError(f"unsupported Telegram access mode: {access_mode}") from exc
```

- [ ] **Step 5: Run focused and existing ingestion tests**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_source_adapters.py tests/test_telegram_public_parser.py \
  tests/test_ingestion_service.py tests/test_repository.py -q
.venv/bin/ruff check app/automations/telegram app/sources/telegram_public.py tests/test_telegram_source_adapters.py
```

Expected: all focused tests pass; existing public Telegram ingestion remains green.

- [ ] **Step 6: Commit source adapters**

```bash
git add backend/pyproject.toml backend/app/automations/telegram \
  backend/app/sources/telegram_public.py backend/tests/fixtures/telegram_public_album.html \
  backend/tests/test_telegram_source_adapters.py backend/tests/test_telegram_public_parser.py
git commit -m "feat: add Telegram source adapters"
```

---

### Task 3: Capture Telegram evidence, albums, media, dispatch, job, and cursor atomically

**Files:**
- Modify: `backend/app/sources/base.py`
- Modify: `backend/app/ingestion/repository.py`
- Create: `backend/app/automations/telegram/media.py`
- Create: `backend/app/automations/telegram/repository.py`
- Create: `backend/tests/test_telegram_media_store.py`
- Create: `backend/tests/test_telegram_capture_repository.py`
- Modify: `backend/tests/test_repository.py`

**Interfaces:**
- Consumes: Task 2 `TelegramEnvelope`/`MaterializedTelegramMedia`; existing `IngestionRepository`; Release 1 `JobRepository.enqueue_job()`.
- Produces: `TelegramMediaStore.persist()`, `TelegramCaptureRepository.capture_and_enqueue() -> AutomationDispatch`, and transactional cursor semantics.

- [ ] **Step 1: Write failing content-addressed media tests**

Create `backend/tests/test_telegram_media_store.py`:

```python
from pathlib import Path

import pytest

from app.automations.telegram.media import MediaLimitExceeded, TelegramMediaStore


def test_media_store_persists_by_checksum_without_duplicate_files(tmp_path):
    store = TelegramMediaStore(tmp_path, max_photo_bytes=10, max_file_bytes=20)

    first = store.persist(b"photo", mime_type="image/jpeg", file_name="source.jpg", kind="photo")
    second = store.persist(b"photo", mime_type="image/jpeg", file_name="again.jpg", kind="photo")

    assert first.path == second.path
    assert first.path.read_bytes() == b"photo"
    assert first.path.name == f"{first.checksum_sha256}.jpg"


def test_media_store_rejects_oversized_file_before_persistence(tmp_path):
    store = TelegramMediaStore(tmp_path, max_photo_bytes=4, max_file_bytes=8)

    with pytest.raises(MediaLimitExceeded, match="photo exceeds 4 bytes"):
        store.persist(b"12345", mime_type="image/jpeg", file_name="big.jpg", kind="photo")

    assert list(Path(tmp_path).rglob("*.*")) == []
```

- [ ] **Step 2: Write a failing transaction-order and duplicate-capture test**

Create `backend/tests/test_telegram_capture_repository.py` with a fake async session/repositories and this invariant test:

```python
async def test_capture_records_evidence_and_process_job_before_cursor_advance():
    events: list[str] = []
    capture = build_capture_repository(events)

    dispatch = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=telegram_source(),
        cursor=route_cursor(last_message_id=100),
        envelope=telegram_album(message_ids=(101, 102, 103)),
        materialized_media=stored_album(),
        dispatch_kind="live",
        dry_run_job_id=None,
    )

    assert dispatch.source_message_ids == [101, 102, 103]
    assert events.index("source_item_flushed") < events.index("dispatch_flushed")
    assert events.index("dispatch_flushed") < events.index("process_job_enqueued")
    assert events.index("process_job_enqueued") < events.index("cursor_advanced:103")


async def test_duplicate_route_source_returns_existing_dispatch_without_second_job_or_cursor_regression():
    events: list[str] = []
    capture = build_capture_repository(events, existing_dispatch=True)

    first = await capture.capture_and_enqueue(
        route_id=ROUTE_ID,
        source=telegram_source(),
        cursor=route_cursor(last_message_id=103),
        envelope=telegram_album(message_ids=(101, 102, 103)),
        materialized_media=stored_album(),
        dispatch_kind="backfill",
        dry_run_job_id=None,
    )

    assert first.id == EXISTING_DISPATCH_ID
    assert "process_job_enqueued" not in events
    assert "cursor_advanced:103" not in events
```

The helper fakes must assert the process job type is `telegram.route.process` and its idempotency key is `telegram-process:{route_id}:{envelope.source_key}`. The first-capture fixture must also assert `Story.status == "telegram_provisional"`, revision 1 has `created_by == "telegram_capture"`, and its `StoryEvidenceLink` points to the captured snapshot. A source-edit fixture must assert it reuses that Story, creates the next child `StoryRevision` with `created_by == "telegram_source_edit"`, and links that revision to the new edit snapshot.

- [ ] **Step 3: Run the tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_media_store.py tests/test_telegram_capture_repository.py -q
```

Expected: FAIL because the media store and capture repository do not exist.

- [ ] **Step 4: Extend media candidates with already-stored metadata**

Add optional fields to `MediaCandidate` in `backend/app/sources/base.py`:

```python
storage_path: str | None = None
checksum_sha256: str | None = None
byte_length: int | None = None
fetch_status: str = "remote_only"
```

Update `_media_asset_values()` and `_apply_media_candidate()` in `backend/app/ingestion/repository.py` to copy those four fields. Treat `telegram_public` source items as `telegram_post` identities in `build_item_identities()` regardless of whether `TelegramSourceConfig.access_mode` is `public_html` or `mtproto_user`; transport mode must not create a second source-platform identity. Existing RSS/public candidates keep defaults; Task 3 Telegram captures pass `fetch_status="downloaded"` and a local content-addressed path. Read each bounded staging file once, persist it through `TelegramMediaStore`, and unlink the staging file after the database transaction commits.

- [ ] **Step 5: Implement bounded content-addressed storage**

Create `backend/app/automations/telegram/media.py` with `MediaLimitExceeded`, an immutable `StoredTelegramMedia`, and:

```python
class TelegramMediaStore:
    def __init__(self, root: Path, *, max_photo_bytes: int, max_file_bytes: int):
        self.root = root
        self.max_photo_bytes = max_photo_bytes
        self.max_file_bytes = max_file_bytes

    def persist(self, content: bytes, *, mime_type: str, file_name: str | None, kind: str) -> StoredTelegramMedia:
        limit = self.max_photo_bytes if kind == "photo" else self.max_file_bytes
        if len(content) > limit:
            raise MediaLimitExceeded(f"{kind} exceeds {limit} bytes")
        checksum = sha256(content).hexdigest()
        extension = safe_extension(mime_type, file_name)
        path = self.root / checksum[:2] / f"{checksum}{extension}"
        if not path.exists():
            atomic_write(path, content)
        return StoredTelegramMedia(
            path=path,
            byte_length=len(content),
            checksum_sha256=checksum,
            mime_type=mime_type,
            kind=kind,
        )
```

`safe_extension()` permits only `.jpg`, `.png`, `.gif`, `.webp`, `.mp4`, `.mov`, `.pdf`, `.doc`, `.docx`, `.zip`, and `.bin`; it never copies directory components from a remote filename.

- [ ] **Step 6: Implement the short capture transaction**

`TelegramCaptureRepository.capture_and_enqueue()` must:

1. Build one `ParsedSourceItem` per envelope, not one per album member. The first capture uses external identity `telegram:{peer_id}:{anchor_message_id}`; a detected edit uses `telegram:{peer_id}:{anchor_message_id}:edit:{source_fingerprint}` so the original `SourceItem` is never overwritten. Store full text, edit timestamp and entities in `parser_meta`, plus one ordered stored `MediaCandidate` per materialized file.
2. Call existing raw/source/content/identity/media ingestion methods and flush `SourceItem`. On first capture create one Release 1 `Story(status="telegram_provisional")`; on `source_edit`, reuse the original dispatch's Story. Create immutable `StoryEvidenceSnapshot(evidence_key=f"content-item:{content_item.id}:{content_sha256}", source_url=envelope.source_url, ...)`. Create `StoryRevision` number 1 with `parent_revision_id=None` and `created_by="telegram_capture"`; an edit creates the next number with `parent_revision_id` set to the prior StoryRevision and `created_by="telegram_source_edit"`. Create a `StoryEvidenceLink` from each revision to its exact snapshot with `claim_key="telegram.source"` and `relationship="supports"`, so generation never has to infer evidence from timestamps or source IDs.
3. Insert `AutomationDispatch(route_id, source_item_id, story_revision_id=story_revision.id, source_key, source_fingerprint, source_message_ids, dispatch_kind, status="captured")`. For a dry run, prefix the key with `dry:{dry_run_job_id}:` so a test does not consume the real live identity. For an edit, use `{base_source_key}:edit:{source_fingerprint}` and `dispatch_kind="source_edit"`.
4. Call Release 1 `JobRepository.enqueue_job()` with job type `telegram.route.process`, origin `automation`, payload `{"dispatch_id": str(dispatch.id)}`, and deterministic key `telegram-process:{route_id}:{dispatch.source_key}`.
5. For `live`, advance only `cursor_state.last_message_id` after job enqueue flush and never backwards. For `live` and `source_edit`, update bounded `cursor_state.recent_fingerprints[str(anchor_message_id)] = source_fingerprint`, retaining only the highest 50 message IDs. Preserve `activation_requested_at`, `activation_boundary_at`, `activation_message_id`, and `initialized_at`. Backfill/dry-run never move or seed the live cursor.
6. Append `WorkflowEvent(event_type="telegram.source.captured")` with route, dispatch, source item, message IDs, media count, and no media bytes/secret values.
7. Return the existing dispatch without a new job when the `(route_id, source_key)` unique identity already exists. A replay of the same edit fingerprint is therefore harmless, while a later different edit creates a new review revision.

The caller owns `async with session.begin()` so all seven database effects commit or roll back together. Adapter fetch and media materialization finish before this method is called.

- [ ] **Step 7: Run focused and ingestion regression tests**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_media_store.py tests/test_telegram_capture_repository.py \
  tests/test_repository.py tests/test_media_downloader.py tests/test_media_quality.py -q
.venv/bin/ruff check app/automations/telegram/media.py app/automations/telegram/repository.py \
  app/sources/base.py app/ingestion/repository.py tests/test_telegram_capture_repository.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 8: Commit durable capture**

```bash
git add backend/app/sources/base.py backend/app/ingestion/repository.py \
  backend/app/automations/telegram/media.py backend/app/automations/telegram/repository.py \
  backend/tests/test_telegram_media_store.py backend/tests/test_telegram_capture_repository.py \
  backend/tests/test_repository.py
git commit -m "feat: capture Telegram albums with durable cursors"
```

---

### Task 4: Add safe Telegram source, destination, and route lifecycle APIs

**Files:**
- Create: `backend/app/generation/provider_settings.py`
- Create: `backend/app/api/telegram_schemas.py`
- Create: `backend/app/api/telegram_sources.py`
- Create: `backend/app/api/telegram_destinations.py`
- Create: `backend/app/api/telegram_automations.py`
- Create: `backend/app/api/generation_settings.py`
- Create: `backend/app/api/generation_schemas.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/jobs/types.py`
- Create: `backend/tests/test_telegram_configuration_api.py`
- Create: `backend/tests/test_telegram_route_api.py`
- Create: `backend/tests/test_generation_settings_api.py`

**Interfaces:**
- Consumes: Release 1 `Destination`, `AutomationRoute`, `AutomationControl`, `JobRepository`, `JobOrigin`, `JobAcceptedOut`, `PromptTemplateVersion`, `BrandProfile`, and `AIProviderProfile`; Task 1 `TelegramSourceConfig`.
- Produces: typed Telegram configuration plus safe brand/prompt/provider settings endpoints; exact job types `telegram.route.initialize`, `telegram.route.poll`, `telegram.route.backfill`, `telegram.route.dry_run`, `telegram.route.process`, `telegram.destination.check`, and `telegram.publish`.

- [ ] **Step 1: Write failing schema tests for safe defaults and bounded backfill**

Create the validation portion of `backend/tests/test_telegram_route_api.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.telegram_schemas import TelegramRouteCreate, TelegramRouteBackfillIn


def valid_route_payload() -> dict:
    return {
        "name": "Rewrite source to newsroom",
        "source_id": uuid4(),
        "destination_id": uuid4(),
        "brand_profile_id": uuid4(),
        "prompt_template_version_id": uuid4(),
        "ai_provider_profile_id": uuid4(),
        "access_mode": "public_html",
        "content_filters": {"model": "openai/gpt-5-mini"},
    }


def test_route_defaults_to_new_only_review_preserve_and_research_off():
    value = TelegramRouteCreate.model_validate(valid_route_payload())

    assert value.research_mode == "off"
    assert value.media_policy == "preserve"
    assert value.publishing_policy == "review_required"
    assert value.poll_interval_seconds == 300
    assert value.confirm_auto_publish is False


def test_auto_publish_requires_explicit_confirmation():
    payload = {**valid_route_payload(), "publishing_policy": "auto_publish"}

    with pytest.raises(ValidationError, match="confirm_auto_publish"):
        TelegramRouteCreate.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"count": 5, "since": "2026-07-10T00:00:00Z"},
        {"count": 0},
        {"count": 101},
        {"since": (datetime.now(UTC) - timedelta(days=31)).isoformat()},
    ],
)
def test_backfill_requires_one_safe_bound(payload):
    with pytest.raises(ValidationError):
        TelegramRouteBackfillIn.model_validate(payload)
```

- [ ] **Step 2: Write failing API tests proving mutations enqueue instead of calling networks**

Add ASGI tests to `backend/tests/test_telegram_configuration_api.py` and `backend/tests/test_telegram_route_api.py` for these exact responses:

```python
async def test_destination_create_stores_secret_reference_and_enqueues_health_check():
    response = await client.post(
        "/telegram/destinations",
        json={
            "name": "News channel",
            "target_ref": "@news_target",
            "secret_ref": "TELEGRAM_DESTINATION_NEWS_TOKEN",
            "allow_auto_publish": False,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["destination"]["configured"] is True
    assert body["destination"]["settings"]["allow_auto_publish"] is False
    assert body["job"] == {"job_id": str(HEALTH_JOB_ID), "status": "queued", "deduplicated": False}
    assert fake_jobs.enqueued[0].job_type == "telegram.destination.check"
    assert fake_transport.calls == []


async def test_route_activation_enqueues_initialization_without_backfill():
    response = await client.post(f"/telegram/automations/{ROUTE_ID}/activate")

    assert response.status_code == 202
    assert response.json()["job"]["job_id"] == str(INITIALIZE_JOB_ID)
    assert fake_jobs.enqueued[0].job_type == "telegram.route.initialize"
    assert saved_route.enabled is True
    assert saved_route.cursor_state["status"] == "initializing"
    assert saved_route.cursor_state["activation_requested_at"]
    assert saved_route.cursor_state["activation_message_id"] is None
    assert saved_route.cursor_state["last_message_id"] is None
    assert saved_route.backfill_limit is None
    assert saved_route.backfill_since is None
    assert fake_source_adapter.calls == []


async def test_backfill_enqueues_bound_job_without_mutating_live_cursor():
    original_cursor = dict(saved_route.cursor_state)
    response = await client.post(f"/telegram/automations/{ROUTE_ID}/backfill", json={"count": 20})

    assert response.status_code == 202
    assert fake_jobs.enqueued[0].job_type == "telegram.route.backfill"
    assert saved_route.cursor_state == original_cursor


async def test_dry_run_is_always_review_only_even_for_auto_route():
    saved_route.publishing_policy = "auto_publish"
    response = await client.post(
        f"/telegram/automations/{ROUTE_ID}/dry-run", json={"source_message_id": 912}
    )

    assert response.status_code == 202
    assert fake_jobs.enqueued[0].job_type == "telegram.route.dry_run"
    assert fake_jobs.enqueued[0].payload["force_review"] is True
```

Also cover: public source rejects every MTProto reference; MTProto requires three valid uppercase references for API ID, API hash, and session; destination secret values containing `:` are rejected; route source/access mode must match; route prompt purpose must be `telegram_rewrite`; route research mode other than `off` returns 422; an auto route is rejected when destination `settings.allow_auto_publish` is false; pause/resume changes only `paused_at`; and duplicate create returns the existing resource rather than a second row. Add an options test proving `GET /telegram/automations/options` returns selectable sources, destinations, brand profiles, active `telegram_rewrite` prompt versions, and enabled/configured AI provider profiles while omitting every `secret_ref` and credential value.

In `backend/tests/test_generation_settings_api.py`, prove: brand create/update validates language/tone/editorial/attribution fields; creating a prompt version never mutates an earlier version; a Telegram prompt requires the server-defined input variables and output schema; activation leaves exactly one active version per template; provider profiles accept only `fake`/`openrouter` in Release 2, store an uppercase secret reference rather than a key, and never return that reference or a resolved secret. Add an OpenRouter create/PATCH/GET round-trip containing both pricing fields and distinct `research_budgets.standard`/`deep` values; PATCH only one pricing field and assert the response preserves the other price plus both budget objects and no secret reference. Assert fake accepts omitted settings and rejects OpenRouter HTTP/pricing/budget settings.

- [ ] **Step 3: Run API tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_configuration_api.py tests/test_telegram_route_api.py tests/test_generation_settings_api.py -q
```

Expected: FAIL because the Telegram/settings schemas, routers, and job-type constants do not exist.

- [ ] **Step 4: Add exact request schemas and validators**

Create `backend/app/api/telegram_schemas.py` with these request contracts:

```python
SecretRef = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,127}$")]


class TelegramSourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel_ref: str = Field(min_length=1, max_length=255)
    access_mode: Literal["public_html", "mtproto_user"] = "public_html"
    api_id_secret_ref: SecretRef | None = None
    api_hash_secret_ref: SecretRef | None = None
    session_secret_ref: SecretRef | None = None
    language_hint: str = Field(default="fa", min_length=2, max_length=12)

    @model_validator(mode="after")
    def validate_secret_mode(self):
        refs = (self.api_id_secret_ref, self.api_hash_secret_ref, self.session_secret_ref)
        if self.access_mode == "public_html" and any(refs):
            raise ValueError("public_html cannot store MTProto credential references")
        if self.access_mode == "mtproto_user" and not all(refs):
            raise ValueError("mtproto_user requires api_id_secret_ref, api_hash_secret_ref, and session_secret_ref")
        return self


class TelegramDestinationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_ref: str = Field(min_length=1, max_length=255)
    secret_ref: SecretRef
    allow_auto_publish: bool = False


class TelegramContentFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, min_length=1, max_length=200)
    include_terms: list[str] = Field(default_factory=list, max_length=20)
    exclude_terms: list[str] = Field(default_factory=list, max_length=20)
    min_text_characters: int = Field(default=1, ge=0, le=100_000)
    require_media: bool = False


class TelegramQuietHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "Asia/Tehran"
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validate_non_empty_window(self):
        if self.start == self.end:
            raise ValueError("quiet-hours start and end cannot be identical")
        return self


class TelegramRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=3, ge=1, le=10)
    base_delay_seconds: int = Field(default=30, ge=1, le=3600)
    max_delay_seconds: int = Field(default=1800, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_delay_order(self):
        if self.max_delay_seconds < self.base_delay_seconds:
            raise ValueError("max_delay_seconds must be greater than or equal to base_delay_seconds")
        return self


class TelegramRouteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_id: UUID
    destination_id: UUID
    brand_profile_id: UUID
    prompt_template_version_id: UUID
    ai_provider_profile_id: UUID
    access_mode: Literal["public_html", "mtproto_user"]
    research_mode: Literal["off"] = "off"
    content_filters: TelegramContentFilters = Field(default_factory=TelegramContentFilters)
    media_policy: Literal["preserve", "omit", "replace_manually"] = "preserve"
    attribution_policy: Literal["preserve", "remove", "custom"] = "preserve"
    custom_footer: str | None = Field(default=None, max_length=512)
    publishing_policy: Literal["review_required", "auto_publish"] = "review_required"
    poll_interval_seconds: int = Field(default=300, ge=60, le=86400)
    quiet_hours: TelegramQuietHours | None = None
    retry_policy: TelegramRetryPolicy = Field(default_factory=TelegramRetryPolicy)
    confirm_auto_publish: bool = False

    @model_validator(mode="after")
    def validate_auto_and_attribution(self):
        if self.publishing_policy == "auto_publish" and not self.confirm_auto_publish:
            raise ValueError("auto_publish requires confirm_auto_publish=true")
        if self.attribution_policy == "custom" and not (self.custom_footer or "").strip():
            raise ValueError("custom attribution requires custom_footer")
        return self


class TelegramRouteBackfillIn(BaseModel):
    count: int | None = Field(default=None, ge=1, le=100)
    since: datetime | None = None

    @model_validator(mode="after")
    def validate_bound(self):
        if (self.count is None) == (self.since is None):
            raise ValueError("provide exactly one of count or since")
        if self.since is not None and self.since < datetime.now(UTC) - timedelta(days=30):
            raise ValueError("since cannot be older than 30 days")
        return self


class TelegramRouteDryRunIn(BaseModel):
    source_message_id: int | None = Field(default=None, ge=1)
```

Define provider-specific safe settings in application-owned `backend/app/generation/provider_settings.py`, then import/re-export them from `backend/app/api/generation_schemas.py` for request validation. The provider resolver and later research code import the application module, never the API layer. These names and JSON paths are cross-release contracts:

```python
class ProviderPricingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_usd_per_million: Decimal = Field(ge=Decimal("0"))
    output_usd_per_million: Decimal = Field(ge=Decimal("0"))


class ResearchBudgetSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_model_calls: int = Field(default=6, ge=1, le=12)
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_cost_usd: Decimal = Field(default=Decimal("2.00"), ge=Decimal("0"), le=Decimal("50"))
    max_queries: int = Field(default=4, ge=1, le=8)
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    max_pages: int = Field(default=8, ge=1, le=16)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)
    max_total_chars: int = Field(default=120_000, ge=10_000, le=500_000)


class ResearchBudgetsSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    standard: ResearchBudgetSettings
    deep: ResearchBudgetSettings


class OpenRouterProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: HttpUrl = "https://openrouter.ai/api/v1"
    timeout_seconds: int = Field(default=60, ge=1, le=300)
    http_referer: HttpUrl | None = None
    app_title: str = Field(default="NewsCraft", min_length=1, max_length=80)
    pricing: ProviderPricingSettings | None = None
    research_budgets: ResearchBudgetsSettings | None = None


class AIProviderProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_type: Literal["fake", "openrouter"]
    default_model: str | None = Field(default=None, min_length=1, max_length=200)
    secret_ref: SecretRef | None = None
    settings: OpenRouterProviderSettings | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_provider_contract(self):
        if self.provider_type == "fake":
            if self.secret_ref is not None or self.settings is not None:
                raise ValueError("fake provider cannot have secret or provider settings")
        elif self.secret_ref is None or self.default_model is None:
            raise ValueError("openrouter requires secret_ref and default_model")
        return self
```

At this release boundary, fake profiles require `settings=None` and use deterministic server defaults; Release 3 may add a separate `CodexProviderSettings` branch without weakening either existing branch. OpenRouter's canonical JSON paths are exactly `settings.pricing.input_usd_per_million`, `settings.pricing.output_usd_per_million`, `settings.research_budgets.standard`, and `settings.research_budgets.deep`. Provider responses return `configured: bool`, the entire safe normalized provider-specific settings object, and default model, but never `secret_ref`. Create/PATCH must round-trip pricing and both budget objects without dropping unknown-to-generation-but-schema-valid fields. PATCH recursively merges nested settings with the stored safe mapping before validating the complete provider profile; changing one pricing field cannot erase budgets, and changing `standard` cannot erase `deep`. Release 2 generation consumes only HTTP/model fields and deliberately ignores pricing/research budgets.

Response models must expose the persisted source/destination/route plus the exact Release 1 `JobAcceptedOut(job_id, status, deduplicated)` where a job is accepted. `TelegramAutomationOptionsOut` returns only IDs, display names, provider type/model availability, and safe policy metadata. They must never expose resolved token/session values or secret-reference names.

- [ ] **Step 5: Implement resource routers and transactional enqueue**

Implement these endpoints:

```text
GET    /telegram/sources
POST   /telegram/sources
GET    /telegram/destinations
POST   /telegram/destinations
GET    /telegram/automations
GET    /telegram/automations/options
POST   /telegram/automations
GET    /telegram/automations/{route_id}
POST   /telegram/automations/{route_id}/activate
POST   /telegram/automations/{route_id}/pause
POST   /telegram/automations/{route_id}/resume
POST   /telegram/automations/{route_id}/dry-run
POST   /telegram/automations/{route_id}/backfill
GET    /telegram/automations/{route_id}/dispatches
GET    /brand-profiles
POST   /brand-profiles
PATCH  /brand-profiles/{brand_profile_id}
GET    /prompt-templates
POST   /prompt-templates
POST   /prompt-templates/{prompt_template_id}/versions
POST   /prompt-template-versions/{version_id}/activate
GET    /ai-provider-profiles
POST   /ai-provider-profiles
PATCH  /ai-provider-profiles/{provider_profile_id}
```

Source creation persists `Source(platform="telegram_public")` plus `TelegramSourceConfig`; `Source.platform` identifies the content platform while `TelegramSourceConfig.access_mode` identifies the transport, so MTProto channels are not invented as a second source platform. Destination creation persists `Destination(platform="telegram", target_ref=body.target_ref, secret_ref=body.secret_ref, enabled=True, health_status="unknown", settings={"allow_auto_publish": body.allow_auto_publish})`, then enqueues `telegram.destination.check` with key `telegram-destination-check:{destination.id}:{destination.updated_at.isoformat()}`.

Route creation fills the exact Release 1 columns. Store `body.content_filters.model_dump(mode="json")`, `body.quiet_hours.model_dump(mode="json") if present else {}`, and `body.retry_policy.model_dump(mode="json")`; set `enabled=False`, `cursor_state={"status": "not_initialized"}`, `backfill_limit=None`, and `backfill_since=None`. Validate every referenced row and the source/destination/prompt/provider purpose before insert. If no route model override is supplied, require the selected profile to have `default_model`; if an override is supplied, preserve it only on this route.

Activation sets `enabled=True`, clears `paused_at`, and stores `cursor_state={"status": "initializing", "activation_requested_at": now.isoformat(), "activation_message_id": None, "last_message_id": None, "recent_fingerprints": {}}`. It enqueues `telegram.route.initialize` with key `telegram-route-initialize:{route.id}:{activation_requested_at}` in the same transaction. The request timestamp is audit metadata; Task 5 establishes the effective remote ID/time boundary and catches up before marking ready. Pause sets `paused_at`; resume clears it without resetting cursor. Dry run enqueues `telegram.route.dry_run` with `force_review=True`. Backfill stores the bound only in job payload and uses SHA-256 of canonical bound JSON in `telegram-route-backfill:{route.id}:{bounds_hash}`; it does not edit cursor state or the legacy backfill columns.

Brand profiles expose all editable editorial fields but no secrets. Prompt templates use a stable purpose key; every edit creates the next immutable version with server-computed checksum and schema, and route creation accepts only an active `telegram_rewrite` version. Provider profile create/PATCH validates the executable schema above, stores safe model/settings plus an uppercase reference, and computes `configured` through `EnvironmentSecretResolver.configured()` without resolving the value. Route options omit disabled or unconfigured live profiles. API output never returns `secret_ref`.

- [ ] **Step 6: Run API, full route, and lint tests**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_configuration_api.py tests/test_telegram_route_api.py tests/test_generation_settings_api.py tests/test_api.py -q
.venv/bin/ruff check app/api/telegram_schemas.py app/api/telegram_sources.py \
  app/api/telegram_destinations.py app/api/telegram_automations.py app/api/generation_settings.py \
  app/api/generation_schemas.py app/generation/provider_settings.py app/jobs/types.py
```

Expected: all tests and Ruff pass.

- [ ] **Step 7: Commit Telegram configuration APIs**

```bash
git add backend/app/api/telegram_schemas.py backend/app/api/telegram_sources.py \
  backend/app/api/telegram_destinations.py backend/app/api/telegram_automations.py \
  backend/app/api/generation_settings.py backend/app/api/generation_schemas.py \
  backend/app/generation/provider_settings.py \
  backend/app/api/routes.py backend/app/jobs/types.py \
  backend/tests/test_telegram_configuration_api.py backend/tests/test_telegram_route_api.py backend/tests/test_generation_settings_api.py
git commit -m "feat: configure Telegram automation routes"
```

---

### Task 5: Implement initialization, live polling, bounded backfill, dry run, and scheduler materialization

**Files:**
- Create: `backend/app/automations/telegram/handlers.py`
- Create: `backend/app/automations/telegram/route_policy.py`
- Modify: `backend/app/automations/telegram/repository.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/jobs/scheduler.py`
- Create: `backend/tests/test_telegram_route_handlers.py`
- Create: `backend/tests/test_telegram_route_policy.py`
- Modify: `backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: Task 2 source registry, Task 3 capture repository, Task 4 route jobs; Release 1 `JobContext`, `JobRepository`, `WorkflowSchedule`, `AutomationControl`.
- Produces: gap-free new-only initialization from a recorded timestamp/ID boundary, ascending live capture, bounded source-edit detection, executable route-policy evaluators, bounded cursor-independent backfill, review-only dry runs, and deterministic due poll jobs.

- [ ] **Step 1: Write failing handler tests for gap-free activation, cursor ordering, edits, pause, and backfill isolation**

Create `backend/tests/test_telegram_route_handlers.py`:

```python
async def test_initialize_captures_every_message_newer_than_recorded_activation_boundary():
    fixture = handler_fixture(
        activation_requested_at="2026-07-11T09:00:00.817231Z",
        activation_pages=[
            [envelope(92, published_at="2026-07-11T09:00:02Z"), envelope(91, published_at="2026-07-11T09:00:01Z")],
            [envelope(90, published_at="2026-07-11T08:59:59Z")],
        ],
        catch_up_pages=[[envelope(93, published_at="2026-07-11T09:00:03Z")], []],
    )

    result = await initialize_route(fixture.job(), fixture.context())

    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [91, 92, 93]
    assert fixture.route.cursor_state["activation_boundary_at"] == "2026-07-11T09:00:00Z"
    assert fixture.route.cursor_state["activation_message_id"] == 90
    assert fixture.route.cursor_state["last_message_id"] == 93
    assert fixture.route.cursor_state["status"] == "ready"
    assert result == {"route_id": str(ROUTE_ID), "cursor": 93, "captured": 3, "initialized": True}


async def test_initialize_does_not_mark_ready_when_adapter_cannot_prove_boundary_is_complete():
    fixture = handler_fixture(activation_pages=[incomplete_page_without_predecessor()])

    result = await initialize_route(fixture.job(), fixture.context())

    assert result["continuation_enqueued"] is True
    assert fixture.route.cursor_state["status"] == "catching_up"
    assert fixture.route.cursor_state["last_message_id"] is None


async def test_initialize_nonempty_channel_with_no_new_messages_starts_catch_up_after_predecessor():
    fixture = handler_fixture(
        activation_requested_at="2026-07-11T09:00:00.817231Z",
        activation_pages=[[envelope(90, published_at="2026-07-11T08:59:59Z")]],
        catch_up_pages=[[]],
    )

    result = await initialize_route(fixture.job(), fixture.context())

    assert fixture.capture.calls == []
    assert fixture.source.catch_up_requests[0].after_id == 90
    assert fixture.route.cursor_state["activation_message_id"] == 90
    assert fixture.route.cursor_state["last_message_id"] == 90
    assert fixture.route.cursor_state["status"] == "ready"
    assert result == {"route_id": str(ROUTE_ID), "cursor": 90, "captured": 0, "initialized": True}


async def test_first_live_poll_captures_only_ids_above_initialized_cursor_in_ascending_order():
    fixture = handler_fixture(cursor=91, remote_envelopes=[envelope(94), envelope(92), envelope(93)])

    result = await poll_route(fixture.job(), fixture.context())

    assert fixture.source.last_request.after_id == 91
    assert [call.envelope.anchor_message_id for call in fixture.capture.calls] == [92, 93, 94]
    assert result["captured"] == 3


async def test_global_or_route_pause_performs_no_source_network_call():
    fixture = handler_fixture(global_pause=True, cursor=91)

    result = await poll_route(fixture.job(), fixture.context())

    assert result == {"held": True, "reason": "global_pause"}
    assert fixture.source.calls == []


async def test_poll_lookback_turns_changed_source_message_into_review_only_edit_revision():
    fixture = handler_fixture(
        cursor=120,
        recent_fingerprints={"110": "old-hash", "120": "same-hash"},
        recent_envelopes=[
            envelope(110, text="corrected", source_fingerprint="new-hash", edited_at=NOW),
            envelope(120, source_fingerprint="same-hash"),
        ],
        remote_envelopes=[envelope(121, source_fingerprint="live-hash")],
        publishing_policy="auto_publish",
    )

    result = await poll_route(fixture.job(), fixture.context())

    assert [(call.envelope.anchor_message_id, call.dispatch_kind) for call in fixture.capture.calls] == [
        (110, "source_edit"),
        (121, "live"),
    ]
    assert fixture.capture.calls[0].force_review is True
    assert fixture.capture.calls[0].source_key.endswith(":edit:new-hash")
    assert fixture.route.cursor_state["last_message_id"] == 121
    assert result == {"captured": 1, "source_edits": 1, "filtered": 0}
    assert fixture.telegram_publish_or_edit_calls == []


async def test_replayed_source_edit_fingerprint_does_not_create_another_dispatch():
    fixture = handler_fixture(
        cursor=120,
        recent_fingerprints={"110": "new-hash"},
        recent_envelopes=[envelope(110, source_fingerprint="new-hash", edited_at=NOW)],
    )

    await poll_route(fixture.job(), fixture.context())

    assert fixture.capture.calls == []


async def test_backfill_honors_count_and_does_not_move_live_cursor():
    fixture = handler_fixture(cursor=120, remote_envelopes=[envelope(90), envelope(91), envelope(92)])
    job = fixture.job(payload={"route_id": str(ROUTE_ID), "count": 2, "since": None})

    result = await backfill_route(job, fixture.context())

    assert [call.dispatch_kind for call in fixture.capture.calls] == ["backfill", "backfill"]
    assert fixture.route.cursor_state["last_message_id"] == 120
    assert result["captured"] == 2


async def test_dry_run_prefixes_identity_and_never_advances_cursor_or_publishes():
    fixture = handler_fixture(cursor=120, remote_envelopes=[envelope(120)])

    result = await dry_run_route(fixture.job(payload={"source_message_id": 120}), fixture.context())

    assert fixture.capture.calls[0].dispatch_kind == "dry_run"
    assert fixture.capture.calls[0].dry_run_job_id == fixture.job_id
    assert fixture.route.cursor_state["last_message_id"] == 120
    assert result["force_review"] is True
```

The activation fixture must simulate a post arriving after the initialization snapshot but before the first database write; the catch-up call still returns and captures it. Add a high-volume case where initialization stops at a configured page budget, enqueues `telegram.route.initialize` with key `telegram-route-initialize-catch-up:{route_id}:{last_scanned_id}`, remains `catching_up`, and resumes without duplicate capture.

Add scheduler tests asserting it ignores disabled, paused, initializing/catching-up, or not-due routes; `AutomationControl(id="global").global_pause` creates no poll job; and a due route gets one `telegram.route.poll` job keyed `telegram-route-poll:{route_id}:{scheduled_for.isoformat()}` even when the scheduler ticks twice.

- [ ] **Step 2: Write failing executable route-policy tests**

Create `backend/tests/test_telegram_route_policy.py` and cover these exact rules:

```python
def test_content_filter_normalizes_text_and_exclusion_wins():
    decision = evaluate_content_filter(
        text="  خبر فوری درباره اقتصاد  ",
        has_media=True,
        policy=content_filters(include_terms=["اقتصاد"], exclude_terms=["خبر فوری"]),
    )
    assert decision == ContentFilterDecision(accepted=False, reason="excluded_term:خبر فوری")


def test_overnight_quiet_hours_returns_first_allowed_instant():
    now = datetime(2026, 7, 11, 21, 30, tzinfo=ZoneInfo("Asia/Tehran"))
    assert next_allowed_at(now, quiet_hours("Asia/Tehran", "21:00", "07:00")) == datetime(
        2026, 7, 12, 7, 0, tzinfo=ZoneInfo("Asia/Tehran")
    )


def test_retry_policy_uses_capped_exponential_delay_and_larger_rate_limit():
    policy = retry_policy(max_attempts=4, base_delay_seconds=30, max_delay_seconds=90)
    assert retry_at(policy, attempt_number=3, now=NOW, jitter_ratio=0) == NOW + timedelta(seconds=90)
    assert retry_at(
        policy, attempt_number=2, now=NOW, retry_after_seconds=120, jitter_ratio=0
    ) == NOW + timedelta(seconds=120)
```

Also prove: Unicode NFKC plus case-folding is applied to text and terms; an empty include list permits content; a non-empty include list requires at least one term; exclusion wins; `min_text_characters` is measured after whitespace normalization; `require_media` fails text-only input; quiet hours are start-inclusive/end-exclusive, support same-day and overnight windows, return `now` outside the window, and reject identical start/end values; an exhausted retry policy returns `None`; jitter is injectable and bounded. Source edits bypass content filters and always enter review so a previously used source cannot silently change.

- [ ] **Step 3: Run handler, policy, and scheduler tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_route_handlers.py tests/test_telegram_route_policy.py tests/test_scheduler.py -q
```

Expected: FAIL because Telegram handlers, route-policy evaluators, edit lookback, and due-route scheduler support do not exist.

- [ ] **Step 4: Implement typed job-payload parsing and gap-free initialization outside transactions**

In `backend/app/automations/telegram/handlers.py`, define Pydantic payloads `RouteJobPayload(route_id: UUID)`, `BackfillJobPayload(route_id, count, since)`, and `DryRunJobPayload(route_id, source_message_id, force_review=True)`. Reject malformed payloads as permanent job errors before any network call.

Implement handlers with signature `(job: WorkflowJob, context: JobContext) -> dict[str, Any]`. Add `build_telegram_route_handlers(source_registry, media_stager)` which returns initialize/poll/backfill/dry-run closures with those transport dependencies captured. Every handler first loads route/source config and `AutomationControl(id="global")`. Poll/backfill/dry-run choose the source adapter, fetch and materialize outside `session.begin()`, then open one short transaction per envelope around `capture_and_enqueue()`.

Activation is a two-coordinate boundary, not “whatever is newest when the worker eventually runs.” The API's `activation_requested_at` is normalized down to the source timestamp precision and stored as `activation_boundary_at`; its boundary tuple is `(activation_boundary_at, 0)`. Using `0` deliberately treats every positive message ID stamped in that precision bucket as new, which may conservatively include at most one timestamp unit of pre-click traffic but can never skip a same-bucket post. The source adapter must page a stable activation snapshot backwards until it returns both (a) every complete envelope whose `(published_at, anchor_message_id)` is strictly greater than that tuple and (b) the greatest predecessor ID at or below the tuple. Public HTML and MTProto implementations must expose a completeness flag/page token; an adapter that cannot prove the boundary complete must fail retryably or enqueue the deterministic continuation and must never mark the route ready.

Fetch the activation pages outside a transaction. In one short transaction, lock the route, confirm its `activation_requested_at` has not changed, store `activation_boundary_at`, store the proven predecessor as both `activation_message_id` and initial `last_message_id` (`0` for an empty channel), and set `status="catching_up"`. Capture the collected post-boundary envelopes in ascending `(published_at, anchor_message_id)` order through the normal atomic capture transaction; each capture advances `last_message_id` beyond that predecessor. Then repeatedly fetch `after_id=last_message_id` until one complete empty snapshot is observed; `after_id` is therefore never `None` and initialization can never fall back to an unbounded/history scan. This catches messages that arrive after the activation snapshot, during capture, or before the cursor commit. Only that empty proof sets `status="ready"`, `initialized_at`, and the final cursor. A bounded invocation enqueues `telegram.route.initialize` with key `telegram-route-initialize-catch-up:{route_id}:{last_scanned_id}`, remains `catching_up`, and continues later. Replays use dispatch identities and the saved cursor, so they are harmless. No message at or below the recorded boundary is captured, and no message strictly above it is used merely as the baseline.

If the channel is empty at activation, store `activation_message_id=0` and `last_message_id=0`, still require one complete empty catch-up snapshot, then mark ready. `activation_requested_at`, `activation_boundary_at`, `activation_message_id`, `initialized_at`, `last_message_id`, and bounded `recent_fingerprints` survive every later cursor update.

- [ ] **Step 5: Implement filtering, quiet hours, retries, and source-edit lookback**

Create pure evaluators in `route_policy.py`:

```python
evaluate_content_filter(text, has_media, policy) -> ContentFilterDecision
next_allowed_at(now, quiet_hours) -> datetime
retry_at(policy, attempt_number, now, retry_after_seconds=None, jitter_ratio=None) -> datetime | None
```

Use Task 2's canonical `telegram_envelope_fingerprint()`. Polling performs two reads outside transactions: forward pages using `after_id=cursor_state["last_message_id"]`, plus a bounded `fetch_recent(limit=50)` lookback. Compare the lookback with `cursor_state.recent_fingerprints`. An existing message with a different fingerprint is captured as `dispatch_kind="source_edit"`, reuses the existing Story, creates a new immutable evidence snapshot and child `StoryRevision`, updates only that fingerprint, and enqueues processing with `force_review=True`. It never advances the numeric cursor and never calls a Telegram remote edit/update API. An unchanged fingerprint does nothing; a later distinct fingerprint creates one more review revision.

Evaluate content filters for first-time live envelopes before generation. A rejected envelope is still durably captured with `AutomationDispatch.status="filtered"`, advances the live cursor, appends a safe event with the filter reason, and does not enqueue `telegram.route.process`; it is not repeatedly reconsidered. Accepted content captured during quiet hours enqueues `telegram.route.process` with `scheduled_for=next_allowed_at(...)`; capture/cursor persistence is never delayed. Outside quiet hours it is immediately eligible. Extend `capture_and_enqueue()` with explicit `enqueue_process`, `process_scheduled_for`, `process_max_attempts`, and `force_review` arguments; keep Task 3 defaults backward-compatible. Pass `route.retry_policy.max_attempts` to the process job. Retryable process failures use `retry_at()` with capped exponential delay; a provider/Telegram `retry_after` wins when larger. Exhaustion becomes operator-visible attention rather than another job.

Polling sorts source edits by `(published_at, anchor_message_id)` and handles them before new live messages, then sorts live envelopes ascending and advances the cursor after each atomic capture. It updates `route.last_polled_at` and `next_poll_at` only after all complete pages succeed. Backfill requests either `limit=count` before the current cursor or `since=since`, caps the adapter result at 100 complete envelopes, uses dispatch kind `backfill`, forces review, and never changes route cursor/fingerprint/next-poll fields. Dry run fetches the requested message or newest available envelope, uses dispatch kind `dry_run`, forces review, and returns the created dispatch ID.

- [ ] **Step 6: Register handlers and materialize due route jobs**

Extend `build_default_registry()` with optional keyword-only source and publishing dependency bundles. When source dependencies are supplied, add these registrations using the closures returned by `build_telegram_route_handlers()`:

```python
registry.register("telegram.route.initialize", initialize_route)
registry.register("telegram.route.poll", poll_route)
registry.register("telegram.route.backfill", backfill_route)
registry.register("telegram.route.dry_run", dry_run_route)
```

Task 7 registers `telegram.route.process` only after its real handler exists. Scheduler selection must require `route.enabled`, `route.paused_at is None`, `cursor_state.status == "ready"`, and `next_poll_at <= now`. Enqueue with `pause_sensitive=True`, `origin=JobOrigin.SCHEDULER`, priority `10`, and the deterministic due timestamp key from the test.

- [ ] **Step 7: Run focused and job-engine regression tests**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_route_handlers.py tests/test_telegram_route_policy.py tests/test_scheduler.py \
  tests/postgres/test_job_repository.py tests/test_job_handler_registry.py tests/test_job_worker.py -q
.venv/bin/ruff check app/automations/telegram/handlers.py app/automations/telegram/route_policy.py \
  app/automations/telegram/repository.py app/jobs/registry.py app/jobs/scheduler.py
```

Expected: all tests and Ruff pass; no source adapter is called in pause tests.

- [ ] **Step 8: Commit route execution**

```bash
git add backend/app/automations/telegram/handlers.py backend/app/automations/telegram/route_policy.py \
  backend/app/automations/telegram/repository.py backend/app/jobs/registry.py \
  backend/app/jobs/scheduler.py backend/tests/test_telegram_route_handlers.py \
  backend/tests/test_telegram_route_policy.py backend/tests/test_scheduler.py
git commit -m "feat: run bounded Telegram route collection"
```

---

### Task 6: Add the immutable Telegram rewrite prompt and OpenRouter structured provider

**Files:**
- Create: `backend/app/generation/telegram_schema.py`
- Create: `backend/app/generation/default_prompts.py`
- Create: `backend/app/generation/providers/openrouter.py`
- Create: `backend/app/generation/providers/profiles.py`
- Create: `backend/app/core/redaction.py`
- Modify: `backend/app/jobs/events.py`
- Modify: `backend/app/jobs/repository.py`
- Modify: `backend/app/generation/providers/registry.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_telegram_generation_schema.py`
- Create: `backend/tests/test_openrouter_provider.py`
- Create: `backend/tests/test_provider_profile_resolver.py`
- Create: `backend/tests/test_default_prompts.py`
- Create: `backend/tests/test_secret_redaction.py`

**Interfaces:**
- Consumes: Release 1 `ProviderMessage`, `GenerationProviderRequest`, `GenerationProviderResult`, `GenerationProvider`, `ProviderRegistry`, `PromptTemplate`, and `PromptTemplateVersion`.
- Produces: `TelegramRewriteInput`, `TelegramRewriteOutput`, shared `TelegramVariantContent`, `TelegramEvidenceCitation`, `seed_default_telegram_prompt()`, `OpenRouterProvider.generate()`, and `ProviderProfileResolver.resolve()`.

- [ ] **Step 1: Write failing schema and provider-contract tests**

Create tests that assert:

```python
def test_telegram_output_rejects_unbounded_or_unsupported_content():
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(body="x" * 4097, parse_mode="HTML", buttons=[])
    with pytest.raises(ValidationError):
        TelegramRewriteOutput(body="<script>alert(1)</script>", parse_mode="HTML", buttons=[])


def test_shared_telegram_variant_allows_truthful_null_source_item_identity():
    value = TelegramVariantContent.model_validate(
        {
            "body": "Operator-authored Telegram draft",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "ltr",
            "dry_run": False,
        }
    )
    assert value.source_item_id is None


async def test_openrouter_posts_json_schema_and_returns_normalized_result():
    provider, requests = provider_with_mock_response(
        {"choices": [{"message": {"content": '{"body":"بازنویسی","parse_mode":"HTML","buttons":[]}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 4}, "model": "openai/gpt-5-mini"}
    )
    result = await provider.generate(provider_request())

    sent = json.loads(requests[0].content)
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert result.output["body"] == "بازنویسی"
    assert result.resolved_model == "openai/gpt-5-mini"


async def test_default_prompt_seed_is_idempotent_and_versions_content():
    first = await seed_default_telegram_prompt(fake_session)
    second = await seed_default_telegram_prompt(fake_session)

    assert first.id == second.id
    assert first.output_schema_version == "telegram_rewrite.v1"
    assert first.checksum_sha256 == sha256_prompt(first.system_template, first.user_template, first.output_schema)


async def test_default_brand_and_provider_profiles_make_a_clean_install_usable():
    result = await seed_default_telegram_configuration(fake_session, openrouter_available=True)
    assert result.brand.name == "Default Newsroom"
    assert result.brand.output_language == "fa"
    assert {profile.provider_type for profile in result.providers} == {"fake", "openrouter"}
    assert result.provider("fake").enabled is True
    assert result.provider("openrouter").secret_ref == "OPENROUTER_API_KEY"


async def test_profile_resolver_honors_selected_secret_settings_and_default_model():
    secrets = FakeSecretResolver({"OPENROUTER_EDITOR_KEY": "editor-secret"})
    resolver = ProviderProfileResolver(
        secret_resolver=secrets,
        http_client_factory=recording_http_client_factory,
        provider_registry=build_default_provider_registry(),
    )
    profile = provider_profile(
        provider_type="openrouter",
        secret_ref="OPENROUTER_EDITOR_KEY",
        default_model="anthropic/claude-sonnet-4.5",
        settings={
            "base_url": "https://openrouter.example/api/v1",
            "timeout_seconds": 45,
            "http_referer": "http://127.0.0.1:3000",
            "app_title": "NewsCraft",
            "pricing": {
                "input_usd_per_million": "1.25",
                "output_usd_per_million": "5.00",
            },
            "research_budgets": {
                "standard": research_budget_settings(max_model_calls=3),
                "deep": research_budget_settings(max_model_calls=6),
            },
        },
    )

    resolved = await resolver.resolve(profile, model_override=None)

    assert resolved.model == "anthropic/claude-sonnet-4.5"
    assert resolved.provider.base_url == "https://openrouter.example/api/v1"
    assert resolved.provider.timeout_seconds == 45
    assert resolved.provider.api_key == "editor-secret"
    assert recording_http_client_factory.last_kwargs == {
        "base_url": "https://openrouter.example/api/v1",
        "timeout_seconds": 45,
        "http_referer": "http://127.0.0.1:3000",
        "app_title": "NewsCraft",
    }


async def test_profile_resolver_uses_route_override_and_only_selected_profile_secret():
    secrets = FakeSecretResolver({"OPENROUTER_A_KEY": "key-a", "OPENROUTER_B_KEY": "key-b"})
    resolver = profile_resolver(secrets)

    selected = await resolver.resolve(
        provider_profile(secret_ref="OPENROUTER_B_KEY", default_model="model-b"),
        model_override="route-model",
    )

    assert selected.model == "route-model"
    assert selected.provider.api_key == "key-b"
    assert "key-a" not in repr(selected)
```

Also assert disabled profiles, missing secrets, unknown provider types, unsupported setting keys, invalid base URLs, and a profile with neither a route override nor default model fail before HTTP. Assert 401/403 are permanent provider errors, 408/429/5xx are retryable, invalid JSON/schema is `needs_review`, Authorization never appears in exception text, and the deterministic fake provider satisfies the same request/result contract.

In `backend/tests/test_secret_redaction.py`, assert recursive redaction covers secret-like keys, Bearer/Basic values, Telegram bot-token patterns, URL userinfo, secret query parameters, nested mappings/sequences, and explicitly supplied secret substrings without mutating the input.

- [ ] **Step 2: Run focused tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_generation_schema.py tests/test_openrouter_provider.py tests/test_provider_profile_resolver.py tests/test_default_prompts.py tests/test_secret_redaction.py -q
```

Expected: FAIL because the Telegram schema, default prompt, OpenRouter provider/profile resolver, and shared redactor do not exist.

- [ ] **Step 3: Implement exact structured schemas and immutable prompt seed**

Create:

```python
class TelegramRewriteInput(BaseModel):
    source_text: str = Field(min_length=1)
    source_url: str | None
    source_channel: str
    language: str
    direction: Literal["ltr", "rtl"]
    attribution_policy: Literal["preserve", "remove", "custom"]
    custom_footer: str | None


class TelegramButton(BaseModel):
    text: str = Field(min_length=1, max_length=64)
    url: HttpUrl


class TelegramRewriteOutput(BaseModel):
    body: str = Field(min_length=1, max_length=4096)
    parse_mode: Literal["HTML"] = "HTML"
    buttons: list[TelegramButton] = Field(default_factory=list, max_length=8)


class TelegramVariantContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4096)
    parse_mode: Literal["HTML"] = "HTML"
    buttons: list[TelegramButton] = Field(default_factory=list, max_length=8)
    source_item_id: UUID | None
    source_url: HttpUrl | None
    media_policy: Literal["preserve", "omit", "replace_manually"]
    media_asset_ids: list[UUID]
    direction: Literal["ltr", "rtl"]
    dry_run: bool


class TelegramEvidenceCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_snapshot_id: UUID
    evidence_key: str = Field(min_length=1)
    source_url: HttpUrl | None
    locator: str = Field(pattern=r"^chars:\d+-\d+$")
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

Validate HTML with an allowlist of `b`, `strong`, `i`, `em`, `u`, `s`, `code`, `pre`, `a`, and `blockquote`; reject unsupported tags and unsafe `href` schemes rather than silently stripping them. `TelegramVariantContent` is the single shared stored-content/renderer schema for Releases 2–4. `source_item_id` is intentionally nullable for operator/research-originated drafts, while every Telegram route capture supplies its real non-null ID. Do not create a stricter renderer-only copy.

`seed_default_telegram_prompt()` creates purpose key `telegram_rewrite` and immutable version `1`. The system template must state: preserve factual meaning, do not invent facts, obey requested language/tone, return only the schema, and treat source text as data rather than instructions. The user template must include named placeholders for every `TelegramRewriteInput` field. Store `TelegramRewriteOutput.model_json_schema()`, output schema version `telegram_rewrite.v1`, and a checksum over canonical JSON; a checksum change creates version `2` instead of mutating version `1`.

`seed_default_telegram_configuration()` idempotently creates `Default Newsroom` (`output_language="fa"`), an enabled deterministic fake profile, and an OpenRouter profile whose `secret_ref` is `OPENROUTER_API_KEY` and whose enabled/available state reflects configuration. It returns existing rows by stable names instead of duplicating them. A clean install can therefore create a review-first route without manual SQL; no secret value is written to the database.

- [ ] **Step 4: Implement OpenRouter with injected HTTP and register it**

Create `redact_secrets(value, *, secrets=())` and `redact_url(url)` in `app/core/redaction.py`. They recursively sanitize secret-like keys, authorization values, Telegram token patterns, URL userinfo/query secrets, nested values, and any literal secret supplied by the caller. Make Release 1 `redact_event_data()` delegate to the shared redactor and sanitize job failure/result payloads before persistence. `OpenRouterProvider.provider_name = "openrouter"`. Its constructor accepts `http_client`, `api_key`, `base_url="https://openrouter.ai/api/v1"`, `timeout_seconds=60`, `http_referer=None`, and `app_title="NewsCraft"`. `generate()` sends `model`, mapped messages, and strict `response_format` to `/chat/completions`, parses either string JSON or object content, and returns the exact Release 1 `GenerationProviderResult`. Every exception and safe metadata value passes through the shared redactor with the API key supplied explicitly; authentication response bodies are never persisted.

Create immutable `ResolvedProviderProfile(profile_id, provider_type, model, provider)` and `ProviderProfileResolver` in `app/generation/providers/profiles.py`. It consumes the selected loaded `AIProviderProfile`, Release 1 `SecretResolver`, an HTTP-client factory, and the fake provider registry. For `fake`, require no `secret_ref` or settings and return the registered fake using `model_override or profile.default_model or "fake-v1"`. For `openrouter`, require/resolve exactly `profile.secret_ref`, validate the full stored mapping through `OpenRouterProviderSettings`, and construct a profile-specific `OpenRouterProvider` from only `base_url`, `timeout_seconds`, `http_referer`, and `app_title`; use `model_override or profile.default_model` and fail if neither exists. `pricing` and `research_budgets` remain preserved safe profile configuration but are not passed to the Release 2 HTTP generation adapter. Unknown, disabled, unconfigured, or schema-invalid profiles are permanent configuration errors. Never cache resolved material in ORM rows, job payloads, registry names, or object representations.

Add settings `openrouter_base_url`, `openrouter_default_model`, `telegram_media_staging_root`, `telegram_max_photo_bytes=10_000_000`, and `telegram_max_file_bytes=49_000_000`; do not bind an OpenRouter key directly onto the Settings object. The default profile references `OPENROUTER_API_KEY`, and its configured/available state comes from `EnvironmentSecretResolver.configured(profile.secret_ref)`. The default provider registry remains deterministic fake only; live providers are created from the selected profile. Call both default seed functions from the existing idempotent application bootstrap/lifespan transaction so a clean install exposes one brand, prompt version, and usable configured provider choice without a manual seed command.

- [ ] **Step 5: Run provider contracts and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_generation_schema.py tests/test_openrouter_provider.py tests/test_provider_profile_resolver.py tests/test_default_prompts.py tests/test_secret_redaction.py tests/test_job_event_redaction.py tests/test_generation_provider_contract.py -q
.venv/bin/ruff check app/core/redaction.py app/jobs/events.py app/jobs/repository.py app/generation/telegram_schema.py app/generation/default_prompts.py app/generation/providers/openrouter.py app/generation/providers/profiles.py
git add backend/app/generation backend/app/core/redaction.py backend/app/jobs/events.py backend/app/jobs/repository.py backend/app/core/config.py backend/app/main.py backend/tests/test_telegram_generation_schema.py \
  backend/tests/test_openrouter_provider.py backend/tests/test_provider_profile_resolver.py backend/tests/test_default_prompts.py backend/tests/test_secret_redaction.py
git commit -m "feat: generate structured Telegram rewrites"
```

---

### Task 7: Process a captured dispatch into an exact review or auto-approved revision

**Files:**
- Create: `backend/app/automations/telegram/policy.py`
- Modify: `backend/app/automations/telegram/handlers.py`
- Modify: `backend/app/jobs/registry.py`
- Create: `backend/app/api/telegram_drafts.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/test_telegram_process_handler.py`
- Create: `backend/tests/test_telegram_draft_api.py`

**Interfaces:**
- Consumes: Task 3 `AutomationDispatch`; Task 6 `ProviderProfileResolver`; Release 1 generation, content-pack, variant/revision, publish, event, and control models.
- Produces: `evaluate_auto_publish() -> AutoPublishDecision`, real `process_route_dispatch()`, and revision list/detail/edit/approve/publish APIs.

- [ ] **Step 1: Write failing review/auto gate and immutability tests**

Cover this matrix in `backend/tests/test_telegram_process_handler.py`:

```python
@pytest.mark.parametrize(
    ("override", "allowed", "reason"),
    [
        ({}, True, None),
        ({"global_pause": True}, False, "global_pause"),
        ({"global_dry_run": True}, False, "global_dry_run"),
        ({"route_paused": True}, False, "route_paused"),
        ({"destination_enabled": False}, False, "destination_disabled"),
        ({"destination_health": "broken"}, False, "destination_unhealthy"),
        ({"destination_allows_auto": False}, False, "destination_auto_disabled"),
        ({"validation_ok": False}, False, "variant_invalid"),
        ({"evidence_ready": False}, False, "evidence_invalid"),
        ({"media_ready": False}, False, "media_not_ready"),
    ],
)
def test_auto_publish_gate_is_fail_closed(override, allowed, reason):
    decision = evaluate_auto_publish(**{**valid_gate_input(), **override})
    assert (decision.allowed, decision.reason) == (allowed, reason)


async def test_review_route_creates_pending_review_revision_linked_to_generation_attempt():
    result = await process_route_dispatch(job_for(DISPATCH_ID), context_for(policy="review_required"))
    revision = stored_revision()
    assert revision.approval_state == "pending_review"
    assert revision.generation_attempt_id == stored_attempt().id
    assert revision.parent_revision_id is None
    assert revision.revision_number == 1
    assert revision.content["source_item_id"] == str(DISPATCH_SOURCE_ITEM_ID)
    assert revision.evidence_map == [captured_snapshot_citation()]
    assert revision.content_hash == sha256_canonical(
        {"content": revision.content, "evidence_map": revision.evidence_map}
    )
    assert result["review_required"] is True
    assert publish_jobs() == []


async def test_auto_route_approves_exact_revision_and_enqueues_one_publish_job():
    result = await process_route_dispatch(job_for(DISPATCH_ID), context_for(policy="auto_publish"))
    revision = stored_revision()
    assert revision.approval_state == "approved"
    assert revision.created_by == f"automation:{ROUTE_ID}"
    assert result["publish_job_id"]
    assert enqueued_job().idempotency_key == f"telegram-publish:{DESTINATION_ID}:{revision.id}:{revision.content_hash}"


async def test_selected_route_provider_profile_is_resolved_for_the_attempt():
    fixture = context_for(
        ai_provider_profile_id=PROFILE_B_ID,
        route_model="route-model",
        available_profiles=[profile_a(), profile_b(secret_ref="OPENROUTER_B_KEY")],
    )

    await process_route_dispatch(job_for(DISPATCH_ID), fixture)

    assert fixture.profile_resolver.calls == [(PROFILE_B_ID, "route-model")]
    assert stored_attempt().provider == "openrouter"
    assert stored_attempt().requested_model == "route-model"


async def test_source_edit_generates_child_revision_for_review_without_remote_update():
    existing = existing_variant_revision(number=1, approval_state="approved")

    result = await process_route_dispatch(
        job_for(SOURCE_EDIT_DISPATCH_ID), context_for(dispatch_kind="source_edit", existing_revision=existing)
    )

    revision = stored_revision()
    assert revision.revision_number == 2
    assert revision.parent_revision_id == existing.id
    assert revision.generation_attempt_id == stored_attempt().id
    assert revision.approval_state == "pending_review"
    assert result["review_required"] is True
    assert publish_jobs() == []
    assert telegram_remote_update_calls() == []


async def test_interleaved_routes_use_global_revision_numbers_and_route_specific_parent():
    shared_variant = telegram_variant_with_dispatch_revisions(
        route_a_revision=revision(1),
        route_b_revision=revision(2),
    )

    await process_route_dispatch(
        job_for(ROUTE_A_EDIT_DISPATCH_ID),
        context_for(route_id=ROUTE_A_ID, dispatch_kind="source_edit", variant=shared_variant),
    )

    created = stored_revision()
    assert created.platform_variant_id == shared_variant.id
    assert created.revision_number == 3
    assert created.parent_revision_id == shared_variant.route_a_revision.id
    assert stored_dispatch().variant_revision_id == created.id
```

Draft API tests must prove a manual edit creates revision `N+1` with `parent_revision_id=N.id`, `generation_attempt_id=None`, and `approval_state="pending_review"` without mutating revision `N`; it copies the parent's nonempty `evidence_map`, revalidates every citation against immutable snapshots, and rejects a missing/mismatched snapshot, key, URL, locator, or excerpt hash. Approval transitions only `pending_review -> approved` and requires the submitted `content_hash` or returns 409; rejection transitions only `pending_review -> rejected`; a rejected revision cannot be approved or published; explicit publish accepts only `approved`; and a dry-run revision cannot publish. List/detail responses expose only the exact Release 1 states `draft`, `pending_review`, `approved`, and `rejected`; no alias such as `unapproved`, `review_required`, or `published` is persisted in `approval_state`.

- [ ] **Step 2: Run tests and verify they fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_process_handler.py tests/test_telegram_draft_api.py -q
```

- [ ] **Step 3: Implement generation attempt persistence and fail-closed policy**

`process_route_dispatch()` first locks `AutomationDispatch` in a short transaction; if `variant_revision_id` is already set, return that exact revision/result without resolving a provider or making another model call. If `generation_run_id` already names a running attempt, report the dispatch as already in progress; if that run has a validated completed output but no linked revision because of a crash, resume persistence from the durable output rather than call the provider again. An unresolved dispatch loads the exact immutable `StoryEvidenceSnapshot` reached through its revision's `StoryEvidenceLink(claim_key="telegram.source")`, the `StoryRevision`, ordered media, route prompt, selected `AIProviderProfile`, and any prior dispatch-linked Telegram variant revision for the same route/story. Resolve only `route.ai_provider_profile_id` through the injected `ProviderProfileResolver`, passing `route.content_filters.get("model")` as the optional route override. Do not call `ProviderRegistry.get(profile.name/provider_type)` for a live profile and do not read a global OpenRouter key. Persist the resolver's provider type/model on the attempt.

Create `GenerationRun(story_revision_id=dispatch.story_revision_id, provider_profile_id=route.ai_provider_profile_id, prompt_template_version_id=route.prompt_template_version_id, requested_model=route.content_filters.get("model"), status="running", input_hash=input_hash, request_payload=sanitized_request)` and `GenerationAttempt(attempt_number=1, provider=resolved.provider_type, requested_model=run.requested_model, prompt_snapshot={"system": prompt.system_template, "user": rendered_user_prompt, "schema": prompt.output_schema}, status="running")`, and set `dispatch.generation_run_id=run.id` in the same pre-dispatch transaction. Commit, call `resolved.provider.generate()` outside the transaction using `resolved.model`, then validate `TelegramRewriteOutput` and finish the exact attempt/run in a new transaction. Provider errors map to Release 1 retryable/needs-review/permanent job classes and Task 5's route retry schedule. Add `build_telegram_process_handler(profile_resolver)` and register its closure as `registry.register("telegram.route.process", process_route_dispatch)` only when generation dependencies are supplied.

Get or create the unresolved route Story's Telegram lineage under row locks. Find the latest earlier `AutomationDispatch.variant_revision_id` for the same route and Story; that revision is the route-specific parent. When it exists, reuse its `PlatformVariant` and `ContentPack`. When it does not, get or create `ContentPack(story_revision_id=dispatch.story_revision_id, brand_profile_id=route.brand_profile_id, status="draft")`, then get or create its Telegram `PlatformVariant`. Lock all revisions for that variant and allocate `revision_number=max(existing)+1`; only a genuinely empty variant creates revision `1` with `parent_revision_id=None`. Every later normal regeneration or `source_edit` uses the next global number for that shared variant and the prior dispatch revision for this route as `parent_revision_id`, so interleaved routes may branch without duplicate revision numbers or adopting another route's parent.

Build and validate the exact stored content through shared `TelegramVariantContent`; route captures always supply the real source item even though the shared field is nullable:

```python
content = TelegramVariantContent(
    body=output.body,
    parse_mode=output.parse_mode,
    buttons=output.buttons,
    source_item_id=dispatch.source_item_id,
    source_url=source_item.source_url,
    media_policy=route.media_policy,
    media_asset_ids=ordered_media_ids if route.media_policy == "preserve" else [],
    direction=content_item.direction or "ltr",
    dry_run=dispatch.dispatch_kind == "dry_run",
).model_dump(mode="json")
```

Build a nonempty exact evidence map from the captured snapshot:

```python
evidence_map = [
    TelegramEvidenceCitation(
        evidence_snapshot_id=snapshot.id,
        evidence_key=snapshot.evidence_key,
        source_url=snapshot.source_url,
        locator=f"chars:0-{len(snapshot.content_text)}",
        excerpt_sha256=snapshot.content_sha256,
    ).model_dump(mode="json")
]
```

Generation requires nonempty captured text, verifies `sha256(snapshot.content_text.encode("utf-8")) == snapshot.content_sha256`, and verifies the full-text locator before provider dispatch; an empty/mismatched snapshot becomes `needs_review` and creates no generated revision. Set validation results from schema/HTML/platform/media/evidence checks and compute `content_hash=sha256_canonical({"content": content, "evidence_map": evidence_map})`. Every provider-generated revision sets `generation_attempt_id=attempt.id`; lineage follows the get-or-create algorithm above. Before completing the handler, persist `dispatch.variant_revision_id`; when auto mode creates a publish job, also persist `dispatch.publish_job_id`, so route-specific lineage never depends on parsing JSON or `created_by` strings. A source edit always produces `approval_state="pending_review"` regardless of route policy, never mutates or withdraws the already published revision, and never invokes a remote Telegram edit. A normal validated auto route persists `approved`; every other completed generation persists `pending_review`. `draft` is reserved for an operator-created revision that has not yet been submitted to review, and `rejected` only for the explicit rejection transition. `replace_manually` always sets `media_replacement_required` and forces review; `omit` is ready without media; missing preserve media forces review. `evaluate_auto_publish()` uses the matrix above and never downgrades validation to make auto mode pass.

- [ ] **Step 4: Implement exact-revision review APIs**

Add:

```text
GET  /telegram/drafts?route_id=&approval_state=
GET  /telegram/drafts/{revision_id}
POST /telegram/drafts/{revision_id}/revisions
POST /telegram/drafts/{revision_id}/approve
POST /telegram/drafts/{revision_id}/reject
POST /telegram/drafts/{revision_id}/publish
```

Edit input is `{content: TelegramRewriteOutput, media_asset_ids: list[UUID]}` and creates a new immutable child revision with `generation_attempt_id=None` and `approval_state="pending_review"`. Rebuild the stored nine-key Telegram content mapping through `TelegramVariantContent` by taking only `body`/`parse_mode`/`buttons` from the submitted schema, validating submitted media IDs, and copying `source_item_id`, `source_url`, `media_policy`, `direction`, and `dry_run` from the parent; the client cannot clear dry-run state, switch provenance, or change route policy through an edit. The server also copies, parses through `TelegramEvidenceCitation`, and revalidates the parent's exact nonempty `evidence_map` against immutable snapshot rows; the client cannot replace it. Recompute `content_hash` over `{content, evidence_map}`. Approve input is `{content_hash: str}`. Reject input is `{content_hash: str, note: str | None}`. Publish input is `{content_hash: str}` and transactionally creates or reuses `PublishJob` plus `telegram.publish` `WorkflowJob`; it never calls Telegram inline. State transitions lock the exact revision and compare its current hash/state, returning 409 for stale or invalid transitions. Append workflow events for generation, review-required reason, source edit, manual edit, approval, rejection, and publish request.

- [ ] **Step 5: Run focused/full generation tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_process_handler.py tests/test_telegram_draft_api.py tests/test_generation_provider_contract.py -q
.venv/bin/ruff check app/automations/telegram/policy.py app/automations/telegram/handlers.py app/api/telegram_drafts.py
git add backend/app/automations/telegram/policy.py backend/app/automations/telegram/handlers.py \
  backend/app/api/telegram_drafts.py backend/app/api/routes.py backend/app/jobs/registry.py \
  backend/tests/test_telegram_process_handler.py backend/tests/test_telegram_draft_api.py
git commit -m "feat: route Telegram rewrites through exact revision review"
```

---

### Task 8: Render deterministic Bot API operations and implement the Telegram client

**Files:**
- Create: `backend/app/publishing/telegram/__init__.py`
- Create: `backend/app/publishing/telegram/contracts.py`
- Create: `backend/app/publishing/telegram/renderer.py`
- Create: `backend/app/publishing/telegram/client.py`
- Create: `backend/tests/test_telegram_renderer.py`
- Create: `backend/tests/test_telegram_bot_client.py`

**Interfaces:**
- Produces: `build_publish_plan(revision, media, destination) -> TelegramPublishPlan` and `TelegramBotClient.execute(operation, token) -> TelegramOperationResult`.

- [ ] **Step 1: Write failing renderer/client contract tests**

Assert: text-only uses `sendMessage`; one photo/video/document re-uploads the local file; 2–10 compatible photo/video items use one `sendMediaGroup`; more than 10 produces stable groups of 10; a caption over 1024 creates media without caption followed by one `sendMessage`; body over 4096 fails validation; `omit` yields no media operations; `replace_manually` cannot render; mixed documents and photo/video require review. Assert a shared `TelegramVariantContent` with `source_item_id=None` renders normally and does not invent an identity, while route-generated content retains its real ID. Assert operation keys and payload hash are identical across two renders.

Client MockTransport tests must assert returned message IDs for text/single/group operations, 429 raises `TelegramRateLimited(retry_after=17)`, connect failure is retryable-before-dispatch, read timeout and 5xx are ambiguous, 400 is permanent, and exception/metadata text never includes the token.

- [ ] **Step 2: Run and verify failures**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_renderer.py tests/test_telegram_bot_client.py -q
```

- [ ] **Step 3: Implement exact plan contracts and renderer**

Use immutable dataclasses:

```python
@dataclass(frozen=True, slots=True)
class TelegramPublishOperation:
    index: int
    key: str
    method: Literal["sendMessage", "sendPhoto", "sendVideo", "sendDocument", "sendMediaGroup"]
    fields: dict[str, Any]
    file_paths: tuple[Path, ...]
    request_hash: str


@dataclass(frozen=True, slots=True)
class TelegramPublishPlan:
    destination_id: UUID
    revision_id: UUID
    payload_hash: str
    operations: tuple[TelegramPublishOperation, ...]
```

Parse revision content through the shared `TelegramVariantContent` before planning; do not introduce a renderer schema that makes `source_item_id` required. Canonicalize fields and file checksums before hashing. Never put token, secret ref, or absolute media path in the hashable/sanitized payload. Media group compatibility is photo+video together, documents only with documents; every operation uses destination `target_ref`, HTML parse mode, and safe button markup.

- [ ] **Step 4: Implement Bot API transport**

`TelegramBotClient` accepts an injected `httpx.AsyncClient` and base URL. `execute()` builds JSON for text and multipart for media, calls `/bot{token}/{method}`, validates `ok=true`, normalizes a single object or group list to `TelegramOperationResult(remote_message_ids, response_metadata)`, and classifies errors exactly as tested. Sanitize `description`, parameters, and URLs before returning metadata.

- [ ] **Step 5: Verify and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_renderer.py tests/test_telegram_bot_client.py -q
.venv/bin/ruff check app/publishing/telegram tests/test_telegram_renderer.py tests/test_telegram_bot_client.py
git add backend/app/publishing/telegram backend/tests/test_telegram_renderer.py backend/tests/test_telegram_bot_client.py
git commit -m "feat: render and send Telegram publish plans"
```

---

### Task 9: Persist operation receipts, resume safely, and reconcile ambiguous publication

**Files:**
- Create: `backend/app/publishing/telegram/service.py`
- Create: `backend/app/publishing/telegram/handlers.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/telegram_drafts.py`
- Create: `backend/tests/test_telegram_publish_service.py`
- Create: `backend/tests/test_telegram_reconciliation_api.py`

**Interfaces:**
- Consumes: Task 1 operation receipts, Task 8 plan/client, Release 1 publish models/jobs/events.
- Produces: idempotent `publish_telegram()`, destination health handler, safe operation resume, final `Publication`, and manual reconciliation.

- [ ] **Step 1: Write failing crash/retry/idempotency tests**

Cover: receipts are inserted before first network call; succeeded operation 0 is skipped when operation 1 retries; two handlers for the same `PublishJob` produce one operation set and one `Publication`; 429 stores `next_attempt_at` and fails job retryably; connect failure retries; read timeout/5xx changes receipt/job/publication reconciliation state to `required` and does not auto-retry; permanent 4xx enters attention; all operations succeeding creates one Publication with ordered remote IDs and permalink; existing Publication returns without network calls.

Reconciliation API tests:

```python
async def test_mark_published_creates_receipt_from_operator_verified_remote_ids():
    response = await client.post(
        f"/telegram/publish-jobs/{PUBLISH_JOB_ID}/reconcile",
        json={"outcome": "published", "remote_message_ids": [501, 502], "permalink": "https://t.me/target/501"},
    )
    assert response.status_code == 200
    assert response.json()["reconciliation_status"] == "confirmed"


async def test_mark_not_published_requeues_only_ambiguous_operation():
    response = await client.post(
        f"/telegram/publish-jobs/{PUBLISH_JOB_ID}/reconcile", json={"outcome": "not_published"}
    )
    assert response.status_code == 202
    assert response.json()["job"]["job_id"] == str(RECONCILE_JOB_ID)
    assert fake_jobs.enqueued[0].job_type == "telegram.publish"
    assert succeeded_receipt.status == "succeeded"
    assert ambiguous_receipt.status == "pending"
```

- [ ] **Step 2: Run tests and verify failures**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_publish_service.py tests/test_telegram_reconciliation_api.py -q
```

- [ ] **Step 3: Implement commit-before-dispatch receipts and safe resumption**

`publish_telegram()` must lock `PublishJob`, return an existing Publication, verify the exact approved revision, revalidate its nonempty `TelegramEvidenceCitation` map, and recompute `sha256_canonical({"content": revision.content, "evidence_map": revision.evidence_map})` before accepting its stored hash. Then re-evaluate global/route/destination pause and health, render the plan, and upsert all `PublishOperationReceipt` rows. For each non-succeeded receipt: mark `dispatching` and increment attempt count in a committed transaction; resolve token by `Destination.secret_ref`; execute outside a transaction; then record success/classified failure in a new transaction. It must never re-send a succeeded or ambiguous receipt.

When all receipts succeed, create one Release 1 `Publication` with ordered remote IDs, permalink `https://t.me/{public_target_without_at}/{first_id}` when derivable, exact payload hash, UTC time, and `reconciliation_status="confirmed"`. Update publish/dispatch status and append a success event. Add `build_telegram_publish_handlers(client, secret_resolver)` and register its `telegram.destination.check` (Bot API `getChat`) and `telegram.publish` closures only when publishing dependencies are supplied to `build_default_registry()`.

- [ ] **Step 4: Implement explicit reconciliation only for ambiguous jobs**

Add `POST /telegram/publish-jobs/{publish_job_id}/reconcile` with input:

```python
class TelegramReconcileIn(BaseModel):
    outcome: Literal["published", "not_published"]
    remote_message_ids: list[int] = Field(default_factory=list)
    permalink: HttpUrl | None = None
```

`published` requires remote IDs, marks ambiguous receipts/operator-confirmed, and finalizes Publication. `not_published` resets only ambiguous receipts to pending and enqueues one publish job with key `telegram-publish-reconcile:{publish_job.id}:{publish_job.updated_at.isoformat()}`. Reject reconciliation for non-ambiguous jobs with 409. Never infer success by blindly retrying.

- [ ] **Step 5: Verify and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_telegram_publish_service.py tests/test_telegram_reconciliation_api.py \
  tests/test_job_handler_registry.py tests/test_job_worker.py tests/test_telegram_bot_client.py -q
.venv/bin/ruff check app/publishing/telegram/service.py app/publishing/telegram/handlers.py app/api/telegram_drafts.py
git add backend/app/publishing/telegram/service.py backend/app/publishing/telegram/handlers.py \
  backend/app/jobs/registry.py backend/app/api/telegram_drafts.py \
  backend/tests/test_telegram_publish_service.py backend/tests/test_telegram_reconciliation_api.py
git commit -m "feat: publish Telegram revisions idempotently"
```

---

### Task 10: Ship the operator-visible automation, review, publish, and outcome flow

**Files:**
- Create: `frontend/features/automations/telegram-types.ts`
- Create: `frontend/features/automations/telegram-api.ts`
- Create: `frontend/features/automations/route-builder.tsx`
- Create: `frontend/features/automations/route-list.tsx`
- Create: `frontend/features/automations/route-detail.tsx`
- Create: `frontend/features/drafts/telegram-draft-list.tsx`
- Create: `frontend/features/review/telegram-review-workspace.tsx`
- Create: `frontend/features/today/telegram-outcomes.tsx`
- Create: `frontend/features/settings/content-settings-page.tsx`
- Create: `frontend/app/automations/page.tsx`
- Create: `frontend/app/automations/new/page.tsx`
- Create: `frontend/app/automations/[routeId]/page.tsx`
- Create: `frontend/app/drafts/page.tsx`
- Create: `frontend/app/review/[revisionId]/page.tsx`
- Create: `frontend/app/settings/content/page.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/features/today/today-page.tsx`
- Modify: `frontend/lib/query-keys.ts`
- Modify: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Modify: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/tests/telegram-api.test.ts`
- Create: `frontend/tests/telegram-route-builder.test.tsx`
- Create: `frontend/tests/telegram-route-detail.test.tsx`
- Create: `frontend/tests/telegram-review-workspace.test.tsx`
- Create: `frontend/tests/content-settings-page.test.tsx`
- Modify: `frontend/tests/navigation.test.tsx`
- Create: `frontend/e2e/telegram-automation.spec.ts`

**Interfaces:**
- Consumes: Release 1 Newsroom shell, jobs/control/Today features, and Tasks 4/7/9 APIs.
- Produces: `Today -> Automation -> dry run -> Draft -> exact revision review -> approve -> publish -> outcome`, route pause/backfill, global pause visibility, and deterministic desktop/mobile E2E coverage.

- [ ] **Step 1: Write failing frontend API and builder tests**

`frontend/tests/telegram-api.test.ts` must assert snake/camel mapping and exact requests for automation options, source/destination/route create, activate, pause/resume, dry run, bounded backfill, drafts, edit, approve, publish, and reconcile. `telegram-route-builder.test.tsx` must assert it renders the safe provider/brand/prompt options without secret references, initial values `public_html`, `off`, `preserve`, `review_required`, and 300 seconds; auto mode reveals a confirmation checkbox and cannot submit without it; MTProto reveals exactly three environment-reference fields for API ID, API hash, and session, never credential-value inputs; successful submit creates source, destination, route, then activates it; errors remain visible and retain inputs.

`frontend/tests/content-settings-page.test.tsx` must prove the operator can create/update a brand, create a new immutable Telegram prompt version from custom instructions/templates, activate that exact version, configure an OpenRouter profile using only an environment-variable name, and inspect destination health. Assert no password/token input exists and returned settings never render secret-reference names.

- [ ] **Step 2: Write failing route-detail and review tests**

Assert route detail displays initializing/ready cursor, next poll, policy, access mode, destination health, pause/resume, dry run, bounded backfill count/date choice, dispatch history, and failure reason. Review tests must render source evidence and album beside an RTL editor, save edit as a new revision, require content-hash approval, disable publish before approval, show global-pause/dry-run/replace-media blockers, and show durable job status after every mutation.

- [ ] **Step 3: Add typed API modules and focused feature components**

Define discriminated types for the exact backend values, add query keys `telegramSources`, `telegramDestinations`, `telegramRoutes`, `telegramRoute(id)`, `telegramDispatches(id)`, `telegramDrafts(filters)`, `telegramDraft(id)`, and `telegramPublishJob(id)`, then implement the files in the map with TanStack Query. Mutations invalidate only affected route/draft/job/Today keys. Use live loading/error/empty states, semantic labels, `dir={revision.direction}`, focus management after dialogs, and no fabricated cursor, health, schedule, success, or publication values.

Build `/settings/content` with Brand, Prompt versions, AI providers, and Telegram destinations sections. Prompt version history is read-only; editing always submits a new version, and activation requires confirmation. Provider configuration explains that the actual key lives in `.env`, accepts only a validated environment name, and shows `Configured`/`Unavailable` from the API. Add the working settings link to desktop/mobile Newsroom navigation.

- [ ] **Step 4: Wire pages and write the complete mocked E2E flow**

In `frontend/e2e/telegram-automation.spec.ts`, intercept `/api/backend/telegram/**`, `/api/backend/jobs/**`, and `/api/backend/automation-control`; drive this exact flow at 1440x900 and 390x844:

```text
Settings -> create and activate a custom Telegram rewrite prompt
-> Automations -> New automation -> defaults visible -> select the custom prompt -> create and activate
-> route initializes at message 90 -> dry run message 91
-> Drafts shows pending revision -> Review opens source album + RTL editor
-> edit creates revision 2 -> approve revision 2 hash -> publish
-> Today shows published remote IDs 501/502 and permalink
-> route pause prevents run -> resume -> bounded backfill count 20 accepted
-> global pause changes auto route outcome to review_required
```

Assert no horizontal overflow and usable mobile navigation. Add a second E2E scenario where publish becomes `reconciliation_required`, automatic retry is absent, and operator-confirmed IDs resolve the card.

- [ ] **Step 5: Run frontend tests/type/build/E2E and commit UI**

```bash
cd frontend
npx vitest run tests/telegram-api.test.ts tests/telegram-route-builder.test.tsx \
  tests/telegram-route-detail.test.tsx tests/telegram-review-workspace.test.tsx tests/content-settings-page.test.tsx
npm run test
npm run typecheck
npm run build
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 npm run test:e2e -- telegram-automation.spec.ts
cd ..
git add frontend/features/automations/telegram-types.ts frontend/features/automations/telegram-api.ts \
  frontend/features/automations/route-builder.tsx frontend/features/automations/route-list.tsx \
  frontend/features/automations/route-detail.tsx frontend/features/drafts/telegram-draft-list.tsx \
  frontend/features/review/telegram-review-workspace.tsx frontend/features/today/telegram-outcomes.tsx \
  frontend/features/settings/content-settings-page.tsx frontend/app/automations/page.tsx \
  frontend/app/automations/new/page.tsx 'frontend/app/automations/[routeId]/page.tsx' \
  frontend/app/drafts/page.tsx 'frontend/app/review/[revisionId]/page.tsx' \
  frontend/app/settings/content/page.tsx frontend/app/page.tsx frontend/features/today/today-page.tsx \
  frontend/lib/query-keys.ts frontend/components/newsroom/newsroom-sidebar.tsx \
  frontend/components/newsroom/mobile-newsroom-nav.tsx frontend/tests/telegram-api.test.ts \
  frontend/tests/telegram-route-builder.test.tsx frontend/tests/telegram-route-detail.test.tsx \
  frontend/tests/telegram-review-workspace.test.tsx frontend/tests/content-settings-page.test.tsx \
  frontend/tests/navigation.test.tsx frontend/e2e/telegram-automation.spec.ts
git commit -m "feat: add Telegram automation newsroom flow"
```

---

### Task 11: Wire capability-separated runtime services and document the local dry run

**Files:**
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/tests/test_job_worker.py`
- Modify: `backend/tests/test_job_handler_registry.py`
- Modify: `backend/tests/test_runtime_heartbeat.py`
- Modify: `backend/tests/test_docker_config.py`

**Interfaces:**
- Consumes: Release 1 atomic `claim_next_job(allowed_job_types=...)`, `JobHandlerRegistry.job_types()`, `RuntimeHeartbeat`, worker/scheduler loops, and Tasks 5/7/9 dependency-injected registries.
- Produces: capability-separated workers whose atomic claim set is derived from the handlers actually registered, truthful multi-process heartbeats, safe Compose wiring, and one documented local review-first flow.

- [ ] **Step 1: Write failing capability, heartbeat, and Compose tests**

Extend worker/registry tests to prove each CLI capability constructs only its permitted dependency bundle; the publishing worker never constructs MTProto/OpenRouter dependencies; the source/generation worker never constructs a Bot API client or resolves a destination token; and `WorkerRunner` receives `allowed_job_types=registry.job_types()` on every claim. Assert there is no static claimed-job rejection/requeue path. Register a synthetic future handler such as `build_export` or `execute_retention` and prove it automatically appears in that worker's claim set without editing a job-type switch.

Extend heartbeat tests with two simultaneous worker component IDs and assert each heartbeat reports the exact CLI capabilities and registry-derived job types at the supplied fake `observed_at`; scheduler reports its own component ID/type and no secret-bearing metadata. Extend Docker tests to assert the exact commands/component IDs below, capability-specific environment names, shared media volume, localhost-only ports, and absence of literal secret values from committed YAML.

- [ ] **Step 2: Wire secrets and long-running services, then document the flow**

Add environment names, never values:

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
TELEGRAM_SOURCE_EDITOR_API_ID=
TELEGRAM_SOURCE_EDITOR_API_HASH=
TELEGRAM_SOURCE_EDITOR_SESSION=
TELEGRAM_DESTINATION_NEWS_TOKEN=
TELEGRAM_MEDIA_STAGING_ROOT=/data/media-staging
```

Extend the Release 1 worker CLI with repeatable `--capability` choices `ingestion`, `source`, `generation`, and `publishing`; the worker constructs only the dependency bundles needed by its selected capabilities and passes them to `build_default_registry()`. A source/generation worker must never resolve destination tokens, and a publishing worker must never resolve MTProto or OpenRouter credentials. Derive `allowed_job_types` from that finished registry's `job_types()` and pass it to Release 1's atomic claim; an unsupported job remains queued because it is excluded before `FOR UPDATE SKIP LOCKED`, never because a worker claims and rejects/requeues it. This registry-derived contract automatically covers future registered handlers such as `build_export` and `execute_retention`. Compose uses these exact commands and stable component IDs:

```yaml
worker-source-generation:
  command: python -m app.jobs.worker --capability ingestion --capability source --capability generation
  environment:
    NEWSCRAFT_COMPONENT_ID: worker-source-generation
worker-publishing:
  command: python -m app.jobs.worker --capability publishing
  environment:
    NEWSCRAFT_COMPONENT_ID: worker-publishing
scheduler:
  command: python -m app.jobs.scheduler
  environment:
    NEWSCRAFT_COMPONENT_ID: scheduler
```

Pass only OpenRouter plus all three source credential variables (API ID, API hash, session) to `worker-source-generation`, and only destination token variables to `worker-publishing`; scheduler receives no AI or Telegram secret. Worker/scheduler loops upsert the Release 1 `RuntimeHeartbeat` with `component_id=NEWSCRAFT_COMPONENT_ID`, semantic CLI capabilities, registry-derived job types in metadata, and the loop's supplied current time. Add shared media/staging volumes, preserve localhost-only ports, and document: configure references in UI, run destination check, activate the gap-free new-only route, run a fake-provider dry run, review, and use opt-in real credentials.

- [ ] **Step 3: Run the Release 2 exit gate**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
PYTHONPATH=. .venv/bin/alembic upgrade head --sql >/tmp/newscraft-release2-upgrade.sql
cd ../frontend
npm run test
npm run typecheck
npm run build
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 npm run test:e2e
cd ..
docker compose config >/tmp/newscraft-release2-compose.yml
git diff --check
git status --short
```

Expected: every deterministic backend/frontend/browser gate passes; migration head is `0006_telegram_automation_vertical`; Compose renders; no token/session/downloaded-media path is staged; only intentionally untracked user artifacts remain.

- [ ] **Step 4: Commit runtime/docs and record the release boundary**

```bash
git add .env.example docker-compose.yml README.md backend/app/jobs/worker.py backend/app/jobs/registry.py \
  backend/tests/test_job_worker.py backend/tests/test_job_handler_registry.py \
  backend/tests/test_runtime_heartbeat.py backend/tests/test_docker_config.py
git commit -m "chore: run the Telegram automation vertical locally"
git log --oneline --decorate -12
git status --short
```

Do not run a credentialed smoke test or push. Hand off the clean deterministic evidence and list the opt-in live dry-run command separately.

## Release 2 Acceptance Checklist

- [ ] Route activation records a timestamp/ID boundary, captures every complete message strictly newer than it (including arrivals before the first poll), and never treats a post-boundary message as baseline history.
- [ ] Once the activation predecessor is proven it becomes both `activation_message_id` and initial `last_message_id`; catch-up never fetches with a null cursor.
- [ ] Live polls capture IDs above the cursor atomically and inspect a bounded recent window for changed source fingerprints.
- [ ] Initial Telegram capture creates `Story(status="telegram_provisional")`, revision 1 by `telegram_capture`, and an exact StoryEvidenceLink; source edits create linked `telegram_source_edit` child revisions.
- [ ] A source edit creates new evidence, StoryRevision, generation attempt, and pending-review child platform revision; it never mutates an approved revision or remotely edits Telegram.
- [ ] Backfill is count- or date-bounded, max 100/30 days, and does not move the live cursor.
- [ ] Public HTML and MTProto source adapters normalize text, edit metadata, entities, albums, and media without exposing credentials.
- [ ] MTProto resolves the selected source's complete API-ID/API-hash/session reference bundle and persists none of the values.
- [ ] `preserve` downloads and re-uploads ordered media; `omit` drops it; `replace_manually` forces review.
- [ ] Content filters, quiet hours, and retry policy have typed deterministic evaluators and are enforced without delaying capture/cursor durability.
- [ ] The selected executable provider profile, exact immutable prompt version, generation attempt, and parent revision are recorded; OpenRouter output is schema/HTML/platform validated.
- [ ] OpenRouter profiles round-trip safe HTTP, optional pricing, and `research_budgets.standard/deep` settings; Release 2 generation consumes only its HTTP/model subset.
- [ ] Review is default; auto mode is explicit and fails closed on pause, dry run, validation, media, destination, or health failures.
- [ ] Revisions use only `draft`, `pending_review`, `approved`, and `rejected`; manual editing creates a pending-review child, and approval/publishing bind to the exact content hash.
- [ ] Generated Telegram revisions have globally monotonic per-variant numbers, route-specific parents, nonempty validated evidence maps, and hashes over both content and evidence; manual edits copy/revalidate that map.
- [ ] The shared Telegram content/renderer schema permits `source_item_id=null`, while route captures persist their truthful non-null source item.
- [ ] Dry run can generate a real draft but cannot create a publication.
- [ ] Deterministic publish operations and receipts prevent successful operations from being repeated.
- [ ] Rate limits retry at Telegram's delay; ambiguous outcomes require reconciliation and never blind retry.
- [ ] Publication records destination, exact revision, payload hash, ordered remote IDs, time, permalink, and reconciliation state.
- [ ] Today, Automations, Drafts, Review, Jobs, and global controls expose every durable outcome at desktop/mobile widths and for RTL content.
- [ ] Workers atomically claim only `registry.job_types()`, and durable multi-worker/scheduler heartbeats report truthful component IDs, capabilities, and observed times.
- [ ] Default tests require no OpenRouter/Telegram credentials and no live external publishing.
