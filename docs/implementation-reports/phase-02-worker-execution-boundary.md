# Phase 02 implementation report: worker execution boundary

Date: 2026-07-17

Baseline revision: `7826ebaf04565b0401baacac8f5234ed88764029`

Final classification: **COMPLETE**.

The previously missing literal process-crash obligation is now verified for all 16 registered job types. The tests use spawned worker processes and `os._exit(86)`, then recover expired leases from PostgreSQL and assert duplicate prevention. Handler-specific hard-death coverage also exercises every non-transactional production mechanism: provider calls, Telegram route media storage, export manifests, retention filesystem deletion, and Telegram dispatch/receipt/publication.

The deferred deployed gate is now verified. On source revision `5ad72dc49bdb9189a7629bcf6b68a181d5c1ec15`, ten counted full smoke executions (five fresh-database and five repeated-database) passed all 13 stages with zero worker or scheduler exit/restart, zero post-handler ORM-expiry failure, zero runner-exception job, zero expired-lease recovery, and zero duplicate job, revision, generation, export, or Telegram operation. No production code was changed during final verification.

## Planning-source caveat

`plan.md` was not present in the working tree, Git history, `.agents`, `.codex`, or `/tmp` when this work began. The pre-existing untracked `solutions.md` contained the detailed Phase 2 problem statement, implementation plan, required tests, acceptance criteria, rollback plan, and Definition of Done; `TASK.md` contained the original phase brief. Both files were read completely. Neither was modified.

Because the requested `plan.md` was unavailable, the implementation was checked against the Phase 2 contract in `solutions.md` and against the current code rather than assuming that artifact was current. This missing source file remains a documentation risk.

> **Resolved 2026-08-13.** The documentation risk recorded above is closed:
> the root-level `solutions.md` cited throughout this report has been
> restored from commit `8f0923d` to `docs/archive/solutions.md`, so its
> Phase 2 contract is readable again.

## Problem reproduction

Documented problem reproduced: **YES, at the causal boundary**.

The pre-change worker tests passed (`31 passed`), demonstrating the missing regression coverage. A focused regression was then added in which the handler calls `expire_all()` and the claimed job raises on any later ORM attribute access. Before the production fix, it failed at the worker's post-handler `job.id` read:

```text
RuntimeError: expired workflow job attribute accessed: id
app/jobs/worker.py:340
```

This deterministically reproduced the lifecycle defect that causes the deployed `MissingGreenlet`. The exact SQLAlchemy `MissingGreenlet` exception was not recreated in a live pre-fix worker; the focused test reproduced its cause without relying on driver timing.

The current repository still had the documented design before the fix:

- `JobHandler` accepted a `WorkflowJob` ORM instance.
- `WorkerRunner.run_once()` claimed, invoked the handler, and terminalized in one `AsyncSession`.
- handlers routinely committed or rolled back that shared session;
- `telegram.route.process` explicitly called `session.expire_all()`;
- the runner read `job.id`, `job.job_type`, and `job.attempt_count` after handler return.

## Confirmed root cause

The worker and handler shared transaction ownership, one SQLAlchemy identity map, and a mutable `WorkflowJob` ORM instance. Handler-controlled `commit()`, `rollback()`, or `expire_all()` could invalidate that instance. The runner then accessed it outside the handler exception boundary while finishing, failing, or logging the job.

Consequences were:

- a post-handler `MissingGreenlet`/detached or expired-attribute failure;
- durable domain work without a durable workflow terminal transition;
- an orphaned running lease;
- at-least-once replay of material or external effects;
- possible duplicate provider work, files, or sends unless the domain idempotency mechanism held.

## Concise implementation plan used

1. Introduce a deeply immutable, secret-safe `JobExecution` snapshot and type every registered handler against it.
2. Give runtime heartbeat, claim, handler, lease heartbeat, and terminal transitions independent session scopes.
3. Preserve generation's durable partial-result and normalized-payload behavior through an owner-fenced checkpoint API instead of mutating the ORM job.
4. Fence checkpoint, finish, and fail transitions by job ID, running status, unexpired lease, and lease owner.
5. Add focused unit, PostgreSQL concurrency, crash-window, idempotency, and broad regression coverage.
6. Attempt the documented credential-free deployed smoke without changing any other phase.

## Architecture decisions

### Immutable execution contract

`JobExecution` is a frozen, slotted dataclass containing only scalar/session-independent values used by handlers:

- job ID and type;
- a recursively frozen deep copy of the JSON payload;
- attempt and maximum-attempt counts;
- origin and lease owner;
- creation/schedule timestamps;
- priority and pause sensitivity.

Payload mappings become nested read-only mappings and sequences become tuples. Unsupported objects, non-finite numbers, invalid timestamps/attempt metadata, and payloads changed by the repository's secret redactor are rejected. The validated server-generated retention preview capability remains the existing narrow exception. `payload_copy()` gives each handler an isolated mutable parse input.

