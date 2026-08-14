# NewsCraft Production Hardening Solutions

> **Archived 2026-08-13 — historical record only.** This is the
> production-hardening plan that the `docs/implementation-reports/` phase
> reports cite as their authoritative source. It lived at the repository
> root as `solutions.md` until it was dropped from the tree; the content
> below is restored verbatim from commit `8f0923d` (2026-07-19) so those
> citations resolve again. All 15 phases were implemented and audited (see
> `docs/implementation-reports/hardening-final-audit.md`), so this plan is
> closed: read it to understand why a phase was done, never as a
> description of current code.

Audit basis: source revision `7826ebaf04565b0401baacac8f5234ed88764029`, inspected on 2026-07-15. This document is a remediation plan only; no production source fix was applied while preparing it.

Notation: every numbered implementation step names its file/component and intended change. “Reason/result” states why and the expected outcome. An omitted dependency means “none beyond earlier numbered steps in this phase”; an omitted risk means the phase's already-listed regression risks apply. In alternative lists, the opening clause is the potential benefit and the remainder states the risk and rejection rationale.

## Executive Summary

NewsCraft has unusually strong safety primitives for a project at this stage: PostgreSQL-backed leased jobs, immutable evidence and revision hashes, explicit approval, capability-separated workers, durable generation attempts, per-operation Telegram receipts, ambiguity reconciliation, checksummed exports, and a defensive backup verifier. Those primitives are real and are covered by a substantial test suite. They do not yet form a production-ready runtime because several boundaries around them are wrong.

The two most urgent defects are transaction-boundary defects. Telegram route mutations commit and then serialize a server-updated ORM field that SQLAlchemy has expired, so the client receives HTTP 500 for an operation that succeeded. Separately, a job handler calls `session.expire_all()` on the same identity map that contains the worker's claimed `WorkflowJob`; the worker then reads that object after the handler returns and exits before its terminal job transition. The second defect is the recommended first implementation phase because it can expose at-least-once execution after a domain side effect and can stop an entire worker capability.

The remaining P0 defects amplify or conceal those failures: no container restart policy, a forced nonexistent proxy, a redaction filter that destroys Uvicorn's structured access arguments, and API injection of worker-only secrets. Restart supervision must follow—not precede—the worker fix so it does not turn the known crash into a noisy loop. Dependency locking and CI should then make the repaired boundaries reproducible; readiness, contract, performance, accessibility, and restore work form the controlled-production gate.

Status by phase:

| Phase | Status | Release consequence |
|---|---|---|
| 1. Route mutation HTTP 500 | Confirmed | P0 blocker |
| 2. Worker post-handler crash | Confirmed | P0 blocker; recommended first |
| 3. Restart supervision | Confirmed | P0 blocker |
| 4. Proxy default | Confirmed | P0 blocker for real ingestion/providers |
| 5. Access logging | Confirmed | P0 operational/security blocker |
| 6. Credential topology | Confirmed | P0 security blocker |
| 7. CI | Confirmed | P1 release blocker |
| 8. Dependency locking | Confirmed | P1 reproducibility blocker |
| 9. Readiness | Confirmed | P1 operational blocker |
| 10. Contract drift | Confirmed | P1 release-gate blocker |
| 11. Inbox performance | Strongly supported | Profile and remediate before scale |
| 12. Diagnostics accessibility | Confirmed | WCAG release blocker |
| 13. Persian generation quality | Blocked by environment | No usable real-provider corpus |
| 14. Live Telegram publication | Blocked by environment | Requires explicit staging credential/authorization |
| 15. Restore proof | Blocked by environment | Requires an isolated destructive drill |

Runtime evidence in `docs/production-readiness-audit-2026-07-15.md` was checked against current call paths. The audit observed route 500s, a stopped worker, forced-proxy RSS failure, the formatter exception, Playwright drift, the inbox timeout, Diagnostics contrast failure, three unusable OpenRouter paths, and no live publish or destructive restore. Current focused validation added: `docker compose config --quiet` passed; Python compilation passed single-process; 170 focused backend tests passed; 16 PostgreSQL worker/publish crash-recovery tests passed; 14 focused frontend tests passed in 5.10 seconds; and `npm run build` completed, including TypeScript and 17 static pages. A direct current-image reproduction of `uvicorn.logging.AccessFormatter` still raised `ValueError: not enough values to unpack (expected 5, got 0)`. Standalone `npm run typecheck` is susceptible to a malformed ignored `.next/dev/types/validator.ts`; the clean production build's TypeScript phase passed, so CI must generate types in a clean directory.

Critical uncertainty remains external: there is no usable output from a funded production model, no authorized test-channel send, and no recorded isolated restore. These are gates, not assumptions that can be resolved by more static inspection.

## Architecture and Runtime Map

- **API.** `backend/app/main.py:20-47` creates FastAPI, seeds default prompts/provider configuration during lifespan, includes the API router, and exposes a process-only `/health`. `docker-compose.yml:39-77` runs Alembic and Uvicorn in one container.
- **Database and transaction boundaries.** `backend/app/db/session.py:7-13` uses SQLAlchemy's async engine and `async_sessionmaker(..., expire_on_commit=False)`. That setting preserves ordinary loaded values across commit, but does not prevent expiry of server-generated/on-update columns, explicit `expire_all()`, rollback expiry, or detachment. API dependencies and workers currently pass ORM instances across transaction boundaries.
- **Job engine.** `backend/app/jobs/repository.py` atomically enqueues by unique idempotency key, claims with a lease and capability/job-type filter, heartbeats leases, completes/fails jobs, and requeues expired leases. `backend/app/jobs/worker.py:259-377` claims, invokes a handler, then performs a terminal transition. The worker and handler currently share one `AsyncSession` and one ORM job instance.
- **Workers.** `worker-source-generation` owns ingestion, Telegram source, generation, research, export, and related handlers; `worker-publishing` owns Telegram publishing. The registry derives claimable job types from capabilities (`backend/app/jobs/registry.py:43-90`).
- **Scheduler.** `backend/app/jobs/scheduler.py:320-361` records a heartbeat, ticks every configured 15 seconds, expires/reconciles leases, and enqueues due source/route work. It has no process supervisor in the stock Compose file.
- **Ingestion.** RSS/Atom ingestion uses `backend/app/ingestion/service.py`; public Telegram HTML and optional Telethon MTProto adapters are built in `backend/app/jobs/worker.py:115-155`. Content, source items, deduplicated records, and media metadata are durable PostgreSQL state; media bytes are filesystem-backed.
- **Generation.** Immutable prompt versions, provider profiles, generation runs/attempts, canonical stories, and platform variants live under `backend/app/generation`. Providers receive strict JSON Schema. OpenRouter is resolved from a credential reference in the generation worker; invalid output is kept out of editorial revisions.
- **Publishing.** Approval and exact content/evidence hashes precede `PublishJob`. `backend/app/publishing/telegram/service.py` creates deterministic operations and durable receipts, marks an operation `dispatching` before the network call, stores remote IDs after success, and routes an uncertain post-dispatch outcome to reconciliation rather than resending.
- **Credentials.** PostgreSQL stores uppercase secret references, not values (`backend/app/core/secrets.py:8-50`). Workers resolve values from their environment. The base Compose file correctly separates source/generation and destination values between workers, but incorrectly injects all of them into the API.
- **Logging.** `backend/app/core/logging.py` recursively redacts messages, arguments, exception text, and extras. Its filter mutates the shared `LogRecord` before formatter execution, violating Uvicorn's access formatter contract.
- **Frontend.** Next.js 16 App Router, React, TanStack Query, Tailwind/shadcn, handwritten wire models and mappers. Vitest covers components; Playwright uses duplicated route mocks plus a smaller live-stack crawl.
- **Backup, restore, retention, and export.** `scripts/backup_restore.py` archives a PostgreSQL custom dump plus media and export trees, writes a strict checksummed manifest, and supports explicit destructive restore. `backend/app/retention` manages application data retention. Exports are deterministic/filesystem-backed. Cross-store backup consistency, encryption, archive rotation, and a recorded real restore are missing.
- **Deployment topology.** Compose has PostgreSQL, API, frontend, two workers, and scheduler, plus an external `xray_proxy` network and named data volumes. No service has a `restart` policy; only PostgreSQL and API have health checks.
- **Tests and release engineering.** Backend unit, PostgreSQL, and durable integration suites exist; frontend has Vitest and Playwright. No `.github/workflows` exists. Python has no lock/constraints file. The frontend lockfile exists, but many direct declarations use `latest`.

## Phase 1 — Telegram Route Mutations Commit Successfully but Return HTTP 500

### 1. Problem Statement

Activation, pause, and resume persist their intended state and activation also enqueues its durable job, but response serialization then returns HTTP 500. Dry-run and backfill use the same unsafe post-commit response pattern. A client cannot tell failure from success and may retry a committed mutation.

### 2. Status

**Confirmed.** Activation, pause, and resume failed in the deployed audit while their database effects remained. The current static path identifies the specific expired field and matches the observed `MissingGreenlet`.

### 3. Evidence

- `backend/app/api/telegram_automations.py:277-312` mutates activation state, enqueues with a stable idempotency key, calls `await session.commit()`, then constructs `TelegramRouteAcceptedOut(route=route, ...)`.
- The same commit-then-return sequence exists at `:315-328` for pause/resume and `:331-372` for dry-run/backfill. Create and research-policy updates at `:240-274` should use the same response-boundary helper for consistency.
- `backend/app/automations/models.py:60-62` declares `AutomationRoute.updated_at` with `server_default=func.now()` and `onupdate=func.now()`. SQLAlchemy expires this generated value after an update even though the session factory uses `expire_on_commit=False`.
- `backend/app/api/telegram_schemas.py:167-193` enables `from_attributes` and reads `updated_at`; that synchronous Pydantic attribute access attempts async IO after commit and raises `MissingGreenlet`.
- Runtime audit: `docs/production-readiness-audit-2026-07-15.md:188-225,328-334`. Activation failed after 391 ms; pause/resume also returned 500; state was committed.
- Existing `backend/tests/test_telegram_route_api.py` uses direct endpoint calls/fake sessions and does not exercise FastAPI response serialization against PostgreSQL, explaining the coverage gap. Its focused suite passed during this audit and therefore does not refute the deployed failure.

### 4. Root Cause

- **Primary root cause:** a server-generated `updated_at` is expired by the update/commit, and the endpoint returns a live ORM instance for synchronous response-model serialization.
- **Contributing factors:** transaction success and response materialization are not represented as separate steps; endpoint tests stop before the real ASGI/Pydantic/PostgreSQL boundary; five mutations duplicate the pattern.
- **Symptoms:** `MissingGreenlet`, HTTP 500, a misleading failed request, and a committed activation/job.
- **Secondary risks:** unsafe client retry, duplicate operator actions, audit ambiguity, and future failures if a lazy relationship or another generated column is added. Enqueue idempotency reduces duplicate jobs but does not make the HTTP contract truthful.

### 5. Impact

Reliability and user experience are critically affected: successful control actions appear failed. Data is not rolled back, so API state and client belief diverge. Repeated mutation calls may change cursors or create extra operational events even when job keys deduplicate. Operators cannot safely recover without reading state back. There is no direct credential risk, but logs and alerts are polluted by false 500s.

### 6. Recommended Solution

Create a single route-response materializer that is called while the transaction and async context are active. For each mutation: mutate/enqueue, `flush`, explicitly `refresh(route, attribute_names=[all response scalars])`, build `TelegramRouteOut` and any job DTO into detached Pydantic values, then commit and return the already-materialized DTO. If commit fails, no response is returned. This preserves the database-generated timestamp without a post-commit read or a concurrent post-commit refresh window.

### 7. Rejected or Alternative Solutions

- **Set `expire_on_commit=False`:** already configured (`backend/app/db/session.py:8`); it does not override generated-value or explicit expiry. No benefit here.
- **Commit then `await session.refresh(route)`:** small and functional, but opens a new read transaction after commit and may serialize a concurrent change rather than this mutation. Acceptable as an emergency patch, not preferred.
- **Catch `MissingGreenlet` and return success:** hides other unloaded fields, cannot recover a truthful timestamp synchronously, and normalizes an invalid boundary.
- **Return the ORM object and eager-load relationships:** generated scalar expiry remains; relationships are not the observed cause.
- **Bulk SQL `UPDATE ... RETURNING`:** gives an excellent scalar result and may be suitable later, but rewrites straightforward ORM mutation logic for no present benefit.

### 8. Step-by-Step Implementation Plan

1. In `backend/app/api/telegram_automations.py`, add a private async `_materialize_route_out(session, route)` that flushes, refreshes every `TelegramRouteOut` scalar, and immediately calls `TelegramRouteOut.model_validate(route)`. Reason/result: centralize the safe async read boundary. Dependency: none. Risk: omitting a future schema field; guard with a schema-field test.
2. Change create, research-policy update, activate, pause, resume, dry-run, and backfill to build their complete response DTO before `commit`, then commit and return only that DTO. Reason/result: no ORM access after transaction completion. Dependency: step 1. Risk: a DTO must never be returned if commit raises; retain the current exception propagation.
3. Materialize accepted job fields in the same way rather than embedding a `WorkflowJob` ORM row. Reason/result: prevent the same bug from moving to job output. Dependency: Phase 2's immutable execution design is compatible but not blocking. Risk: status enum mapping drift.
4. Add a small service/helper boundary only if endpoint duplication remains; do not introduce a repository rewrite. Reason/result: smallest reviewable patch. Risk: over-abstraction could obscure transaction order.
5. Update route API tests to use the real ASGI app and async PostgreSQL dependency override. Reason/result: exercise Pydantic serialization and commit. Dependency: test database. Risk: test isolation; use a `_test` database and truncate fixtures.

### 9. Required Tests

- Unit: materializer refreshes and returns every response field without retaining an ORM object.
- PostgreSQL/ASGI regression: create, policy update, activate, pause, resume, dry-run, and bounded backfill each return the documented 2xx body and the state is committed in a fresh session.
- Failure path: force commit failure; assert no 2xx response and no falsely materialized state escapes.
- Retry/idempotency: repeat activation and backfill request; assert the existing job/key semantics and no duplicate durable job.
- Concurrency: two activation requests serialize on the locked route and return a consistent route/job pair.
- Security: response contains no provider/destination/source secret reference or value.

### 10. Validation Commands

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/postgres/test_telegram_route_api.py tests/test_telegram_route_api.py
cd ..
docker compose -f docker-compose.yml -f docker-compose.acceptance.yml up -d --build
python scripts/smoke.py --base-url http://127.0.0.1:8000 --provider fake \
  --telegram-mode dry-run --output-dir /tmp/newscraft-smoke-route-response
```

### 11. Acceptance Criteria

- All seven route mutations return their documented 2xx response and committed state on PostgreSQL.
- Zero ORM SELECT occurs during synchronous response serialization; a test fails if a detached/expired attribute is read.
- Ten clean fresh-database smoke runs and three same-database reruns have zero route 500s.
- Repeating an accepted operation never creates a second job for the same idempotency key.

### 12. Rollback Plan

Revert the endpoint/materializer patch as one change; no schema migration is involved. If the shared helper regresses one endpoint, temporarily use explicit `flush`/`refresh`/DTO construction inline there while retaining the regression tests. Do not roll back by reintroducing ORM responses after commit.

### 13. Estimated Complexity

**Low — 0.5 to 1.5 engineering days**, including PostgreSQL ASGI coverage.

### 14. Dependencies on Other Phases

No implementation blocker. Phase 2 should land first in the recommended order because its side-effect risk is greater. Phases 7 and 10 should make these deployed-boundary tests mandatory. Phase 14 must not begin until this phase is complete.

### 15. Definition of Done

- [ ] Every route mutation returns a pre-materialized DTO.
- [ ] No response path touches a route/job ORM instance after commit.
- [ ] PostgreSQL ASGI tests cover success, failure, retry, and concurrency.
- [ ] Fresh and rerun smoke gates meet the stated counts.
- [ ] API schema and secret boundary are unchanged.

## Phase 2 — Worker Crashes After a Handler Commits

### 1. Problem Statement

A handler can successfully persist domain work and return, but the worker then reads expired attributes from the shared `WorkflowJob` ORM object. The worker exits before `finish_job`, leaving a lease to recover work whose side effects may already exist.

### 2. Status

**Confirmed.** The deployed source/generation worker crashed after creating a Telegram revision/event. Static analysis identifies the exact `expire_all()` and post-handler reads on the shared identity map.

### 3. Evidence

- `backend/app/jobs/worker.py:263-307` claims and commits a `WorkflowJob`, then passes that ORM object and the same `AsyncSession` to a handler.
- After handler return, `backend/app/jobs/worker.py:332-374` reads `job.id`, `job.job_type`, and `job.attempt_count` for finish/fail/logging.
- `backend/app/automations/telegram/handlers.py:1737-1742` snapshots two values locally, but `:2235-2241` explicitly calls `session.expire_all()` to reload generation state. That expires the worker's `WorkflowJob` in the same identity map. The handler persists and returns a revision at `:2503-2544`.
- Commits/rollbacks are normal handler behavior, not an isolated mistake: `backend/app/generation/handlers.py:730,750,1480,1541,1699,1855`, Telegram route handlers `:809,856,1196,1347,1382`, publishing handler `backend/app/publishing/telegram/handlers.py:94`, and research rollback paths.
- `backend/app/jobs/registry.py:15-21` types handlers as `Callable[[WorkflowJob, JobContext], ...]`, making session-bound state part of the contract.
- Runtime audit: `docs/production-readiness-audit-2026-07-15.md:211-225,336-342`; the lease recovered, the only capable worker stayed stopped, and export timed out.
- Current audit ran `tests/integration/test_worker_crash_recovery.py` and `test_publish_crash_recovery.py`: 16 passed. Those tests validate existing lease/idempotency behavior but do not simulate a handler returning after expiring the runner's job object.

### 4. Root Cause

- **Primary root cause:** worker orchestration and domain handlers share transaction ownership, an `AsyncSession`, and a mutable ORM job instance across handler-controlled commits/rollbacks/expiry.
- **Contributing factors:** the handler interface exposes the ORM model; only some handler code snapshots values; terminal bookkeeping is performed in the handler session; post-handler logging is outside the handler exception boundary.
- **Symptoms:** `MissingGreenlet`, container exit, uncompleted job, expired lease, starved export, and operator cancellation/restart.
- **Secondary risks:** duplicate provider calls, duplicate artifacts, or duplicate external sends under at-least-once recovery. Telegram publishing's receipt/reconciliation design contains its uncertain-send case, but other handlers must prove their own idempotency.

### 5. Impact

Reliability and recovery are critical: a durable queue cannot terminalize completed work and a single job can remove a whole capability. Data may be correct but its workflow status lies. Retried generation may cost money or create duplicate artifacts; an inadequately fenced publisher could duplicate a message. Operations see a stale lease rather than the completed domain result. Security impact is indirect through repeated provider/secret use and confusing logs.

### 6. Recommended Solution

Replace the handler's ORM input with a frozen, scalar `JobExecution` envelope and give domain work and terminal bookkeeping separate session scopes. The claim transaction creates the envelope (`id`, `job_type`, an exact deep copy of the JSON payload validated to contain no secret values, attempt/max-attempt values, origin, lease owner, schedule/control fields actually used). The handler receives the envelope plus a handler-owned session. After it returns, the runner closes/rolls back that scope and uses a fresh terminal session to lock the job by envelope ID and lease owner and call `finish_job`/`fail_job`. Heartbeats already use independent sessions. No runner path may read the claimed ORM instance after envelope construction.

### 7. Rejected or Alternative Solutions

- **Snapshot only `job.id` in `run_once`:** stops the observed line from crashing but leaves type/attempt/failure reads and the handler contract session-bound. Useful emergency patch, not a complete boundary.
- **Remove `expire_all()` from the Telegram handler:** may hide this instance, but commits/rollbacks and future expiry still invalidate the shared object; it also weakens the handler's intentional reload.
- **Never commit inside handlers:** architecturally clean only after redesigning long network/provider flows. A broad unit-of-work rewrite is larger and would hold locks across network calls if done naively.
- **Catch `MissingGreenlet` around completion:** cannot reconstruct all metadata safely and leaves a poisoned session; it treats a lifecycle violation as a transient error.
- **Set `expire_on_commit=False`:** already set and irrelevant to explicit expiry/rollback.

### 8. Step-by-Step Implementation Plan

1. Add frozen `JobExecution` in `backend/app/jobs/types.py` (or a new `execution.py`) and inventory all `job.<field>` reads under registered handlers. Include only immutable scalars and an exact deep copy of the JSON payload, with construction rejecting any secret value rather than silently altering handler input. Reason/result: make the execution contract independent of an identity map while preserving job semantics. Dependency: none. Risk: missing a rarely used field or accepting a leaked value; typed migration, search-based coverage, and secret-canary tests must catch both.
2. Change `JobHandler` in `backend/app/jobs/registry.py` and every handler signature from `WorkflowJob` to `JobExecution`; parse payload from the envelope. Reason/result: handlers cannot trigger lazy ORM IO. Dependency: step 1. Risk: broad mechanical change; keep behavior tests green.
3. Refactor `WorkerRunner.run_once` in `backend/app/jobs/worker.py`: claim/commit, construct envelope while loaded, release claim session, run handler in a fresh session, and terminalize in another fresh session/repository. Reason/result: explicit ownership and a clean terminal transaction. Dependency: steps 1-2. Risk: handler code that assumed an already-open transaction; assert session state at entry/exit.
4. In the terminal repository methods, lock by `job_id` and require matching `lease_owner` plus `RUNNING` status. Reason/result: a late/stale handler cannot finish a re-leased job. Dependency: existing lease semantics. Risk: races at exact lease expiry; test with controlled clocks.
5. Keep heartbeat sessions independent and stop/join the heartbeat before terminal lock. If heartbeat fails, classify the execution conservatively and do not use the handler session to recover. Reason/result: deterministic lease ownership. Risk: premature failure under transient DB outage; use bounded behavior and metrics.
6. Document transaction ownership in `backend/app/jobs/registry.py` and worker docs: runner owns claim/terminal transactions; a handler owns domain transactions and must leave its session usable or rolled back; external side effects require an idempotency/receipt strategy. Reason/result: future handlers follow the boundary.
7. Audit each side-effecting handler. Preserve generation input hashes/run attempts, export checksums, source dedup keys, and Telegram operation receipts. Add a declared idempotency note/test per job type. Reason/result: retry safety after a crash. Dependency: phase implementation. Risk: uncovered side-effect path blocks release rather than being assumed safe.

### 9. Required Tests

- Unit regression: handler commits, calls `expire_all()`, and returns; worker finishes and logs using only the envelope.
- Unit failure paths: handler rollback, failed transaction, unknown exception, cancellation, heartbeat failure, and terminal commit failure.
- PostgreSQL concurrency: lease expires and another worker claims while the first returns; stale owner cannot finish/fail the new lease.
- Integration: inject crash before side effect, after side effect/before durable result, after durable result/before job finish, and after job finish.
- Idempotency: generation produces one revision/run per input hash; exports produce one artifact identity; ingestion deduplicates; publishing uncertain send enters `needs_review` without a resend.
- Security: envelope/job result/events/logs redact credential values and do not serialize transport/provider objects.
- Regression: all worker, scheduler, generation, research, export, Telegram process, and publishing suites.

### 10. Validation Commands

```bash
docker compose --profile test up -d --wait postgres-test
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_job_worker.py tests/integration/test_worker_crash_recovery.py \
  tests/integration/test_publish_crash_recovery.py tests/postgres
PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q
```

### 11. Acceptance Criteria

- No registered handler accepts `WorkflowJob`; no post-claim runner code reads it after the envelope is built.
- Handler commit, rollback, `expire_all()`, and return all end in a correct terminal job state without `MissingGreenlet`.
- A stale lease owner can never terminalize a job claimed by another worker.
- Every side-effecting job type has an automated crash/retry duplicate-prevention assertion.
- Ten full acceptance runs have zero worker exits and zero lease recovery caused by a runner exception.

### 12. Rollback Plan

Ship the interface/session refactor as one reversible commit with no schema migration. If a handler migration fails, roll back the whole interface change, not just its terminal-session checks. An emergency interim can retain the old handler input while snapshotting every runner scalar before invocation, but live publication must remain disabled until the immutable boundary returns.

### 13. Estimated Complexity

**Medium — 3 to 5 engineering days**, including handler migration and crash/concurrency coverage.

### 14. Dependencies on Other Phases

Recommended first phase. Phase 3 must follow to avoid supervising the known crash loop. Phases 1, 5, and 4 can be developed independently. Phase 14 depends on this phase's external-side-effect guarantees. Phase 7 must make its integration suite merge-blocking.

### 15. Definition of Done

- [ ] Frozen execution envelope replaces the ORM handler contract.
- [ ] Claim, handler, heartbeat, and terminal transactions have explicit owners/sessions.
- [ ] Lease-owner fencing covers finish and fail.
- [ ] Crash/retry tests cover every external or material side effect.
- [ ] Full backend and repeated deployed smoke gates pass with no worker exit.

## Phase 3 — Missing Worker Restart Policies

### 1. Problem Statement

When a worker or scheduler process exits, Compose leaves the service down indefinitely. Durable leases eventually make jobs recoverable, but no capable process remains to claim them.

### 2. Status

**Confirmed.** The stock Compose file contains no `restart:` entries, and the audit's crashed source/generation worker remained stopped until manual intervention.

### 3. Evidence

- `docker-compose.yml:39-178` defines API, frontend, both workers, and scheduler without restart policies. PostgreSQL also has none.
- Only PostgreSQL (`:16-20`) and API (`:72-77`) have health checks; workers, scheduler, and frontend do not.
- Worker lease defaults are 120 seconds with 30-second heartbeat (`backend/app/core/config.py:25-29`); scheduler polling is 15 seconds.
- `backend/app/jobs/repository.py:611-625,695-788` bounds retry/lease recovery and handles ambiguous publishing, but it cannot start a dead container.
- Runtime audit `docs/production-readiness-audit-2026-07-15.md:211-223,344-350`: worker stayed exited and export timed out at 300 seconds.
- Current `docker compose ps` returned no running services; therefore no kill/recovery drill was performed during this planning pass.

### 4. Root Cause

- **Primary root cause:** critical long-running services have neither Docker restart manager policy nor an external orchestrator/supervisor contract.
- **Contributing factors:** no worker/scheduler container health command, no alert on zero capable workers plus due jobs, and API startup dependency checks do not monitor runtime dependency loss.
- **Symptoms:** permanent capability outage after one process exception, queue growth, stale heartbeats, and manual restart.
- **Secondary risks:** adding restart alone before Phase 2 can create a crash loop; poison jobs can repeatedly kill processes; API may continue accepting work that cannot execute.

### 5. Impact

One unhandled exception becomes an indefinite outage despite durable recovery data. Queue latency and user-visible timeouts grow; scheduled and publishing work can miss deadlines. Restart loops can increase provider calls or log volume if idempotency is incomplete. Security is not directly reduced, but incident visibility and controlled recovery are.

### 6. Recommended Solution

Use a production override with `restart: unless-stopped` for PostgreSQL, API, frontend, both workers, and scheduler; use `restart: "no"` for one-shot migrations/tests. Split migration from API startup into a one-shot `migrate` service so a bad migration cannot make API restart forever. Add DB-backed worker/scheduler health commands for visibility, but do not assume Docker Compose restarts an `unhealthy` container—it restarts exited processes only. Alert externally on stale heartbeats/queue capability gaps and on restart rate. Keep local development override at `restart: "no"` for debuggability.

### 7. Rejected or Alternative Solutions

- **`on-failure` only:** avoids restart after a clean zero exit but does not recover daemon/host restarts and has weaker operator semantics for long-running production services.
- **Healthcheck plus `depends_on`:** `depends_on` is startup ordering only; Compose does not restart a dependent when a dependency later becomes unhealthy.
- **An `autoheal` sidecar:** grants Docker socket authority and adds a security-sensitive component. Prefer process exit/watchdog plus external monitoring or a real orchestrator.
- **Restart without fixing Phase 2:** improves availability briefly but obscures a deterministic crash and can repeat side effects.
- **Kubernetes migration now:** would provide probes/backoff, but is an unjustified platform rewrite for a Compose deployment.

### 8. Step-by-Step Implementation Plan

1. Add `docker-compose.production.yml` with `restart: unless-stopped` for long-running services and `docker-compose.dev.yml`/test overrides with `restart: "no"`. Reason/result: explicit environment policy. Dependency: Phase 2 before production enablement. Risk: developers surprised by restarts; document profiles.
2. Add a one-shot `migrate` service and make API depend on its successful completion; remove `alembic upgrade head &&` from the API command. Reason/result: migration failure is visible and non-looping. Risk: Compose version compatibility; validate `service_completed_successfully`.
3. Add `python -m app.jobs.healthcheck` with component ID, expected capability/job types, and max heartbeat age. Use it for both workers and scheduler with start periods longer than initialization. Reason/result: `docker compose ps` exposes stale loops. Risk: a separate process must query the same DB and must not report healthy solely because it can run.
4. Add a lightweight frontend health endpoint/check and change API container health to Phase 9 readiness after that endpoint exists. Reason/result: complete topology visibility. Dependency: Phase 9 for final API probe.
5. Add diagnostics/alerts: no healthy capable worker while a due job exists; scheduler stale over 90 seconds with enabled schedules; restart count >3 in 10 minutes; crash-loop/failed-job identity. Reason/result: restart is observable. Dependency: Phase 9 metrics.
6. Document poison-job handling: max attempts remain bounded; after final failure move to failed/needs-review, preserve evidence, and alert. Reason/result: no infinite job loop. Risk: process-killing defects must still increment attempts through lease expiry.

### 9. Required Tests

- Compose schema test asserts exact restart policy per service and no restart on migration/test jobs.
- Healthcheck unit tests: fresh, stale, missing, wrong-capability heartbeat and DB failure.
- Kill drill: SIGKILL each worker and scheduler; assert new process/container start, fresh heartbeat, expired lease recovery, and canary completion.
- Poison job: deterministic process exit reaches bounded terminal state and triggers an alert without endless side effects.
- Host/daemon restart drill in staging.
- Regression: explicit operator `docker compose stop` remains stopped under `unless-stopped`.

### 10. Validation Commands

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
docker compose kill -s KILL worker-source-generation
docker compose ps
docker inspect -f '{{.RestartCount}} {{.State.Status}} {{.State.Health.Status}}' \
  newscraft-worker-source-generation-1
curl -fsS http://127.0.0.1:8000/operations/diagnostics
```

### 11. Acceptance Criteria

- A killed worker/scheduler returns with a fresh heartbeat within 90 seconds and processes a compatible canary within 180 seconds.
- Explicitly stopped services do not restart.
- Migration failure leaves API unavailable without an unbounded restart loop and emits a clear failure.
- Three crashes in ten minutes alert; a final-attempt poison job becomes terminal and is not executed again.
- No duplicate revision, export, or Telegram operation occurs during the drill.

### 12. Rollback Plan

Remove the production override/revert the deployment revision and restore the prior API command if the migration service is incompatible. Keep Phase 2's correctness fix. During rollback, pause automation, drain/inspect running jobs, deploy, then resume; never swap restart policy while an ambiguous publish receipt exists.

### 13. Estimated Complexity

**Medium — 2 to 3 engineering days**, plus one staging host-restart drill.

### 14. Dependencies on Other Phases

Blocked for production enablement by Phase 2. Phase 9 supplies final readiness/alerts. Phase 7 validates Compose. Phase 15's restore service-stop/start list must remain synchronized with any new migration service.

### 15. Definition of Done

- [ ] Production/dev/test restart policies are explicit.
- [ ] Migrations are one-shot and non-looping.
- [ ] Worker, scheduler, API, frontend, and database health are visible.
- [ ] Kill, poison-job, and host restart drills meet measurable recovery bounds.
- [ ] Alerts and runbook distinguish unhealthy from exited/restarting.

## Phase 4 — Blank Proxy Variables Force a Nonexistent Proxy

### 1. Problem Statement

The documented no-proxy configuration is not actually direct. Compose's `:-` interpolation replaces an unset or empty proxy variable with `http://xray-proxy:10808`, so HTTP clients route through an external network/host that may not exist. Real ingestion then fails even though direct connectivity works.

### 2. Status

**Confirmed.** Two stock real-RSS runs fetched 0/4 sources; an audit override that only removed the forced proxy fetched 4/4, parsed 1,151 items, and produced 1,149 unique records.

### 3. Evidence

- `docker-compose.yml:46-49,97-100,132-135,161-164` uses `${HTTP_PROXY:-http://xray-proxy:10808}` and equivalents. In Compose, `:-` substitutes for both unset and empty values.
- `.env.example:16-21` documents the proxy as optional/blank, contradicting the rendered deployment.
- `docker-compose.yml:186-189` also requires an external `xray_proxy` network in the base topology.
- RSS uses `_configured_proxy()` but also `trust_env=True` (`backend/app/ingestion/service.py:179-188`), allowing conventional environment variables to override/bypass the intended normalization.
- Public Telegram and Bot API clients use `trust_env=True` (`backend/app/jobs/worker.py:136-141,184-191`); media (`backend/app/media/downloader.py:39`) and daily bundle (`backend/app/daily_bundle/__main__.py:203`) do likewise. OpenRouter's owner-created client uses httpx defaults.
- Telethon is instantiated without a proxy argument (`backend/app/jobs/worker.py:148-153`), so HTTP proxy environment variables do not establish a documented MTProto policy.
- `backend/app/core/safe_http.py:164-165` deliberately uses `proxy=None, trust_env=False` for pinned/SSRF-safe manual fetches; this is an intentional exception and must remain explicit.
- Runtime evidence: `docs/production-readiness-audit-2026-07-15.md:95-115,354-358`.
- `docker compose config --quiet` currently passes syntactically; syntax validation cannot detect the semantically wrong fallback.

### 4. Root Cause

- **Primary root cause:** the base deployment treats a private proxy hostname as a default rather than an opt-in.
- **Contributing factors:** proxy interpretation is split between Pydantic settings, httpx `trust_env`, explicit `proxy=`, Compose uppercase variables, possible lowercase variables, and a Telethon client with different semantics. Empty/whitespace/invalid/conflicting values have no single validation boundary.
- **Symptoms:** proxy DNS errors, 0 fetched sources, provider/Telegram transport failures, and misleading source health.
- **Secondary risks:** silent direct fallback could violate an operator's egress policy; proxy credentials can leak in diagnostics/logs; `NO_PROXY` inconsistencies can proxy database/internal traffic; an unconditional external Docker network prevents an otherwise direct deployment.

### 5. Impact

Real ingestion and provider execution can be completely unavailable out of the box. Source failures create operational noise and stale content. A misapplied authenticated proxy expands credential exposure. Inconsistent direct/proxy behavior makes incidents hard to reproduce and could violate security policy. Database integrity is not directly affected, but retries and queue lag increase.

### 6. Recommended Solution

Make direct networking the base default and introduce one normalized outbound policy used by every network-client factory. Normalize missing, empty, and whitespace-only values to `None`; reject malformed URLs and conflicting upper/lowercase variants; define HTTP/HTTPS/ALL precedence and `NO_PROXY` semantics; set `trust_env=False` everywhere after policy resolution; and explicitly translate supported proxy schemes for Telethon. If a proxy is configured but unreachable, report the capability unhealthy and retry according to policy—never silently bypass it. Keep the SSRF-safe manual fetch path explicitly direct until a proxy transport can preserve its DNS/IP pinning guarantees.

### 7. Rejected or Alternative Solutions

- **Change only `:-` to `-`:** makes an empty value stay empty but leaves `trust_env`, lowercase variables, client divergence, validation, and Telethon unresolved.
- **Clear proxy variables inside containers:** works diagnostically but silently discards a legitimate operator configuration and is not declarative.
- **Leave `trust_env=True` everywhere:** delegates precedence to each library/version and makes application diagnostics unable to state the effective route.
- **Fallback to direct when proxy connection fails:** improves availability but violates explicit egress/security intent and can deanonymize traffic.
- **Route the SSRF-safe client through the general proxy:** a proxy may resolve a blocked host differently and defeat local-address validation; not safe without an equivalent pinned resolver/transport.

### 8. Step-by-Step Implementation Plan

1. In `docker-compose.yml`, remove proxy fallback hostnames and use empty-preserving, no-default interpolation; move the `xray_proxy` network attachment into an opt-in proxy override. Reason/result: the base stack is truly direct. Dependency: none. Risk: existing proxy users must enable the override; document migration.
2. Add `OutboundProxyPolicy` under `backend/app/core/` with normalized `http`, `https`, `all`, and no-proxy rules. Accept uppercase/lowercase legacy variables during transition, fail on unequal nonempty duplicates, strip whitespace, reject URL userinfo in diagnostics, and support only reviewed `http`, `https`, `socks5`, and `socks5h` schemes. Reason/result: deterministic startup contract. Risk: SOCKS support requires the locked httpx extra.
3. Add a shared httpx client/transport factory that resolves per-scheme proxy and bypass rules, always with `trust_env=False`. Migrate ingestion, public Telegram, OpenRouter/research, Bot API, media download, and daily bundle. Reason/result: one effective policy. Dependency: step 2. Risk: connection pooling/lifecycle; retain `HttpClientOwner` ownership.
4. Update `MtprotoTelegramAdapter` construction to receive an explicitly translated supported proxy or fail source-capability readiness with a sanitized code. Reason/result: no false claim that HTTP environment variables configure MTProto. Risk: Telethon/PySocks tuple semantics; test every supported scheme.
5. Preserve `safe_http.py` as a named `direct_pinned_ssrf` exception with `trust_env=False`; document why. Reason/result: security invariant remains visible. Risk: operators expecting all traffic through a proxy; expose the exception in deployment docs.
6. Add a safe diagnostics projection: mode (`direct`/`proxy`), scheme, bypass rule count, and last connectivity result—never hostname userinfo, credentials, or raw URL. Reason/result: debuggability without leakage. Dependency: Phase 9.
7. Update `.env.example`, README, and operations runbooks with exact unset/empty/valid/invalid examples and no lowercase ambiguity. Reason/result: docs match runtime.

