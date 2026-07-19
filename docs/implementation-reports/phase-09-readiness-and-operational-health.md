# Phase 09 — Readiness and Operational Health

Date: 2026-07-17

Authoritative plan: `solutions.md`, Phase 9 only

## Outcome

Phase 9 is complete. Process liveness, deployment readiness, and rich operational health are separate contracts. Readiness now checks PostgreSQL connectivity, the exact Alembic head, required storage access, and configured required capabilities. Worker and scheduler heartbeats run independently of their main work loops, queue and lease anomalies are projected by job type, API-owned asynchronous work is gated by exact fresh job-type coverage and a queue ceiling, and all public diagnostics use bounded, sanitized output.

The observed Diagnostics timestamp race was reproduced before the production fix and was not reproduced by the focused regression, 100 repeated deployed Diagnostics smoke observations, or the final 13-stage deployed smoke.

No Phase 3 restart supervision, Phase 6 credential topology, Phase 10 contract correction, or other phase was implemented. Phase 5 logging and redaction production files were not changed by this work.

## Reproduction result

The focused regression `test_snapshot_timestamp_covers_heartbeat_committed_during_observation` models the observed statement-order race with a heartbeat committed one microsecond after the snapshot's initially captured application time.

Pre-fix command:

```bash
docker compose run --rm --no-deps -w /workspace/backend api \
  python -m pytest -p no:cacheprovider -q \
  tests/operations/test_diagnostics.py::test_snapshot_timestamp_covers_heartbeat_committed_during_observation
```

Pre-fix result: **failed as intended**. `generated_at` was `2026-07-13T08:30:00.000000+00:00`; the heartbeat returned by the following query was `2026-07-13T08:30:00.000001+00:00`.

Post-fix focused result: the race regression and exact boundary test both passed. The final deployed smoke's Diagnostics step also passed with scheduler, publishing worker, and source/generation worker healthy.

## Confirmed root cause of the timestamp race

The confirmed cause was **heartbeat observation ordering combined with PostgreSQL READ COMMITTED statement visibility**:

1. Legacy Diagnostics captured `generated_at` before reading runtime heartbeats.
2. A concurrent heartbeat could commit after that clock read.
3. The subsequent heartbeat query could see that newly committed row.
4. The response then contained `observed_at > generated_at`, tripping `component_observation_from_future`.

The alternatives requested in the phase brief were checked explicitly:

- **Aware versus naive datetimes:** ruled out. The reproduced values were timezone-aware UTC values; naive values are rejected by focused tests.
- **Inconsistent database/server clocks:** not supported by the reproduction. The failure occurs with a controlled single clock and a one-microsecond observation-order difference.
- **Transaction visibility:** contributing mechanism, confirmed under the statement ordering above.
- **Heartbeat observation ordering:** primary confirmed cause.
- **Precision truncation:** ruled out. Microseconds survive database values, normalization, comparison, and serialization; the one-microsecond regression is preserved.
- **Another cause:** none was needed to reproduce the deployed invariant failure.

The fix reads PostgreSQL `clock_timestamp()` after all projected rows and computes a timezone-normalized high-water timestamp over that database time and every returned heartbeat/attention timestamp. This is deterministic even if a supplied test clock or application clock lags an observed durable timestamp.

## Architecture and timestamp-handling decisions

### Health boundaries

- `GET /health/live`: event-loop/process liveness only; it has no session dependency and performs no database or storage I/O.
- `GET /health/ready`: bounded checks for `SELECT 1`, exact Alembic head `0010_readiness_health_indexes`, readable/traversable media and export roots, and optional `READINESS_REQUIRED_CAPABILITIES`.
- `GET /operations/health`: sanitized dependency, component, per-job-type queue, alert, and metric projection.
- `GET /operations/metrics`: Prometheus-compatible fixed-name gauges and sanitized labels.
- `GET /health`: retained as the temporary compatibility alias.
- `GET /operations/diagnostics`: retained for the existing UI/operator contract, with its timestamp race fixed.

Readiness uses a 0.9-second database timeout and parallel 0.25-second storage probes. It returns constant error codes rather than exception text, URLs, paths, or configuration values. No cache was added: at 20,000 representative workflow rows, the rich health endpoint measured 60.097 ms p95 and the aggregate query executed in 13.327 ms. Immediate anomaly visibility was retained; this should be re-benchmarked if production cardinality grows materially.

