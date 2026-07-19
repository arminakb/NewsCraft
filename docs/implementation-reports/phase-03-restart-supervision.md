# Phase 3 restart supervision implementation report

Date: 2026-07-18  
Status: **COMPLETE**  
Host/Docker-daemon restart criterion: **NOT VERIFIED**

## Scope and defect reproduction

This change implements Phase 3 only. It preserves the completed route response boundary,
worker execution boundary, outbound proxy policy, logging/redaction boundary, credential
topology, and readiness/operational-health model.

The missing-supervision defect was reproduced before implementation. Existing stopped
containers remained down, and inspection showed:

```text
/newscraft-api-1 restart=no status=exited exit=255 health=unhealthy
/newscraft-postgres-1 restart=no status=exited exit=0 health=unhealthy
```

The base Compose file had no restart directives, so Docker's effective policy was `no`.
The API command also combined `alembic upgrade head` and Uvicorn. A worker/scheduler exit
therefore removed execution capacity indefinitely, while putting an automatic restart policy
on that API command would also have made a bad migration loop.

The confirmed root cause was the absence of an environment-specific supervisor contract.
Health checks and durable leases supplied visibility/recoverability, but neither starts an
exited container. Compose also does not restart a merely `unhealthy` container.

## Before-and-after service policy matrix

| Service | Before | Base/dev/test/acceptance | Production | Process form |
|---|---|---|---|---|
| `postgres` | effective `no` | `no` | `unless-stopped` | long-running |
| `api` | effective `no`; migration inline | `no` | `unless-stopped` | Docker init + Uvicorn only |
| `frontend` | effective `no` | `no` | `unless-stopped` | Docker init + Next.js |
| `worker-source-generation` | effective `no` | `no` | `unless-stopped` | Docker init + worker |
| `worker-publishing` | effective `no` | `no` | `unless-stopped` | Docker init + worker |
| `scheduler` | effective `no` | `no` | `unless-stopped` | Docker init + scheduler |
| `migrate` | part of API command | `no` | `no` | one-shot Alembic command |
| `postgres-test` | effective `no` | `no` | `no` | explicit test profile |

Production application services use `init: true`. The minimal init process forwards signals,
reaps children, and makes it possible to SIGKILL the supervised application child without
Docker classifying the operation as a manual container stop. It is not a watchdog or autoheal
agent.

## Migration service design

`migrate` is a separate backend-image service with:

```yaml
restart: "no"
command: alembic upgrade head
depends_on:
  postgres:
    condition: service_healthy
```

API runs Uvicorn only and depends on `migrate` with
`condition: service_completed_successfully`. Within a Compose project, API replicas therefore
wait for the same completed migration service instead of independently racing Alembic.

The current deployment implementation is Docker Compose 5.1.4. Base, development, test,
acceptance, and production configurations all rendered successfully with the completion
condition.

Restore now runs `docker compose run --rm --no-deps migrate` after replacing the database and
volumes. It then starts exactly the five runtime services using
`docker compose up -d --no-deps ...`. `--no-deps` is important: a drill proved that
`docker compose start` traverses dependencies and can rerun a completed migration service.

## Health-check and diagnostics design

Worker and scheduler container probes query the existing Phase 9 PostgreSQL heartbeat row. A
probe succeeds only when all of the following match:

- exact component ID and component type;
- exact sorted capability set;
- exact registered/claimable job-type set;
- timezone-aware, fresh heartbeat bounded by PostgreSQL time;
- live database access.

Missing, stale, wrong-ID, wrong-type, wrong-capability, wrong-job-coverage, malformed timestamp,
or database-failure cases exit nonzero without printing exception, connection, payload, or
credential data. Scheduler uses the same implementation with its own identity, `scheduling`
capability, empty claimable-job set, and 90-second maximum age.

Frontend has a process-only `/health` route. API continues to use Phase 9 readiness. Health is
visibility: no watchdog exits a process because a probe is unhealthy, and no Docker-socket
autoheal sidecar was added.

Each worker/scheduler process records a random instance marker and process start time. The
heartbeat service retains at most 32 sanitized restart timestamps. Operational health projects:

- `stable`, `recovered`, `crash_loop`, or `unknown` restart state;
- restart count in the configured 600-second window;
- `restart_rate_high` at three observed process changes;
- recent lease-recovery records using safe job UUID and validated job type only;
- `repeated_lease_recovery`, `poison_job_terminal`, and
  `recovery_requires_review` alerts/metrics.