### 9. Required Tests

- Unit matrix: unset, empty, whitespace, upper-only, lower-only, equal duplicates, conflicting duplicates, malformed, userinfo, supported/unsupported scheme, IPv4/IPv6/domain/CIDR bypass.
- Client-factory contract for RSS, Telegram HTML, OpenRouter/research, Bot API, media, and bundle: effective transport is direct or the expected proxy and `trust_env=False`.
- Telethon proxy translation tests and unsupported-scheme failure.
- Integration with a local recording proxy: proxied requests reach it; bypassed internal/database hosts do not; configured-but-dead proxy never falls back direct.
- SSRF regression: manual intake still rejects loopback/private/redirect rebinding with or without general proxy configuration.
- Secret test: proxy user/password canary absent from logs, diagnostics, jobs, history, and exception text.
- Compose rendered-config tests for unset and explicitly blank values.

### 10. Validation Commands

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  docker compose config --quiet
HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= docker compose config | \
  sed -n '/worker-source-generation:/,/worker-publishing:/p'
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_content_production_providers.py tests/test_media_downloader.py \
  tests/test_telegram_bot_client.py tests/test_telegram_source_adapters.py \
  tests/stories/test_manual_intake_policy.py
```

### 11. Acceptance Criteria

- Unset, empty, and whitespace proxy settings make every general outbound client direct and do not require the external proxy network.
- A valid configured proxy is used by all supported outbound clients; MTProto behavior is explicit.
- Invalid/conflicting configuration fails the owning capability before it claims work, with no credential in output.
- A dead configured proxy never causes direct egress.
- The four-source real-ingestion check succeeds 4/4 in direct mode and through the approved proxy mode.

### 12. Rollback Plan

Retain an opt-in compatibility override containing the previous proxy hostname for one release, without making it the base default. If the shared factory regresses a client, roll back that client's migration while keeping the base fallback removed; explicitly set its proxy in the service override rather than restoring `trust_env` globally.

### 13. Estimated Complexity

**Medium — 3 to 5 engineering days**, mainly due to multi-client/Telethon and bypass testing.

### 14. Dependencies on Other Phases

Independent P0 fix. Phase 5 protects proxy credential logging; Phase 6 defines which services receive proxy credentials; Phase 9 exposes safe connectivity status; Phase 13 requires stable provider networking.

### 15. Definition of Done

- [ ] Base Compose has no forced proxy or unconditional proxy network.
- [ ] One policy and client factory govern all intended clients.
- [ ] MTProto and SSRF-safe exceptions are explicit and tested.
- [ ] Direct, proxied, invalid, bypass, and no-leak cases pass.
- [ ] Real ingestion succeeds in the approved networking modes.

## Phase 5 — Access-Log Redaction Breaks Uvicorn Structured Logging

### 1. Problem Statement

The global redaction filter pre-renders every log record and clears `record.args`. Uvicorn's access formatter expects a five-element tuple, so formatting itself throws for each request and useful access logs disappear.

### 2. Status

**Confirmed.** Static inspection matches the deployed audit, and a direct reproduction in the current backend image raised `ValueError: not enough values to unpack (expected 5, got 0)`.

### 3. Evidence

- `backend/app/core/logging.py:24-45` sanitizes arguments, calls `getMessage()`, replaces `msg` with rendered text, and sets `record.args = ()`.
- `_RedactingFilter.filter` applies that mutation at `:77-92`; `configure_logging` installs it on every existing logger and handler at `:135-147`.
- `uvicorn.logging.AccessFormatter` copies the record and unpacks `(client_addr, method, full_path, http_version, status_code)` from `args`; clearing it violates this contract.
- Existing `backend/tests/core/test_redaction.py:284-429` uses generic formatters and therefore passes without testing Uvicorn's structure.
- Current-image reproduction command created a real `LogRecord`, ran `_RedactingFilter`, then real `AccessFormatter`; it failed at Uvicorn's tuple unpack.
- Runtime evidence: `docs/production-readiness-audit-2026-07-15.md:360-364`.

### 4. Root Cause

- **Primary root cause:** redaction is implemented as a mutating pre-formatter filter even though structured formatters own the meaning and shape of `LogRecord.args`.
- **Contributing factors:** the same record may be shared by multiple handlers; no Uvicorn formatter integration test exists; the fallback also destroys structure; configuration applies indiscriminately.
- **Symptoms:** formatter traceback, missing access line, inflated stderr, and obscured request diagnostics.
- **Secondary risks:** a naive fix that preserves raw arguments may leak sensitive query parameters, proxy credentials, headers, cookies, API keys, Telegram tokens, or exception text.

### 5. Impact

Operators lose request method/path/status correlation during incidents. Logging errors can dominate service output and break collectors. Security review cannot rely on access logs, while removing redaction would expose secrets. Data integrity is not directly changed, but diagnosis and recovery from every other phase are impaired.

### 6. Recommended Solution

Move sanitization to formatter boundaries and never mutate the shared original record. Use a `RedactingAccessFormatter` that clones the record, validates/preserves the five-element access tuple and status integer, redacts/sanitizes each string field (especially query values), then delegates to Uvicorn. Use a `RedactingFormatter` for normal logs that clones and sanitizes `msg`, args, extras, exception, and stack text. Both formatters must catch their own failures and emit a constant safe sentinel containing only logger name/level—not the raw message. Configure Uvicorn access/error and application handlers explicitly with these formatters.

### 7. Rejected or Alternative Solutions

- **Skip redaction for `uvicorn.access`:** restores formatting but leaks sensitive URL query values.
- **Special-case by leaving raw tuple args:** still leaks and leaves other structured loggers fragile.
- **Mutate a record in a handler filter:** Python can support replacement records in newer versions, but formatter-specific semantics remain clearer and shared-handler behavior easier to reason about at the formatter.
- **Redact only after producing a final string:** can preserve access shape if wrapped carefully, but secrets may already have been interpolated and format failures may include them.
- **Disable access logs:** eliminates the exception and essential operational evidence.

### 8. Step-by-Step Implementation Plan

1. In `backend/app/core/logging.py`, replace `_RedactingFilter` message/args mutation with clone-based formatter classes; leave only non-mutating routing filters if needed. Reason/result: preserve the original structured record. Dependency: none. Risk: exception formatting differences; snapshot tests.
2. Implement `RedactingAccessFormatter(uvicorn.logging.AccessFormatter)` with exact five-field validation, string sanitization, integer status preservation, and a constant fail-closed fallback. Reason/result: keep Uvicorn colors/request-line/status behavior. Risk: Uvicorn version contract drift; pin and integration-test it (Phase 8).
3. Implement generic clone sanitization for positional/mapping args, extras, `exc_info`, `exc_text`, and `stack_info`. Reason/result: maintain current secret boundary. Risk: objects with unsafe `__str__`; never invoke them in fallback.
4. Extend URL redaction to relative request targets and sensitive query names (`token`, `key`, `secret`, `password`, `authorization`, `credential`, session variants), while preserving path and non-sensitive diagnostics. Reason/result: useful safe access lines. Risk: over-redaction; tests define intended output.
5. Supply an explicit logging dictionary/configuration for Uvicorn access/error and app handlers and verify app import does not overwrite it. Reason/result: deterministic formatter installation. Risk: duplicate handlers; assert one line per record.
6. Add a last-resort handler/formatter guard that returns `[LOG_FORMAT_FAILED] logger=<safe> level=<safe>` and never raw args. Reason/result: logging never raises into application flow.

### 9. Required Tests

- Real `uvicorn.logging.AccessFormatter` with five args: method/path/status preserved; token query canary absent.
- Generic positional and mapping interpolation, malformed format strings, non-string messages, hostile `__str__`, extras, stack and exception records.
- Canaries for API key, Bot token, authorization/cookie headers, secret reference/value, proxy userinfo, Telegram session, and sensitive queries.
- Multiple handlers receive independent cloned records and produce one line each.
- Fuzz/property test: arbitrary message/args never raises and never emits registered canaries.
- ASGI integration: make success, 4xx, and 500 requests; capture valid access/error lines with no `Logging error` traceback.

### 10. Validation Commands

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/core/test_redaction.py tests/core/test_logging_uvicorn.py
docker compose up -d --build postgres api
curl -fsS 'http://127.0.0.1:8000/health?token=log-canary'
docker compose logs --no-color api | tee /tmp/newscraft-api.log
! rg -n 'log-canary|Logging error|not enough values to unpack' /tmp/newscraft-api.log
rg -n 'GET .*health.* 200' /tmp/newscraft-api.log
```

### 11. Acceptance Criteria

- 10,000 generated valid/malformed records produce zero formatter exceptions.
- Uvicorn access output retains client, method, safe path, protocol, and status.
- No registered secret canary appears in access, error, exception, or fallback output.
- One request produces one access record; logger/handler configuration is not duplicated.
- Full backend and deployed smoke logs contain no `Logging error`.

### 12. Rollback Plan

Keep the old redaction unit corpus and make the formatter replacement one commit. If rollout fails, disable Uvicorn access logging temporarily while rolling back—never restore unredacted access args. Application error logging should remain on the last known safe generic formatter.

### 13. Estimated Complexity

**Medium — 2 to 3 engineering days**, including adversarial secret tests.

### 14. Dependencies on Other Phases

Independent P0 fix, but should precede Phase 3/9 operational drills so logs are trustworthy. Phase 8 must pin the Uvicorn version; Phase 6 supplies the credential canary matrix.

### 15. Definition of Done

- [ ] No filter destroys `msg`/`args` structure.
- [ ] Uvicorn and generic clone-based formatters are installed explicitly.
- [ ] Real formatter, ASGI, failure, and secret-canary tests pass.
- [ ] Logging cannot raise and fallback cannot leak.
- [ ] Deployed access logs are useful and clean.

## Phase 6 — API Container Receives Worker-Scoped Credentials

### 1. Problem Statement

The capability model says source, generation, and publishing secrets belong only to their workers, but the API receives all of them. A compromise of the public API can therefore expose every external capability.

### 2. Status

**Confirmed.** The violation is explicit in current Compose and is partly enshrined by configuration tests.

### 3. Evidence

- `docker-compose.yml:52-57` injects OpenRouter, all three MTProto values, and the Telegram destination token into API.
- The source/generation worker receives OpenRouter and MTProto only (`:104-108`); publishing receives destination token only (`:138`); scheduler receives none. Those worker scopes match `README.md:74-90`.
- API bind-mounts the repository root at `/workspace` (`docker-compose.yml:62-65`), so an API compromise may read the ignored root `.env` even if environment entries are removed.
- `EnvironmentSecretResolver` reads process environment (`backend/app/core/secrets.py:32-50`). API endpoints call presence checks: destinations `backend/app/api/telegram_destinations.py:31-46`, generation capabilities `backend/app/api/generation_settings.py:145-170`, and automation options/validation `backend/app/api/telegram_automations.py:55-70,179`.
- Workers resolve actual values in `backend/app/generation/providers/profiles.py:101-148`, MTProto adapter setup, and publishing service. Database models store only `secret_ref`: `backend/app/generation/models.py:68-83`, `backend/app/publishing/models.py:14-31`, and Telegram source configuration.
- API response mappers omit secret references/values, and existing secret-boundary tests are strong. The problem is injection/blast radius, not evidence of a current API response leak.
- `backend/tests/test_docker_config.py` currently expects the API environment to contain reference names, so the test must be inverted rather than merely extended.

### 4. Root Cause

- **Primary root cause:** API computes synchronous `configured`/capability booleans by inspecting secrets locally, so deployment broadened its environment instead of projecting worker-owned validation state.
- **Contributing factors:** local convenience/base Compose doubles as production topology; root repository bind mount exposes ignored configuration; environment variables are the only resolver implementation.
- **Symptoms:** worker-only values visible in API process environment and filesystem, despite correct worker separation.
- **Secondary risks:** API RCE/SSRF/debug exposure yields provider spend, private source access, and live publication authority; Compose/diagnostic dumps can reveal environment values; backups/logs could capture values if future code serializes environment.

### 5. Impact

This is a high-severity blast-radius violation. The internet-facing API can acquire private Telegram source sessions, spend provider credit, and publish to the destination. Current redaction reduces accidental output but cannot protect a compromised process. Data integrity and editorial approval can be bypassed if a stolen token is used outside NewsCraft. Incident response requires rotating every credential rather than only the affected capability.

### 6. Recommended Solution

Remove all provider/source/destination credential values and the repository-root mount from the production API. API validates only reference syntax and configuration shape. Secret availability/health is evaluated by the owning worker and persisted/projected as non-secret, time-bounded capability state (or through destination/provider validation jobs), never by duplicating the value. Prefer read-only mounted secret files/Docker secrets in workers with an environment resolver only for local development. Enforce the topology in CI by inspecting rendered environment *names*, mounts, job payloads, diagnostics, exports, backups, and logs without ever printing values.

### 7. Rejected or Alternative Solutions

- **Keep secrets in API but rely on redaction:** redaction addresses accidental output, not process compromise.
- **Duplicate `*_CONFIGURED=true` flags into API:** flags drift from reality and broaden deployment coordination; use durable worker-observed state.
- **Have API call workers synchronously:** introduces availability coupling and a new RPC/security surface. Durable validation jobs/heartbeats fit the architecture.
- **Return secret references to the frontend:** references aid reconnaissance and violate the existing API boundary.
- **Use one global `.env` for every service:** convenient locally but defeats least privilege; use per-service env/secret mounts in a dev override.

### 8. Step-by-Step Implementation Plan

1. Define and document the topology: API—DB plus media/export read access only; source/generation worker—OpenRouter and MTProto only; publishing worker—destination token only; scheduler—DB only; frontend—no secrets; backup job—data access plus backup-encryption key only. Reason/result: reviewable capability contract. Risk: classify proxy credentials as service-specific secrets too.
2. Remove secret entries from API and move the root bind mount out of base/production Compose. A dev override may mount `./backend` only, not repository `.env`. Reason/result: close environment and filesystem paths. Dependency: step 3 for UI status behavior. Risk: API presence checks will change and must not silently reject valid configuration.
3. Replace API `EnvironmentSecretResolver.configured()` decisions. Destination check/publish jobs update existing health timestamps/status; provider/source validation jobs or a small safe capability projection record `available/unavailable/unknown`, owner component, and observation time without values or returned refs. Reason/result: truthful worker-owned state. Risk: stale state; require TTL and show unknown.
4. Change options/create/activation APIs to validate reference syntax and require a recent healthy owning capability where execution is imminent. A missing value becomes a sanitized worker permanent/configuration error, not an API secret lookup. Reason/result: API remains usable for configuration without authority. Risk: behavior/API contract change; Phase 10 codegen.
5. Add file-backed secret resolution (`/run/secrets/...`) to workers and keep uppercase environment references as an explicitly local-development resolver. Reason/result: values are not exposed by ordinary container environment inspection. Risk: permissions/rotation; test reload/restart semantics.
6. Audit serialization boundaries: workflow payloads, events/history, attempts, diagnostics, exports, backup manifest/content, frontend responses, and logs. Store only IDs/non-secret refs where internally necessary; never return refs. Reason/result: defense in depth. Dependency: Phase 5 logging.
7. Invert `backend/tests/test_docker_config.py` to assert forbidden name sets per service and no production root bind mount. Add rendered-Compose and running-container name-only checks. Reason/result: topology cannot regress. Risk: never print `docker inspect` values in CI artifacts.
8. Add credential rotation/runbook tests: revoke one capability and prove only its worker is restarted/affected. Reason/result: least-privilege operations.

### 9. Required Tests

- Compose static test for exact allowlist/denylist of environment names, secrets, mounts, and service capabilities.
- Running-container test checks `/proc/1/environ` key names without emitting values; API cannot read worker secret files or root `.env`.
- API tests with no external secrets: configuration endpoints work; responses show safe unknown/stale status; no value/reference leaks.
- Worker tests: each resolves only its own secret type and rejects another capability.
- Canary sweep through database JSON/text fields, jobs, events/history, attempts, logs, diagnostics, exports, backup archives, and frontend payloads.
- Rotation/revocation: OpenRouter revocation cannot affect publishing, destination-token revocation cannot affect ingestion, and API restart is unnecessary.
- Security test for error/traceback/Compose rendering artifact redaction.

### 10. Validation Commands

```bash
env -u OPENROUTER_API_KEY -u TELEGRAM_SOURCE_EDITOR_API_ID \
  -u TELEGRAM_SOURCE_EDITOR_API_HASH -u TELEGRAM_SOURCE_EDITOR_SESSION \
  -u TELEGRAM_DESTINATION_NEWS_TOKEN docker compose config --quiet
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_docker_config.py tests/core/test_external_secret_boundary.py \
  tests/core/test_job_diagnostic_secret_boundary.py \
  tests/core/test_attempt_error_secret_boundary.py tests/test_secret_redaction.py
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d
docker compose exec -T api sh -c 'test ! -e /workspace/.env && test ! -e /run/secrets/openrouter_api_key'
```

### 11. Acceptance Criteria

- API environment, mounts, and secret files contain zero source, provider, destination, or authenticated-proxy credential values.
- Each worker can access only its documented capability secrets; scheduler/frontend access none.
- Configuration and diagnostics remain truthful through worker-observed state with a defined TTL.
- A canary secret has zero matches in every durable/output surface listed above.
- Revoking one secret affects only its owning capability and rotation requires only that worker restart.

### 12. Rollback Plan

If worker-observed status breaks configuration UI, return `configured: unknown` or temporarily hide the field; do not re-inject values into API. Roll back file-secret resolution per worker to its scoped environment variable while retaining service separation and removal of the API root mount.

### 13. Estimated Complexity

**Medium — 4 to 6 engineering days**, including a small capability-state/API contract change and security sweep.

### 14. Dependencies on Other Phases

P0 and independently actionable. Phase 5 must cover new status/error logs. Phase 9 consumes capability state. Phase 10 updates frontend contracts. Phase 15 verifies backups contain no values. Phase 14 cannot run until destination authority is publishing-worker-only.

### 15. Definition of Done

- [ ] Service credential topology is documented and CI-enforced.
- [ ] API has neither credential values nor repository-root access.
- [ ] API no longer decides availability from its environment.
- [ ] Worker-scoped file/env resolution and rotation tests pass.
- [ ] Full canary sweep reports zero leaks.

## Phase 7 — Missing CI Workflow

### 1. Problem Statement

The repository has no automated, required merge gate. Locally strong tests therefore do not prevent changes that break production serialization, migrations, Compose, contracts, security boundaries, frontend build, or crash recovery.

### 2. Status

**Confirmed.** There is no `.github/workflows` directory or equivalent CI configuration in the current repository.

### 3. Evidence

- No tracked `.github/workflows/*` exists.
- Backend commands/dependencies are in `backend/pyproject.toml`; Ruff and pytest are present, but no Python type checker or committed lock is configured.
- Frontend scripts in `frontend/package.json:5-10` provide test, typecheck, and build but no lint script. Many dependencies use `latest` (Phase 8).
- Alembic has one current chain through `backend/alembic/versions/0009_operational_retention.py`; this is not checked on each merge.
- Backend Dockerfile `:12-20` installs editable `.[dev]` into the production image; CI does not verify a production-only image.
- Audit baseline: 1,598 backend assertions effective pass, Ruff pass, frontend build/typecheck pass, Vitest 368/370, mocked Playwright 23/33. Current focused checks: 170 backend + 16 PostgreSQL integration + 14 frontend tests passed; production build passed. Those are manual and non-enforcing.
- Standalone typecheck currently sees a malformed ignored `.next/dev/types/validator.ts:206`, while clean `next build` type checking passes. CI must generate types in a clean workspace and assert generated tracked files do not drift.