### Explicit states

- `healthy`: observation is fresh and no hard anomaly is present.
- `stale`: observation/progress exceeds the warning threshold.
- `unavailable`: a required dependency or compatible execution path cannot serve work.
- `unknown`: no trustworthy observation exists or the timestamp/shape is invalid.

Worker boundaries are healthy through 60 seconds, stale above 60 through 120 seconds, and unavailable above 120 seconds. Scheduler boundaries are healthy through 45 seconds, stale above 45 through 90 seconds, and unavailable above 90 seconds. Missing observations are unknown. A timestamp more than one second ahead of PostgreSQL time is unknown rather than fresh.

### Heartbeats and progress

- Worker runtime heartbeat is an independent task, separate from per-job lease heartbeat and the handler call.
- Worker metadata contains only allowlisted job types, state, active work type/start time, and last successful loop time. It contains no job ID, payload, error, credential, or reference.
- Scheduler runtime heartbeat is independent of `tick()` and stores last successful committed tick time, duration, and fixed numeric result counts.
- A fresh runtime heartbeat with active work older than `JOB_STUCK_SECONDS` becomes stale as `active_work_overdue`; a blocked handler therefore remains live without being reported as making progress.
- Compose worker/scheduler health checks compare persisted heartbeat time to PostgreSQL time and fail closed. They mark containers unhealthy but do not restart them.

### Queue, lease, and capability policy

Operational health aggregates by exact job type:

- due and oldest-due work;
- running work;
- expired leases;
- stale lease heartbeat and excessive running duration;
- near-exhausted and exhausted active retries;
- failed and needs-review terminal counts;
- fresh exact-compatible worker count.

Publishing/manual thresholds are 2/5 minutes, source/generation/research/route thresholds are 5/15 minutes, and export/retention/background thresholds are 10/30 minutes. A due job with no fresh worker advertising that exact job type is unavailable immediately. An expired lease or exhausted active retry is unavailable.

API sessions are explicitly marked as API-owned. Newly accepted jobs and operator retries require a fresh worker advertising the exact job type and fewer than `CAPABILITY_QUEUE_CEILING` active jobs of that type. Rejections are safe HTTP 503 responses with `job_capability_unavailable`, `job_capability_unknown`, or `job_queue_capacity_exceeded` and `Retry-After`. Existing idempotent requests return their already accepted job. Scheduler and worker continuation sessions are intentionally not API-gated.

### Security boundary

Only allowlisted capabilities, validated job types, sanitized component IDs, fixed codes, counts, and durations are emitted. Raw heartbeat metadata, payloads, source content, exception messages, storage paths, connection strings, credential values, and credential references are excluded. Unsafe component IDs are replaced by a stable short SHA-256-derived identifier.

## Changed files

### Production and deployment

- `.env.example` — Phase 9 readiness, heartbeat, stuck-work, and API queue-gate settings.
- `backend/alembic/versions/0010_readiness_health_indexes.py` — operational queue index migration.
- `backend/app/api/health.py` — live, ready, and compatibility health routes.
- `backend/app/api/operations.py` — rich health and Prometheus endpoints.
- `backend/app/api/routes.py` — health router registration.
- `backend/app/core/config.py` — validated Phase 9 thresholds and limits.
- `backend/app/db/schema.py` — single application schema-head constant.
- `backend/app/db/session.py` — API-session capability-gate marker.
- `backend/app/jobs/capability_gate.py` — exact job-type and active-queue admission policy.
- `backend/app/jobs/errors.py` — stable capability rejection type.
- `backend/app/jobs/healthcheck.py` — worker/scheduler database-clock CLI probe.
- `backend/app/jobs/models.py` — operational health index metadata.
- `backend/app/jobs/repository.py` — new-job/retry gate with idempotent replay preservation.
- `backend/app/jobs/scheduler.py` — independent scheduler heartbeat and last-success state.
- `backend/app/jobs/worker.py` — independent runtime heartbeat and truthful work progress.
- `backend/app/main.py` — moved health routing and sanitized capability-gate 503 handler.
- `backend/app/operations/diagnostics.py` — post-observation database/high-water timestamp boundary.
- `backend/app/operations/health.py` — readiness and rich operational-health implementation.
- `docker-compose.yml` — readiness-based API check and worker/scheduler persisted-heartbeat checks.
- `docs/operations/readiness-and-health.md` — state, threshold, endpoint, gate, security, and runbook contract.