### Session and transaction ownership

- Runtime observation: its own session and commit.
- Claim: its own session; materialize `JobExecution` while the ORM row is loaded, commit, then close.
- Handler: a new handler-owned session. The handler may commit, roll back, or expire it. The runner commits any residual successful domain work or rolls back a failed transaction.
- Lease heartbeat: an independent session per heartbeat. The loop is stopped and joined before workflow transition.
- Finish/fail: a fresh terminal session and commit.

No runner path reads the claimed ORM instance after envelope construction. Invalid-envelope handling fences with the runner's own worker ID, never an untrusted owner read from a questionable row.

### Lease fencing and generation checkpoints

Existing `finish_job()` and `fail_job()` row locks and active-lease checks were retained and exercised with stale-owner concurrency tests. A new `checkpoint_job()` applies the same active-lease fence to generation payload/result checkpoints.

The generation handlers previously mutated `job.result` for completed-platform checkpoints and `job.payload` while normalizing regeneration work. They now persist those values through `checkpoint_job()` and continue with a newly derived immutable envelope. This preserves partial-pack durability without returning an ORM object to the handler contract.

### Crash windows

Two worker fault points were added:

- `worker.after_handler_before_terminal`: handler transaction is durable but workflow transition is not;
- `worker.after_terminal_commit`: workflow transition is durable but the process has not returned/logged completion.

Two additional production-window points were added in this continuation:

- `telegram_process.after_provider_before_persist`: the Telegram rewrite provider returned, but its output is not durable;
- `retention.after_filesystem_delete_before_finalize`: cleanup paths were removed, but the retention run/count checkpoint is not durable.

The Telegram publish and retention builders now accept an optional fault injector, as does the Telegram process builder. Production construction remains no-op; the optional arguments exist only to make the real non-transactional boundaries directly killable in tests.

Together with the existing after-claim, generation, research, export, and Telegram publication points, automated coverage exercises all boundary positions:

1. before handler work or a side effect (`worker.after_claim`);
2. after an external/filesystem effect but before its durable checkpoint;
3. after durable handler work but before workflow completion (`worker.after_handler_before_terminal`);
4. after workflow completion (`worker.after_terminal_commit`).

The new tests do **not** count `InjectedFault`, `BaseException`, or an ordinary Python exception as process death. They create a fresh interpreter with the multiprocessing `spawn` context and terminate it with `os._exit(86)`. The parent requires that exact exit code. Thus no exception handler, `finally` block, task cancellation, SQLAlchemy close/rollback, or pytest unwinding runs in the killed child.

Coverage is deliberately compositional for transaction-only handlers. The exact registry-key matrix proves the common worker boundary, real PostgreSQL rollback/commit behavior, lease recovery, and one durable effect across replay for every job type. Existing production-handler replay tests prove each handler's domain key/fence. Additional hard-death tests invoke the actual production handler or storage mechanism wherever an effect crosses the database transaction boundary. No ordinary-exception test is used as a substitute for this process-death evidence.

### Idempotency preserved

No existing idempotency key, content/input hash, revision fence, artifact checksum, source identity, retention state hash, or Telegram receipt/reconciliation behavior was removed or weakened.

## Registered-handler and side-effect audit

All 16 default registry keys are enumerated by the new test and compared at runtime with `build_default_registry()`, so an omitted or newly registered handler fails the inventory assertion.

The original ORM-field dependency audit remains: `ingest.collect`, `manual_intake`, and `story.group_pending` used `payload`/`id`; the four Telegram route readers used `payload`/`id`/`job_type`; `telegram.route.process`, canonical generation, and research used `payload`/`id` plus attempt metadata where applicable; pack generation and regeneration additionally mutated workflow `result` or normalized `payload` and required `lease_owner`; export used `payload`/`id`/`created_at`; retention and the two publishing handlers used `payload`. All are now satisfied by immutable `JobExecution` values and explicit owner-fenced checkpoints, never by a claimed ORM instance.