### 4. Root Cause

- **Primary root cause:** release verification exists as documentation/manual commands but not executable repository policy.
- **Contributing factors:** environment-sensitive tests are mixed into the suite; no locked Python environment; duplicated browser mocks currently fail; type generation mutates/reads volatile `.next` state; production and test image concerns are mixed.
- **Symptoms:** deployed-only P0 failures escaped 1,598 backend assertions; known browser failures cannot block; clean-install behavior is uncertain.
- **Secondary risks:** secret leakage into artifacts, migration divergence, dependency/advisory drift, and branch merges without review or reproducible evidence.

### 5. Impact

Every phase can regress silently. Reliability, security, data integrity, and release recovery depend on the engineer's local environment. Contributors cannot distinguish required from optional failures. Artifact-less failures are slow to debug. Branch protection cannot enforce anything.

### 6. Recommended Solution

Add a GitHub Actions pipeline after the P0 patches, built from small required jobs with a final `release-gate` dependency. Use Python 3.14, Node 26, and PostgreSQL 18 matching deployment; frozen dependency installs; no live credentials; a dedicated `_test` database; clean generated-type/OpenAPI checks; production image builds; secret/dependency scanning; and retained JUnit/coverage/Playwright artifacts. Make deterministic unit, PostgreSQL, migration, contract, frontend, Compose, security, and mocked browser jobs merge-blocking once green. Put real-stack browser, backup/restore drill, long performance, and optional live-provider checks on scheduled/manual workflows with protected environments.

### 7. Rejected or Alternative Solutions

- **One monolithic job:** simple YAML but slow, poor caching/diagnostics, and a single environment hides job boundaries.
- **Run only unit tests:** the known failures occur at PostgreSQL/ASGI/Uvicorn/container boundaries.
- **Make currently failing browser checks optional forever:** preserves a false green gate. Fix Phase 10, then require them.
- **Use live OpenRouter/Telegram credentials in PR CI:** untrusted code, cost, rate limits, and external side effects make this unsafe and nondeterministic.
- **Rely on Docker build alone:** does not prove migrations, contracts, retries, or frontend behavior.

### 8. Step-by-Step Implementation Plan

1. Add `.github/workflows/ci.yml` with `changes`/setup metadata and concurrency cancellation per branch. Reason/result: one current run, clear scope. Dependency: Phase 8 lock files. Risk: path filtering must never skip shared config/security checks.
2. Add `backend-static`: frozen install, `compileall`, `ruff check`, `ruff format --check`, and a configured mypy/pyright baseline over `app` and operational scripts. Reason/result: deterministic static gate. Risk: type checker is new; land a reviewed baseline, never mass-ignore errors.
3. Add `backend-unit`: ignore `tests/postgres` and `tests/integration`, disable cache provider, unset all external secrets/proxies, publish JUnit/coverage. Reason/result: fast deterministic feedback. Risk: explicitly include root tests needing Docker in a separate job.
4. Add `backend-postgres`: PostgreSQL 18 service, database name ending `_test`, create/migrate, then `tests/postgres` and `tests/integration`, including Phase 1/2/14 crash paths. Reason/result: real async/database boundary. Risk: parallel truncation; isolate databases or serialize groups.
5. Add `migrations`: assert exactly one `alembic heads`, upgrade empty database to head, run `alembic current` and `alembic check`, and test upgrade from the oldest supported production snapshot. Reason/result: schema deployability. Risk: never run destructive tests against a non-`_test` URL.
6. Add `frontend`: `npm ci`, clean route-type generation, standalone typecheck, Vitest with JUnit, and `next build`; assert `git diff --exit-code` after generation. Reason/result: no stale `.next` cache or tracked generated drift. Risk: Next currently toggles `next-env.d.ts`; first stabilize the documented generation order/file.
7. Add `contracts`: generate canonical OpenAPI, compare committed artifact, generate frontend wire types, run schema-validated mocks and API mapping tests (Phase 10). Reason/result: drift fails at source. Dependency: Phase 10.
8. Add `compose-and-images`: rendered config with unset/blank proxies, credential/mount allowlists, `docker compose config --quiet`, backend/frontend production image builds, image smoke, and SBOM. Reason/result: deploy topology checked. Dependency: Phases 3,4,6,8.
9. Add `security`: gitleaks (full history policy), dependency audit (`pip-audit`/OSV and `npm audit` with severity policy), container scan, and credential-canary tests. Reason/result: merge blocks new secret/high-critical vulnerability. Risk: approved exception file must include owner/expiry.
10. Add required Playwright mocked suite after Phase 10; add scheduled no-mock Compose browser smoke, worker kill recovery, backup/restore drill, and performance budgets. Reason/result: deterministic PR gate plus production-like scheduled evidence. Risk: artifact retention must not capture secrets.
11. Add final `release-gate` requiring all blocking jobs and configure branch protection: current branch required, one approving review, resolved conversations, no force pushes, and required signed/provenance policy as appropriate. Reason/result: CI becomes policy.

### 9. Required Tests

- Validate workflow syntax locally and with a test branch/PR.
- Intentional-failure tests: lint, unit, migration multi-head, OpenAPI drift, secret canary, Compose forbidden env, frontend contract, and browser failure each block `release-gate`.
- Cache cold/warm runs produce identical test/build artifacts.
- Fork/untrusted PR receives no secrets and cannot publish artifacts containing credentials.
- PostgreSQL service isolation and `_test` guard test.
- Nightly workflow proves no-mock stack, restart recovery, restore drill, and large-list budget with retained reports.

### 10. Validation Commands

```bash
actionlint .github/workflows/ci.yml
gh workflow view ci.yml
gh workflow run ci.yml --ref <test-branch>
gh run watch --exit-status
git diff --exit-code
```

### 11. Acceptance Criteria

- Required PR jobs cover static, unit, PostgreSQL/integration, migrations, frontend test/type/build, contracts, Compose/images, security, and browser mocks.
- A deliberately broken assertion in each category makes `release-gate` fail.
- Clean and warm-cache runs use frozen dependency graphs and produce equivalent build/SBOM identities apart from declared timestamps.
- PR CI has zero live provider/Telegram credentials and zero external publication.
- Median required pipeline is under 15 minutes; nightly evidence is retained at least 30 days.

### 12. Rollback Plan

Workflow changes are independently revertible. If a new job is flaky, keep it visible and temporarily non-required with an owner, issue, and seven-day expiry; do not delete it or mark arbitrary failures successful. Never relax secret, migration, or production-build gates to restore speed.

### 13. Estimated Complexity

**High — 5 to 8 engineering days** after dependency/contract prerequisites, plus branch-administration time.

### 14. Dependencies on Other Phases

Phase 8 should provide frozen installs first. Phase 10 must be fixed before browser/contracts become blocking. P0 phase tests should land with their fixes even before the full workflow. Phases 3,4,6 define Compose checks; Phase 15 supplies scheduled restore commands.

### 15. Definition of Done

- [ ] CI workflow and required `release-gate` exist.
- [ ] Every listed backend/frontend/database/deployment/security category is exercised.
- [ ] Cold/frozen installs and artifact retention work.
- [ ] No PR job receives live external credentials.
- [ ] Branch protection requires the green gate and review.

## Phase 8 — Missing Backend Dependency Locking and Unpinned Frontend Dependencies

### 1. Problem Statement

Python installation resolves open-ended lower bounds at build time, and most frontend direct dependencies declare `latest`. A source-identical clean build can therefore acquire a different toolchain or transitive graph after a lock update/rebuild. The checked-in npm lock protects current `npm ci`, but the source declarations do not constrain intentional updates.

### 2. Status

**Confirmed.** No backend lock/constraints file exists; current declarations and Docker build behavior are explicit. The frontend has a lockfile but widespread `latest` ranges.

### 3. Evidence

- `backend/pyproject.toml:5-33` requires Python `>=3.14` and mostly specifies only dependency lower bounds; dev tools are also lower-bounded.
- No `uv.lock`, requirements lock, constraints, Poetry/PDM lock, or hashes exist under `backend/`.
- `backend/Dockerfile:1-20` uses mutable `python:3.14-slim`, upgrades pip, and installs editable `.[dev]`; production therefore includes test tools and resolves the network graph during build.
- `frontend/package.json:13-41` uses `latest` for Next, React, TanStack, TypeScript, Vitest, Playwright, Tailwind, and most other direct dependencies.
- `frontend/package-lock.json` is lockfile version 3 and Docker uses `npm ci` (`frontend/Dockerfile`), so a build from the unchanged lock is currently much more reproducible than Python. `latest` becomes dangerous when someone regenerates the lock.
- Frontend/base image tags are mutable (`node:26-alpine`, `postgres:18`, Python slim). No image digest/SBOM policy exists.
- Runtime audit `docs/production-readiness-audit-2026-07-15.md:275-279,414-416` reported a moderate PostCSS advisory in the then-current lock; no automated fix was applied because compatibility needed review.

### 4. Root Cause

- **Primary root cause:** the project treats an application like a reusable library for Python resolution and uses npm dist-tags as source constraints, without a reviewed lock/update policy.
- **Contributing factors:** production/test Python dependencies share one image; base images are tag-only; no automated update PR or clean-build equivalence check exists.
- **Symptoms:** potential version drift, hard-to-reproduce deployed failures, advisory lag, and a production image with unnecessary dev tools.
- **Secondary risks:** unreviewed major frontend upgrades, transitive supply-chain changes, Uvicorn/httpx/SQLAlchemy contract changes, and rollback inability if old artifacts cannot be rebuilt.

### 5. Impact

Reliability and recovery suffer because a rebuild may not recreate the audited runtime. Security updates are ad hoc, while urgent updates may accidentally jump majors. Larger production images increase attack surface. CI caches can mask missing constraints. Database/application compatibility may differ across environments even with identical source.

### 6. Recommended Solution

Use `pyproject.toml` as the Python intent/source file and commit a universal Python 3.14 `uv.lock` containing exact transitive versions/hashes for production and dev groups. Build production with `uv sync --frozen --no-dev` in a multi-stage image and tests with the dev group. Keep compatible direct ranges in `pyproject`, but let the lock define deployments. For frontend, replace `latest` with reviewed exact direct versions (or narrowly reviewed ranges), retain `package-lock.json`, and always use `npm ci`. Pin release base images by patch tag and digest, produce an SBOM, and use scheduled Renovate/Dependabot PRs with isolated major upgrades and security SLAs.

### 7. Rejected or Alternative Solutions

- **Exact-pin only `pyproject.toml`:** does not lock transitives/hashes and mixes intent with resolution.
- **`pip freeze` from the current environment:** captures incidental/editable/platform packages and is not a maintainable resolver input.
- **Constraints without hashes:** acceptable fallback using pip-tools, but `uv.lock` supports the current `pyproject` workflow and dev/production groups more directly.
- **Rely only on npm lock while keeping `latest`:** `npm ci` is safe, but any legitimate lock refresh can take unreviewed direct majors.
- **Automatic `npm audit fix --force`:** can introduce incompatible downgrades/majors; update the owning framework/package with full tests.
- **Never update dependencies:** freezes vulnerabilities and loses supported runtimes.

### 8. Step-by-Step Implementation Plan

1. Select and pin a `uv` release; generate/commit `backend/uv.lock` for Python 3.14 and all supported platforms, with production/dev dependency groups. Reason/result: deterministic resolver graph. Risk: packages without 3.14 wheels; build/test on deployment architecture.
2. Add mypy/pyright, security audit, and any test-only tools explicitly to the dev group; remove implicit environment assumptions. Reason/result: CI installs exactly what commands require. Risk: lock growth is expected, production excludes it.
3. Convert backend Dockerfile to a multi-stage, non-editable frozen install; runtime copies only app/migrations/locked environment and runs as a non-root user. Pin Python base patch/digest. Reason/result: small reproducible production image. Risk: editable import/path assumptions; run all CLI entry points.
4. Replace every frontend `latest` with the versions resolved/reviewed in the current lock, using exact direct versions for Next/React/build/test infrastructure. Regenerate lock once with the selected npm version. Reason/result: lock diffs explain intent. Risk: peer constraints; use `npm explain` and full build/browser tests.
5. Pin Node and PostgreSQL release images by patch/digest in production; document a controlled minor/major upgrade workflow. Reason/result: release artifact identity. Risk: digest is architecture-specific; support required platforms explicitly.
6. Add Renovate/Dependabot policy: weekly grouped patch/minor PRs by ecosystem, separate majors/frameworks, immediate high/critical security PR, owner/expiry for exceptions. Reason/result: updates are routine and reviewed. Risk: noisy PRs; cap concurrency.
7. Add CI frozen-install, lock-drift, clean-build-twice, SBOM, and audit jobs. Reason/result: source and locks cannot diverge. Dependency: Phase 7.
8. Record resolved Python/npm/base-image/SBOM identifiers in release metadata and retain built images. Reason/result: rollback does not depend on re-resolution.

### 9. Required Tests

- Delete all local environments/caches in a disposable workspace; frozen Python and npm installs succeed without changing locks.
- Production and test image stages run their intended commands; production cannot import pytest/Ruff and contains no source `.env`.
- Build the same revision twice from cold cache; compare application layers/SBOM package graphs, allowing only documented nondeterministic metadata.
- Full backend/frontend/Playwright/PostgreSQL suite after initial pin and each dependency PR.
- Compatibility tests around sensitive contracts: SQLAlchemy async expiry, Uvicorn formatter, httpx proxy, Pydantic/OpenAPI, Telethon, Next route types.
- Security audit policy test and exception expiry.

### 10. Validation Commands

```bash
cd backend
uv lock --check
uv sync --frozen --all-extras
uv run python -m pytest -p no:cacheprovider -q
uv run ruff check .
cd ../frontend
npm ci
npm test
npm run typecheck
npm run build
cd ..
git diff --exit-code -- backend/uv.lock frontend/package-lock.json
docker compose build --no-cache api frontend
```

### 11. Acceptance Criteria

- Frozen installs from a clean checkout change no lock/source file and resolve identical package versions.
- Production backend image has no dev dependencies/editable install and is pinned to an approved base digest.
- Frontend direct dependencies contain no `latest`; `npm ci` is the only CI/image install path.
- Every release records Python/npm/base-image and SBOM identities and retains a rollback artifact.
- No unexcepted high/critical advisory; every exception has owner, justification, mitigation, and expiry.

### 12. Rollback Plan

Locks and Dockerfile changes land together. Retain the previous signed image and lockfiles; rollback deploys that image rather than regenerating it. If `uv` is blocked, temporarily use hash-pinned pip-tools production/dev lock files generated from `pyproject`, preserving the same frozen-install policy.

### 13. Estimated Complexity

**Medium — 3 to 5 engineering days**, excluding dependency incompatibilities discovered during the initial lock.

### 14. Dependencies on Other Phases

Should precede Phase 7's frozen CI. Pins protect Phase 4 httpx, Phase 5 Uvicorn, Phase 10 OpenAPI/codegen, and Phase 11/12 frontend behavior. Phase 15 records versions for restore compatibility.

### 15. Definition of Done

- [ ] Python production/dev lock strategy is committed and frozen.
- [ ] Frontend has no `latest` direct declarations and uses its lock exclusively.
- [ ] Runtime images are production-only, non-root, and digest-pinned.
- [ ] Update/security/exception policy is automated.
- [ ] Cold reproducible build and full regression evidence pass.

## Phase 9 — Missing Real Readiness and Operational Health Checks

### 1. Problem Statement

The API's container can report healthy when PostgreSQL, storage, workers, scheduler, or capability queues are unusable. Existing diagnostics show useful durable state but not readiness, lag, stuck leases, or capability-specific availability with actionable thresholds.

### 2. Status

**Confirmed.** Current `/health` is unconditional; the richer projection omits required readiness metrics and is not used by container health.

### 3. Evidence

- `backend/app/main.py:45-47` returns `{"status":"ok"}` without a dependency check. Compose API health uses this endpoint (`docker-compose.yml:72-77`).
- `backend/app/operations/diagnostics.py:55-108` returns generated time, pause/dry-run, component heartbeats, queue counts by status, and attention items.
- Queue aggregation at `:110-115` has counts only—no oldest due age, capability, retry pressure, or stuck lease.
- Component status at `:316-357` uses fixed 30/90-second thresholds and always returns `last_success_at=None`. It does not derive thresholds from component cadence.
- Worker runtime heartbeat is recorded only at the start of `run_once` (`backend/app/jobs/worker.py:259-262`); a legitimate long provider/handler operation can make it look stale. Lease heartbeat is separate.
- Scheduler records a heartbeat before each tick (`backend/app/jobs/scheduler.py:326-359`) but does not persist last successful tick/result.
- Heartbeat records include safe capabilities/job types (`backend/app/jobs/runtime.py:23-60`), which are enough to compute coverage after freshness is fixed.
- The audit observed API availability while its sole source/generation worker was stopped and export starved (`docs/production-readiness-audit-2026-07-15.md:211-223`).

### 4. Root Cause

- **Primary root cause:** liveness, core readiness, dependency health, and business capability readiness are conflated or absent.
- **Contributing factors:** heartbeats describe loop observation rather than last successful work; queue metrics aggregate away time/capability; no endpoint/alert policy consumes leases and required job types; Compose has probes only for API/PostgreSQL.
- **Symptoms:** false healthy API, no alert for zero capable workers, opaque queue starvation, and hardcoded stale-state messages.
- **Secondary risks:** making all worker degradation fail API readiness could remove read/diagnostic access; expensive health queries can overload PostgreSQL; exposing metadata could leak configuration.

### 5. Impact

Load balancers and operators cannot distinguish a live process from a service able to perform accepted work. Jobs can queue beyond SLO without alerts. Scheduled/publishing outages may be noticed only by users. Recovery starts late and has weak evidence. A poor implementation can cause cascading restarts or disclose secrets, so checks must be bounded and sanitized.

### 6. Recommended Solution

Expose three boundaries: `/health/live` (process/event-loop only), `/health/ready` (bounded core API dependencies and explicitly configured required capabilities), and `/operations/health` (rich, sanitized dependency/capability/queue state). Keep the API available for reads/diagnostics when a worker is down unless `READINESS_REQUIRED_CAPABILITIES` says that capability is a deployment-level gate; async mutation endpoints should independently reject or defer work when the owning capability is unavailable/over its queue ceiling. Run worker/scheduler runtime heartbeats on independent background loops, persist last successful cycle, compute queue age and lease anomalies by required job type, and export Prometheus-compatible metrics/alerts.

### 7. Rejected or Alternative Solutions