### Tests

- `backend/tests/api/test_capability_gate_routes.py`
- `backend/tests/api/test_health_routes.py`
- `backend/tests/api/test_operations_routes.py`
- `backend/tests/operations/test_diagnostics.py`
- `backend/tests/operations/test_health.py`
- `backend/tests/postgres/test_capability_gate.py`
- `backend/tests/postgres/test_operational_health.py`
- `backend/tests/test_docker_config.py`
- `backend/tests/test_job_worker.py`
- `backend/tests/test_readiness_health_migration.py`
- `backend/tests/test_runtime_healthcheck.py`
- `backend/tests/test_runtime_heartbeat.py`

### Explicitly not changed by Phase 9

- `backend/app/core/logging.py` was not modified.
- `backend/app/core/redaction.py` was already modified in the incoming working tree for completed Phase 5 work and was not edited by Phase 9.
- `scripts/smoke.py` was not modified; the validation-only status allowance was performed in memory.

## Tests added and focused coverage

- Process-only liveness and legacy alias behavior.
- Readiness success with real schema/storage/required capability.
- Database failure, schema mismatch, missing/unavailable storage, and configured capability loss.
- Exact worker boundaries at 60/120 seconds and scheduler boundaries at 45/90 seconds.
- Missing heartbeat unknown state and future-clock unknown state.
- Independent worker heartbeat during a blocked handler and overdue active-work state.
- Independent scheduler heartbeat and last successful tick metadata.
- Exact worker capability mismatch for due work.
- Due queue warning/unavailable ages.
- Expired lease, stale/overdue running work, retry pressure, and exhausted active retries.
- API exact-job-type gate, queue ceiling, idempotent replay, and retry gate.
- Sanitized stable 503 response and `Retry-After`.
- Safe JSON and Prometheus output with secret values/references, payload, raw metadata, and unsafe component IDs supplied as canaries.
- UTC normalization, offset conversion, naive rejection, one-microsecond preservation, and timestamp high-water behavior.
- Alembic head/index and SQLAlchemy metadata agreement.
- Worker/scheduler CLI health-check exact boundary and database-failure behavior.
- Real PostgreSQL readiness, queue aggregation, capability coverage, gate behavior, and index existence.

## Exact validation commands executed

### Migration and focused/backend suites

```bash
docker compose --profile test up -d --wait postgres-test

docker compose run --rm --no-deps -w /workspace/backend \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  api alembic upgrade head

docker compose run --rm --no-deps -w /workspace/backend \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  api python -m pytest -p no:cacheprovider -q tests/operations tests/postgres

docker compose run --rm --no-deps -w /workspace/backend \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  api python -m pytest -p no:cacheprovider -q \
  tests/postgres/test_capability_gate.py \
  tests/postgres/test_operational_health.py \
  tests/postgres/test_job_repository.py

docker compose run --rm --no-deps -w /workspace/backend api \
  python -m pytest -p no:cacheprovider -q \
  tests/test_runtime_healthcheck.py \
  tests/core/test_redaction.py \
  tests/core/test_logging_uvicorn.py

docker compose run --rm --no-deps \
  -v /tmp/newscraft-alembic-wrapper:/workspace/backend/.venv/bin/alembic:ro \
  -w /workspace/backend \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  api python -m pytest -p no:cacheprovider -q tests \
  -k 'not local_service_ports_bind_to_loopback'

docker compose run --rm --no-deps -w /workspace/backend api ruff check app tests
docker compose run --rm --no-deps -w /workspace/backend api python -m compileall -q app ../scripts
docker compose config --quiet
git diff --check
```

The temporary Alembic wrapper contained `exec /usr/local/bin/alembic "$@"`. It was mounted because one pre-existing migration test hard-codes `/workspace/backend/.venv/bin/alembic`, while the bind-mounted workspace `.venv` is empty. The installed container executable was used without changing the repository environment.

### Final deployment and smoke