| Registered job type | Material or external side effect | Durable idempotency/checkpoint/receipt mechanism | Existing production replay/crash tests | New literal process-death coverage | Missing required process coverage |
| --- | --- | --- | --- | --- | --- |
| `ingest.collect` | Reads configured sources; persists ingestion runs, raw/source/content/media rows; enqueues grouping. Source reads do not mutate the remote system. | Source/content natural identities and upserts; ingestion-run status; stable `story-group:{job.id}` successor key. | `test_ingestion_job_transactions.py`; ingestion service/repository suites; `stories/test_handlers.py` replay. | Exact-key worker death before handler, after committed effect, and after terminal commit; lease recovery creates one effect. DB-only material writes are transaction-atomic. | None. A remote read may be repeated, but no remote mutation exists. |
| `manual_intake` | Optional URL GET; persists one story, evidence snapshot/link, and completion event. | Job-derived deterministic evidence/story identity, advisory serialization, and one `manual_intake.completed` event. | `test_two_session_manual_replay_serializes_to_one_complete_materialization`; handler replay and savepoint rollback tests. | Exact-key three-window worker death/recovery matrix. URL GET is read-only; material writes commit atomically. | None. |
| `story.group_pending` | Groups pending content into stories/evidence and may enqueue another page. | Deterministic grouping/evidence identities and `story-group-page:{root}:{cursor}` continuation key. | Deterministic replay and full-page continuation tests in `stories/test_handlers.py`. | Exact-key three-window worker death/recovery matrix. | None. |
| `telegram.route.backfill` | Reads Telegram history; content-addresses any media; persists capture, story/revision/dispatch, cursor, and process job. | Route/source key + envelope fingerprint, source/content upserts, checksum-addressed media, snapshot/page tokens, stable continuation/process keys. | Route backfill/replay tests and Telegram capture repository duplicate tests. | Exact-key worker matrix plus a real child killed immediately after production `TelegramMediaStore.persist()`; retry reuses one checksum path. | None. |
| `telegram.route.dry_run` | Reads one Telegram message; stores media/capture and review-only dispatch state. | Job-bound dry-run source identity, envelope fingerprint, content-addressed media, stable process key. | Dry-run and duplicate capture tests. | Exact-key worker matrix plus production media-store hard death/dedup test for this key. | None. |
| `telegram.route.initialize` | Reads activation/backfill pages; stores captures/media; advances bounded snapshot/cursor state and continuations. | Activation token, snapshot/page state, source fingerprints, checksum-addressed media, unique scan/capture continuation keys. | Bounded resume, no-skip/no-duplicate, token-loop, and pause-resume tests. | Exact-key worker matrix plus production media-store hard death/dedup test for this key. | None. |
| `telegram.route.poll` | Reads new/edited Telegram messages; stores captures/media; advances cursor and schedules processing. | Source key/fingerprint, recent-fingerprint cursor fence, content-addressed media, deterministic continuation/process keys. | Poll ordering, pause replay, edit replay, and capture-repository duplicate tests. | Exact-key worker matrix plus production media-store hard death/dedup test for this key. | None. |
| `telegram.route.process` | Calls the generation provider; persists generation run/attempt, revision, dispatch state, and optional publish intent. | Generation input hash, active attempt ID, durable output, revision fence, dispatch `variant_revision_id`, stable publish-intent key. | Durable-output resume, stale-attempt fence, retry timing, and exact revision replay tests in `test_telegram_process_handler.py`. | Actual worker killed after provider return/before output persistence; lease retry yields two attempts but one revision/dispatch artifact. Exact-key outer-boundary matrix also passes. | None. Provider invocation itself is at-least-once when its result was not checkpointed. |
| `content_pack.generate` | Calls provider; creates canonical story revision and one continuation job. | Workflow-bound input hash, generation run/attempt, persisted output/artifact, story revision fence, stable continuation key. | Generation provider-crash and canonical replay tests. | Actual worker killed after provider return/before persistence; retry produces one run, one canonical revision, and one continuation. Exact-key matrix passes. | None. Provider call can repeat after an unknowable post-return crash; durable materialization does not duplicate. |
| `content_pack.generate_telegram` | Calls provider; creates content pack, platform variant/revision, and result checkpoints. | Per-stage input hash/run/attempt, artifact reuse, revision fence, and lease-owner-fenced workflow result checkpoint. | Multiplatform durable-attempt reuse and partial-result durability tests. | Actual worker killed after provider return/before persistence; retry creates one pack and one revision. Exact-key matrix passes. | None. Provider call is at-least-once across that ambiguity window. |
| `content_pack.regenerate` | Calls provider; creates one child revision from an immutable base. | Immutable base revision/hash, normalized owner-fenced payload checkpoint, generation stage hash/artifact, current-revision fence. | Regeneration idempotency, committed-artifact replay, and revision-fence suites. | Actual worker killed after provider return/before persistence; retry adds exactly one child revision. Exact-key matrix passes. | None. Provider call is at-least-once across that ambiguity window. |
| `build_export` | Writes a deterministic export directory, files, optional archive, and manifest. | Export ID equals workflow job ID; complete checksummed manifest validates exact revision/file set before reuse; atomic file replacement. | Export handler/service crash and complete-manifest reuse tests. | Actual worker killed after complete manifest creation/before handler commit; retry preserves the manifest hash and one export tree. Exact-key matrix passes. | None. |
| `execute_retention` | Scrubs/expires database data and deletes owned export/media paths. | Signed preview token, schema/state hashes, durable cleanup-intent snapshot, tombstones, safe missing-path deletion, exact count snapshot. | Retention revalidation, partial cleanup, simulated deletion failure, replay, and lease-sync tests. | Actual worker killed after filesystem deletion/before run finalization; retry treats missing paths idempotently, records each intended deletion once, and succeeds. Exact-key matrix passes. | None. |
| `research_story` | Calls research backend/provider; stores discovered evidence, result revision, attempts, and continuation jobs. | Research run/attempt IDs, stale-attempt fence, evidence keys, one result revision, subscriber/continuation idempotency. | `test_crash_after_research_provider_retries_without_duplicate_materialization` and research continuation/replay suites. | Actual worker killed after backend return/before persistence; retry marks the stale attempt failed and creates one result revision. Exact-key matrix passes. | None. Backend call is at-least-once across an uncheckpointed return. |
| `telegram.destination.check` | Performs read-only Telegram `getChat`; persists destination health/check state. | Locked destination configuration recheck and repeat-safe health/status replacement. No remote mutation occurs. | Destination check success/error/configuration-change tests. | Exact-key three-window worker death/recovery matrix. | None; there is no external write checkpoint. The read may repeat. |
| `telegram.publish` | Sends Telegram messages, then persists operation receipts, publication, publish attempt, dispatch, and event. | Stable publish intent/payload hash; per-operation receipt and attempt count; durable remote IDs; unique publication; ambiguous-send reconciliation forbids blind resend. | Existing pre-send, post-send, durable-receipt, reconciliation, and replay crash suite. | Actual workers killed at `before_send`, after send/before receipt, after receipt/before publication, and after handler commit/before workflow completion. Ambiguous states never auto-resend; receipted states finish with one remote ledger entry and one publication. Exact-key matrix passes. | None. Telegram cannot provide exactly-once knowledge after an unreceipted send; the safe terminal state is `needs_review`. |

