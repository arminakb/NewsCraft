# Release 5 Operational Hardening and Product Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the completed local content platform usable on mobile and in Persian, observable and recoverable under failure, safe around secrets and retained data, restorable from a verified backup, and proven by full acceptance tests.

**Architecture:** Operational truth is derived from durable jobs/events/attempts/publications and surfaced through diagnostics, history, and reconciliation resources. Cleanup and backup are explicit operator workflows with dry-run/verification boundaries; crash and fault injection tests exercise leases, idempotency, ambiguous publishing, and restart recovery without adding a distributed system.

**Tech Stack:** Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, pytest, Docker Compose, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright, axe-core.

## Global Constraints

- Releases 0–4 are complete and their full gates pass before this plan begins.
- Product mode remains local, single operator, and bound to `127.0.0.1` by default.
- PostgreSQL remains the queue and source of truth; no Redis, Celery, Kafka, Kubernetes, or microservice split is added.
- The UI never fabricates worker, scheduler, source, provider, destination, route, job, publication, backup, or retention health.
- Persian content uses explicit `dir="rtl"` boundaries. Application chrome remains navigable LTR; mixed content uses `dir="auto"` where direction is not stored.
- Every interactive function is keyboard reachable, has a visible focus state and accessible name, and works at 390×844 and 1440×1000 viewports.
- Ambiguous Telegram timeouts never blind-retry. An operator must reconcile the exact Release 2 `PublishOperationReceipt` set for one `publish_job_id` before retry can be scheduled.
- Retention never automatically deletes stories, evidence snapshots referenced by a revision, prompt versions, revisions, approvals, publication receipts, or audit events tied to a retained publication.
- Backup archives contain the database, media, export metadata, schema/version manifest, and checksums; secret files and environment values are excluded.
- Restore is destructive only after archive verification and an explicit `--confirm-replace` flag.
- Secret redaction applies recursively before logs, events, job errors, attempt metadata, diagnostics, or API responses are persisted or emitted.
- Failure injection is unavailable in normal runtime and may activate only when `APP_ENV=test`.
- Credentialed Telegram/OpenRouter/Codex smoke tests remain opt-in; deterministic acceptance uses fakes.
- Every task is test-first and ends in a focused commit; do not stage backups, test output, local media, credentials, `.superpowers/`, or unrelated files.

## Dependencies and Exclusions

This release consumes Release 1 jobs, events, pause controls, scheduler/worker loops, and the existing `RuntimeHeartbeat`/`RuntimeHeartbeatService`; Release 2 split worker services with stable `NEWSCRAFT_COMPONENT_ID` values plus Telegram `PublishOperationReceipt`/publication/reconciliation state; Release 3 research/generation attempts and exact revisions; Release 4 persistent exports/manual plans/calendar. Task 2 hardens and projects the existing heartbeat records without adding another table, model, writer, or emission loop. It does not add multi-user auth, live Instagram/X/blog publishing, remote Telegram message edits, cloud backup, distributed workers, or product analytics.

Run before Task 1:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
cd ../frontend
npm run test
npm run typecheck
npm run build
cd ..
docker compose config >/tmp/newscraft-release5-start.yml
git status --short
```

Expected: all gates pass and no unfinished Release 4 file is present.

## File and Responsibility Map

### Backend and operations

- `app/operations/diagnostics.py`: derived component health and attention summary.
- `app/jobs/models.py` and `app/jobs/runtime.py`: existing Release 1 `RuntimeHeartbeat` and `RuntimeHeartbeatService`, consumed unchanged as operational truth.
- `app/operations/history.py`: cursor-paginated route/story/job timeline projection.
- `app/publishing/telegram/service.py`: existing Release 2 receipt-based reconciliation, reused and hardened without a second state machine.
- `app/retention/models.py`: policy/run/candidate contracts.
- `app/retention/service.py`: preview, confirm, execute, and protected-reference rules.
- `app/retention/handlers.py`: durable retention job.
- `app/core/redaction.py`: recursive secret detection and sanitization.
- `app/core/faults.py`: no-op production boundary and test-only scripted faults.
- `app/api/operations.py`: diagnostics/history/retention APIs.
- `app/api/telegram_drafts.py`: Release 2 Telegram reconciliation API extensions.
- `scripts/backup_restore.py`: create, verify, and explicitly restore local archives.
- `scripts/smoke.py`: deterministic local acceptance driver.

### Frontend

- `components/newsroom/mobile-newsroom-nav.tsx`: keyboard-accessible responsive navigation established in Release 1.
- `components/newsroom/direction-boundary.tsx`: explicit content direction.
- `features/operations/diagnostics-dashboard.tsx`: truthful runtime health/attention.
- `features/operations/history-timeline.tsx`: route/job/attempt/publication history.
- `features/operations/reconciliation-panel.tsx`: ambiguous Telegram resolution.
- `features/settings/retention-settings.tsx`: preview-before-delete retention controls.
- `app/diagnostics/page.tsx`, `app/automations/[routeId]/history/page.tsx`, and `app/settings/retention/page.tsx`: operator routes.

---

### Task 1: Complete responsive navigation, RTL boundaries, and accessibility gates

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/app/layout.tsx`
- Modify: `frontend/app/globals.css`
- Modify: `frontend/components/newsroom/newsroom-shell.tsx`
- Modify: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Modify: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/components/newsroom/direction-boundary.tsx`
- Create: `frontend/tests/mobile-nav.test.tsx`
- Create: `frontend/tests/direction-boundary.test.tsx`
- Create: `frontend/e2e/accessibility.spec.ts`

**Interfaces:**
- Consumes: all Newsroom routes from Releases 1–4.
- Produces: skip link, responsive drawer, focus restoration, content direction boundary, reduced-motion behavior, and automated axe checks.

- [ ] **Step 1: Add axe dependency and write failing component tests**

Add:

```json
"@axe-core/playwright": "latest"
```

Write:

```tsx
it("opens mobile navigation, traps focus, closes on Escape, and restores the trigger", async () => {
  render(<MobileNav items={navItems} />)
  const trigger = screen.getByRole("button", { name: "Open navigation" })
  await userEvent.click(trigger)
  expect(screen.getByRole("dialog", { name: "Newsroom navigation" })).toBeInTheDocument()
  await userEvent.keyboard("{Escape}")
  expect(screen.queryByRole("dialog", { name: "Newsroom navigation" })).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
})