- **Make `/health` run `SELECT 1` only:** catches database loss but not schema, storage, workers, scheduler, or queue starvation.
- **Fail API readiness for every worker outage:** stops diagnostic/read traffic and can create cascading dependency failure. Use configured scope plus endpoint capability gates.
- **Use container process existence as worker health:** misses dead/stuck event loops and capability mismatch.
- **Query every table deeply on every probe:** can turn probes into load incidents; use indexed aggregates, caching, and strict timeouts.
- **Expose raw heartbeat metadata/errors:** unnecessary and may reveal refs/URLs; return enumerated codes and sanitized measures.

### 8. Step-by-Step Implementation Plan

1. Add response models and `/health/live`, `/health/ready`, `/operations/health`; keep `/health` as a temporary alias with deprecation. Reason/result: explicit contracts. Dependency: Phase 10 updates clients. Risk: probe consumers; migrate Compose before removal.
2. Core readiness checks: DB `SELECT 1` within 500 ms, schema/Alembic head cached for 30 seconds, the API's required media/export read/traverse check, and event-loop timeout. Worker-specific health may use a bounded write/delete canary in a private health directory because workers own writes. Return 503 on a hard failure. Reason/result: each service proves only its authorized storage operation. Risk: health canaries; isolate, bound, and clean them.
3. Move worker runtime heartbeat to an independent background task (not one per job) and record `last_loop_success_at`, active job ID hash/age, capabilities, and job types without payload. Scheduler records last successful tick and duration/result after commit. Reason/result: truthful long-job health. Dependency: Phase 2 session ownership. Risk: heartbeat must not mask a stuck main loop; include progress age.
4. Add indexed queue metrics by job type/capability: due queued count, oldest due age, running count, lease expiry/heartbeat age, retry count/attempt pressure, final failed/needs-review count. Reason/result: lag/stuck detection. Risk: query cost; benchmark and cache 5-10 seconds.
5. Implement thresholds as settings: workers healthy at <=60 s, degraded 60-120 s, unavailable >120 s; scheduler healthy <=45 s, degraded 45-90 s, unavailable >90 s. Any expired running lease is stuck. Queue warn/fail: publish/manual 2/5 min; source/generation 5/15 min; export/retention/background 10/30 min. No fresh capable worker plus a due job makes that capability unavailable immediately. Reason/result: objective states. Risk: tune only with recorded SLO evidence.
6. Gate async mutation endpoints by owning capability and queue ceiling, returning a stable 503 error code/retry hint while preserving read/diagnostic endpoints. Reason/result: API does not accept unbounded impossible work. Risk: short deployment restart; use grace window and retryable code.
7. Add worker/scheduler CLI health checks for Compose and use core readiness for API. Note Compose marks unhealthy but does not restart it; Phase 3 supervision/alerts handle process action. Reason/result: deployment-visible state.
8. Export counters/gauges: heartbeat age, last-success age, due queue age/count, running/expired lease, attempts/failures, provider/Telegram outcomes, restart count supplied by platform. Add alerts and runbook links. Reason/result: actionable operations. Dependency: Phase 5 safe logs, Phase 6 safe capability state.

### 9. Required Tests

- Endpoint unit/contract: live always process-only; ready returns 200/503 for DB/schema/storage/required-capability cases; response has no secrets.
- Controlled-clock component threshold boundaries at 45/60/90/120 seconds.
- Long handler keeps runtime heartbeat fresh but progress age reveals a stuck job.
- Queue fixtures for no worker, wrong capability, oldest age warn/fail, future schedule, expired lease, retry exhaustion, global pause, and reconciliation-required publish.
- PostgreSQL query plan/performance test at representative job volume; health response p95 under one second.
- Container integration: stop DB, worker, scheduler, and storage permission; assert the correct endpoint/status/alert without cascading API removal.
- Security: canary payload/error/ref absent from health, metrics labels, and logs.

