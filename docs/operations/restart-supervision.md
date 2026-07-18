# Restart supervision

NewsCraft uses Docker's restart manager only in the production Compose mode. The durable queue,
lease fencing, handler checkpoints, artifact identities, and Telegram receipts make interrupted
work recoverable; restart policy restores execution capacity after a process exits.

## Policy matrix

| Service | Base/dev/test/acceptance | Production | Meaning |
|---|---|---|---|
| `postgres` | `no` | `unless-stopped` | Long-running database |
| `api` | `no` | `unless-stopped` | Uvicorn only; never runs migrations |
| `frontend` | `no` | `unless-stopped` | Next.js HTTP process |
| `worker-source-generation` | `no` | `unless-stopped` | Ingestion/source/generation claims |
| `worker-publishing` | `no` | `unless-stopped` | Destination checks and publishing claims |
| `scheduler` | `no` | `unless-stopped` | Lease recovery and due-work scheduling |
| `migrate` | `no` | `no` | One-shot Alembic upgrade |
| `postgres-test` | `no` | `no` | Explicit test resource |

`docker-compose.dev.yml`, `docker-compose.test.yml`, and
`docker-compose.acceptance.yml` repeat the non-restarting policy so local behavior is not hidden
in undocumented configuration. One-shot `docker compose run` commands and backup/restore actions
must not be given automatic restart.

## Migration behavior

`migrate` waits for healthy PostgreSQL, runs `alembic upgrade head` once, and exits. API depends
on `service_completed_successfully`, so an upgrade failure leaves `migrate` visibly failed and
API unavailable. Because `migrate` has `restart: "no"`, a bad migration cannot create an
unlimited API restart loop and concurrent API replicas do not race to migrate.

The supported Docker Compose implementation must render this dependency condition before every
deployment:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
```

Local development remains `docker compose up api`; Compose starts PostgreSQL and `migrate` as
dependencies. Restore runs the same image and command with
`docker compose run --rm --no-deps migrate` after database and volume replacement.

## Exited is not unhealthy

- An exited production long-running container is restarted by `unless-stopped`.
- An `unhealthy` container keeps running. Compose does not restart it automatically.
- Health checks provide visibility: API readiness checks DB/schema/storage; frontend checks its
  process-only `/health`; workers and scheduler require exact persisted component identity,
  component type, capability set, claimable job types, heartbeat freshness, and DB access.
- There is no Docker-socket autoheal sidecar and no application watchdog that exits a process
  solely because a probe failed.

The operational projection reports missing/stale heartbeat, due work without a compatible
worker, application-observed process restarts, restart-rate warnings, and recent lease-recovery
or poison-job identifiers. Docker `RestartCount` must still be captured during deployment drills.

## Kill and recovery drill

Use an isolated Compose project, fake provider, dry-run publication, and empty test credentials.
Never use a live Telegram token. Record timestamps before each action.

```bash
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml \
  up -d --build
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml ps
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml \
  exec -T worker-source-generation sh -c \
  'read child rest < /proc/1/task/1/children; kill -KILL "$child"'
docker inspect -f '{{.RestartCount}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' \
  phase3-drill-worker-source-generation-1
curl -fsS http://127.0.0.1:8000/operations/health
```

Repeat for `worker-publishing` and `scheduler`. For workers, require a new fresh heartbeat and a
compatible isolated canary to reach its expected terminal state. For scheduler, require a fresh
heartbeat and successful tick metadata. Repeat process recovery for API and frontend, then run
the fake/dry-run acceptance smoke. Recovery targets are fresh heartbeat within 90 seconds and
compatible canary completion within 180 seconds.

Production app services use Docker's minimal init process. The command above kills the worker
child process; init then exits and Docker observes an unexpected container exit. Do not use
`docker compose kill` for this drill: Docker treats that operator action like a manual stop under
`unless-stopped`, so it intentionally suppresses automatic restart.

The worker canaries only validate queue claim and completion; they do not contact an upstream or
publishing destination:

```bash
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml \
  exec -T api python -m app.jobs.canary --target source-generation --wait-seconds 180
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml \
  exec -T api python -m app.jobs.canary --target publishing --wait-seconds 180
```

For an in-flight lease-recovery drill, `--hold-seconds 30 --max-attempts 2` creates a bounded
no-side-effect execution window. Kill the owning worker only after PostgreSQL shows that canary
as `running`; the scheduler must recover the expired lease and the replacement worker must make
the same job `succeeded`. Do not add a process-exit payload to a production handler.

For in-flight safety, use the controlled fault suites rather than a live side effect. They cover
death before a side effect, after a durable checkpoint, before job terminalization, while a lease
is owned, after lease reassignment, and after terminal commit. They assert lease-owner fencing,
one revision/run/export identity, ingestion deduplication, and Telegram ambiguity without resend.

## Manual stop semantics

`unless-stopped` respects an explicit stop. Verify it in the isolated project:

```bash
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml \
  stop worker-source-generation
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml ps -a
```

The service must remain stopped until an operator starts that container or recreates the service.
Use `docker start phase3-drill-worker-source-generation-1` when preserving the current container;
`docker compose start` also traverses dependencies and can rerun a completed one-shot dependency.
Do not use a process signal when the intent is a durable manual stop.

## Poison jobs

Every claim increments `attempt_count`. A process-killing job is recovered only after lease
expiry; it is requeued while `attempt_count < max_attempts` and becomes terminal failed with the
safe code `worker_lease_expired` on the final attempt. Publishing with a dispatching receipt
becomes `needs_review` instead of being resent. Operators must never reset attempts or clear an
ambiguous receipt to make a queue appear healthy.

`GET /operations/health` reports safe job UUIDs for `repeated_lease_recovery`,
`poison_job_terminal`, and `recovery_requires_review`. Investigate the referenced job and code,
disable the triggering automation if necessary, preserve evidence, and correct the handler or
input before an explicit operator retry.

## Backup/restore interaction

The backup/restore tool stops exactly API, both workers, scheduler, and frontend. PostgreSQL stays
up and `migrate` is one-shot, so neither belongs to the long-running stop/start tuple. A manual
stop remains stopped under production policy; after the one-shot migration succeeds, the restore
tool uses `docker compose up -d --no-deps` for exactly the five runtime services. This avoids
traversing the API dependency graph and running migration a second time. On any restore failure,
keep them stopped and follow `docs/operations/backup-and-restore.md`.

## Rollback

Before changing supervision policy, pause automation, inspect running leases, drain or record
in-flight work, and reconcile every ambiguous publication. Render the intended Compose files,
then remove/revert the production override and recreate only the affected services. Do not roll
back the Phase 2 execution boundary or duplicate-prevention mechanisms.

If the one-shot dependency condition is incompatible with the target Compose implementation,
keep API unavailable, run the migration explicitly once, verify the schema head, and use a
reviewed compatibility deployment. Do not restore inline migration plus unlimited API restart as
an emergency shortcut.

Clean an isolated drill only after evidence is captured:

```bash
docker compose -p phase3-drill -f docker-compose.yml -f docker-compose.production.yml down -v
```