```bash
env -u OPENAI_API_KEY -u OPENROUTER_API_KEY \
  -u TELEGRAM_SOURCE_EDITOR_API_ID -u TELEGRAM_SOURCE_EDITOR_API_HASH \
  -u TELEGRAM_SOURCE_EDITOR_SESSION -u TELEGRAM_DESTINATION_NEWS_TOKEN \
  docker compose -p phase9acceptance \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d --build postgres api worker-source-generation worker-publishing scheduler frontend

python3 scripts/smoke.py \
  --base-url http://127.0.0.1:8000 \
  --provider fake --telegram-mode dry-run \
  --output-dir /tmp/newscraft-smoke-phase9
```

That first unmodified smoke stopped before Diagnostics on the known Phase 10 contract drift described below. To reach Diagnostics without changing repository files, a validation-only in-memory substitution added the API's current `pending_review` dispatch state to the smoke's accepted transitional states:

```bash
python3 -c 'from pathlib import Path; import sys; path=Path("scripts/smoke.py"); source=path.read_text(); old="{\"captured\", \"researching\", \"generating\", \"needs_review\"}"; new="{\"captured\", \"researching\", \"generating\", \"needs_review\", \"pending_review\"}"; assert source.count(old)==1; sys.argv=[str(path),"--base-url","http://127.0.0.1:8000","--provider","fake","--telegram-mode","dry-run","--output-dir","/tmp/newscraft-smoke-phase9-final"]; exec(compile(source.replace(old,new),str(path),"exec"),{"__name__":"__main__","__file__":str(path)})'
```

The final run returned `generating`, which is already accepted by the unmodified smoke; therefore the added validation branch was not exercised. All 13 stages passed, including the exact `observed_at <= generated_at` Diagnostics invariant.

The smoke driver's exact Diagnostics method was also run 100 times under live concurrent heartbeats:

```bash
python3 -c 'import runpy,time; ns=runpy.run_path("scripts/smoke.py",run_name="phase9_diagnostics_smoke"); Driver=ns["SmokeDriver"]; driver=Driver(base_url="http://127.0.0.1:8000",output_dir="/tmp/newscraft-phase9-diagnostics-smoke",timeout_seconds=30); driver._deadline=driver._clock()+30; original=driver._request("GET","/automation-control").data; driver._request("PATCH","/automation-control",body={"global_pause":False,"dry_run":True}); passed=0; last=None
try:
 for _ in range(100): last=driver._diagnostics(); passed+=1
finally:
 body={"global_pause":bool(original["global_pause"]),"dry_run":bool(original["dry_run"])}
 if original["global_pause"]: body["pause_reason"]=original.get("pause_reason")
 driver._request("PATCH","/automation-control",body=body)
print("diagnostics_smoke_passed",passed,"iterations",dict(last.statuses))'
```

### Deployed probe and failure commands

```bash
curl -i --max-time 3 http://127.0.0.1:8000/health/live
curl -i --max-time 3 http://127.0.0.1:8000/health/ready
curl -fsS --max-time 3 http://127.0.0.1:8000/operations/health | python3 -m json.tool

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  stop worker-source-generation
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "UPDATE runtime_heartbeats SET observed_at = clock_timestamp() - interval '121 seconds' WHERE component_id = 'worker-source-generation';"
curl -i -X POST -H 'Content-Type: application/json' \
  -d '{"kind":"text","title":"Phase 9 final capability gate","text":"This job must not be accepted without a compatible worker.","source_label":"phase-09-final"}' \
  http://127.0.0.1:8000/stories/manual

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml stop scheduler
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "UPDATE runtime_heartbeats SET observed_at = clock_timestamp() - interval '91 seconds' WHERE component_id = 'scheduler';"

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml stop postgres
curl --max-time 3 -i http://127.0.0.1:8000/health/live
curl --max-time 5 -i http://127.0.0.1:8000/health/ready
curl --max-time 5 -i http://127.0.0.1:8000/operations/health

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "UPDATE alembic_version SET version_num = 'phase9_outdated';"
curl --max-time 3 -i http://127.0.0.1:8000/health/ready
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "UPDATE alembic_version SET version_num = '0010_readiness_health_indexes';"
```

Storage failure used a validation-only API on port 8001 with a regular file mounted where `/data/exports` must be a directory:

```bash
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  run --rm -d --no-deps --name phase9-storage-drill \
  -p 127.0.0.1:8001:8000 \
  -v /tmp/newscraft-unavailable-storage:/data/exports:ro \
  api uvicorn app.main:app --host 0.0.0.0 --port 8000
curl -i http://127.0.0.1:8001/health/live
curl -i http://127.0.0.1:8001/health/ready
docker stop phase9-storage-drill
```

Configured required-capability failure used a validation-only API on port 8002:

```bash
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  run --rm -d --no-deps --name phase9-required-capability \
  -e READINESS_REQUIRED_CAPABILITIES=source \
  -p 127.0.0.1:8002:8000 \
  api uvicorn app.main:app --host 0.0.0.0 --port 8000
curl -i http://127.0.0.1:8002/health/ready
```

Representative-volume and security validation:

```bash
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "INSERT INTO workflow_jobs (id, job_type, status, payload, result, idempotency_key, origin, scheduled_for, max_attempts) SELECT gen_random_uuid(), CASE WHEN g % 2 = 0 THEN 'phase9.volume_a' ELSE 'phase9.volume_b' END, 'failed', '{}'::jsonb, '{}'::jsonb, 'phase9-volume-' || g, 'manual', clock_timestamp() - interval '1 day', 3 FROM generate_series(1, 20000) AS g;"

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft \
  -c "EXPLAIN (ANALYZE, BUFFERS) SELECT job_type, count(*) FROM workflow_jobs WHERE status IN ('queued','running','failed','needs_review') GROUP BY job_type ORDER BY job_type;"

docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml \
  logs --no-color --tail=1000 api worker-source-generation worker-publishing scheduler | \
  rg -n 'NEWSCRAFT_SMOKE_0B1A2168|OPENROUTER_API_KEY|TELEGRAM_DESTINATION_NEWS_TOKEN|Logging error|not enough arguments for format string|Traceback'
```

The final cleanup command was:

```bash
docker compose -p phase9acceptance -f docker-compose.yml -f docker-compose.acceptance.yml down -v
```

## Test results

| Validation | Result |
|---|---|
| Pre-fix timestamp race regression | 1 intended failure; reproduced one-microsecond future observation |
| Post-fix timestamp-focused tests | 2 passed |
| Final Phase 9 `tests/operations tests/postgres` command | **240 passed** |
| Gate/operational health/job repository PostgreSQL selection | **40 passed** |
| Runtime healthcheck + Phase 5 redaction/logging selection | **39 passed** |
| Readiness/API focused selection | **20 passed** |
| Required-capability health file after final added case | **18 passed** |
| Compose contract in backend container | **20 passed, 1 deselected** |
| Host `docker compose config --quiet` | Passed |
| Final whole-backend Ruff | Passed |
| Final compileall | Passed |
| Final `git diff --check` | Passed |
| Final backend regression suite | **1,705 passed, 1 deselected, 1 warning** |
| Final deployed full smoke | **13/13 stages passed** |
| Repeated deployed Diagnostics invariant | **100/100 passed** |

The one full-suite deselection was `local_service_ports_bind_to_loopback`: the backend test container has no Docker CLI. Its exact host-side Compose configuration check passed.

Two non-green full-suite attempts were investigated and superseded:

1. Before the capability gate was added, 1,699 tests passed and one migration test failed because the bind-mounted workspace has no `.venv/bin/alembic`. Mounting the installed container executable at the test's hard-coded path made that exact test pass.
2. After adding the gate, eight tests using minimal session doubles failed because those doubles had no `.info` attribute. The gate marker check was made safely tolerant of non-API/test sessions; all eight exact regressions passed, followed by the clean 1,705-test run.

The only warning is Starlette's `TestClient` deprecation notice for its current `httpx` integration.

## Deployed smoke evidence

Final smoke report:

`/tmp/newscraft-smoke-phase9-final/smoke-20260717T184751044540Z-0b1a2168.json`

Evidence:

- Status `succeeded`, `failed: []`, cleanup succeeded.
- All 13 ordered stages passed in 9.040 seconds.
- Diagnostics passed in 70 ms.
- Diagnostics components: scheduler healthy, publishing worker healthy, source/generation worker healthy.
- Diagnostics invariants: `runtime_diagnostics`, `queue_truth`, and `control_truth`.
- The earlier `component_observation_from_future` invariant did not recur.
- A separate exact Diagnostics loop passed 100/100 concurrent-heartbeat observations.
- Final Compose state before cleanup showed API, PostgreSQL, scheduler, publishing worker, and source/generation worker healthy.
- The final ten-run Phase 1/Phase 2 gate was **not started**, as required.

One earlier unmodified smoke stopped at `telegram_dry_run` because the API returned `pending_review`, while `scripts/smoke.py` accepts `captured`, `researching`, `generating`, or `needs_review`. This is the already documented Phase 10 contract-drift class, occurs before Diagnostics, and was not changed in Phase 9. The successful final run returned `generating`, so the validation-only `pending_review` allowance did not affect its result.

## Deployed failure and latency evidence

- Final liveness, 50 requests: p95 **4.000 ms**, max 45.429 ms.
- Final readiness, 50 requests: p95 **9.419 ms**, max 13.785 ms.
- Rich operational health with 20,000 synthetic workflow rows, 50 requests: p95 **60.097 ms**, max 193.928 ms.
- PostgreSQL aggregate plan at that volume: 13.327 ms execution. PostgreSQL correctly chose a sequential scan because virtually every synthetic row matched; the Phase 9 index exists and is covered by migration/model tests.
- Database stopped: liveness 200; readiness 503 in 901 ms with `database_unavailable`; rich health remained 200 with safe unavailable/unknown projections. Readiness returned to 200 after restart.
- Schema marker outdated: readiness 503 with `schema_mismatch`; restored head returned readiness to 200.
- Required export storage replaced by a non-directory: liveness 200; readiness 503 with `export_storage_unavailable`; no path was returned.
- Optional source/generation worker stopped and aged: ordinary API readiness remained 200; component became unavailable; read diagnostics remained available.
- With that worker unavailable, `POST /stories/manual` returned 503, `Retry-After: 5`, and only `job_capability_unavailable`, `manual_intake`, and the retry duration.
- A due `manual_intake` job with the worker unavailable was projected as `no_compatible_worker` in one probe; restarting the worker drained the job and returned `workerless_due_job_types` to zero.
- Scheduler stopped and aged beyond 90 seconds: scheduler became unavailable with a safe alert/runbook while optional-component loss left API readiness 200.
- `READINESS_REQUIRED_CAPABILITIES=source`: readiness was 200 with the fresh worker and 503 `capability_unavailable` after the worker crossed the 60-second fresh boundary.
- Endpoint scan across ready, rich health, metrics, and Diagnostics found no smoke secret-reference canary, provider/destination credential reference, database URL, or `secret_ref` key.
- Bounded API/worker/scheduler logs contained no smoke canary, credential-reference names, `Logging error`, formatter-argument failure, or traceback.

## Acceptance-criteria checklist

### Phase 9 acceptance criteria

- [x] **Liveness responds within 100 ms without dependency I/O.** Direct no-session-dependency contract test passed; deployed p95 was 4.000 ms and max was 45.429 ms.
- [x] **Core readiness p95 is below one second and uses bounded queries.** Deployed p95 was 9.419 ms; database and storage checks have explicit timeouts; 20,000-row rich health p95 was 60.097 ms.
- [x] **Database failure returns 503.** Direct deployed stop/recovery drill passed.
- [x] **Schema failure returns 503.** Unit regression and direct deployed schema-marker drill passed.
- [x] **Required storage failure returns 503.** Unit regression and deployed non-directory export-root drill passed.
- [x] **Optional worker loss preserves read diagnostics while marking/gating the exact capability.** Direct deployed drill showed readiness 200, readable health, unavailable worker state, and exact `manual_intake` 503 gate.
- [x] **Configured required capability loss returns readiness 503.** Focused regression and deployed `READINESS_REQUIRED_CAPABILITIES=source` drill passed.
- [x] **Threshold boundaries match documented values.** Controlled microsecond boundary tests cover 45/60/90/120 seconds.
- [x] **Every hard state has an alert and runbook URL.** Unit projection tests and deployed worker/scheduler/database/queue outputs verified fixed alert codes and runbook URLs.
- [x] **Expired lease is visible within one probe.** Focused queue fixture reports `expired_running_lease` unavailable.
- [x] **Due work with no compatible worker is visible within one probe.** Focused unit, real PostgreSQL, and deployed drills passed.
- [x] **No secret value/reference, payload, source content, or proxy credential appears in health/metric labels.** Canary unit tests, endpoint scan, and bounded log scan passed.