The process tests establish the following checkpoint matrix:

| Required position | Literal coverage |
| --- | --- |
| Crash before side effect | `worker.after_claim` for every one of the 16 exact registry keys; Telegram `before_send` additionally proves zero client calls. |
| Crash after side effect but before durable checkpoint | Actual generation, Telegram-process, and research provider returns; route media persistence; export manifest; retention deletion; Telegram send before receipt. |
| Crash after durable checkpoint but before job completion | `worker.after_handler_before_terminal` for every registry key; actual Telegram receipt/publication and actual publish-handler commit paths. |
| Crash after job terminal commit | `worker.after_terminal_commit` for every registry key; a restarted worker finds no claim. |
| Lease recovery and duplicate prevention | Every registry-key case expires and recovers its lease; actual handler tests assert one revision, pack, export tree, retention count, media object, publication, or safe ambiguous receipt as applicable. |

`app/research/handlers.py` still queries and locks `WorkflowJob` internally while updating research continuation subscriptions. That is domain repository work performed through the handler-owned session; the queried ORM object is not the handler input and is never returned to the runner.

## Files changed

Production code:

- `backend/app/core/faults.py`
- `backend/app/jobs/types.py`
- `backend/app/jobs/registry.py`
- `backend/app/jobs/repository.py`
- `backend/app/jobs/worker.py`
- `backend/app/jobs/handlers.py`
- `backend/app/stories/handlers.py`
- `backend/app/research/handlers.py`
- `backend/app/generation/handlers.py`
- `backend/app/exports/handlers.py`
- `backend/app/retention/handlers.py`
- `backend/app/retention/service.py`
- `backend/app/automations/telegram/handlers.py`
- `backend/app/publishing/telegram/handlers.py`

Tests:

- `backend/tests/test_job_execution.py` (new)
- `backend/tests/test_job_worker.py`
- `backend/tests/test_job_handler_registry.py`
- `backend/tests/postgres/test_job_repository.py`
- `backend/tests/postgres/test_multiplatform_pack_durability.py`
- `backend/tests/postgres/test_worker_execution_boundary.py` (new)
- `backend/tests/integration/test_registered_handler_process_crashes.py` (new)
- `backend/tests/integration/test_material_side_effect_process_crashes.py` (new)

Report:

- `docs/implementation-reports/phase-02-worker-execution-boundary.md` (new)

No schema migration was added.

## Tests added or materially extended