it.each([
  ["fa", "rtl", "گزارش امروز"],
  ["en", "ltr", "Today report"],
  [null, "auto", "2026 — گزارش AI"],
])("uses stored language direction without changing app chrome", (language, direction, text) => {
  render(<DirectionBoundary language={language}>{text}</DirectionBoundary>)
  expect(screen.getByTestId("direction-boundary")).toHaveAttribute("dir", direction)
  expect(document.documentElement).toHaveAttribute("dir", "ltr")
})
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npm install
npx vitest run tests/mobile-nav.test.tsx tests/direction-boundary.test.tsx
```

Expected: import failures for the new components.

- [ ] **Step 3: Implement shell accessibility and direction contracts**

`layout.tsx` sets `<html lang="en" dir="ltr">`, adds `<a className="skip-link" href="#main-content">Skip to content</a>`, and the shell renders `<main id="main-content" tabIndex={-1}>`. Desktop navigation is hidden below 900px; mobile trigger is shown below 900px. The drawer uses a real dialog, focus trap, Escape/backdrop close, current-page `aria-current="page"`, and trigger focus restoration.

```tsx
export function DirectionBoundary({ language, children }: { language: string | null; children: React.ReactNode }) {
  const dir = language === "fa" || language === "ar" ? "rtl" : language ? "ltr" : "auto"
  return <div data-testid="direction-boundary" lang={language ?? undefined} dir={dir}>{children}</div>
}
```

Add visible `:focus-visible`, 44×44 minimum pointer targets for primary mobile actions, horizontal overflow containment, and `prefers-reduced-motion: reduce` rules. Apply `DirectionBoundary` to source evidence, editors, previews, story copy, and publication copy; do not flip numeric metadata or global navigation.

- [ ] **Step 4: Add axe desktop/mobile tests**

```ts
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  for (const path of ["/", "/inbox", "/automations", "/drafts", "/calendar", "/diagnostics"]) {
    test(`${path} has no serious axe violations at ${viewport.width}`, async ({ page }) => {
      await page.setViewportSize(viewport)
      await page.goto(path)
      const results = await new AxeBuilder({ page }).analyze()
      expect(results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""))).toEqual([])
    })
  }
}
```

- [ ] **Step 5: Run gates and commit**

```bash
cd frontend
npm run test
npm run typecheck
npm run build
npx playwright test e2e/accessibility.spec.ts --project=chromium
git diff --check
cd ..
git add frontend/package.json frontend/package-lock.json frontend/app/layout.tsx frontend/app/globals.css frontend/components/newsroom frontend/tests/mobile-nav.test.tsx frontend/tests/direction-boundary.test.tsx frontend/e2e/accessibility.spec.ts
git commit -m "feat: complete mobile RTL and accessibility behavior"
```

Expected: unit, type, build, and axe tests pass at both viewports.

---

### Task 2: Derive truthful diagnostics and cursor-paginated history

**Files:**
- Create: `backend/app/operations/__init__.py`
- Create: `backend/app/operations/diagnostics.py`
- Create: `backend/app/operations/history.py`
- Create: `backend/app/api/operations.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/operations/test_diagnostics.py`
- Create: `backend/tests/operations/test_history.py`
- Create: `backend/tests/api/test_operations_routes.py`
- Modify: `backend/tests/test_docker_config.py`

**Interfaces:**
- Consumes: Release 1 `RuntimeHeartbeat(component_id, component_type, capabilities, observed_at, runtime_metadata)` and `RuntimeHeartbeatService.list_recent()`, Release 2 `NEWSCRAFT_COMPONENT_ID` service identities, durable source health, schedules, routes, provider/destination health, jobs, attempts, events, publications, and manual plans.
- Produces: read-only `OperationsSnapshot`, `AttentionItem`, `HistoryEntry`, `GET /operations/diagnostics`, and `GET /operations/history` projections over existing durable records. It produces no heartbeat schema, writer, migration, or runtime loop.

- [ ] **Step 1: Write failing truth and pagination tests**

```python
async def test_diagnostics_derives_degraded_and_down_states_from_persisted_times(db_session, frozen_clock):
    heartbeats = RuntimeHeartbeatService(db_session)
    source_observed_at = frozen_clock.now() - timedelta(seconds=35)
    publishing_observed_at = frozen_clock.now() - timedelta(seconds=10)
    scheduler_observed_at = frozen_clock.now() - timedelta(seconds=130)
    await heartbeats.record(
        component_id="worker-source-generation",
        component_type="worker",
        capabilities=("ingestion", "source", "generation"),
        observed_at=source_observed_at,
        metadata={"job_types": ["ingest.collect", "build_export"]},
    )
    await heartbeats.record(
        component_id="worker-publishing",
        component_type="worker",
        capabilities=("publishing",),
        observed_at=publishing_observed_at,
        metadata={"job_types": ["telegram.publish"]},
    )
    await heartbeats.record(
        component_id="scheduler",
        component_type="scheduler",
        capabilities=("scheduling",),
        observed_at=scheduler_observed_at,
        metadata={},
    )
    snapshot = await OperationsDiagnostics(db_session, clock=frozen_clock).snapshot()
    assert snapshot.components["worker-source-generation"].status == "degraded"
    assert snapshot.components["worker-publishing"].status == "healthy"
    assert snapshot.components["scheduler"].status == "down"
    assert snapshot.components["worker-source-generation"].observed_at == source_observed_at
    assert snapshot.components["worker-publishing"].observed_at == publishing_observed_at
    assert snapshot.components["scheduler"].observed_at == scheduler_observed_at


async def test_history_cursor_is_stable_when_new_events_arrive(db_session):
    first = await HistoryService(db_session).list(subject_type="automation_route", subject_id=ROUTE_ID, limit=2, cursor=None)
    await add_event(db_session, occurred_at=datetime(2026, 7, 11, 12, tzinfo=UTC))
    second = await HistoryService(db_session).list(subject_type="automation_route", subject_id=ROUTE_ID, limit=2, cursor=first.next_cursor)
    assert set(item.id for item in first.items).isdisjoint(item.id for item in second.items)