### User-requested focused tests

- [x] Liveness.
- [x] Readiness success.
- [x] Database failure.
- [x] Unavailable storage.
- [x] Fresh and stale worker heartbeats.
- [x] Fresh and stale scheduler heartbeat.
- [x] No capable worker for due work.
- [x] Timestamp boundary and race behavior.
- [x] Safe diagnostics output.
- [x] Timezone and precision handling.
- [x] Stuck, overdue, and excessively retried jobs.
- [x] Exact API capability gate and queue ceiling.

## Definition of Done checklist

- [x] **Live, core-ready, and rich operational boundaries are distinct.** Routes and dependency-I/O tests directly verify the separation.
- [x] **Worker/scheduler heartbeat and last-success semantics are truthful.** Independent-loop, blocked-handler, exact metadata, and deployed freshness tests passed.
- [x] **Capability queue/lease metrics and thresholds are implemented and indexed.** Migration/model, fixture, PostgreSQL, EXPLAIN, and representative-volume tests passed.
- [x] **Compose checks, endpoint gates, alerts, and runbooks agree.** Direct Compose contract, CLI health, endpoint-gate, required-capability, alert, and runbook tests passed.
- [x] **Failure drills meet latency/status/no-leak criteria.** Database, schema, storage, worker, scheduler, configured capability, endpoint scans, log scans, and latency measurements passed.

## Remaining risks and unverified items

- The separate final ten-run Phase 1/Phase 2 deployed gate was intentionally not run. This report does not claim it.
- The pre-existing Phase 10 smoke contract can nondeterministically stop before Diagnostics when the dispatch is already `pending_review`. It was not fixed here. The final successful run returned the unmodified accepted `generating` state.
- Compose marks unhealthy services but does not restart them. Automated restart/backoff remains Phase 3 and was intentionally not implemented.
- Credential/provider topology remains Phase 6 and was intentionally not inferred from secret configuration. Phase 9 consumes only safe runtime capability/job-type advertisements.
- Rich health is uncached. Current 20,000-row evidence is well below the one-second gate, but production should re-benchmark at materially larger cardinality before changing probe frequency.
- PostgreSQL outage readiness measured 901 ms against a 0.9-second timeout, leaving little scheduling margin below one second on the hard-failure path. The directly required healthy p95 gate passed comfortably; operators should keep probe timeouts above the application bound.
- Platform-supplied restart counts and external alert-delivery/on-call routing were not available in this repository. Phase 9 emits actionable alert objects, metrics, and runbook URLs; it does not claim an external alert receiver was verified.
- The full backend suite's one Docker-CLI test was verified on the host rather than inside the backend image, which intentionally does not contain Docker.

None of these items invalidates a directly tested Phase 9 acceptance criterion or Definition of Done item.

## Confirmation of phase scope

- **Phase 3:** no restart policy, process supervisor, backoff, or automated restart action added.
- **Phase 5:** no logging formatter or redaction production change made; direct regression and deployed log scans passed.
- **Phase 6:** no credential topology, secret discovery, provider credential status, or credential reference output added.
- **Phase 10:** no frontend type, mock, status-contract, or smoke-script change made.
- **Other phases:** no implementation work performed.

The migration, probe endpoints, heartbeat loops, safe metrics/alerts, capability admission gate, queue/lease projection, timestamp fix, tests, Compose checks, and runbook are all Phase 9 work.

## Is Phase 9 genuinely complete?

**Yes.** Every Phase 9 acceptance criterion and Definition of Done item is marked passed only where direct unit, PostgreSQL, Compose, deployed failure-drill, latency, security-scan, or smoke evidence exists. The timestamp race was reproduced before the fix and was absent from all post-fix focused and deployed observations. The known Phase 10 smoke drift and the explicitly deferred repeated Phase 1/Phase 2 gate are reported without being misclassified as Phase 9 completion evidence.