- Deep envelope immutability, source-payload detachment, mutable copy isolation, unsafe payload rejection, and the retention capability exception.
- Registry-wide type-hint assertion that every default handler accepts `JobExecution`.
- Pre-fix `expire_all()` regression.
- Independent claim, handler, heartbeat, and terminal session assertions.
- Handler `commit()`, `rollback()`, failed transaction, unknown exception, cancellation, heartbeat failure, and terminal commit failure paths.
- Invalid claims fence with the runner's identity rather than the ORM row's owner value.
- PostgreSQL handler commit/`expire_all()`, rollback/`expire_all()`, and failed-transaction isolation.
- PostgreSQL owner-fenced checkpoints and stale-owner finish/fail rejection after a second claim.
- Crash after handler commit followed by lease recovery and one idempotent material effect.
- Crash after terminal commit followed by restart with no handler replay.
- Real generation partial-result checkpoint durability through `JobExecution`.
- A runtime assertion that the hard-death matrix exactly matches all 16 default registry keys.
- For each registry key, three separate `os._exit(86)` workers: after claim, after durable handler work, and after terminal commit; plus a healthy restarted process. Each case recovers leases and leaves one durable effect.
- Actual canonical, pack, regeneration, Telegram-process, and research handlers killed after provider return but before output persistence, followed by lease recovery and a one-artifact assertion.
- Production Telegram media-store death/replay for each of the four route reader keys, proving checksum-addressed reuse without duplicate files.
- Actual export handler death after manifest creation, proving stable manifest hash and one export tree on retry.
- Actual retention handler death after owned-path deletion but before run finalization, proving missing-path replay and exact deletion counts.
- Actual Telegram publish deaths before send, after send/before receipt, after receipt/before publication, and after publication commit/before workflow completion, proving safe ambiguity or one-send/one-publication replay as appropriate.

## Exact test and validation commands

### Environment and initial reproduction

```bash
docker compose --profile test up -d --wait postgres-test
```

Result: `postgres-test` healthy.

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_job_worker.py
```

Result: not run; `.venv/bin/python` did not exist. Host Python also lacked `pytest`, so all authoritative tests used the existing backend image.

```bash
docker compose run --rm --no-deps -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q tests/test_job_worker.py
```

Pre-fix baseline result: `31 passed`.

```bash
docker compose run --rm --no-deps -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q \
  tests/test_job_worker.py::test_handler_expire_all_cannot_invalidate_worker_terminal_bookkeeping
```

Pre-fix regression result: `1 failed` at the post-handler `job.id` read, as intended. The same test passes after the fix.

### Focused Phase 2 gate on the final tree

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace api sh -lc \
  'ruff check . && \
   ruff format --check app/core/faults.py app/jobs/types.py app/jobs/registry.py \
   app/jobs/repository.py app/jobs/worker.py app/jobs/handlers.py \
   app/stories/handlers.py app/research/handlers.py app/generation/handlers.py \
   app/exports/handlers.py app/retention/handlers.py \
   app/automations/telegram/handlers.py app/publishing/telegram/handlers.py \
   tests/test_job_execution.py tests/test_job_worker.py \
   tests/test_job_handler_registry.py tests/postgres/test_job_repository.py \
   tests/postgres/test_multiplatform_pack_durability.py \
   tests/postgres/test_worker_execution_boundary.py && \
   python -m pytest -p no:cacheprovider -q \
   tests/test_job_execution.py tests/test_job_worker.py \
   tests/test_job_handler_registry.py tests/postgres/test_worker_execution_boundary.py \
   tests/postgres/test_job_repository.py \
   tests/postgres/test_multiplatform_pack_durability.py'
```

Result: Ruff passed, all 19 selected files formatted, `92 passed`.

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_job_worker.py \
  tests/integration/test_worker_crash_recovery.py \
  tests/integration/test_publish_crash_recovery.py \
  tests/postgres
```

Result: `162 passed`.

### Domain regression groups

```bash
docker compose run --rm --no-deps -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_job_execution.py tests/test_job_worker.py tests/test_job_handler_registry.py \
  tests/test_scheduler.py tests/test_ingestion_job_transactions.py \
  tests/test_ingestion_service.py tests/stories \
  tests/test_telegram_route_handlers.py tests/test_telegram_process_handler.py \
  tests/test_telegram_capture_repository.py tests/test_telegram_route_policy.py \
  tests/test_telegram_revision_fence.py
```

Result: `200 passed, 12 skipped`.

```bash
docker compose run --rm --no-deps -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/generation tests/research tests/exports \
  tests/api/test_export_rebuild.py tests/api/test_export_routes.py \
  tests/integration/test_multiplatform_export_flow.py
```

Result: `406 passed, 1 skipped`.

```bash
docker compose run --rm --no-deps -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_telegram_publish_service.py tests/test_telegram_bot_client.py \
  tests/test_telegram_renderer.py tests/test_telegram_reconciliation_api.py \
  tests/test_telegram_draft_api.py tests/test_telegram_generation_schema.py \
  tests/test_telegram_route_api.py tests/test_telegram_configuration_api.py \
  tests/manual_publication tests/test_approval_workflow.py \
  tests/test_draft_workflow.py tests/retention
```

Result: `226 passed`, one Starlette deprecation warning.

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_worker_crash_recovery.py \
  tests/integration/test_publish_crash_recovery.py \
  tests/integration/test_editorial_research_generation_flow.py \
  tests/integration/test_multiplatform_export_flow.py
```