Docker `RestartCount` remains authoritative deployment evidence. Application restart history is
an observable process-instance history and intentionally does not require Docker-socket access.

Two no-side-effect job types provide worker-compatible deployed canaries:

- `operations.canary.source_generation`
- `operations.canary.publishing`

The canary validates queue claim and completion only. A bounded `hold_seconds` of 0 through 60
supports an in-flight lease drill; it performs no provider, source, storage, or publishing side
effect. CLI `max_attempts` is limited to 1 through 3.

## Changed files

Deployment and runtime:

- `docker-compose.yml`
- `docker-compose.production.yml`
- `docker-compose.dev.yml`
- `docker-compose.test.yml`
- `docker-compose.acceptance.yml`
- `backend/app/core/config.py`
- `backend/app/jobs/canary.py`
- `backend/app/jobs/healthcheck.py`
- `backend/app/jobs/registry.py`
- `backend/app/jobs/runtime.py`
- `backend/app/jobs/worker.py`
- `backend/app/jobs/scheduler.py`
- `backend/app/operations/health.py`
- `frontend/app/health/route.ts`
- `scripts/backup_restore.py`

Tests and exact registry expectations:

- `backend/tests/test_docker_config.py`
- `backend/tests/test_restart_canary.py`
- `backend/tests/test_runtime_healthcheck.py`
- `backend/tests/test_runtime_heartbeat.py`
- `backend/tests/test_job_handler_registry.py`
- `backend/tests/test_telegram_route_handlers.py`
- `backend/tests/test_telegram_publish_service.py`
- `backend/tests/integration/test_worker_crash_recovery.py`
- `backend/tests/integration/test_registered_handler_process_crashes.py`
- `backend/tests/operations/test_health.py`
- `backend/tests/operations/test_backup_restore_script.py`
- `backend/tests/postgres/test_operational_health.py`

Documentation:

- `README.md`
- `docs/operations/restart-supervision.md`
- `docs/operations/readiness-and-health.md`
- `docs/operations/backup-and-restore.md`
- this report

No Phase 3 schema migration was added.

## Automated validation

### Final full backend suite

The exact final tree was tested in one invocation. A temporary executable wrapper was mounted
over the workspace's pre-existing zero-byte, non-executable `.venv/bin/alembic`; it invoked the
image's installed `python -m alembic` and did not change the repository.

```bash
docker run --rm --network newscraft_default \
  -v /home/armin/Documents/NewsCraft:/workspace \
  -v /tmp/newscraft-phase3-alembic-final:/workspace/backend/.venv/bin/alembic:ro \
  -w /workspace/backend \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins:/usr/lib/docker/cli-plugins:ro \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@postgres-test:5432/newscraft_test \
  -e ENRICHMENT_PROVIDER=none -e LLM_PROVIDER=none \
  newscraft-backend:local python -m pytest -p no:cacheprovider -q
```

Result:

```text
1778 passed, 1 warning in 359.36s (0:05:59)
```

The warning is the existing Starlette/httpx deprecation warning. This single run includes
Compose policy/render tests, migration tests, health checks, Phase 9 diagnostics, Phase 6
credential topology, Phase 4 proxy policy, Phase 5 logging/redaction, Phase 1 route behavior,
Phase 2 worker/lease/publishing crash recovery, and the poison process test.

Additional focused results collected while developing the phase:

- Phase 3/registry/health/backup focus: `179 passed in 9.55s`.
- Compose policy suite after final init policy: `29 passed in 2.76s`.
- Backup/restore command suite after `--no-deps` correction: `32 passed in 0.83s`.
- Real process-killing poison test: `1 passed in 17.57s`.
- Final canary/registry focus: `13 passed in 3.58s`.
- PostgreSQL runtime-heartbeat focus: `11 passed`.

### Compose renders

Each command returned exit 0:

```bash
docker compose --env-file /dev/null --profile '*' -f docker-compose.yml config --quiet
docker compose --env-file /dev/null --profile '*' -f docker-compose.yml -f docker-compose.dev.yml config --quiet
docker compose --env-file /dev/null --profile '*' -f docker-compose.yml -f docker-compose.test.yml config --quiet
docker compose --env-file /dev/null --profile '*' -f docker-compose.yml -f docker-compose.acceptance.yml config --quiet
docker compose --env-file /dev/null --profile '*' -f docker-compose.yml -f docker-compose.production.yml config --quiet
```

### Frontend and static validation

- `docker compose ... build api frontend`: backend and production Next.js image passed; Next.js
  compiled, ran TypeScript, and generated all 17 routes including `/health`.