### 10. Validation Commands

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:8000/operations/health | python -m json.tool
docker compose stop worker-source-generation
curl -fsS http://127.0.0.1:8000/operations/health
docker compose start worker-source-generation
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/operations tests/postgres
```

### 11. Acceptance Criteria

- Liveness responds within 100 ms without dependency IO; core readiness p95 is <1 s and uses bounded queries.
- DB/schema/required-storage failure returns 503; optional worker loss leaves read diagnostics available but marks/gates that capability exactly.
- Threshold boundary tests match documented values and every hard state has an alert/runbook URL.
- An expired lease or due queue with no capable worker is visible within one probe/cache interval.
- No secret value/reference, payload, source content, or proxy credential appears in health/metric labels.

### 12. Rollback Plan

Keep legacy `/health` during one compatibility release. If richer checks overload the database, disable only the expensive operational projection/cache it longer while retaining live/core DB readiness. Do not revert to reporting worker capabilities healthy; return `unknown` when data is unavailable.

### 13. Estimated Complexity

**High — 5 to 8 engineering days**, including metrics, endpoint gates, query/index validation, and deployment drills.

### 14. Dependencies on Other Phases

Phase 2 should establish worker sessions/progress ownership; Phase 3 consumes probes/alerts; Phase 6 supplies non-secret capability status; Phase 10 generates client types. Phase 14/15 production gates consume these health checks.

### 15. Definition of Done

- [ ] Live, core-ready, and rich operational boundaries are distinct.
- [ ] Worker/scheduler heartbeat and last-success semantics are truthful.
- [ ] Capability queue/lease metrics and thresholds are implemented and indexed.
- [ ] Compose checks, endpoint gates, alerts, and runbooks agree.
- [ ] Failure drills meet latency/status/no-leak criteria.

## Phase 10 — Frontend and Backend Contract Drift in Browser E2E Tests

### 1. Problem Statement

Frontend wire types, mappings, fixtures, and Playwright route handlers are handwritten in several places. Backend endpoints evolved, but some mocks and assertions did not, causing ten mocked browser failures and making the suite an unreliable release signal.

### 2. Status

**Confirmed.** Runtime browser results and current source show an exact stale Diagnostics route and missing reconciliation request in a duplicated mock backend.

### 3. Evidence

- `frontend/features/operations/api.ts:31-144` defines extensive handwritten snake_case backend types; `:187-212` calls `/operations/diagnostics` and `/telegram/reconciliation`.
- `frontend/e2e/accessibility.spec.ts:111-186` installs a per-file offline backend. It handles obsolete `GET /diagnostics` at `:171-177`, not `/operations/diagnostics`, and has no `/telegram/reconciliation`; unhandled requests become HTTP 501.
- Other suites contain their own fixtures/intercepts, while the fuller platform mock has newer paths. Duplication permits suite-specific drift.
- Handwritten clients also exist in `frontend/features/automations/telegram-api.ts`, `frontend/lib/editorial-api.ts`, and package APIs. There is no OpenAPI generator/client dependency or contract script.
- Audit result: 23/33 mocked Playwright checks passed; ten failed around reconciliation, diagnostics labels, and desktop assumptions (`docs/production-readiness-audit-2026-07-15.md:262-272,400-404`). The live deployed crawl loaded critical pages, showing the mocks were often staler than production.

### 4. Root Cause

- **Primary root cause:** there is no enforced contract source-of-truth pipeline from FastAPI/Pydantic to frontend wire types and mocks.
- **Contributing factors:** duplicated route interception, permissive partial fixtures, manual snake/camel models, and no unmatched-request global failure or OpenAPI diff in CI.
- **Symptoms:** HTTP 501 in mocked E2E, stale labels/status assumptions, false-red release evidence, and hidden optional/required/date/enum drift.
- **Secondary risks:** production mapping may silently drop fields, malformed mocks may test impossible states, error/pagination handling can diverge, and generated status unions may become unsafe casts.

### 5. Impact

Release confidence is materially reduced: browser failures do not reliably identify product failures, and real contract changes can escape TypeScript because handwritten types assert the desired shape. Users may see runtime errors or incorrect status rendering. Security-sensitive fields could accidentally enter frontend projections if schemas are not checked.

### 6. Recommended Solution

Treat FastAPI's Pydantic-generated OpenAPI document as the wire-contract source. Generate and commit a canonical, deterministic `openapi.json`, generate TypeScript wire types (and optionally an `openapi-fetch` client), and retain small explicit mappers into UI/domain camelCase types. Centralize Playwright/MSW handlers and typed fixture builders; validate every mocked response against the OpenAPI response schema and fail immediately on any unmatched backend request. CI regenerates both artifacts and fails on diff.

### 7. Rejected or Alternative Solutions

- **Manually patch the ten mocks only:** restores green temporarily but leaves the cause and next drift intact.
- **Use generated types directly throughout UI:** reduces mapping code but leaks wire naming/nullability into components and makes domain behavior harder to isolate. Keep a wire/domain boundary.
- **Rely only on live E2E:** catches integration drift but is slower/flakier and cannot cheaply cover all errors/states.
- **Rely only on TypeScript types:** fixtures can be cast/partial and runtime JSON is not validated.
- **Make unmatched requests return generic empty success:** hides missing contracts and produced the current false assumptions.

### 8. Step-by-Step Implementation Plan

1. Add `backend/scripts/export_openapi.py` that imports `app.openapi()` without running lifespan, sorts/canonicalizes JSON, and writes `contracts/openapi.json`; include a schema/version header and deterministic output test. Reason/result: stable backend source artifact. Risk: import-time logging/settings; run with credential-free test settings.
2. Add pinned OpenAPI TypeScript tooling and generate `frontend/lib/api/generated.ts` (wire types/paths). Reason/result: required/optional/enums/date formats derive from backend. Dependency: Phase 8 locks. Risk: generator churn; pin and review output.
3. Migrate clients incrementally: typed request/response paths at transport, explicit tested wire-to-domain mappers. Remove duplicate handwritten wire interfaces once covered. Reason/result: compile-time drift failure without coupling UI domain. Risk: accidental semantic mapping change; snapshot mapper tests.
4. Create a shared deterministic mock server/route registry and typed fixture builders for operations, reconciliation, jobs, stories, automations, etc. Reason/result: one route definition. Risk: suite-specific overrides; compose them from the shared base rather than copy.
5. Validate mock status/body against the exact OpenAPI operation/response schema (AJV or equivalent), validate date-time/enum/nullability, and fail any unmatched `/api/backend/**` request with the method/path in the assertion. Reason/result: mocks cannot describe impossible responses. Risk: validation overhead; cache compiled schemas.
6. Standardize or document existing error envelopes, pagination/cursors, date-time UTC format, status enums, and optional/null semantics in Pydantic. Reason/result: generators have unambiguous contracts. Risk: API compatibility; version changes explicitly.
7. Add backend contract tests using ASGI/PostgreSQL for representative real responses and a small no-mock Playwright stack. Reason/result: OpenAPI declaration matches serialization. Dependency: Phase 1 boundary tests.
8. Add CI regeneration/diff and contract jobs; forbid unchecked casts/inline backend response types in reviewed client directories. Reason/result: drift blocks merge. Dependency: Phase 7.

### 9. Required Tests

- Deterministic OpenAPI generation and single committed artifact diff.
- Type generation then frontend typecheck from a clean directory.
- Mapper tests for snake/camel, missing optional, explicit null, enum additions, cursor pagination, date-time, 4xx validation, 409, and 503 capability errors.
- Every fixture validates against its operation/status schema; an intentionally missing required field fails.
- Every E2E suite fails on unmatched backend request; current Diagnostics/reconciliation requests are covered.
- ASGI contract tests compare actual representative responses to OpenAPI.
- Full mocked Playwright 33/33 and no-mock critical route smoke.
- Security test asserts generated/API types expose no secret value/reference fields intended to remain internal.

### 10. Validation Commands

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/export_openapi.py --output ../contracts/openapi.json
cd ../frontend
npm run api:generate
npm run typecheck
npm test -- tests/operations-api.test.ts tests/telegram-api.test.ts
npm run test:e2e
cd ..
git diff --exit-code -- contracts/openapi.json frontend/lib/api/generated.ts
```

### 11. Acceptance Criteria

- Regeneration from backend source produces zero diff in a clean checkout.
- No frontend transport uses an ungenerated handwritten wire response for covered endpoints.
- All mock responses validate and every unmatched backend request fails the owning test.
- Mocked Playwright is 33/33 (or its updated intentional count) and no-mock critical flow passes.
- Actual ASGI samples validate against OpenAPI for success and documented errors.

### 12. Rollback Plan

Migrate endpoint groups in separate commits while retaining old mappers until each group is verified. If generator output is unstable, keep canonical OpenAPI/schema-validation and temporarily pause client generation for that group; do not return to unvalidated copied fixtures. API compatibility changes should be versioned/reverted independently.

### 13. Estimated Complexity

**High — 5 to 8 engineering days** for infrastructure plus incremental client migration.

### 14. Dependencies on Other Phases

Phase 8 pins tools; Phase 7 enforces drift. Phases 1,6,9 introduce/adjust response contracts and should land before final generation. Phase 12's E2E accessibility gate uses the shared mock/live setup.

### 15. Definition of Done

- [ ] Canonical OpenAPI and generated wire types are committed/deterministic.
- [ ] Clients maintain explicit, tested wire/domain boundaries.
- [ ] Central mocks validate bodies and reject unmatched requests.
- [ ] ASGI and browser contract gates are green and required.
- [ ] Secret fields remain absent from public schemas.

## Phase 11 — Story Inbox Large-List Performance Timeout

### 1. Problem Statement

The Story Inbox renders more than 200 complex rows and updates selection in a way that can rerender and linearly scan the entire list. Its 201-row bulk-selection test exceeded its explicit 10-second budget in the full audit, although it passes in isolation. Production interaction cost has not been profiled.

### 2. Status

**Strongly supported.** The audit repeatedly observed 10.6-11.7 seconds under the broader suite, while the current isolated focused run passed (14 tests across two files in 5.10 seconds). The code has clear scaling costs, but the share caused by JSDOM/test contention versus production rendering is unmeasured.

### 3. Evidence

- `frontend/tests/story-inbox.test.tsx:234-244` creates 201 stories, waits for all checkboxes, selects 200, performs a failed bulk mutation, and sets an explicit 10,000 ms timeout.
- `frontend/components/editorial/story-inbox.tsx:19-40` requests up to 200 records, stores selected IDs as an array, and accumulates pages in component state (`:104-115`).
- `:125-140` maps every story into a complex `StoryRow`; each row executes `selected.includes(story.id)` and receives new inline callback functions on every parent render.
- `StoryRow` at `:146-184` is not memoized and includes Card/actions/query hooks. Selecting 200 replaces state and rerenders the full tree.
- There is no pagination window or virtualization; repeated “load more” can grow the DOM beyond 200.
- Runtime evidence: `docs/production-readiness-audit-2026-07-15.md:262-268,406-408`.
- Current `npm test -- tests/story-inbox.test.tsx tests/button-contrast.test.tsx` passed; this rules out a deterministic >10 s isolated failure, not the scaling concern.

### 4. Root Cause

- **Primary root cause:** unbounded/large DOM rendering plus parent-wide selection state updates, with O(n) array membership and unstable props for every row.
- **Contributing factors:** 200 default page size, append-only pagination, complex accessible role queries in JSDOM, full-suite CPU contention, and no production performance budget/profile.
- **Symptoms:** test timeout, delayed bulk-selection feedback, and potential long tasks as pages accumulate.
- **Secondary risks:** merely raising the timeout hides production INP; naive virtualization can break expanded rows, deep-link focus, screen-reader list semantics, and selection across pages.

### 5. Impact

The current issue is primarily user experience and test reliability, not data integrity. Slow feedback can cause repeat clicks or uncertainty around destructive bulk actions. Large DOMs consume memory and make filtering/scrolling/focus slower. A broken optimization could harm accessibility or bulk selection correctness.

### 6. Recommended Solution

Profile first in a production browser at 200, 1,000, and 10,000 available/accumulated records. Then apply the smallest data-structure/render fixes (`Set` membership, memoized row, stable callbacks) and bound the rendered window with cursor pagination or accessible virtualization. Prefer server-side cursor pages of 50-100 and a maximum retained/rendered window; if product requirements demand continuous accumulated scrolling, use TanStack Virtual with measured dynamic rows and keep expanded/deep-linked content mounted appropriately. Split correctness tests from a Playwright performance budget rather than using a larger Vitest timeout.

### 7. Rejected or Alternative Solutions

- **Increase the test timeout:** improves CI pass rate but supplies no evidence that production interaction is acceptable.
- **`useMemo` everywhere:** unstable callbacks and a large DOM remain; memoization must follow measured prop stability.
- **Virtualize immediately without profiling:** can add focus/height/semantic regressions and may not address test setup overhead.
- **Client-render all 10,000 with a `Set`:** membership improves but DOM/layout remain unbounded.
- **Reduce the test to a tiny list only:** preserves correctness coverage but deletes the regression signal; keep separate scale/performance coverage.

### 8. Step-by-Step Implementation Plan

1. Add browser instrumentation around initial list commit, select-visible, single toggle, filter, and bulk-response state; collect React Profiler commits, DOM nodes, long tasks, memory, and INP-like event duration at 200/1k/10k in production build. Reason/result: attribute product versus JSDOM cost. Dependency: Phase 7 scheduled benchmark. Risk: instrumentation overhead; development/test only.
2. Change selected state to `Set<string>` with immutable updates and derive request arrays only at the API boundary. Reason/result: O(1) membership. Risk: React state mutation; always create a new Set and test order-independent payload.
3. Wrap `StoryRow` with `memo`, move row actions to stable `useCallback` handlers keyed by ID, and avoid parent-created closures/objects where profiling shows benefit. Reason/result: unchanged rows skip commits. Risk: stale closures; exhaustive behavior tests.
4. Lower server page size to 50-100 and define a bounded retained-page policy. Preserve a global selected-ID set capped at 200 and clearly show selection beyond the current page. Reason/result: predictable DOM/memory. Risk: cursor/filter/deep-link behavior; tests.
5. If continuous accumulated rows remain required, add `@tanstack/react-virtual`: semantic list/listitem structure, overscan, `measureElement` for expanded rows, scroll-to/focus for deep links, and a non-virtualized expanded detail region if necessary. Reason/result: rendered rows stay <=80. Dependency: Phase 8 dependency review. Risk: keyboard/screen-reader regression; Phase 12 checks.
6. Refactor the 201-row Vitest test into bounded correctness tests plus a production Playwright performance test. Keep a reasonable watchdog, but assert measured interaction thresholds rather than wall time for JSDOM setup. Reason/result: stable, meaningful gate.

### 9. Required Tests

- Unit: Set selection cap 200, toggle, clear, failed mutation retains selection, successful mutation clears, page/filter changes follow defined policy.
- Render-count test: toggling one item does not rerender every unchanged row after memoization.
- Browser benchmarks at 200/1k/10k data: initial render, select up to 200, individual toggle, scroll, filter, and failure response.
- DOM/window assertion: virtualized/windowed mode renders <=80 rows at once while correct total/selection is announced.
- Accessibility: list semantics, checkbox names/states, keyboard navigation, focus restoration, deep-link evidence focus, 200% zoom, and screen-reader count announcement.
- Network: cursor ordering/dedup, out-of-order load cancellation, failed page, and server filter/sort.
- Regression under full Vitest parallel load and low-resource CI runner.

### 10. Validation Commands

```bash
cd frontend
npm test -- tests/story-inbox.test.tsx
npm run build
npx playwright test e2e/story-inbox-performance.spec.ts --project=chromium
npx playwright test e2e/accessibility.spec.ts --project=chromium
```

### 11. Acceptance Criteria

- Selection visual feedback p95 is <=100 ms at 200, 1,000, and 10,000 available records on the reference production-build runner.
- Select-up-to-200 completes p95 <=200 ms; no single UI long task exceeds 100 ms.
- Rendered row count remains <=80 in continuous mode, or <=100 under explicit pagination; selection remains capped/correct.
- Initial usable page p95 <=1.5 s on the reference fixture/network, and scrolling maintains >=55 fps over the sampled interval.
- Correctness tests pass at the normal timeout under full-suite concurrency; no accessibility regression.

### 12. Rollback Plan

Land Set/memo/paging/virtualization separately behind a component flag. If virtualization regresses focus or dynamic expansion, switch to bounded cursor pagination while retaining Set/memo improvements and the performance benchmark. Never roll back by only raising the timeout.

### 13. Estimated Complexity

**Medium — 3 to 6 engineering days**, depending on whether pagination is sufficient or accessible virtualization is required.

### 14. Dependencies on Other Phases

Phase 7 hosts stable benchmarks; Phase 8 pins any virtualization dependency; Phase 10 supplies typed cursor contracts; Phase 12 must approve semantics/focus. It does not block P0 repairs.

### 15. Definition of Done

- [ ] Production-browser profile identifies the dominant cost.
- [ ] Selection membership/row props no longer scale unnecessarily.
- [ ] Rendered DOM is bounded by pagination/windowing.
- [ ] Measurable latency/DOM/fps budgets pass at 200/1k/10k.
- [ ] Bulk, cursor, deep-link, keyboard, and screen-reader behavior remain correct.

## Phase 12 — Diagnostics Accessibility and Contrast Issue

### 1. Problem Statement

Diagnostics renders at least one status/error treatment whose text/background contrast fails automated WCAG checks at desktop and mobile widths. The shared destructive badge uses a translucent destructive background with destructive-colored small text, and status palettes are not consistently defined for both themes.

### 2. Status

**Confirmed.** The deployed Axe run reported a serious `color-contrast` violation on Diagnostics at both viewports. Current code contains the matching low-contrast destructive badge treatment; a fresh live Axe reproduction is pending the repaired E2E contract from Phase 10.

### 3. Evidence

- `frontend/features/operations/diagnostics-dashboard.tsx:81-90` renders error attention severity with `<Badge variant="destructive">`.
- `frontend/components/ui/badge.tsx:15-16` defines that variant as `bg-destructive/10 text-destructive`, with only a 20% background in dark mode. This is 12 px normal text (`:8`) and therefore needs 4.5:1 contrast.
- Light destructive token is HSL `0 84% 60%` (`frontend/app/globals.css:7-18`); dark token is `oklch(0.704 0.191 22.216)` (`:156-172`). Translucent same-hue background/foreground is not an explicit contrast pair.
- Diagnostics component status badges use explicit light text/border classes but no dark variants (`diagnostics-dashboard.tsx:16-21`). Status is also written as text and icon, so it is not color-only.
- The button destructive variant already uses explicit high-contrast light/dark pairs, and `frontend/tests/button-contrast.test.tsx:3-10` protects it. No equivalent badge test exists.
- Global focus-visible and reduced-motion rules exist (`frontend/app/globals.css:79-110`); component markup has headings, time elements, named review links, and `aria-hidden` decorative icons. The confirmed issue is narrower than “Diagnostics is inaccessible.”
- Audit evidence: `docs/production-readiness-audit-2026-07-15.md:262-272,418-420`.

### 4. Root Cause

- **Primary root cause:** the destructive badge derives foreground and a translucent background from one token rather than an approved foreground/background contrast pair.
- **Contributing factors:** badge variants lack contrast regression tests; status utility classes are light-theme-centric; E2E contract drift prevents the accessibility suite from being a reliable gate.
- **Symptoms:** serious Axe violation on the error attention badge in desktop/mobile Diagnostics.
- **Secondary risks:** dark/high-contrast/forced-color modes, focus states, future warning/success badges, and small text can regress even if the one node is patched. Color-only risk is currently mitigated by visible text/icon but must remain so.

### 5. Impact

Low-vision users may be unable to read critical operational errors—the most important information on the page. This fails the intended WCAG AA release bar and weakens incident response. It does not alter data, but inaccessible diagnostics can delay safe recovery. A global token change could regress unrelated buttons/charts, so the fix should be semantic and tested.

### 6. Recommended Solution

Define semantic status badge variants with explicit light/dark foreground, background, border, and focus colors, following the already-correct destructive button pattern (for example, dark red text on pale red in light mode and pale red on very dark red in dark mode). Target WCAG 2.2 AA: 4.5:1 for normal text, 3:1 for large text and meaningful non-text UI/focus indicators. Keep text plus icon/status, do not encode state by color alone. Run component and real-browser Axe tests in both themes and manual keyboard/screen-reader/forced-color checks.

### 7. Rejected or Alternative Solutions

- **Darken the global `--destructive` token only:** may repair one foreground but break buttons/charts and still leaves translucent pairing unpredictable.
- **Suppress the Axe rule/node:** hides a real readability failure.
- **Increase badge text size until 3:1 applies:** distorts the design and does not address theme/focus pairs.
- **Use only an icon:** removes readable status and creates color/shape ambiguity.
- **Fix Diagnostics with a one-off class:** works locally but leaves the shared destructive badge unsafe elsewhere; fix the semantic component and test Diagnostics.

### 8. Step-by-Step Implementation Plan

1. Capture the exact Axe node, computed colors, contrast ratio, theme, and viewport in a repaired live/mocked test. Reason/result: prove the target and prevent fixing the wrong node. Dependency: Phase 10 route mocks. Risk: no attention error fixture; include one.
2. Add explicit semantic badge palettes in `frontend/components/ui/badge.tsx` (or CSS variables such as `--status-error-bg/fg/border`) for error, warning, success, and neutral across light/dark. Reason/result: contrast is designed as pairs. Risk: visual changes across all Badge consumers; inventory snapshots.
3. Replace Diagnostics ad hoc status classes with semantic variants while retaining visible label and decorative icon semantics. Reason/result: consistent theme behavior. Risk: type variant expansion; exhaustively map statuses.
4. Add static palette tests comparable to `button-contrast.test.tsx`, plus a computed-color DOM/browser contrast test. Reason/result: classes alone do not prove rendered contrast. Risk: JSDOM cannot compute Tailwind output; use Playwright for final ratio.
5. Extend Playwright accessibility to Diagnostics error/healthy/unknown states at 390 px and 1440 px, light and dark; fail serious/critical violations and attach Axe JSON/screenshot. Reason/result: release gate. Dependency: Phases 7/10.
6. Manually verify keyboard order, visible focus, names/landmarks, status announcements, 200%/400% zoom, RTL/Persian content, reduced motion, forced colors, and NVDA/VoiceOver. Reason/result: cover behavior Axe cannot.

### 9. Required Tests

- Unit: every status maps to visible text and the expected semantic variant; icons are decorative.
- Palette regression: light/dark foreground/background pairs meet 4.5:1; focus/borders meet 3:1 where meaningful.
- Axe browser tests at mobile/desktop and light/dark for error, warning, healthy, down, unknown, empty, loading, and API-error states.
- Keyboard: skip link, page headings, review links, focus order/visibility, no trap.
- Screen-reader: component/status labels and timestamps are understandable; no duplicated icon name.
- Zoom/reflow/RTL/forced-colors/reduced-motion manual checklist.

### 10. Validation Commands

```bash
cd frontend
npm test -- tests/diagnostics-dashboard.test.tsx tests/badge-contrast.test.tsx \
  tests/button-contrast.test.tsx
npm run build
npx playwright test e2e/accessibility.spec.ts e2e/full-platform-acceptance.spec.ts \
  --project=chromium
```

### 11. Acceptance Criteria

- Zero serious/critical Axe violations on Diagnostics in both themes and both reference widths.
- All normal status/error text has measured contrast >=4.5:1; meaningful non-text/focus indicators >=3:1.
- Status remains understandable without color and under forced colors.
- All controls are keyboard reachable with visible focus; 200% zoom has no information/action loss.
- Manual screen-reader/RTL checklist has no blocker and is attached to release evidence.

### 12. Rollback Plan

Keep semantic palette changes isolated. If a shared Badge change regresses another page, temporarily apply the verified semantic status class to Diagnostics while correcting the component; never roll back to the failing colors or disable Axe. Retain screenshots/ratios to compare.

### 13. Estimated Complexity

**Low — 1 to 2 engineering days**, plus manual assistive-technology verification.

### 14. Dependencies on Other Phases

Phase 10 must make the Diagnostics fixture/routes reliable; Phase 7 makes Axe blocking. Coordinate with Phase 11 if list virtualization changes semantics. No P0 dependency.

### 15. Definition of Done

- [ ] Exact failing node/ratio is captured.
- [ ] Semantic light/dark status pairs replace translucent destructive text treatment.
- [ ] Automated contrast/Axe/keyboard tests pass at required states/viewports.
- [ ] Manual zoom, forced-color, RTL, and screen-reader checks pass.
- [ ] WCAG 2.2 AA evidence is retained.

## Phase 13 — Real Persian Generation Quality Is Unproven

### 1. Problem Statement

The structural generation pipeline works with its deterministic fake provider, but every attempted live OpenRouter path produced no usable content. There is therefore no evidence that NewsCraft can reliably create accurate, natural, grounded Persian output across its four platforms, and one provider failure cannot currently be diagnosed precisely.

### 2. Status

**Blocked by environment.** The absence of usable live output is confirmed, as are an invalid-output observability defect and model-change idempotency defect. Editorial quality itself cannot be scored until a funded, rate-stable, structured-output-compatible model is authorized and produces the controlled corpus.

### 3. Evidence

- Live attempt 1, `openai/gpt-5-mini`, reached OpenRouter but returned HTTP 402 in 1.09 s; no pack. Attempt 2, `openai/gpt-oss-20b:free`, returned HTTP 200 but `openrouter_output_invalid` after 22.55 s; no pack. Attempt 3, `qwen/qwen3-next-80b-a3b-instruct:free`, returned HTTP 429 on all three attempts and exhausted its budget in about 64.9 s. See `docs/production-readiness-audit-2026-07-15.md:281-320`.
- `backend/app/generation/providers/openrouter.py:89-106` requests strict JSON Schema. `:135-215` groups response JSON, choice/content parsing, JSON Schema, Telegram Pydantic, usage, model, finish reason, and post-redaction validation failures into one `openrouter_output_invalid` and does not retain a safe stage/field descriptor.
- Generation attempts have `response_payload` and `validation_errors` columns (`backend/app/generation/models.py:114-136`), but provider parse failure occurs before a result exists, so the broad provider error leaves them largely empty.
- Default prompts require evidence-only structured output (`backend/app/generation/default_prompts.py:47-70`); platform prompts receive canonical story plus full brand JSON/output language (`backend/app/generation/handlers.py:133-155,1334-1392`). Canonical generation receives story title/evidence, not a brand language (`:994-1034`), which is defensible for reusable canonical truth but must be distinguished from Persian platform adherence.
- `TelegramRewriteOutput` strictly validates nonempty <=4096-character HTML and buttons (`backend/app/generation/telegram_schema.py:112-119`). Canonical schema requires headline, >=50-character narrative, at least one cited fact (`backend/app/generation/canonical.py:14-30`). Strictness protects persistence but may expose model incompatibility.
- Audit fake output was generic/repetitive English for a Persian brand; that is expected scaffolding and cannot be treated as model-quality evidence (`audit:227-248`).
- Content-pack enqueue hashes the request/profile ID but not current profile model/settings (`backend/app/generation/editorial_service.py:200-257,289-304`). Changing a model on the same profile returned the old failed job as deduplicated; audit `:322-323,422-426`.
- Upstream real ingestion includes Persian/RTL successfully, but also thin/link-only items, weak titles, promo misclassification, and language-hint/script conflict (`audit:117-186`). The corpus must isolate these factors rather than blaming prompts/models.

### 4. Root Cause

- **Primary root cause of the unproven state:** no authorized account/model combination completed the live structured generation path; one was unfunded, one incompatible/invalid, and one rate-limited.
- **Confirmed contributing defects:** invalid output loses its safe parse/validation stage; a mutable provider model/configuration is absent from enqueue idempotency; free-tier models were used as emergency fallbacks without a qualified compatibility baseline.
- **Unproven contributors:** prompt sufficiency, Persian naturalness, title quality, schema/model interaction, context size, and upstream evidence quality. No usable output exists to attribute failure among these.
- **Symptoms:** no content pack, no persisted platform revisions, no quality scores, and stale deduplicated failure after model change.
- **Secondary risks:** automatic fallback changes editorial behavior silently; retries add cost/latency; weak evidence can invite hallucination; raw invalid response retention could leak content/secrets if implemented carelessly.

### 5. Impact

The core product objective—useful Persian editorial output—is unvalidated. Operators cannot assess factual accuracy, unsupported claims, title/platform fit, or natural writing. Provider costs/SLOs are unknown. Invalid output diagnosis is speculative, and model changes can be ignored by idempotency. Safety controls correctly prevent bad output from publishing, but availability/product value remain blocked.

### 6. Recommended Solution

First make provider execution diagnosable and model configuration immutable/idempotent; then qualify one funded production model with a blinded, labeled 36-story Persian corpus run twice (72 packs, 288 platform variants). Do not automatically cross-model fallback. Retry the same qualified model only for explicitly retryable transport/429/5xx outcomes with provider `Retry-After`, bounded exponential backoff, jitter, cost/time budgets, and durable attempts. Any model fallback is a new reviewed provider-profile revision and evaluation cohort. Score generated claims against immutable evidence and require the thresholds below before enabling controlled production.

### 7. Rejected or Alternative Solutions

- **Declare free models good enough after one HTTP 200:** that response failed the contract and produced no inspectable content.
- **Loosen schemas until a model passes:** may improve completion by deleting integrity/platform boundaries. Diagnose the failing stage first; relax only non-integrity limits with corpus evidence.
- **Persist raw provider failures in normal DB/logs:** aids debugging but can retain source/secret/sensitive content. Store structured descriptors; use an encrypted, access-controlled, short-TTL quarantine only when explicitly enabled.
- **Automatically fall back on 402/429/invalid output:** changes model/quality/cost invisibly and can duplicate work. 402/configuration is permanent; invalid structured output needs review; 429 retries the same model within budget.
- **Evaluate only fluent text:** fluent hallucination is unsafe; claim/evidence integrity, schema, promo, cost, and latency are mandatory.
- **Tune prompts on the final test set:** overfits and invalidates the gate; split calibration and held-out evaluation examples.

### 8. Step-by-Step Implementation Plan

1. In `openrouter.py`, introduce safe diagnostic stages/codes: HTTP/body JSON, choices/message/content type, content JSON, JSON Schema path, Telegram/Pydantic location, usage, finish reason, resolved model, and redaction revalidation. Record stage, error type/path, response byte count/hash, and request/model IDs—no raw body/value. Reason/result: distinguish adapter, model, and metadata failures. Risk: paths/messages can include values; allowlist fields and redact.
2. Add optional encrypted invalid-output quarantine behind a disabled-by-default operator setting, strict size limit, worker-only key, access audit, and <=7-day retention. Reason/result: last-resort debugging. Dependency: Phase 6/15 security. Risk: sensitive content; production acceptance does not require enabling it.
3. Add provider configuration revision/checksum covering provider type, resolved model, safe settings, pricing/budgets, and prompt compatibility, excluding secret values/refs from job payload. Include revision/checksum in content-pack payload/idempotency digest and exact-revalidate before provider call. Reason/result: a model change creates new work and queued work cannot drift. Risk: migration/API changes; Phase 10 types.
4. Define the qualified provider profile: funded model, structured-output support, timeout, pricing, max tokens/cost, allowed retry classes, and no automatic cross-model fallback. Reason/result: reproducible cohort. Risk: provider model revisions; pin identifier and record resolved model.
5. Build a versioned 36-story corpus: 18 RSS/18 Telegram; 12 short/12 medium/12 long or multi-evidence; 6 hard news, 6 tutorial/analysis, 6 research/technical, 6 product announcements, and 12 promotion/borderline. Include at least 8 conflicting/multi-source, 6 deliberately insufficient-evidence, 10 mixed Persian/English/name/numeral/ZWNJ, and 6 language-hint/script conflicts across the strata. Reason/result: representative upstream/context stress.
6. Freeze immutable evidence, expected claim inventory, promo label, expected language/script, and title constraints. Split 12 calibration and 24 held-out stories; prompt changes create a new prompt version and restart held-out scoring. Reason/result: avoid test leakage. Risk: labeling bias; two reviewers and adjudication.
7. In an isolated evaluation database, run each story twice through canonical plus Telegram/Instagram/X/blog with research disabled initially; then separately test approved research-enriched cases. Give each repeat a distinct, stored evaluation-run ID in the harness execution identity so production idempotency does not return the first result; do not expose that bypass in normal APIs. Capture all 360 baseline provider calls' first/final schema result, retry reason, input/output tokens, cost, provider/resolved model, and stage latency; label and report supplemental research-enriched calls separately. Reason/result: 72 independent pack/288 platform-variant baseline reliability sample without hiding research cost or failures. Risk: cost and accidental dedup bypass; preapprove the campaign budget and confine the flag to the evaluation runner.
8. Have two blinded native-Persian editors independently score factual accuracy, evidence grounding, relevance, clarity, natural Persian, title, and platform fit on 1-5 rubrics; adjudicate >1-point differences. Label every factual claim supported/minor-unsupported/material-unsupported and every promo decision. Reason/result: reproducible human quality evidence.
9. Analyze failures by upstream evidence, prompt, schema, adapter, model, network/rate, and budget. Change one versioned factor per cohort; never edit persisted attempts. Reason/result: causal remediation rather than speculative prompt tweaking.
10. Add the qualified corpus runner/report to a protected manual/nightly environment; production enablement requires a signed result and continuous sample monitoring. Reason/result: quality remains a release property. Dependency: Phases 4,6,7,8,9.

### 9. Required Tests

- Provider unit matrix for every diagnostic stage, with no raw response/API key leakage.
- Idempotency regression: changing model/settings revision creates a new job; unchanged revision deduplicates; post-enqueue drift is rejected.
- Retry tests: 402 permanent/no retry; 429 honors `Retry-After` and budget; transport/5xx bounded; invalid schema needs review/no cross-model fallback; timeout cancels cleanly.
- Unicode/Persian: RTL text, Arabic/Persian characters, نیم‌فاصله (ZWNJ), Persian/Latin numerals, mixed brand names, HTML escaping, and no mojibake/truncation.
- Evidence/citation integrity and deliberately insufficient evidence leading to `needs_review` rather than invention.
- Corpus rubric/inter-rater calculation, cost/latency aggregation, and immutable report hash.
- Security tests for prompts/responses/diagnostics/quarantine and secret-canary absence.

### 10. Validation Commands

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_openrouter_provider.py tests/generation tests/postgres/test_multiplatform_pack_durability.py
# Protected, credentialed environment only; never PR CI:
PYTHONPATH=. .venv/bin/python -m app.validation.persian_generation \
  --corpus ../validation/persian-generation/corpus-v1.json \
  --provider-profile-id <immutable-profile-revision-id> --repeats 2 \
  --output ../validation/persian-generation/run-v1.json
PYTHONPATH=. .venv/bin/python -m app.validation.persian_generation score \
  --run ../validation/persian-generation/run-v1.json \
  --reviews ../validation/persian-generation/reviews-v1.json
```

### 11. Acceptance Criteria

- Funded qualified profile completes all 72 packs; first-attempt structured completion across the 360 required provider calls is >=98%, final structured completion is 100%, and retrying packs are <=5%.
- Zero material unsupported claim; minor unsupported claims <=2% of all factual claims; 100% factual-claim citation coverage with valid immutable locators.
- Mean human editorial score >=4.2/5; no dimension mean below 4.0; no held-out story has factual accuracy or grounding below 3.
- Correct Persian language/script/profile adherence >=95%; no full English platform output for a Persian profile; no encoding corruption.
- Title mean >=4.0/5 and no generic/link-only/incomplete title accepted on held-out cases.
- Promotional classification precision and recall each >=90% on the labeled promo/borderline subset.
- Mean generation cost per four-platform pack <=US$0.75, p95 <=US$1.50, no pack >US$2.00; p95 pack latency <=120 s and max <=180 s. Product/finance must approve any changed ceiling *before* the run.
- Inter-rater weighted agreement target >=0.70; disagreements are adjudicated and report/corpus/prompt/profile hashes are retained.

### 12. Rollback Plan

Provider/prompt/profile versions are immutable. If monitoring drops below a hard threshold, disable that profile for new work, preserve attempts, and return jobs to review—do not silently switch models. Roll back to the last separately qualified profile/prompt version and rerun a 12-story canary before resume.

### 13. Estimated Complexity

**High — 6 to 10 engineering days** for diagnostics/idempotency/harness, plus editor review time and external model cost.

### 14. Dependencies on Other Phases

Blocked by a funded compatible provider and authorization. Requires Phase 4 networking, Phase 6 secret scope, Phase 8 pins, Phase 9 capability/cost health, and Phase 7 protected manual workflow. Phase 10 covers new profile-version contracts. Phase 14 should use only a qualified output or a deliberately authored test revision.

### 15. Definition of Done

- [ ] Invalid provider failures have safe field/stage diagnostics.
- [ ] Provider model/settings revision participates in exact idempotency.
- [ ] Qualified model/retry/cost policy is frozen with no silent fallback.
- [ ] Blinded 36-story x2 corpus meets every threshold.
- [ ] Signed immutable quality report and ongoing monitor exist.

## Phase 14 — Controlled Live Telegram Publishing Is Unproven

### 1. Problem Statement

NewsCraft's Telegram publisher has strong deterministic and crash-recovery tests, but no message has been sent through the complete current stack to an authorized private/staging channel. Bot permissions, real API behavior, remote IDs/permalinks, and operator reconciliation therefore remain unproven.

### 2. Status

**Blocked by environment.** This audit had neither explicit authorization for an external send nor an approved staging destination credential. Static and PostgreSQL test evidence supports the design, but cannot substitute for a controlled live proof.

### 3. Evidence

- Approval/revision APIs are in `backend/app/api/telegram_drafts.py:909-951`; publish jobs and reconciliation endpoints are at `:982-1194`.
- `backend/app/publishing/telegram/service.py:785-1009` locks and validates existing publication, Telegram variant, approval state, dry-run, exact content hash, route provenance/control, destination enabled/healthy state, evidence snapshots, media, deterministic plan, and receipt-plan equality.
- `backend/app/publishing/models.py:34-135` uniquely constrains publish idempotency, one publication per job/destination+revision, and operation key/index receipts.
- Before each send, the service locks/revalidates and changes `pending -> dispatching` in a committed transaction (`service.py:1461-1555`). It sends at `:1597-1610`, durably stores remote IDs at `:1639-1658`, then creates/validates one `Publication` at `:1668-1721`.
- A stale `dispatching` receipt becomes `ambiguous`/`reconciliation_required`, not pending (`service.py:1011-1041`; queue lease recovery in `backend/app/jobs/repository.py:260-282,728-739`).
- `TelegramBotClient` classifies connection errors before dispatch as retryable, transport/5xx/invalid success as ambiguous, 429 as rate-limited, and 4xx as permanent (`backend/app/publishing/telegram/client.py:90-143`). It validates returned positive message IDs/counts.
- Current audit ran `backend/tests/integration/test_publish_crash_recovery.py`: all scenarios passed as part of 16 integration tests. `:435-539` proves crash after remote send creates ambiguity and replay does not call the client again; `:542-612` proves durable receipt replay skips send and completes publication.
- No real Telegram send occurred (`docs/production-readiness-audit-2026-07-15.md:31-36,491`). Exactly-once delivery cannot be guaranteed by Telegram's Bot API in an unknown network outcome because it accepts no NewsCraft idempotency key; zero-duplicate policy therefore depends on stopping and reconciling ambiguity.

### 4. Root Cause

- **Primary root cause of the unproven state:** live external publication was intentionally excluded without a dedicated credential/channel and explicit authorization.
- **Contributing factors:** real remote state cannot be inferred from a local receipt if the connection fails after dispatch; Telegram offers no request idempotency token or general sent-message lookup by NewsCraft operation key.
- **Symptoms:** no proven remote message ID/permalink, permission check, live rate behavior, or human reconciliation drill.
- **Secondary risks:** a careless validation can publish publicly, duplicate an ambiguous message, expose a Bot token, publish an edited/revoked revision, or leave test content undeleted. The current design mitigates many but requires live confirmation.

### 5. Impact

Production publication must remain disabled. A false assumption could create duplicate/publicly incorrect messages and reputational harm. On-call operators have not demonstrated the ambiguous-outcome decision path. Credential scope and destination permissions are unverified in reality. Database safety tests are strong, but external consistency is the remaining boundary.

### 6. Recommended Solution

Run a protected, explicitly authorized staging-channel qualification after P0/readiness fixes. Use a dedicated low-privilege Bot token mounted only in the publishing worker and a private channel with named owners. Begin with dry-run and a single text-only uniquely marked revision; prove success and replay suppression. Exercise all failure states against a local Telegram-compatible fault server first. For the one live ambiguous-outcome drill, deliberately stop after a known remote send only under written authorization, confirm the system never resends, have an operator inspect the channel and reconcile with exact remote IDs, then verify one remote message and one publication. Zero duplicates takes precedence over automatic recovery: any uncertain outcome stops in `needs_review`.

### 7. Rejected or Alternative Solutions

- **Enable auto-publish on a real/public channel as the test:** unacceptable blast radius and no controlled rollback.
- **Retry every timeout:** may duplicate a message that Telegram accepted before the response was lost.
- **Treat local `dispatching` as success:** invents a remote ID/publication and loses audit truth.
- **Treat every timeout as not published:** unsafe resend assumption.
- **Use message text search as automatic reconciliation:** bots may lack history/search guarantees; text can collide/change. Human verification with remote IDs is required.
- **Claim integration tests prove live delivery:** they prove local safety transitions, not token permission/network/platform behavior.

### 8. Step-by-Step Implementation Plan

1. Complete Phases 1-6 and 9; run all deterministic publish/crash tests. Reason/result: no known runtime/secret/readiness blocker reaches external action. Dependency: explicit.
2. Create a private staging channel and dedicated bot with only required post permission; record channel owner, target, token rotation/revocation, allowed hours, and cleanup policy. Store token as publishing-worker-only file secret. Reason/result: bounded authority. Risk: target typo; verify `getChat` identity/title/ID and require operator confirmation.
3. Add a protected `live-telegram-staging` environment/manual workflow requiring two approvers and parameters for destination ID, exact revision ID/hash, expected unique marker, and scenario. Never accept a token as input/artifact. Reason/result: explicit authorization/audit. Dependency: Phase 7/6.
4. Run dry-run through source/evidence/generation-or-authored revision, edit/hash invalidation, reapproval, plan, and publish-intent creation; assert zero Bot send. Reason/result: prove controls before live mode. Risk: accidental global dry-run off; workflow checks it.
5. Run text-only success: health-check destination, approve exact hash, send once, capture returned positive remote ID/permalink, verify channel manually/API where permitted, and replay the same API/job. Reason/result: one remote/local truth and idempotent replay. Risk: cleanup deletion is separate authorized action and must retain evidence first.
6. Repeat with photo, document, media group, buttons/HTML, and scheduled send within Telegram limits. Reason/result: renderer/remote response variants. Risk: test media contains no sensitive/copyrighted data.
7. Against a local fault server, execute credential failure, 4xx, 429 with `retry_after`, 5xx, connect failure, pre-send crash, mid-upload/transport timeout, after-send-before-receipt crash, after-receipt-before-publication crash, worker kill/restart, approval revocation, and content/hash edit. Reason/result: deterministic exhaustive safety.
8. Under separate explicit authorization, run one live post-send ambiguity drill using the built-in fault point immediately after a confirmed test-channel send. Verify receipt ambiguous, workflow needs review, restart/replay makes zero client send, operator records exact outcome/remote IDs, and reconciliation is idempotent/conflict-fenced. Reason/result: prove the irreducible external boundary. Risk: deliberately uncertain message; two-person observation required.
9. Add metrics/alerts/runbook for `dispatching` age, ambiguity, reconciliation age, duplicate marker, permission/token failure, 429, and worker availability. Reason/result: safe ongoing operation. Dependency: Phase 9.

### 9. Required Tests

- Dry-run: no client call and no `Publication`.
- Success for text/photo/document/media group/buttons; exact operation order, IDs, permalink, hash, receipt, attempt, publication/event.
- Crash before send: safe retry once; during/after send: ambiguity/no retry; after receipt: replay skips send and finishes.
- Timeout/5xx unknown outcome, 429 scheduled retry without duplicate, 4xx/credential permanent failure, revoked bot/permissions.
- Duplicate API request, duplicate worker delivery, concurrent worker claim, stale lease owner, process/container restart.
- Approval revoked, parent edited, content/evidence/hash mismatch before first and between multiple operations.
- Reconciliation published/not-published, stale/conflicting/replayed decisions, remote ID count/uniqueness.
- Secret canary absent from logs, attempts, responses, receipts, events, screenshots/artifacts.
- Live staging remote assertion: exactly one message per unique marker/scenario.

### 10. Validation Commands

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_telegram_renderer.py tests/test_telegram_bot_client.py \
  tests/test_telegram_publish_service.py tests/test_telegram_reconciliation_api.py \
  tests/integration/test_publish_crash_recovery.py
# Protected staging environment and explicit authorization only:
gh workflow run live-telegram-staging.yml \
  -f destination_id=<staging-destination-id> \
  -f revision_id=<approved-revision-id> -f content_hash=<exact-hash> \
  -f scenario=success -f marker=<unique-nonsecret-marker>
```

### 11. Acceptance Criteria

- Dry-run produces zero remote message; successful live scenario produces exactly one remote message and one confirmed local `Publication` with matching ID/hash/permalink.
- Replaying API/job/restart/concurrent claim produces zero additional remote messages.
- Any unknown delivery state creates one ambiguous receipt and blocks automatic resend indefinitely until an operator decision.
- Published reconciliation requires verified positive remote IDs and is idempotent; conflicting/stale decisions return 409.
- Approval/hash/evidence/control/credential failures cause zero sends.
- All listed deterministic fault tests pass; live success and one authorized ambiguity drill have signed two-person evidence and zero secret leakage.

### 12. Rollback Plan

Set global dry-run/pause, disable the route and destination, stop publishing worker, and revoke/rotate the staging token. Do not retry or delete an ambiguous message until reconciled. Roll back code/deployment only after recording receipts/remote state; preserve publication/audit rows. Any message deletion is a separately authorized platform action after evidence capture.

### 13. Estimated Complexity

**High — 4 to 7 engineering days** for harness/runbook/observability plus a controlled staging window; core receipt logic already exists.

### 14. Dependencies on Other Phases

Blocked by explicit external authorization/credential. Requires Phases 1-6 and 9; Phase 7 protects the workflow; Phase 10 provides current contracts; Phase 13 is required only if generated rather than operator-authored copy is being qualified. Phase 15 should precede broader production, not the private-channel test.

### 15. Definition of Done

- [ ] Dedicated private channel/token and two-person protected workflow exist.
- [ ] Dry-run, deterministic fault matrix, and restart tests pass.
- [ ] Live success yields exactly one matching remote/local publication.
- [ ] Authorized ambiguity drill proves no resend and correct reconciliation.
- [ ] Token canary is absent and rollback/revocation evidence is retained.

## Phase 15 — Backup and Restore Have Not Been Proven End to End

### 1. Problem Statement

NewsCraft can create and statically verify a database/media/export archive, and it has a destructive restore script/runbook. It has not restored a real archive into a disposable current stack and proved relational/file/application usability. Moreover, current backup capture is not cross-store consistent, archives are not encrypted by the tool, version compatibility is recorded but not enforced, and archive retention is manual.

### 2. Status

**Blocked by environment.** Static gaps are confirmed and unit tests are strong, but an actual restore is destructive. No running source stack, disposable drill authorization, or approved backup key/storage was available in this planning turn, so no end-to-end drill was performed.

### 3. Evidence

- `scripts/backup_restore.py:130-252` sequentially runs live `pg_dump`, then tars media, then exports while API/workers/scheduler remain active. PostgreSQL dump is transactionally consistent internally, but its snapshot is not coordinated with later filesystem captures.
- The tar commands use the running API (`:146-193`), preventing a simple stop-all-writers procedure without changing the capture service.
- Manifest records Git SHA, Alembic current/head, PostgreSQL version, byte counts, and SHA-256 (`:195-233`). Verification enforces exact members/checksums/safe paths and custom dump header (`:488-677`).
- Archive/staging modes are 0600/0700 and publish is fsync/hard-link based (`:130-140,228-251,470-486`). The archive itself is plaintext; docs only instruct operators to copy it via approved encrypted storage (`docs/operations/backup-and-restore.md:31-47`).
- Restore requires `--confirm-replace`, validates `pg_restore --list`, stops five runtime services, drops/recreates the fixed database, restores DB, destructively replaces current media/exports, migrates, and restarts (`scripts/backup_restore.py:267-388,412-430`). A mid-restore failure leaves services stopped but may leave partially replaced stores; there is no automatic old-volume rollback.
- Manifest verification checks that version strings are nonempty, not that the restore client/server/application is compatible (`:637-676`).
- No archive rotation/retention implementation exists; application retention is separate from disaster-recovery backup retention.
- `docs/operations/backup-and-restore.md:96-163` describes post-restore counts and a quarterly separate Compose project, but no committed drill result proves it was run. The audit explicitly excluded destructive restore (`docs/production-readiness-audit-2026-07-15.md:31-36`).
- `backend/tests/operations/test_backup_restore_script.py` covers commands, checksums, corrupt/missing/unsafe archives, explicit confirmation, order, containment, and CLI (tests at `:197-749`). Its focused suite passed within the 170-test current run. It uses `FakeRunner`, not PostgreSQL/volumes.
- The current raw validation artifact is owned by `nobody:nobody` with mode 0600, so the operator user cannot read it; future drill artifacts need deliberate ownership/retention.

### 4. Root Cause

- **Primary root cause of the unproven state:** verification stops at archive structure/command simulation; no automated disposable restore and application smoke closes the loop.
- **Confirmed design gaps:** database and files are captured at different live times; plaintext archive; no enforced version matrix; no backup rotation; in-place restore is not atomic across three stores.
- **Symptoms:** unknown RPO/RTO, referential/file consistency, credential exclusion, real `pg_restore`, migrated app health, and corrupted/partial operational behavior.
- **Secondary risks:** DB rows may reference a file created/deleted outside the dump snapshot; plaintext off-host theft; current-client restore incompatibility; partial destructive restore; accidental cleanup of the primary Compose project; credential values accidentally persisted in DB/media/export would be backed up.

### 5. Impact

Disaster recovery cannot be claimed. A verified archive may still restore into an unusable cross-store state. Failure during in-place restore can extend outage and complicate rollback. Plaintext backups expand breach impact. Unknown retention/RPO can cause unacceptable loss, while untested version drift can make the only archive unreadable during an incident.

### 6. Recommended Solution

For the current local Compose architecture, choose correctness over zero-downtime: quiesce every writer, capture DB/media/exports from a dedicated read-only backup service, verify, encrypt/authenticate with a backup-only key, publish atomically off-host, then resume. Add generation retention and compatibility preflight. Restore drills must create a separate Compose project/volumes/database, decrypt and verify, restore with a compatible image, run migrations/integrity/file checks and the credential-free smoke, measure RPO/RTO, and preserve a signed report. For production recovery, prefer restore-into-new database/volumes followed by a controlled cutover, retaining old stores for rollback, rather than destructive in-place replacement.

### 7. Rejected or Alternative Solutions

- **Trust checksums/unit tests as restore proof:** they validate bytes and command order, not PostgreSQL constraints/files/application startup.
- **Keep live sequential capture:** low downtime but no shared snapshot across PostgreSQL/filesystems.
- **Global pause only:** scheduled automation pauses, but API/manual writes and in-flight workers can still change DB/files. Stop/drain all writers or implement a true application backup barrier.
- **Archive `.env` for convenience:** backs up live authority and violates credential separation. Restore configuration from the secret manager separately.
- **Encrypt by filesystem permissions only:** 0600 does not protect copied/off-host/stolen media.
- **Test restore against the primary project:** unnecessary destructive risk; use a named disposable project and verify its labels before cleanup.
- **Migrate first, then restore an old dump into current schema:** can conflict. Restore with recorded-compatible code/schema/client, then run forward migrations.

### 8. Step-by-Step Implementation Plan

1. Set and approve SLOs: baseline RPO <=24 h, RTO <=2 h, nightly backups, retain 7 daily/5 weekly/12 monthly, quarterly restore drill; adjust only through an explicit business decision. Reason/result: objective schedule/capacity. Risk: storage cost; measure archive sizes.
2. Add a dedicated `backup` Compose service/image with matching PostgreSQL client and read-only media/export mounts; it receives no OpenRouter/Telegram credentials and uses a backup-recipient/encryption key file only. Reason/result: backup does not require a running privileged API. Dependency: Phase 6/8. Risk: client/server major compatibility; pin digest.
3. Implement quiesce protocol: block new mutations, pause automation, drain/terminalize in-flight jobs, stop API/workers/scheduler, verify no DB writer sessions, then capture DB and both volumes. Frontend may show maintenance. Resume only after archive verify/encrypt/publish. Reason/result: one cross-store point. Risk: downtime/failure; timeout and recovery command.
4. Extend manifest with backup ID, code/image digests, PostgreSQL dump/client/server major, schema head, quiesce start/end, per-store inventory/root hash, and declared consistency mode. Reason/result: compatibility and proof. Risk: do not include environment/host secrets.
5. Encrypt after internal verification using an approved authenticated tool (for example `age` recipients or an encrypted backup repository). Extend backup `verify`/`restore` to accept the encrypted format and decrypt only into private encrypted-storage or tmpfs staging using a file-mounted identity. Fsync encrypted output, verify decrypt+manifest, atomically publish, then unlink plaintext staging (secure deletion is not guaranteed on copy-on-write media). Keep the decryption key outside application services. Reason/result: confidential/authenticated archive with an executable CLI path. Risk: key loss/plaintext remnants; escrow/rotation drill and encrypted staging.
6. Add retention/pruning that never deletes the newest verified backup or the last member of a generation; verify before and after off-host transfer; alert on missed/failed/old backup and capacity. Reason/result: bounded safe history. Risk: timezone/generation bug; dry-run and two-phase deletion.
7. Add compatibility preflight: select recorded PostgreSQL client image, reject unsupported major path with an actionable code, restore recorded schema/code first, then run forward Alembic migrations. Reason/result: no surprise during outage. Risk: old images unavailable; retain approved restore images.
8. Add `restore --project-name/--target` or a separate drill orchestrator that creates uniquely labeled disposable project/networks/volumes, refuses a primary project name, checks free ports/space, and never runs `down -v` without matching drill labels. Reason/result: safe repeatable drill. Risk: cleanup error; require printed/confirmed IDs.
9. Restore into new stores, not current ones: new database/volumes, validate, then controlled configuration/volume cutover; retain old stores read-only through rollback window. Keep in-place mode only for documented local emergency with explicit confirmation. Reason/result: rollbackable recovery. Risk: Compose volume switch complexity; rehearse.
10. Automate proof: compare pre-backup/restored table counts and selected row hashes, run `NOT VALID`/FK/orphan checks as appropriate, compare every media/export inventory hash, verify a representative export download, check Alembic head, start full stack, run readiness and credential-free smoke. Reason/result: actual usability.
11. Seed a unique secret canary only in runtime secret storage (never legitimate data), and make the drill return a count-only scan over restored DB/text/JSON plus media/export bytes; require zero. Verify `.env`, Compose render, logs, and secret files are absent from archive members. Reason/result: credential exclusion proof without printing value. Risk: scan implementation must not log/decompress raw matches.
12. Save a mode-0600 operator-owned drill report containing archive/manifest hash, project/volume IDs, versions, counts/hashes, smoke result, RPO/RTO, failures, approvers, and cleanup/rollback result. Reason/result: auditable proof. Risk: report itself must contain no values.

### 9. Required Tests

- Existing unit corruption/safe-path/partial/archive/order suite remains green.
- Quiesce integration: concurrent API/job write is drained/blocked; manifest consistency point encloses all three captures; services recover after backup failure.
- PostgreSQL real backup/restore with constraints, sequences, extensions, large objects if used, Unicode/Persian, and migration from supported prior version.
- Media/export create/update/delete race fixtures prove no row/file mismatch in quiesced backup.
- Encryption: wrong/missing key, tampered ciphertext, interrupted encryption/publish, key rotation/escrow recovery.
- Retention: daily/weekly/monthly generations, clock boundaries, partial/failed backups, last-good protection, capacity alerts.
- Restore failure after DB, media, export, migration, and start; old stores remain available and disposable services contained.
- Referential/orphan/count/hash/application smoke and secret-canary zero scan.
- Quarterly full disposable drill from an off-host copy, with measured RPO/RTO and cleanup label safety.

### 10. Validation Commands

```bash
python scripts/backup_restore.py backup --output-dir ./backups
python scripts/backup_restore.py verify ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz.age
# Disposable project only; exact command should be wrapped by the new drill tool:
python scripts/restore_drill.py \
  --archive ./backups/newscraft-YYYYMMDDTHHMMSSZ.newscraft-backup.tar.gz.age \
  --project-name newscraft-restore-drill-YYYYMMDD --confirm-disposable
docker compose -p newscraft-restore-drill-YYYYMMDD ps
curl -fsS http://127.0.0.1:<drill-api-port>/health/ready
python scripts/smoke.py --base-url http://127.0.0.1:<drill-api-port> \
  --provider fake --telegram-mode dry-run --output-dir /tmp/newscraft-restore-smoke
```

### 11. Acceptance Criteria

- Backup is captured under verified quiescence, encrypted/authenticated before leaving private staging, and no final partial/plaintext artifact remains.
- Disposable restore reproduces database selected counts/hashes, zero FK/orphan violations, and exact media/export inventory hashes.
- Restored stack reaches Alembic head/core readiness and completes credential-free fake-provider/dry-run smoke.
- Secret canary count is zero across DB/media/exports/manifest/report; archive contains only declared encrypted payload.
- Baseline RPO <=24 h and measured RTO <=2 h; retention keeps 7 daily/5 weekly/12 monthly and never prunes last verified.
- A deliberately corrupt/partial/wrong-key archive is rejected before destructive/cutover action.
- Old stores remain rollbackable until the drill/cutover is signed complete.

### 12. Rollback Plan

For backups, failure resumes the prior writer set only after confirming no partial final artifact and records a missed-backup alert. For restore, do not modify primary stores during the drill. In production cutover, stop new writers, switch back to retained old DB/volume identifiers, restart, verify readiness, and preserve failed new stores for analysis. Never automatically start services after an uncontained partial in-place restore.

### 13. Estimated Complexity

**High — 7 to 12 engineering days**, plus storage/key setup and a scheduled drill window.

### 14. Dependencies on Other Phases

Requires Phase 6 credential topology, Phase 8 pinned compatible images, Phase 9 readiness/smoke, and Phase 3 synchronized service control. Phase 7 schedules/retains drill evidence. It is a production gate before anything beyond controlled staging.

### 15. Definition of Done

- [ ] Cross-store capture is quiesced and versioned.
- [ ] Backups are encrypted, verified, transferred, retained, and monitored.
- [ ] Restore targets new disposable/new production stores with safe project labels.
- [ ] DB/file/integrity/no-secret/application smoke proof passes within RPO/RTO.
- [ ] Operator-owned signed drill evidence and rollback result are retained.

## Final Execution Order

The order below deliberately puts correctness before supervision and observability before live external validation. Work inside a priority group may be parallelized only where its listed dependency is not crossed.

### P0 — Immediate runtime and security blockers

1. **Phase 2 — Worker execution/session boundary.** First because completed side effects can outlive an uncompleted job, and because restart policy would otherwise supervise a known deterministic crash.
2. **Phase 1 — Telegram route response materialization.** Small, high-impact repair that makes state-changing API results truthful and unblocks the official smoke workflow.
3. **Phase 5 — Uvicorn-safe logging/redaction.** Restore trustworthy, secret-safe evidence before proxy/restart/readiness drills.
4. **Phase 4 — Normalized optional proxy.** Restore deterministic external networking; validate direct and approved-proxy modes with safe logs.
5. **Phase 6 — Strict credential topology.** Remove worker authority and repository `.env` access from API; expose only safe worker-observed capability state.
6. **Phase 3 — Restart supervision.** Enable only after the worker crash fix; add one-shot migration, health visibility, kill/poison-job drills, and alerts.

P0 exit: ten fresh-database and three same-database official fake/dry-run smoke runs; zero route 500, worker exit, unexpected lease recovery, formatter exception, forced proxy, secret topology violation, or duplicate durable side effect.

### P1 — Production-readiness requirements

1. **Phase 8 — Dependency locking/images.** Establish frozen toolchains and production-only images for all subsequent automation.
2. **Phase 7 — CI and branch protection.** Initially land P0/static/database/frontend gates; expand as the following phases become green.
3. **Phase 10 — OpenAPI contracts and validated mocks.** Make API/UI changes and browser results enforceable.
4. **Phase 9 — Real readiness/operational health.** Build on safe capability state and expose the final health/alert contract through generated types.
5. **Phase 12 — Diagnostics WCAG fix.** Repair and require the now-reliable accessibility suite.
6. **Phase 11 — Inbox profiling/bounded rendering.** Use the pinned frontend and CI browser benchmark; accessibility signs off the optimization.
7. **Phase 15 — Encrypted, consistent backup and disposable restore proof.** Last P1 gate because it consumes final service topology, images, readiness, smoke, and secret boundaries.

P1 exit: protected CI is green from a clean checkout; fresh/supported database upgrades pass; OpenAPI/mocks have zero drift; health failure drills/alerts pass; WCAG/performance budgets pass; and a disposable encrypted restore meets RPO/RTO/integrity/no-secret/smoke gates.

### P2 — Product-quality and external-side-effect validation

1. **Phase 13 — Qualified Persian generation.** Fund and pin a compatible model, repair diagnostics/idempotency, and pass the blinded 36-story x2 evaluation.
2. **Phase 14 — Controlled Telegram publication.** Use a qualified generated revision or an explicitly authored test revision in a protected private channel; prove success, no duplicate replay, and one authorized ambiguity reconciliation.

P2 exit: every Phase 13 quantitative threshold and every Phase 14 remote/local/no-duplicate/no-secret assertion passes with signed evidence.

### P3 — Non-blocking improvements after the controlled-production gate

No unresolved phase is intentionally deferred to P3. Optional follow-ups include migrating Compose supervision to an orchestrator with native probes/backoff, expanding OpenAPI generation to all internal tools, automating more quality sampling, and adopting snapshot-capable object storage/backups. They must not be used to waive a P0-P2 acceptance criterion.

## Cross-Phase Regression Plan

Use immutable run IDs and retain sanitized JUnit, Playwright, smoke, SBOM, quality, publication, and restore artifacts. PR rows are merge-blocking; scheduled/manual rows become release-blocking before controlled production.

| Scenario | Primary phases | Test setup and objective assertions | Cadence/gate |
|---|---|---|---|
| Fresh database | 1,2,7,8,9,10 | Empty PostgreSQL 18 `_test`; Alembic single head/upgrade; seed once; ASGI route mutations return 2xx; fake/dry-run workflow completes; readiness green | Every PR and 10-run P0 exit |
| Existing database | 1,2,7,8,10 | Restore oldest supported fixture, migrate, seed idempotently, rerun smoke three times; no 409 poison data, duplicate prompts/jobs/revisions, or contract drift | PR migration job + release |
| Worker restart | 2,3,9,14 | SIGKILL each worker during before-side-effect, after-durable-side-effect, and publish ambiguity points; restart/heartbeat/capability within bounds; stale owner fenced; no duplicate | PR fault integration + nightly container drill |
| API restart | 1,3,6,9 | Restart after committed mutation and during queued work; no secret injection, migration loop, lost job, or false readiness; reads/diagnostics recover | Nightly/release |
| Scheduler restart | 3,9 | Kill before/after tick; exactly one due job through idempotency; heartbeat/last-success fresh; missed schedule lag within threshold | Nightly/release |
| Network failure | 2,4,9,13,14 | DNS/connect/TLS/read timeout before and after dispatch through local fault transports; classifications/retry/ambiguity match policy; no silent direct proxy fallback | PR unit/integration |
| Provider failure | 4,6,9,13 | 402, 429+Retry-After, 5xx, invalid JSON/choice/content/schema/usage/model, timeout; safe diagnostic stage, bounded retry/cost, no raw/key leak | Every PR; protected live qualification |
| Telegram failure | 2,3,6,9,14 | Token/permission 4xx, 429, 5xx, invalid success, transport timeout, worker kill; exact receipt/attempt/job state and operator alert | Every PR; protected staging |
| Retry | 1,2,9,13,14 | Controlled clock across API repeat, queue retry, lease expiry, provider retry, publishing retry; max attempts/backoff/jitter/due time correct | Every PR |
| Duplicate prevention | 1,2,10,13,14 | Concurrent identical API calls/workers, crash boundaries, replayed reconciliation; unique jobs/runs/revisions/receipts/publications and exactly one remote marker | Every PR + live staging |
| Backup and restore | 3,6,8,9,15 | Quiesced encrypted archive to disposable project; corruption/wrong key/partial reject; DB/file hashes/FKs/no-secret/smoke/RPO/RTO pass; old stores retained | Quarterly and pre-major-upgrade release gate |
| Secret leakage | 4,5,6,7,13,14,15 | Unique canaries in each runtime secret; scan environment allowlists, logs, DB durable surfaces, API/UI, jobs/events/attempts, diagnostics/metrics, exports/backups/artifacts | Every PR static/unit + release canary |
| Proxy enabled | 4,5,6,9,13,14 | Approved recording proxy; all intended HTTP clients traverse it, `NO_PROXY` bypasses internal endpoints, MTProto explicit, credentials redacted | PR integration + staging |
| Proxy disabled | 4,9,13 | All proxy variants unset/empty/whitespace; no external proxy network; 4/4 real-source canary direct; no client inherits host environment | Every PR Compose/unit + release network smoke |
| Large frontend data | 7,10,11,12 | Production build with 200/1k/10k records; latency/DOM/fps budgets, correct selection/cursors/deep link, Axe/keyboard/screen-reader semantics | PR correctness; nightly performance |
| Accessibility/themes | 7,10,11,12 | Diagnostics and inbox states, 390/1440 px, light/dark, Axe serious/critical zero, measured contrast, keyboard/focus/zoom/RTL | Every PR browser gate + manual release check |
| Contract evolution | 1,6,7,9,10 | Regenerate OpenAPI/types, validate real ASGI responses and all mocks, unmatched request fails, generated diff zero | Every PR |
| Host/deployment recovery | 3,8,9,15 | Docker daemon/host reboot with retained volumes; services restart in order, migration one-shot, probes/alerts recover, canary finishes | Pre-release staging |

Canonical deterministic command sequence after implementation:

```bash
# Static/configuration
env -u OPENAI_API_KEY -u OPENROUTER_API_KEY -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet

# Backend clean/frozen and PostgreSQL
docker compose --profile test up -d --wait postgres-test
cd backend
uv sync --frozen --all-extras
uv run ruff check .
uv run ruff format --check .
uv run python -m compileall -q app ../scripts
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  uv run python -m pytest -p no:cacheprovider -q

# Frontend clean/frozen
cd ../frontend
npm ci
npm run api:generate
npm run typecheck
npm test
npm run build
npm run test:e2e

# Source/generated artifact integrity
cd ..
git diff --exit-code
```

## Final Production-Readiness Gate

NewsCraft is ready only for **controlled, review-required production use** when every hard gate below is true on the exact release image/digests. A compensating explanation, high unit-test count, or manual workaround is not a pass.

### 1. Source, build, and migration gate

- Protected `release-gate` is green from a clean checkout with frozen Python/npm installs and no generated diff.
- Ruff/format/type/compile, all backend unit/PostgreSQL/integration, frontend unit/type/build, contract, Compose/image, secret/security, and browser/Axe jobs pass.
- Exactly one Alembic head; empty database and oldest supported production snapshot upgrade to head; API starts only after one-shot migration succeeds.
- Release records source SHA, prompt/profile/config revisions, Python/npm locks, base/image digests, and SBOM; rollback images are retained.
- No unexpired high/critical vulnerability without an approved owner/mitigation/expiry.

### 2. P0 runtime-correctness gate

- Ten consecutive unmodified official fake-provider/dry-run smoke runs on fresh databases and three consecutive reruns on one existing database complete within the documented 300-second workflow/export timeout.
- Zero HTTP 500 after committed route mutation; every response matches fresh database state.
- Zero worker/scheduler unexpected exit, `MissingGreenlet`, Uvicorn `Logging error`, or lease recovery caused by runner failure.
- Handler commits/rollbacks/expiry cannot affect terminal job bookkeeping; stale owners are fenced; every side-effecting job has crash/retry duplicate protection.
- Direct mode and approved-proxy mode each pass; unset/blank settings never force a proxy and configured proxy failure never falls back direct.
- Kill/poison/host restart drills meet Phase 3 recovery/alert bounds without a duplicate.

### 3. Security and credential gate

- API has no OpenRouter, MTProto, destination token, authenticated-proxy value, worker secret file, or root `.env` access. Each worker has only its documented authority; scheduler/frontend have none.
- Unique canary scan returns zero across logs, exceptions, API/frontend, database payload fields, jobs, events/history, attempts/receipts, diagnostics/metrics, exports, backups, and CI artifacts.
- Uvicorn access/error logs remain formatted and useful while redacting all required secret classes.
- Secret rotation/revocation affects only the owning worker; protected live workflows never receive credentials as inputs/artifacts.
- Backup encryption/decryption keys are backup-only, escrowed/tested, and absent from application services.

### 4. Operational health and recovery gate

- Liveness, core readiness, dependency/capability health, queue lag, stuck leases, last-success, and safe metrics implement the documented thresholds and pass failure drills.
- No due capability queue can be silently workerless; mutation endpoints bound/reject unavailable capability work while read/diagnostic access remains available.
- Alerts for restarts, stale components, queue SLO, provider/Telegram failure, reconciliation, missed backup, and capacity reach the on-call path and link to tested runbooks.
- A quiesced, encrypted off-host backup restores into a disposable project: database/file hashes and referential checks match, canary leakage is zero, readiness and credential-free smoke pass, RPO <=24 h and RTO <=2 h.
- Rollback of application, database/volume cutover, provider profile, route, and credential is rehearsed; ambiguous publications are reconciled before any rollback/resend.

### 5. Frontend, contract, performance, and accessibility gate

- Canonical OpenAPI/generated types have zero diff; actual ASGI responses and every mock validate; no unmatched request; mocked and no-mock critical browser suites pass.
- Story Inbox meets Phase 11 p95 <=100 ms selection feedback, bounded DOM, bulk/fps/initial-load targets at 200/1k/10k, with correct cursor/selection/deep-link behavior.
- Diagnostics/inbox have zero serious/critical Axe violations in light/dark mobile/desktop; text contrast >=4.5:1, meaningful non-text/focus >=3:1; keyboard, zoom, forced-color, RTL, and screen-reader checks pass.

### 6. Editorial quality gate

- A funded immutable provider profile and versioned prompts complete the 36-story x2 Persian campaign, including its untouched 24-story held-out cohort, and meet every Phase 13 schema, retry, unsupported-claim, citation, language, title, promo, human-score, cost, latency, and agreement threshold.
- Invalid provider output is diagnosable by safe stage/path; model/settings changes create new idempotency identities; no silent cross-model fallback exists.
- Corpus, evidence, reviews, prompt/profile hashes, usage/cost, and signed score report are retained without credentials.

### 7. External publishing gate

- Dedicated private staging destination/token is verified and publishing-worker-only.
- Dry-run and full deterministic Telegram fault matrix pass; approval/hash/evidence/control failures cause zero sends.
- Authorized live success creates exactly one remote message and one matching confirmed `Publication`; replay/restart/concurrent claim creates zero additional message.
- One separately authorized post-send ambiguity drill stops automatic resend, is manually verified/reconciled with exact remote IDs, and remains idempotent/conflict-fenced.
- Initial production routes remain `review_required`; `auto_publish` is a separate later approval after production observation and is not implied by this gate.

### 8. Controlled rollout and stop conditions

- Begin with one approved source/route/destination, review-required publishing, bounded queue/concurrency, named operators, and a documented observation window. Expand only after seven consecutive days within SLO and no P0/security/duplicate incident.
- Immediate stop/pause conditions: any committed-mutation 500, worker runner crash, secret canary match, unbounded/stuck queue, readiness hard failure, material unsupported generated claim, unexplained remote message, duplicate, or unresolved ambiguous publish outside the response SLO.
- A stopped gate returns to not-ready until the root cause is fixed and the affected acceptance cohort/drill is rerun; an operator workaround does not reset the gate.