Result: `21 passed`.

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short tests/postgres
```

Result: `106 passed`.

Two earlier integration invocations used incomplete container mounts. The first produced `13 passed, 3 failed, 5 errors` because `/backend`, `/docs`, and `/README.md` were unavailable; the second produced `20 passed, 1 failed` with only `/README.md` still missing. Both were invocation-layout failures and were superseded by the `21 passed` command above. A broad development run whose tool output was truncated was not counted as verified.

### Full backend gate on the final tree

The full suite was split because one migration test deliberately invokes `backend/.venv/bin/alembic` and one Compose test invokes a host Docker CLI. The backend image contains Alembic but has neither that local virtualenv path nor the Docker CLI.

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  --deselect tests/test_dispatch_sequence_migration_postgres.py::test_upgrade_backfills_canonical_chronology_and_advances_db_sequence \
  --deselect tests/test_docker_config.py::test_local_service_ports_bind_to_loopback
```

Final result: `1615 passed, 2 deselected`, one Starlette deprecation warning.

The test schema was then rebuilt and migrated truthfully:

```bash
docker compose exec -T postgres-test psql -U newscraft -d newscraft_test \
  -v ON_ERROR_STOP=1 -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

docker compose run --rm --no-deps \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace api alembic upgrade head
```

The two split tests used a temporary read-only shim from `backend/.venv/bin/alembic` to the image's `/usr/local/bin/alembic`, plus read-only host Docker CLI/plugin mounts:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace \
  -v /tmp/phase2-test-bin:/workspace/backend/.venv/bin:ro \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins:/usr/lib/docker/cli-plugins:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_dispatch_sequence_migration_postgres.py::test_upgrade_backfills_canonical_chronology_and_advances_db_sequence \
  tests/test_docker_config.py::test_local_service_ports_bind_to_loopback
```

Final result: `2 passed`.

Pre-continuation backend baseline: **1,617 passed**, one non-failing Starlette deprecation warning.

### Literal process-death continuation on the final tree

The missing production hook was first demonstrated by running the actual Telegram-process death test before changing production code:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_material_side_effect_process_crashes.py::test_telegram_process_hard_death_retries_to_one_revision
```

Pre-hook result: `1 failed`. The spawned child exited with the harness error code `87`, and its traceback showed `build_telegram_process_handler() got an unexpected keyword argument 'fault_injector'`. This was the focused pre-fix regression for the missing provider-return process-death checkpoint. After the hook was added, the same command passed (`1 passed`).

An initial combined run of both new process suites reported `25 passed, 2 failed`. The two failures were test-harness lease expirations: a deliberately tiny two-second lease expired while slow spawned generation workers were still setting up, and the production owner fence correctly rejected the stale workers. The harness lease was increased to 30 seconds; recovery still advances a logical clock and does not sleep. The two affected tests then passed together:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_material_side_effect_process_crashes.py::test_pack_generation_hard_death_retries_to_one_pack_artifact \
  tests/integration/test_material_side_effect_process_crashes.py::test_regeneration_hard_death_retries_to_one_child_revision
```

Result: `2 passed`.

The final actual-handler/non-transactional side-effect suite was:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_material_side_effect_process_crashes.py
```

Result: **`15 passed in 111.35s`**.

The final exact 16-key execution-boundary matrix was:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_registered_handler_process_crashes.py
```

Result: **`17 passed in 191.86s`** (one registry-inventory test plus 16 parameterized job-type cases, with 48 intentional hard exits).

The pre-existing crash-recovery and PostgreSQL worker-boundary suites were rerun:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/integration/test_worker_crash_recovery.py \
  tests/integration/test_publish_crash_recovery.py \
  tests/postgres/test_worker_execution_boundary.py
```

Result: **`21 passed in 26.52s`**.

The relevant worker, scheduler, generation, research, export, Telegram route/process/publish, retention, PostgreSQL, and integration regressions were:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -v ./backend:/app -v ./backend:/backend:ro -v ./docs:/docs:ro \
  -v ./README.md:/README.md:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_job_execution.py tests/test_job_worker.py \
  tests/test_job_handler_registry.py tests/test_scheduler.py \
  tests/generation tests/research tests/exports \
  tests/test_telegram_route_handlers.py tests/test_telegram_capture_repository.py \
  tests/test_telegram_publish_service.py tests/retention \
  tests/postgres/test_telegram_process_handler.py \
  tests/postgres/test_retention_service.py \
  tests/integration/test_editorial_research_generation_flow.py \
  tests/integration/test_multiplatform_export_flow.py
```

The first run found one compatibility issue in a retention test double (`592 passed, 1 failed`): the default handler forwarded the newly optional keyword even when no injector was configured. The builder was changed to forward it only when explicitly supplied. The affected default and hard-death paths then passed (`2 passed`), and the exact domain command above was rerun with final result **`593 passed in 49.04s`**.

Final lint and formatting gate:

```bash
docker compose run --rm --no-deps -w /app -v ./backend:/app api sh -lc \
  'ruff check . && \
   ruff format --check app/core/faults.py app/automations/telegram/handlers.py \
   app/retention/service.py app/retention/handlers.py \
   app/publishing/telegram/handlers.py \
   tests/integration/test_registered_handler_process_crashes.py \
   tests/integration/test_material_side_effect_process_crashes.py'