- `npm run typecheck`: exit 0.
- `npm test`: 369 passed, 1 unrelated story-inbox test timed out at its existing 10-second
  limit; isolated rerun timed out at the same test. Phase 3 does not modify story-inbox code.
- `ruff check .`: all checks passed.
- Phase 3-targeted `ruff format --check`: 20 Python files formatted; both changed ranges in
  `scripts/backup_restore.py` formatted.
- `python -m compileall -q app tests`: exit 0.
- `git diff --check`: exit 0.

Repository-wide `ruff format --check .` reports 103 pre-existing unrelated files that would be
reformatted. They were intentionally not mechanically rewritten during this phase.

## Deployed drills

All drills used isolated Compose project names, new volumes, inert credential files, direct
proxy mode, and no live Telegram or provider credentials.

### Migration failure

A temporary override replaced the migration command with `sh -c "exit 42"`:

```bash
docker compose -p phase3-migration \
  -f docker-compose.yml \
  -f /tmp/newscraft-phase3-migration-failure.yml up -d api
```

The command failed visibly with `service "migrate" didn't complete successfully: exit 42`.
Inspection showed:

```text
/phase3-migration-migrate-1 restart=no count=0 status=exited exit=42
/phase3-migration-api-1 restart=no count=0 status=created exit=0
```

The migration did not restart and API never started.

### Successful one-shot migration

A fresh production-policy project started only API and dependencies:

```bash
docker compose --env-file /dev/null -p phase3-once \
  -f docker-compose.yml -f docker-compose.production.yml up -d api
```

The sole Alembic log sequence advanced `0001` through `0010`. Inspection after API became
healthy showed:

```text
restart=no count=0 status=exited exit=0
started=2026-07-18T18:58:20.203319722Z
finished=2026-07-18T18:58:25.997260755Z
```

### Idle process kill and recovery

The production application child was killed beneath Docker init with:

```bash
docker exec SERVICE-CONTAINER sh -c \
  'read child rest < /proc/1/task/1/children; kill -KILL "$child"'
```

| Service | Docker restart count | Recovery evidence |
|---|---:|---|
| source/generation worker | 1 | healthy exact heartbeat; source canary succeeded |
| publishing worker | 1 | healthy exact heartbeat; publishing canary succeeded |
| scheduler | 1 | healthy exact heartbeat and fresh successful tick |
| API | 1 | `/health/ready` ready about 13 seconds after new start |
| frontend | 1 | `/health` returned `{"status":"alive"}` |

The source and publishing canary commands completed in 8.9 and 7.4 seconds respectively after
their replacement workers were available. All recoveries were below the documented 90-second
heartbeat and 180-second canary bounds.

`docker compose kill` was deliberately tried first and was observed to behave like an operator
stop under `unless-stopped`; Docker suppressed restart. The runbook therefore uses a real child
process SIGKILL and explicitly warns against `compose kill` for this drill.

### In-flight leased canary

The final isolated project enqueued:

```bash
docker exec phase3-inflight-api-1 python -m app.jobs.canary \
  --target source-generation --hold-seconds 30 --max-attempts 2 --wait-seconds 240
```

PostgreSQL first showed:

```text
90f4e654-3e4a-4d8b-a35e-436a4e459fc5|running|1|2|worker-source-generation
```

The worker child was SIGKILLed while it owned that lease. Docker returned a replacement with
restart count 1, while the job remained fenced to the first lease owner until expiry. The durable
event sequence was:

```text
19:05:57.501663 job.enqueued
19:05:58.100119 job.claimed       (attempt 1)
19:05:58.122807 job.heartbeat
19:08:03.832126 job.lease_expired
19:08:04.917646 job.claimed       (attempt 2)
19:08:04.943714 job.heartbeat
19:08:34.976412 job.heartbeat
19:08:34.987004 job.succeeded
```

Outcome:

```json
{"job_id":"90f4e654-3e4a-4d8b-a35e-436a4e459fc5","status":"succeeded"}
```

End-to-end enqueue-to-success time was about 157.5 seconds. Diagnostics reported the worker as
healthy/recovered and the job as `lease_recovered`, `attempt_count: 2`, `max_attempts: 2`.
There was one job identity, one lease-expiry event, one terminal success, and no external or
material side effect.

### Manual stop

```bash
docker compose ... stop worker-source-generation
```

The worker remained `exited` with Docker restart count unchanged at 1 until an explicit
`docker start phase3-drill-worker-source-generation-1`. The runbook avoids `docker compose start`
when preserving the current container because Compose can traverse and rerun completed
dependencies.