def test_expected_runtime_components_match_release_two_compose_identities():
    assert Settings().expected_runtime_component_ids == "worker-source-generation,worker-publishing,scheduler"
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["worker-source-generation"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == "worker-source-generation"
    assert compose["services"]["worker-publishing"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == "worker-publishing"
    assert compose["services"]["scheduler"]["environment"]["NEWSCRAFT_COMPONENT_ID"] == "scheduler"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/operations tests/api/test_operations_routes.py \
  tests/test_runtime_heartbeat.py tests/test_docker_config.py -q
```

Expected: operations projection/config assertions fail while the existing Release 1/2 heartbeat and Compose tests continue to pass.

- [ ] **Step 3: Project the existing heartbeat contract without another persistence path**

Add `expected_runtime_component_ids: str = "worker-source-generation,worker-publishing,scheduler"` to settings. Diagnostics splits, strips, and deduplicates this list so a required component that has never emitted a row is represented as `unknown`; it does not infer required identities from currently running jobs.

`OperationsDiagnostics` reads all rows through the existing Release 1 `RuntimeHeartbeatService.list_recent()` contract. Each row retains its existing text primary key `component_id`, `component_type`, sorted capabilities, exact persisted `observed_at`, and already-redacted `runtime_metadata`. Do not add a second operations heartbeat persistence module, ORM mapping, migration, upsert service, or worker/scheduler emission change. Release 2 already assigns `NEWSCRAFT_COMPONENT_ID=worker-source-generation`, `worker-publishing`, and `scheduler` and already records semantic capabilities/job types; Release 5 only verifies that wiring in `test_docker_config.py`.

- [ ] **Step 4: Implement exact diagnostics contracts**

```python
class ComponentHealth(BaseModel):
    status: Literal["healthy", "degraded", "down", "unknown"]
    observed_at: datetime | None
    last_success_at: datetime | None
    message: str
    action_url: str | None


class AttentionItem(BaseModel):
    id: str
    severity: Literal["warning", "error"]
    kind: Literal["job", "route", "research", "generation", "publication", "destination", "source"]
    title: str
    occurred_at: datetime
    action_url: str


class OperationsSnapshot(BaseModel):
    generated_at: datetime
    global_paused: bool
    dry_run: bool
    components: dict[str, ComponentHealth]
    queue_counts: dict[str, int]
    attention: list[AttentionItem]
```

Each existing `RuntimeHeartbeat` row becomes its own component keyed by `component_id`; never collapse both workers into one synthetic `worker`. Return the union of configured expected IDs and persisted component IDs so additional local instances remain visible. Worker/scheduler components are healthy through 30 seconds, degraded through 90 seconds, down beyond 90 seconds, and unknown only when an expected component ID has no row. `observed_at` is exactly the persisted heartbeat timestamp and is never replaced with request time; `generated_at` owns the request clock. Do not expose raw `runtime_metadata` in the summary. Provider/destination health uses persisted health-check attempts only; no check runs in GET. Queue counts and attention are database queries ordered by persisted timestamps.

- [ ] **Step 5: Implement history contracts and routes**

```python
class HistoryEntry(BaseModel):
    id: str
    occurred_at: datetime
    category: Literal["collection", "research", "generation", "edit", "approval", "schedule", "publish", "retry", "pause", "cancel", "reconcile"]
    status: str
    title: str
    summary: str
    job_id: UUID | None
    subject_url: str
    sanitized_metadata: dict[str, object]
```

Cursor encodes `(occurred_at, id)` and queries descending with both values. API allows `subject_type`, `subject_id`, `category`, `status`, `limit<=100`, and cursor. Metadata passes through redaction before response. Diagnostics/history routes perform read-only queries and never trigger health checks or retries.

- [ ] **Step 6: Run projection and existing-heartbeat regression tests, then commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/operations tests/api/test_operations_routes.py \
  tests/test_runtime_heartbeat.py tests/test_docker_config.py -q
.venv/bin/ruff check app/operations app/api/operations.py tests/operations tests/api/test_operations_routes.py
git diff --check
cd ..
git add backend/app/operations backend/app/api/operations.py backend/app/core/config.py \
  backend/app/api/routes.py backend/tests/operations backend/tests/api/test_operations_routes.py \
  backend/tests/test_docker_config.py
git commit -m "feat: expose truthful diagnostics and history"
```

Expected: diagnostics, history, API, existing heartbeat, and Compose identity tests pass with no schema/runtime-emitter changes.

---

### Task 3: Harden the existing Release 2 receipt-based Telegram reconciliation flow

**Files:**
- Modify: `backend/app/publishing/telegram/service.py`
- Modify: `backend/app/api/telegram_drafts.py`
- Modify: `backend/app/operations/history.py`
- Modify: `backend/tests/test_telegram_publish_service.py`
- Modify: `backend/tests/test_telegram_reconciliation_api.py`

**Interfaces:**
- Consumes: Release 2 `PublishOperationReceipt`, `PublishJob`, `Publication`, `publish_telegram()`, and `POST /telegram/publish-jobs/{publish_job_id}/reconcile`.
- Produces: read-only `ReconciliationCase` projections keyed by `publish_job_id`, hardened replay/audit behavior, and GET list/detail endpoints while preserving the existing POST decision endpoint and receipt state machine.

- [ ] **Step 1: Write failing receipt-based state and API tests**

```python
async def test_ambiguous_receipts_block_publish_replay_until_existing_endpoint_reconciles(client, ambiguous_publish_job):
    assert {receipt.status for receipt in ambiguous_publish_job.receipts} == {"succeeded", "ambiguous"}
    replay = await run_publish_job(ambiguous_publish_job.id)
    assert replay.status == "needs_review"
    assert telegram_send_count() == 0


async def test_existing_reconcile_post_confirms_exact_publish_job_receipts(client, ambiguous_publish_job):
    response = await client.post(
        f"/telegram/publish-jobs/{ambiguous_publish_job.id}/reconcile",
        json={
            "outcome": "published",
            "remote_message_ids": [701, 702],
            "permalink": "https://t.me/target/701",
            "operator_note": "Verified in the destination channel",
        },
    )
    assert response.status_code == 200
    assert response.json()["reconciliation_status"] == "confirmed"
    event = await latest_reconciliation_event()
    assert event.event_data["publish_job_id"] == str(ambiguous_publish_job.id)
    assert event.event_data["operation_keys"] == [receipt.operation_key for receipt in ambiguous_publish_job.receipts]


async def test_existing_reconcile_post_not_published_resets_only_ambiguous_receipts_once(client, ambiguous_publish_job):
    first = await client.post(
        f"/telegram/publish-jobs/{ambiguous_publish_job.id}/reconcile",
        json={"outcome": "not_published", "operator_note": "Checked the destination channel"},
    )
    second = await client.post(
        f"/telegram/publish-jobs/{ambiguous_publish_job.id}/reconcile",
        json={"outcome": "not_published", "operator_note": "Checked the destination channel"},
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["job"]["job_id"] == second.json()["job"]["job_id"]
    assert succeeded_receipt().status == "succeeded"
    assert ambiguous_receipt().status == "pending"
```

Add GET projection tests for `GET /telegram/reconciliation` and `GET /telegram/reconciliation/{publish_job_id}`. Assert cases are keyed by publish job, include ordered sanitized operation receipt summaries/request hashes/destination/send timestamps/ambiguity reason, and never expose `sanitized_payload`, token references, headers, or response bodies.

- [ ] **Step 2: Run tests and verify the hardening cases fail**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_publish_service.py tests/test_telegram_reconciliation_api.py -q
```

Expected: projection/operator-note/replay-audit assertions fail against the Release 2 baseline; the existing POST route remains present.

- [ ] **Step 3: Extend the existing receipt state machine without adding another service**

Keep `TelegramReconcileIn.outcome`, `remote_message_ids`, and `permalink`; add backward-compatible `operator_note: str | None = Field(default=None, min_length=5, max_length=1_000)`. Implement list/detail projection helpers in `backend/app/publishing/telegram/service.py` over `PublishJob` plus ordered `PublishOperationReceipt` rows. Do not create `app/publishing/telegram/reconciliation.py`, `ReconciliationService`, `ReconciliationDecision`, new attempt rows, or a second POST route family.

The existing `POST /telegram/publish-jobs/{publish_job_id}/reconcile` remains authoritative. `published` requires remote IDs, marks only ambiguous receipts as operator-confirmed, creates/reuses the Release 2 `Publication`, and records publish job ID plus operation keys. `not_published` resets only ambiguous receipts to pending and reuses Release 2 deterministic reconcile job behavior. Exact decision replay returns the existing result; a conflicting second decision is HTTP 409. Both outcomes append redacted immutable history keyed by `publish_job_id`.

- [ ] **Step 4: Add read-only case routes and run tests**

```text
GET  /telegram/reconciliation
GET  /telegram/reconciliation/{publish_job_id}
POST /telegram/publish-jobs/{publish_job_id}/reconcile
```

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_telegram_publish_service.py tests/test_telegram_reconciliation_api.py tests/test_telegram_draft_api.py -q
.venv/bin/ruff check app/publishing/telegram/service.py app/api/telegram_drafts.py app/operations/history.py tests/test_telegram_reconciliation_api.py
git diff --check
cd ..
git add backend/app/publishing/telegram/service.py backend/app/api/telegram_drafts.py \
  backend/app/operations/history.py backend/tests/test_telegram_publish_service.py \
  backend/tests/test_telegram_reconciliation_api.py
git commit -m "feat: harden Telegram receipt reconciliation"
```

Expected: existing Release 2 publication/reconciliation tests plus new receipt projections/replay/audit cases pass, with no `PublishAttempt` dependency or duplicate decision service.

---

### Task 4: Add retention preview, protected-reference pruning, and audit records

**Files:**
- Create: `backend/alembic/versions/0008_operational_retention.py`
- Modify: `backend/app/db/model_registry.py`
- Create: `backend/app/retention/__init__.py`
- Create: `backend/app/retention/models.py`
- Create: `backend/app/retention/service.py`
- Create: `backend/app/retention/handlers.py`
- Modify: `backend/app/api/operations.py`
- Modify: `backend/app/jobs/registry.py`
- Create: `backend/tests/retention/test_service.py`
- Create: `backend/tests/retention/test_handlers.py`
- Create: `backend/tests/test_retention_migration.py`

**Interfaces:**
- Consumes: raw payloads, workflow jobs/events, attempt metadata, exports, media, evidence/revision/publication references, and job queue.
- Produces: Alembic head `0008_operational_retention`, `RetentionPolicy`, `RetentionPreview`, `RetentionRun`, job type `execute_retention`, generation-capability/source-worker registration, and retention APIs.

- [ ] **Step 1: Write failing safety tests**

```python
async def test_preview_never_selects_evidence_or_media_referenced_by_revision_or_publication(db_session, retention_fixture):
    preview = await RetentionService(db_session).preview(retention_fixture.policy)
    protected = {retention_fixture.evidence.id, retention_fixture.published_media.id}
    assert protected.isdisjoint({candidate.record_id for candidate in preview.candidates})


async def test_execution_requires_matching_preview_token(db_session, retention_fixture):
    preview = await RetentionService(db_session).preview(retention_fixture.policy)
    with pytest.raises(RetentionConflict, match="preview token does not match"):
        await RetentionService(db_session).enqueue(preview_token="wrong", confirmation="DELETE PREVIEWED DATA")


async def test_retention_replay_is_idempotent(run_job, confirmed_retention):
    first = await run_job(confirmed_retention.job_id)
    second = await run_job(confirmed_retention.job_id)
    assert first.deleted_counts == second.deleted_counts


def test_retention_job_is_claimable_only_by_source_generation_registry():
    source_generation = build_default_registry(capabilities={"ingestion", "source", "generation"})
    publishing = build_default_registry(capabilities={"publishing"})
    assert "execute_retention" in source_generation.job_types()
    assert "execute_retention" not in publishing.job_types()


def test_retention_migration_follows_manual_publication_head():
    migration = Path("alembic/versions/0008_operational_retention.py").read_text(encoding="utf-8")
    assert 'revision = "0008_operational_retention"' in migration
    assert 'down_revision = "0007_manual_publication_plans"' in migration
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/retention tests/test_retention_migration.py -q
```

Expected: missing migration/module failures.

- [ ] **Step 3: Create exact policy and preview contracts**

Migration `0008_operational_retention` revises `0007_manual_publication_plans` and creates `retention_policies` and `retention_runs`. Default policy:

```python
class RetentionPolicyInput(BaseModel):
    raw_payload_days: int = Field(default=30, ge=7, le=3650)
    completed_job_days: int = Field(default=90, ge=14, le=3650)
    attempt_metadata_days: int = Field(default=90, ge=14, le=3650)
    export_artifact_days: int = Field(default=14, ge=1, le=3650)
    unreferenced_media_days: int = Field(default=30, ge=7, le=3650)
```

Preview returns category counts, bytes when known, oldest/newest timestamps, stable candidate IDs, and `preview_token = sha256(policy_json + sorted_candidate_ids + database_revision)`. It never selects failed/needs-review/running jobs, events linked to retained publications, any evidence, any revision/prompt/approval/publication, or referenced media. Execution requires the exact string `DELETE PREVIEWED DATA`, revalidates candidates in one transaction, skips newly referenced records, deletes filesystem artifacts only after database marking, and records counts/errors in `RetentionRun`.

- [ ] **Step 4: Add retention APIs and job registration**

```text
GET  /operations/retention-policy
PUT  /operations/retention-policy
POST /operations/retention-preview
POST /operations/retention-runs       -> 202 JobAcceptedOut
GET  /operations/retention-runs
GET  /operations/retention-runs/{id}
```

Use idempotency `retention:{preview_token}` and global pause sensitivity. Never accept arbitrary paths or record IDs from the client; execution loads the server preview snapshot.

Register `execute_retention` only in the source-generation handler bundle under existing capability `generation`. Assert it appears in that registry's `job_types()`/atomic claim allowlist and is absent from the publishing-only registry. The handler receives the server-side preview token, uses `settings.export_root` for eligible export cleanup, and never accepts a filesystem root from its job payload.

- [ ] **Step 5: Run migration/tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/retention tests/test_retention_migration.py tests/test_job_handler_registry.py tests/test_job_worker.py tests/postgres/test_job_repository.py -q
.venv/bin/ruff check app/retention app/api/operations.py tests/retention
git diff --check
cd ..
docker compose --profile test rm -sf postgres-test
docker compose --profile test up -d --wait postgres-test
cd backend
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic downgrade 0007_manual_publication_plans
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
cd ..
git add backend/alembic/versions/0008_operational_retention.py backend/app/db/model_registry.py backend/app/retention backend/app/api/operations.py backend/app/jobs/registry.py backend/tests/retention backend/tests/test_retention_migration.py
git commit -m "feat: add safe retention controls"
```

Expected: migration round trip, retention, and job tests pass.

---

### Task 5: Redact secrets recursively at every persistence and logging boundary

**Files:**
- Modify: `backend/app/core/redaction.py`
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/jobs/repository.py`
- Modify: `backend/app/generation/providers/openrouter.py`
- Modify: `backend/app/research/codex_adapter.py`
- Modify: `backend/app/publishing/telegram/client.py`
- Modify: `backend/app/operations/diagnostics.py`
- Create: `backend/tests/core/test_redaction.py`
- Create: `backend/tests/core/test_secret_boundary.py`

**Interfaces:**
- Consumes: the shared Release 2 `redact_secrets()`/`redact_url()` implementation plus errors, headers, URLs, nested event/attempt/job metadata, and log fields.
- Produces: hardened cycle/depth/size handling and one mandatory sanitization boundary before every persistence/emission path.

- [ ] **Step 1: Write failing recursive and integration tests**

```python
def test_recursive_redaction_handles_keys_values_headers_urls_and_cycles():
    value = {
        "Authorization": "Bearer abc",
        "nested": [{"bot_token": "123:secret", "url": "https://user:pass@example.com/?api_key=secret"}],
        "safe_key": "prefix explicit-canary suffix",
    }
    value["cycle"] = value
    redacted = redact_secrets(value, secrets=("explicit-canary",))
    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"][0]["bot_token"] == "[REDACTED]"
    assert "secret" not in json.dumps(redacted)
    assert "explicit-canary" not in json.dumps(redacted)
    assert redacted["cycle"] == "[CYCLE]"


async def test_job_provider_and_publish_failures_persist_no_canary_secrets(app_harness, caplog):
    canaries = ["telegram-canary", "openrouter-canary", "cookie-canary", "db-canary"]
    await app_harness.fail_every_external_boundary(canaries)
    persisted = await app_harness.dump_jobs_events_attempts_and_diagnostics()
    combined = json.dumps(persisted) + caplog.text
    assert all(canary not in combined for canary in canaries)
    assert "[REDACTED]" in combined
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/core/test_redaction.py tests/core/test_secret_boundary.py -q
```

Expected: at least one canary/boundary assertion fails before all later-release persistence and logging paths use the shared redactor.

- [ ] **Step 3: Implement one recursive sanitizer**

```python
SECRET_KEY_PATTERN = re.compile(r"(?i)(authorization|cookie|token|secret|password|api[_-]?key|session|credential|database_url)")
BEARER_PATTERN = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
TELEGRAM_TOKEN_PATTERN = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b")


def redact_secrets(
    value: object,
    *,
    secrets: Collection[str] = (),
    seen: set[int] | None = None,
    depth: int = 0,
) -> object:
    active = seen if seen is not None else set()
    if depth > 20:
        return "[MAX_DEPTH]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, str):
        return redact_string(value, secrets=secrets)
    identity = id(value)
    if identity in active:
        return "[CYCLE]"
    active.add(identity)
    try:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        elif dataclasses.is_dataclass(value):
            value = {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        if isinstance(value, Mapping):
            result: dict[str, object] = {}
            for key, nested in list(value.items())[:500]:
                name = str(key)
                result[name] = "[REDACTED]" if SECRET_KEY_PATTERN.search(name) else redact_secrets(
                    nested, secrets=secrets, seen=active, depth=depth + 1
                )
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            return [
                redact_secrets(item, secrets=secrets, seen=active, depth=depth + 1)
                for item in list(value)[:1_000]
            ]
        return f"[{type(value).__name__}]"
    finally:
        active.remove(identity)
```

The public signature remains backward compatible with Release 2 exactly: `redact_secrets(value, *, secrets=(), seen=None, depth=0)`. `redact_string(value, *, secrets=())` applies every non-empty explicit secret replacement before `BEARER_PATTERN` and `TELEGRAM_TOKEN_PATTERN`; when the whole value parses as HTTP(S), it rebuilds it without userinfo and replaces query values whose keys match `SECRET_KEY_PATTERN` with `[REDACTED]`. Every recursive call forwards the same `secrets` collection. Maximum depth is 20; dictionary key cap is 500; sequence cap is 1,000; secret-like keys become `[REDACTED]`; bytes become `[BYTES:<length>]`; cycles become `[CYCLE]`. Logging processor and every job/event/attempt error write call `redact_secrets()` before serialization. Raw provider response bodies are not persisted on authentication errors.

- [ ] **Step 4: Run security/regression tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/core/test_redaction.py tests/core/test_secret_boundary.py tests/test_job_handler_registry.py tests/test_job_worker.py tests/postgres/test_job_repository.py tests/research tests/generation tests/publishing tests/operations -q
.venv/bin/ruff check app/core app/jobs app/research app/generation app/publishing app/operations tests/core
git diff --check
cd ..
git add backend/app/core backend/app/jobs/repository.py backend/app/generation/providers/openrouter.py backend/app/research/codex_adapter.py backend/app/publishing/telegram/client.py backend/app/operations/diagnostics.py backend/tests/core
git commit -m "security: redact secrets across operational boundaries"
```

Expected: canary scan and all affected subsystem tests pass.

---

### Task 6: Create verified backup and explicit restore tooling

**Files:**
- Create: `scripts/backup_restore.py`
- Create: `backend/tests/operations/test_backup_restore_script.py`
- Create: `docs/operations/backup-and-restore.md`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: Compose `postgres`/`api` services, PostgreSQL database, media/export roots, and Alembic head.
- Produces: `backup`, `verify`, and `restore --confirm-replace` CLI commands plus a checksummed `newscraft-backup-v1` archive.

- [ ] **Step 1: Write failing command/manifest/safety tests**

```python
def test_backup_runs_consistent_database_and_media_commands(tmp_path, fake_runner):
    archive = BackupRestore(runner=fake_runner).backup(tmp_path)
    assert fake_runner.commands[0][:5] == ["docker", "compose", "exec", "-T", "postgres"]
    assert archive.name.startswith("newscraft-")
    assert read_manifest(archive)["schema"] == "newscraft-backup-v1"


def test_verify_rejects_checksum_mismatch(tmp_path):
    archive = tampered_archive(tmp_path)
    with pytest.raises(BackupVerificationError, match="checksum mismatch"):
        BackupRestore().verify(archive)


def test_restore_requires_explicit_confirmation(valid_archive):
    with pytest.raises(SystemExit, match="--confirm-replace"):
        main(["restore", str(valid_archive)])


def test_restore_stops_and_restarts_the_actual_split_runtime_services(valid_archive, fake_runner):
    BackupRestore(runner=fake_runner).restore(valid_archive, confirm_replace=True)
    assert [
        "docker", "compose", "stop", "api", "worker-source-generation",
        "worker-publishing", "scheduler", "frontend",
    ] in fake_runner.commands
    assert all(command != ["docker", "compose", "stop", "api", "worker", "scheduler", "frontend"] for command in fake_runner.commands)
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/operations/test_backup_restore_script.py -q
```

Expected: script import/file failure.

- [ ] **Step 3: Implement archive and verification contract**

CLI:

```text
python scripts/backup_restore.py backup --output-dir ./backups
python scripts/backup_restore.py verify ./backups/newscraft-YYYYMMDDTHHMMSSZ.tar.gz
python scripts/backup_restore.py restore ./backups/newscraft-YYYYMMDDTHHMMSSZ.tar.gz --confirm-replace
```

Backup runs `docker compose exec -T postgres pg_dump -U newscraft -d newscraft --format=custom`, `docker compose exec -T api tar -C /data/media -czf - .`, and `docker compose exec -T api tar -C /data/exports -czf - .`. The last path is the exact Release 4 `export_data:/data/exports` mount shared by API and `worker-source-generation`; its absence is an error once Release 4 is complete, not a silently skipped archive. Manifest fields are schema, created UTC, git SHA, Alembic current/head, PostgreSQL version, database dump filename, media/export filenames, file byte counts, and SHA-256. Use a private `0700` temporary directory and write final archive atomically. Do not include `.env`, secret files, Compose-rendered environment, logs, or credentials.

Verify rejects absolute/member traversal paths, symlinks, duplicates, files not in manifest, missing files, size mismatch, checksum mismatch, and wrong schema. Restore verifies first, then runs `docker compose stop api worker-source-generation worker-publishing scheduler frontend`. It recreates the database through `postgres`, restores with `pg_restore --exit-on-error`, and only after DB success replaces media/export volume contents through one-shot `docker compose run --rm --no-deps api` commands; that service owns both exact `/data/media` and `/data/exports` mounts. Run `docker compose run --rm --no-deps api alembic upgrade head`, then `docker compose start api worker-source-generation worker-publishing scheduler frontend`. On failure, leave all five services stopped and print the exact recovery command; never report success and never refer to a nonexistent `worker` service.

- [ ] **Step 4: Document a drill and ignore archives**

Add `backups/` and `*.newscraft-backup.tar.gz` to `.gitignore`. Document backup, verify, destructive restore warning, expected service interruption, free-space check, and a quarterly drill into a disposable Compose project name. Include proof queries for counts of stories, evidence, revisions, routes, publications, and media after restore.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/operations/test_backup_restore_script.py -q
.venv/bin/ruff check ../scripts/backup_restore.py tests/operations/test_backup_restore_script.py
cd ..
python scripts/backup_restore.py --help
git diff --check
git add scripts/backup_restore.py backend/tests/operations/test_backup_restore_script.py docs/operations/backup-and-restore.md .gitignore README.md
git commit -m "feat: add verified backup and restore tooling"
```

Expected: deterministic script tests and CLI help pass. Do not run destructive restore against the operator database during the normal suite.

---

### Task 7: Inject failures and prove lease, crash, and duplicate recovery

**Files:**
- Create: `backend/app/core/faults.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/jobs/worker.py`
- Modify: `backend/app/research/handlers.py`
- Modify: `backend/app/generation/handlers.py`
- Modify: `backend/app/exports/handlers.py`
- Modify: `backend/app/publishing/telegram/service.py`
- Create: `backend/tests/operations/test_fault_injection.py`
- Create: `backend/tests/integration/test_worker_crash_recovery.py`
- Create: `backend/tests/integration/test_publish_crash_recovery.py`

**Interfaces:**
- Consumes: job leases/heartbeats/requeue, attempts, idempotency, reconciliation, and fake external adapters.
- Produces: `FaultInjector`, `NoopFaultInjector`, test-only `ScriptedFaultInjector`, named fault points, and crash-recovery acceptance.

- [ ] **Step 1: Write failing production lockout and crash tests**

```python
def test_fault_injection_cannot_start_outside_test_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FAILURE_INJECTION_PROFILE", "worker_after_claim")
    with pytest.raises(SettingsError, match="failure injection requires APP_ENV=test"):
        Settings()


async def test_worker_death_after_claim_requeues_expired_lease_once(crash_worker, job_repository, clock):
    job = await queued_job("generate_platform_pack", idempotency_key="generation:case-1")
    await crash_worker.at("worker.after_claim", job.id)
    clock.advance(seconds=91)
    assert await job_repository.requeue_expired_leases() == 1
    await healthy_worker.run_once()
    assert (await job_repository.get_job(job.id)).status == "succeeded"
    assert await generation_attempt_count(job.id) == 1


async def test_death_after_telegram_send_enters_reconciliation_not_retry(crash_worker, fake_telegram):
    fake_telegram.send_then_crash_at("telegram.after_send_before_receipt")
    await crash_worker.run_publish_job()
    await requeue_expired_leases()
    assert await fake_telegram.send_count() == 1
    assert (await current_publish_job()).status == "needs_review"
    assert (await reconciliation_case()).status == "pending"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/operations/test_fault_injection.py tests/integration/test_worker_crash_recovery.py tests/integration/test_publish_crash_recovery.py -q
```

Expected: missing fault module or recovery assertion failures.

- [ ] **Step 3: Implement injection boundary and named points**

```python
class FaultInjector(Protocol):
    async def hit(self, point: str, context: Mapping[str, object]) -> None:
        raise NotImplementedError


class NoopFaultInjector:
    async def hit(self, point: str, context: Mapping[str, object]) -> None:
        return None
```

Production constructs only `NoopFaultInjector`. Tests inject `ScriptedFaultInjector` directly. Named points are `worker.after_claim`, `worker.before_heartbeat`, `research.after_provider_before_persist`, `generation.after_provider_before_persist`, `export.after_manifest_before_commit`, `telegram.before_send`, `telegram.after_send_before_receipt`, and `publication.after_receipt_before_commit`. Fault metadata is redacted. Worker crash tests use a subprocess/process boundary, a 90-second lease, deterministic clock, and `requeue_expired_leases()`.

For a send side effect before its success receipt can be durably updated, `telegram.after_send_before_receipt` marks that existing `PublishOperationReceipt` ambiguous and the publish job `needs_review`; lease recovery must not issue another send. For side effects with a durable succeeded receipt, replay skips that operation and resolves the existing publication by idempotency key. Provider/export faults may retry within configured bounds and create their normal attempt/job records without duplicate revisions/artifacts. Do not create a Telegram `PublishAttempt` substitute in fault injection.

- [ ] **Step 4: Run recovery and regression suites, then commit**

```bash
cd backend
APP_ENV=test PYTHONPATH=. .venv/bin/python -m pytest tests/operations/test_fault_injection.py tests/integration/test_worker_crash_recovery.py tests/integration/test_publish_crash_recovery.py tests/test_job_handler_registry.py tests/test_job_worker.py tests/postgres/test_job_repository.py tests/publishing tests/research tests/generation tests/exports -q
.venv/bin/ruff check app/core/faults.py app/jobs app/research app/generation app/exports app/publishing tests/operations tests/integration
git diff --check
cd ..
git add backend/app/core/faults.py backend/app/core/config.py backend/app/jobs/worker.py backend/app/research/handlers.py backend/app/generation/handlers.py backend/app/exports/handlers.py backend/app/publishing/telegram/service.py backend/tests/operations/test_fault_injection.py backend/tests/integration/test_worker_crash_recovery.py backend/tests/integration/test_publish_crash_recovery.py
git commit -m "test: prove crash and duplicate recovery"
```

Expected: fault, crash, affected subsystem, and duplicate-prevention tests pass.

---

### Task 8: Build operations UI for diagnostics, history, reconciliation, and retention

**Files:**
- Create: `frontend/features/operations/types.ts`
- Create: `frontend/features/operations/api.ts`
- Create: `frontend/features/operations/diagnostics-dashboard.tsx`
- Create: `frontend/features/operations/history-timeline.tsx`
- Create: `frontend/features/operations/reconciliation-panel.tsx`
- Create: `frontend/features/settings/retention-settings.tsx`
- Modify: `frontend/app/diagnostics/page.tsx`
- Create: `frontend/app/automations/[routeId]/history/page.tsx`
- Create: `frontend/app/settings/retention/page.tsx`
- Modify: `frontend/lib/query-keys.ts`
- Create: `frontend/tests/diagnostics-dashboard.test.tsx`
- Create: `frontend/tests/history-timeline.test.tsx`
- Create: `frontend/tests/reconciliation-panel.test.tsx`
- Create: `frontend/tests/retention-settings.test.tsx`

**Interfaces:**
- Consumes: Tasks 2–4 backend resources.
- Produces: truthful diagnostics/attention, paginated history, safe reconciliation decisions, and preview-confirm retention controls.

- [ ] **Step 1: Write failing operational UI tests**

```tsx
it("renders observed health timestamps and never invents a healthy state", () => {
  render(
    <DiagnosticsDashboard
      snapshot={diagnostics({
        "worker-source-generation": { status: "unknown", observedAt: null, lastSuccessAt: null },
        "worker-publishing": { status: "degraded", observedAt: "2026-07-11T08:00:00Z", lastSuccessAt: null },
      })}
    />
  )
  expect(screen.getByText("Source/generation worker status unknown")).toBeInTheDocument()
  expect(screen.getByText("Publishing worker last observed Jul 11, 2026, 11:30 AM")).toBeInTheDocument()
  expect(screen.queryByText("Healthy")).not.toBeInTheDocument()
})

it("requires explicit reconciliation choice and operator note", async () => {
  render(<ReconciliationPanel value={pendingCase} />)
  expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Confirm not published" }))
  expect(screen.getByRole("button", { name: "Confirm and queue retry" })).toBeDisabled()
  await userEvent.type(screen.getByLabelText("Verification note"), "Checked the destination channel")
  expect(screen.getByRole("button", { name: "Confirm and queue retry" })).toBeEnabled()
})

it("shows retention candidates before enabling typed confirmation", async () => {
  render(<RetentionSettings policy={policy} preview={preview} />)
  expect(screen.getByText("14 export artifacts · 120 MB")).toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Run cleanup" })).toBeDisabled()
  await userEvent.type(screen.getByLabelText("Type DELETE PREVIEWED DATA"), "DELETE PREVIEWED DATA")
  expect(screen.getByRole("button", { name: "Run cleanup" })).toBeEnabled()
})
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/diagnostics-dashboard.test.tsx tests/history-timeline.test.tsx tests/reconciliation-panel.test.tsx tests/retention-settings.test.tsx
```

Expected: import failures for operational components.

- [ ] **Step 3: Implement typed API/query contracts and screens**

```tsx
export const operationsQueryKeys = {
  diagnostics: ["operations", "diagnostics"] as const,
  history: (filters: HistoryFilters) => ["operations", "history", filters] as const,
  reconciliations: ["publications", "reconciliation"] as const,
  retentionPolicy: ["operations", "retention-policy"] as const,
  retentionPreview: (policyHash: string) => ["operations", "retention-preview", policyHash] as const,
}
```

Diagnostics displays each persisted runtime instance and its exact `observedAt` timestamp plus action links. History uses load-more cursor pagination, filters, and durable event metadata. Reconciliation is keyed by `publishJobId` and presents ordered operation keys/request hashes, destination, send time, ambiguity reason, exact verification steps, remote IDs/permalink fields, and separate confirm-present/confirm-absent actions that call the existing Release 2 POST endpoint. Retention requires preview after every policy change, invalidates preview after any mutation, and never lets the browser submit record IDs.

- [ ] **Step 4: Run tests, type check, and commit**

```bash
cd frontend
npm run test -- tests/diagnostics-dashboard.test.tsx tests/history-timeline.test.tsx tests/reconciliation-panel.test.tsx tests/retention-settings.test.tsx
npm run typecheck
git diff --check
cd ..
git add frontend/features/operations frontend/features/settings frontend/app/diagnostics/page.tsx frontend/app/automations frontend/app/settings frontend/lib/query-keys.ts frontend/tests/diagnostics-dashboard.test.tsx frontend/tests/history-timeline.test.tsx frontend/tests/reconciliation-panel.test.tsx frontend/tests/retention-settings.test.tsx
git commit -m "feat: add operational recovery workspace"
```

Expected: focused tests and TypeScript pass.

---

### Task 9: Run full local acceptance and add deterministic smoke tooling

**Files:**
- Create: `scripts/smoke.py`
- Create: `backend/tests/operations/test_smoke_script.py`
- Create: `frontend/e2e/full-platform-acceptance.spec.ts`
- Create: `docs/operations/release-acceptance.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: the complete platform.
- Produces: one fake-backed smoke command, full desktop/mobile/RTL browser acceptance, and a release evidence checklist.

- [ ] **Step 1: Write failing smoke-driver test**

```python
def test_smoke_driver_runs_complete_fake_workflow(fake_http, tmp_path):
    result = SmokeDriver(base_url=fake_http.base_url, output_dir=tmp_path).run()
    assert result.steps == [
        "health",
        "configure",
        "manual_intake",
        "collect",
        "research",
        "generate_four_platforms",
        "edit_and_approve",
        "telegram_dry_run",
        "export",
        "manual_plan",
        "pause_and_resume",
        "history",
        "diagnostics",
    ]
    assert result.failed == []
    assert result.report_path.exists()
```

- [ ] **Step 2: Implement exact smoke command**

```text
python scripts/smoke.py --base-url http://127.0.0.1:8000 --provider fake --telegram-mode dry-run --output-dir ./smoke-results
```

The driver uses unique `smoke-{UTC timestamp}` names/idempotency keys, polls jobs with a five-minute global timeout, never uses external credentials, records IDs/status/durations but no secrets, and exits nonzero on the first failed invariant. It validates new-post-only route activation, bounded backfill request validation, album preservation in Telegram dry run, research citations, four platform payloads, edit-invalidates-approval, exact reapproval, duplicate publish prevention, export manifest checksums, manual plan, global pause override, history, and diagnostics.

- [ ] **Step 3: Add full browser acceptance at both viewports and Persian content**

```ts
for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
  test(`complete newsroom flow ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto("/")
    await expect(page.getByRole("heading", { name: "Today" })).toBeVisible()
    await page.goto("/inbox")
    await expect(page.getByText("گزارش امروز")).toHaveAttribute("dir", "rtl")
    await page.getByRole("link", { name: "Review draft" }).click()
    await page.getByRole("button", { name: "Approve revision" }).click()
    await page.goto("/calendar")
    await expect(page.getByRole("heading", { name: "Publication calendar" })).toBeVisible()
    await page.goto("/diagnostics")
    await expect(page.getByText("Source/generation worker status")).toBeVisible()
    await expect(page.getByText("Publishing worker status")).toBeVisible()
  })
}
```

Include separate browser cases for route review, route auto mode, global pause, retryable failure, ambiguous reconciliation, manual URL/text, manual/deep/auto research, all exports/copy actions, mobile navigation, keyboard-only editor use, and no serious/critical axe violations.

- [ ] **Step 4: Run migration and failure acceptance**

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
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic downgrade 0007_manual_publication_plans
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test PYTHONPATH=. .venv/bin/alembic upgrade head
cd ../frontend
npm run test
npm run typecheck
npm run build
npx playwright test --project=chromium
cd ..
docker compose config >/tmp/newscraft-release5-compose.yml
docker compose up -d --build postgres api worker-source-generation worker-publishing scheduler frontend
python scripts/smoke.py --base-url http://127.0.0.1:8000 --provider fake --telegram-mode dry-run --output-dir ./smoke-results
docker compose ps
git diff --check
```

Expected: all tests/build/browser/migration/Compose/smoke gates pass; Compose reports healthy/running services. If Docker is unavailable, record that environmental blocker and do not claim the Compose/smoke gate passed.

- [ ] **Step 5: Document evidence and commit**

Document exact command results, migration head `0008_operational_retention`, desktop/mobile viewports, fake provider/dry-run qualification, backup verification test, secret canary test, lease recovery test, duplicate prevention test, and any optional credentialed smoke run separately.

```bash
git add scripts/smoke.py backend/tests/operations/test_smoke_script.py frontend/e2e/full-platform-acceptance.spec.ts docs/operations/release-acceptance.md README.md
git commit -m "test: complete NewsCraft acceptance suite"
git status --short
git log --oneline --decorate -12
```

Expected: no Release 5 implementation file remains uncommitted; only explicitly excluded user artifacts may remain.

## Release 5 Exit Criteria

- All primary flows work at desktop/mobile sizes, with keyboard access, visible focus, truthful states, Persian RTL content, and no serious/critical axe violations.
- Diagnostics are derived from separate persisted `RuntimeHeartbeat` observations for source-generation worker, publishing worker, and scheduler; displayed observation times equal stored times.
- Ambiguous Telegram outcomes remain keyed to Release 2 `PublishOperationReceipt` rows and `publish_job_id`, require the existing explicit reconciliation endpoint, and cannot blind-retry.
- Retention is previewed, confirmed, auditable, and protects evidence/revisions/publications/referenced media.
- Recursive redaction passes canary tests across logs, jobs, events, attempts, diagnostics, URLs, and API responses.
- Backup archives verify checksums and paths for PostgreSQL plus the exact media/export mounts; restore controls the actual split worker service names, requires explicit destructive confirmation, and has a documented drill.
- Lease expiry, worker death, provider/export faults, and Telegram crash windows recover without duplicate revisions, artifacts, or posts.
- Full backend, Ruff, Alembic, frontend unit/type/build, Playwright desktop/mobile, Compose, and deterministic smoke gates pass with captured evidence.
- The complete acceptance criteria in the approved rescue design are demonstrably satisfied.