```

Result: Ruff passed; all seven selected files were formatted.

Final main backend gate:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  --deselect tests/test_dispatch_sequence_migration_postgres.py::test_upgrade_backfills_canonical_chronology_and_advances_db_sequence \
  --deselect tests/test_docker_config.py::test_local_service_ports_bind_to_loopback
```

Result: **`1,647 passed, 2 deselected, 1 warning in 438.98s`**. The warning is the pre-existing Starlette/httpx deprecation warning.

Final environment-specialized split:

```bash
docker compose run --rm --no-deps \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -w /workspace/backend -v .:/workspace \
  -v /tmp/phase2-test-bin:/workspace/backend/.venv/bin:ro \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins:/usr/lib/docker/cli-plugins:ro api \
  python -m pytest -p no:cacheprovider -q --tb=short \
  tests/test_dispatch_sequence_migration_postgres.py::test_upgrade_backfills_canonical_chronology_and_advances_db_sequence \
  tests/test_docker_config.py::test_local_service_ports_bind_to_loopback
```

Result: **`2 passed in 10.81s`**.

Combined final backend result: **1,649 passed**, one non-failing pre-existing warning.

### Deployed acceptance attempt

The documented default-project startup was attempted first:

```bash
docker compose -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d --build postgres api worker-source-generation worker-publishing scheduler frontend
```

Result: API startup failed before smoke because the pre-existing default PostgreSQL volume was stamped with unavailable historical revision `0016_persian_llm_generation`. That volume was preserved and not modified.

An isolated fresh-volume project then started successfully:

```bash
docker compose -p phase2acceptance \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d postgres api worker-source-generation worker-publishing scheduler frontend
```

The sandboxed smoke invocation could not access localhost and failed health with `transport_failure`; it was not counted. The authorized local invocation was:

```bash
python3 scripts/smoke.py \
  --base-url http://127.0.0.1:8000 \
  --provider fake \
  --telegram-mode dry-run \
  --output-dir /tmp/phase2-smoke-results/run-01-escalated
```

Result: health passed; configure failed with HTTP 500. API logs showed the existing Phase 1 defect:

```text
TelegramRouteAcceptedOut.route.updated_at
MissingGreenlet
app/api/telegram_automations.py:312
```

During the aborted run, `telegram.route.initialize` completed successfully through the new worker boundary. `api`, both workers, scheduler, frontend, and PostgreSQL all remained healthy/running; no worker exited. This was not a complete smoke run and does not count toward the required ten. The isolated project and disposable volumes were removed afterward. The default legacy data volume was retained.

### Final deployed verification gate

The blocked gate was completed on 2026-07-17 after the independent Phase 1, Phase 5, and Phase 9 fixes were present. Five isolated cohorts each ran once on newly created volumes and once more against the retained database. All ten counted executions passed all 13 stages, cleanup, and a 15-assertion post-run audit. Phase 2-specific evidence was:

- source/generation worker, publishing worker, and scheduler remained running and healthy with restart count zero after every run;
- `workflow_events` contained zero `job.lease_expired` event and `workflow_jobs` contained zero `unhandled_exception` or `worker_lease_expired` error;
- no queued or running job remained after each audit;
- each content pack had exactly four platform variants and five distinct revisions, with no duplicate revision number or content hash;
- generation input hashes, attempt numbers, workflow idempotency keys, exports, and Telegram dispatch/operation cardinalities contained no duplicate;
- bounded logs contained zero `MissingGreenlet`, traceback, runner-exception code, Uvicorn formatter error, route-mutation 500, or secret-reference canary;
- all isolated containers, networks, and volumes were removed after the gate.

Exact commands, revision/environment/image metadata, all ten smoke artifacts, all ten machine-audit sidecars, non-counting attempt classifications, and cleanup evidence are recorded in `docs/implementation-reports/phase-01-02-final-deployed-verification.md`. The aggregate machine-readable result is `/tmp/newscraft-phase01-02-final-gate/final-verification.json`.

## Test result summary

| Gate | Result |
| --- | --- |
| Focused envelope/worker/registry/PostgreSQL boundary | PASS — 92 tests |
| Phase 2 plan group | PASS — 162 tests |
| Literal process death for all 16 registry keys | PASS — 17 tests; 48 intentional worker hard exits |
| Actual non-transactional handler/storage crash windows | PASS — 15 tests |
| Pre-existing crash-recovery and PostgreSQL boundary suites | PASS — 21 tests |
| Relevant worker/scheduler/generation/research/export/Telegram/retention regressions | PASS — 593 tests |
| Complete PostgreSQL suite (pre-continuation gate) | PASS — 106 tests |
| Full backend final tree | PASS — 1,649 tests across the documented split |
| Ruff lint and selected-file format check | PASS |
| Ten complete deployed smoke runs | **PASS — 10/10 complete; 5 fresh and 5 repeated; 130/130 stages and 150/150 audit assertions** |