### Crash-rate warning

After three rapid source-worker child SIGKILLs, Docker restart count reached 3 and the replacement
still completed a source canary. `/operations/health` reported:

```text
state=stale
component=worker-source-generation
code=restart_rate_high
restart_state=crash_loop
crash_loop_components=1
```

The application count was 6 in that ten-minute window because it also truthfully included earlier
process recreations/manual starts in the same persisted component history.

### Poison job and duplicate prevention

The poison regression now spawns a separate real worker process for each attempt. Each process
claims `fault.poison` and exits after the claim without a terminal transition. Three lease
expiries produce:

- terminal `failed` status;
- `attempt_count == max_attempts == 3`;
- safe error code `worker_lease_expired` in durable job state;
- no fourth claim;
- exactly three `job.lease_expired` events and one `job.failed` event;
- safe `poison_job_terminal` diagnostic/alert and metric;
- no payload, error text, credential value, or reference in health output.

Publishing recovery continues to route a dispatching/ambiguous receipt to `needs_review` rather
than resend. The full crash matrix covers 18 registered job types and termination before a
material side effect, after durable checkpoint, before terminal transition, during lease
ownership, after lease reassignment, and after terminal commit. Assertions preserve:

- stale-owner terminal fencing;
- one revision/generation-run identity;
- ingestion deduplication;
- one export artifact identity;
- one publishing operation/receipt;
- no duplicate fake Telegram send.

## Acceptance checklist

- [x] Production policies are explicit for all long-running services.
- [x] Base, development, test, acceptance, migration, and test-job policies are explicitly `no`.
- [x] Migration is one-shot; failure leaves API unavailable without a restart loop.
- [x] Current Compose supports and rendered `service_completed_successfully` in all modes.
- [x] Source/generation worker SIGKILL recovery, fresh heartbeat, and compatible canary verified.
- [x] Publishing worker SIGKILL recovery, fresh heartbeat, and compatible canary verified.
- [x] Scheduler SIGKILL recovery, fresh heartbeat, and tick verified.
- [x] API and frontend process recovery verified.
- [x] In-flight leased canary recovered once and succeeded within 180 seconds.
- [x] Explicit manual stop remained stopped.
- [x] Three rapid crashes produced a visible crash-loop warning.
- [x] Poison retries are bounded, terminal, visible, and non-reclaimable.
- [x] Duplicate-prevention and publishing ambiguity suites are green.
- [x] Phase 1, 2, 4, 5, 6, and 9 backend regressions are green.
- [x] Required frontend typecheck and production build are green.
- [x] All Phase 3 containers, networks, volumes, test database, wrappers, and inert secret files
  were removed.
- [ ] **NOT VERIFIED:** host or Docker-daemon restart recovery.

## Cleanup evidence

Every `phase3-migration`, `phase3-drill`, `phase3-once`, and `phase3-inflight` project was removed
with `docker compose ... down -v`. The temporary default-project `postgres-test` container was
stopped and removed without changing existing user containers or persistent volumes. Final
filters showed no Phase 3 containers, volumes, or networks. A pre-existing
`newscraft-acceptance-audit2-postgres-test-1` container was intentionally left untouched.

## Remaining risks

- **Host/daemon restart is NOT VERIFIED.** Restarting the shared Docker daemon was not safe in
  this workspace. A staging host must still verify `unless-stopped` across daemon/host restart.
- Docker Compose does not restart an `unhealthy` process. External alerting must act on stale
  heartbeat, queue-capability gaps, and crash-rate signals; no socket-privileged autoheal was
  added.
- Application restart history cannot distinguish a crash from a reviewed manual process
  recreation. Operators should correlate it with Docker `RestartCount` and deployment events.
- Local Compose reports that bind-file secret `mode` is ignored. Drill files were host mode 0400;
  production must preserve restrictive host ownership/mode or use a secrets backend.
- The unrelated frontend story-inbox timeout and repository-wide formatting backlog remain
  outside Phase 3 scope.

## Rollback

Pause automation, inspect all running leases, and reconcile ambiguous publishing receipts before
changing supervision. Render the intended Compose configuration, remove/revert the production
restart override, and recreate only affected services. Keep the Phase 2 execution boundary and
duplicate-prevention mechanisms. Never restore inline migration under an unlimited API restart
policy; if the completion dependency is unavailable on a target, keep API down, run migration
exactly once, verify schema head, and use a reviewed compatibility deployment.