Skipped tests were pre-existing environment/optional-path skips and were not counted as passes. The one warning is a pre-existing `StarletteDeprecationWarning` concerning `httpx`/`TestClient`.

## Acceptance criteria checklist

- [x] **PASS** — No registered handler accepts `WorkflowJob`; all 16 default handler annotations are asserted as `JobExecution`, and source search confirms the only remaining handler-module `WorkflowJob` usage is an internal research continuation query.
- [x] **PASS** — Handler commit, rollback, `expire_all()`, and return end in the correct terminal workflow state without post-handler ORM reads. Verified in unit and real PostgreSQL tests.
- [x] **PASS** — A stale lease owner cannot finish, fail, checkpoint, or otherwise terminalize a second worker's live claim. Verified with controlled-clock PostgreSQL re-claim tests.
- [x] **PASS** — Every side-effecting registered job type has an automated literal process-crash/retry duplicate-prevention assertion. A runtime inventory test proves the matrix contains exactly the 16 default registry keys. Every key is killed with `os._exit(86)` before handler work, after committed handler work, and after terminal commit; each expired lease is recovered and leaves exactly one durable effect. Actual production handlers/storage are additionally hard-killed at every non-transactional provider, media, export, retention, and Telegram send/receipt boundary.
- [x] **PASS** — Ten full acceptance runs had zero worker/scheduler exit or restart, zero post-handler ORM-expiry failure, zero runner-exception job, and zero expired-lease recovery.

## Definition of Done checklist

- [x] **PASS** — Frozen execution envelope replaces the ORM handler contract.
- [x] **PASS** — Claim, handler, heartbeat, and terminal transactions have explicit independent owners/sessions.
- [x] **PASS** — Lease-owner fencing covers finish and fail; checkpoint fencing was added as well.
- [x] **PASS** — Crash/retry tests cover every external or material side-effect mechanism with literal interpreter termination and cover every exact registered job type at the worker boundary. Ordinary Python exceptions are supplemental only and were not counted as this evidence.
- [x] **PASS** — Full backend gate passes.
- [x] **PASS** — Repeated deployed smoke gate passes with no worker exit, lease recovery, runner exception, or duplicate material/external operation.

## Rollback plan

There is no database migration. Roll back the handler-interface, runner-session, checkpoint, and fault-point changes together; do not retain a mixed registry where some handlers receive ORM rows and others receive envelopes.

Operational rollback should:

1. pause automation and stop new claims;
2. inspect/drain running jobs and reconcile any ambiguous Telegram publish receipt;
3. deploy the prior application image/revision as one unit;
4. resume only after compatible workers and API are healthy.

An emergency snapshot-only runner patch is not equivalent to this boundary and must not be used to enable live publishing.

## Remaining risks and unverified items

- `plan.md` is absent, so the detailed Phase 2 source of truth could not be read at the requested path.
- No live OpenRouter, Codex, Telegram MTProto, or Telegram publishing credential was used. Tests were deterministic and credential-free; real external-provider behavior remains outside this session's verification.
- Generation/research provider invocations are necessarily at-least-once when a process dies after the provider returns but before its output is durable. The tests prove one durable run artifact/revision, not one billable upstream invocation. Provider-level exactly-once behavior would require an upstream idempotency contract.
- Telegram sends without a durable receipt are fundamentally ambiguous. The verified safety policy prevents an automatic resend and transitions to operator reconciliation; it does not claim unknowable exactly-once remote delivery.
- A process can leave an ephemeral Telegram download staging directory behind. The durable media store is checksum-addressed and was hard-death tested for one stored object, but periodic staging cleanup remains an operational hygiene concern rather than a duplicate-publication risk.
- The default local PostgreSQL volume contains an unavailable historical Alembic revision. It was preserved; acceptance used and then removed an isolated fresh volume.
- The final deployed verification used the independently completed Phase 5 formatter and observed zero access-logging formatting error.

## Changes outside Phase 2

No repository code was changed for Phase 1, Phase 3, or any later phase. The shared fault-point catalog was extended only to test Phase 2 crash windows. Test-only Docker containers/volumes were created as part of validation; the isolated acceptance project was removed, the existing default data volume was preserved, and the already-running `postgres-test` service was left available.

Pre-existing untracked files (`TASK.md`, `solutions.md`, `docs/production-readiness-audit-2026-07-15.md`, and `validation/`) were not modified.

## Is Phase 2 genuinely complete?

**Yes:** **COMPLETE**.

All Phase 2 implementation requirements and applicable acceptance criteria are complete, including literal per-job-type process-crash coverage and the final ten-run deployed gate.

## Final phase determination

Phase 2 is **COMPLETE**. The final verification did not start or implement Phase 3, Phase 4, Phase 6, or any other phase.
