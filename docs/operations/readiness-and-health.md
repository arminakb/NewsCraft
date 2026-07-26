# Readiness and operational health

NewsCraft exposes three different health boundaries. They are intentionally not interchangeable.

- `GET /health/live` proves only that the API process and event loop can answer. It performs no database or storage IO.
- `GET /health/ready` proves database connectivity, the exact Alembic schema head, readable/traversable media and export storage, and any capabilities listed in `READINESS_REQUIRED_CAPABILITIES`. It returns HTTP 503 when a required check is not healthy.
- `GET /operations/health` returns sanitized dependency, component, queue, recent lease-recovery, alert, and metric state. `GET /operations/metrics` exposes the same bounded measures in Prometheus text format.
- `GET /operations/diagnostics` is the operator/UI diagnostics contract.

The JSON diagnostic projections also include the safe outbound proxy summary defined in `docs/operations/outbound-proxy-policy.md`: mode, scheme, bypass count, last connectivity status, and a sanitized configuration error code only. Proxy configuration does not change core database/storage readiness; the owning outbound capability fails safely when its policy is invalid or its configured proxy is unavailable.

API-owned asynchronous mutations and operator retries are admitted only when a fresh worker heartbeat advertises the exact job type and that type is below `CAPABILITY_QUEUE_CEILING`. Rejections use HTTP 503 with the stable codes `job_capability_unavailable`, `job_capability_unknown`, or `job_queue_capacity_exceeded`, plus a `Retry-After` header. Idempotent replays still return the already accepted job. Scheduler and worker continuation sessions are not API-gated.

## State meanings

- `healthy`: the required observation is fresh and no hard anomaly is present.
- `stale`: the last trustworthy observation or progress is older than its warning threshold.
- `unavailable`: a required dependency or compatible execution path cannot currently serve work.
- `unknown`: no trustworthy observation exists, or the observation has an invalid shape or clock boundary.

Worker heartbeat boundaries are healthy through 60 seconds, stale above 60 through 120 seconds, and unavailable above 120 seconds. Scheduler boundaries are healthy through 45 seconds, stale above 45 through 90 seconds, and unavailable above 90 seconds. Missing components are unknown.

Each worker and scheduler heartbeat also carries an internal process-instance marker and start
time. The heartbeat service preserves only bounded restart timestamps; raw process-instance
markers are never projected. One or two observed process changes in the ten-minute window are
`recovered`; three or more are `crash_loop` and raise `restart_rate_high`. Docker's authoritative
container `RestartCount` remains deployment evidence and is captured separately during drills.

Queue warning/unavailable ages are 2/5 minutes for publishing and manual intake, 5/15 minutes for source/generation/research/route work, and 10/30 minutes for export, retention, and other background work. A due job with no fresh worker advertising that exact job type is unavailable immediately. An expired lease or active retry exhaustion is unavailable; stale running progress, excessive duration, and near-exhausted retry pressure are stale.

All timestamps are timezone-aware UTC values with microseconds preserved. Operational snapshots read PostgreSQL time after their data queries and use a high-water boundary over returned observations. A component timestamp more than one second ahead of the database clock is unknown rather than silently treated as fresh.

## Database unavailable

Keep `/health/live` available for process diagnosis. Check PostgreSQL service health, connectivity, pool exhaustion, and the configured database name. Readiness and operational output intentionally return constant error codes rather than connection strings or exception text.

## Schema mismatch

Run the normal one-shot deployment migration command and verify `alembic current` equals the application schema head. Do not bypass this readiness failure by changing the expected revision.

## Storage unavailable

Verify that the API container has the required media and export mounts and can open, read, and traverse both directories. Health checks never return filesystem paths and do not create probe files.

## Heartbeat missing or stale

Inspect the affected worker or scheduler process and its safe access/error logs. A fresh runtime heartbeat with overdue active work means the process is alive but its main work has stopped making timely progress. Compose health status remains visibility only: `unhealthy` does not trigger a restart. Production restart policy acts only after process/container exit; see `docs/operations/restart-supervision.md`.

## Capability unavailable

Check that at least one fresh worker advertises the required semantic capability. `READINESS_REQUIRED_CAPABILITIES` is deployment policy; leaving it empty keeps worker loss from removing API read/diagnostic access. Due work is still reported unavailable when no fresh heartbeat advertises the exact compatible job type.

## Queue and lease anomalies

For `no_compatible_worker`, restore the correct capability worker before adding more work. For `expired_running_lease`, inspect lease recovery and the owning worker before retry. For `active_retry_exhausted`, preserve evidence and terminalize through the existing bounded job policy. For stale/overdue work, inspect queue age, active progress, provider latency, and pause state. Never manually clear an ambiguous publication receipt.

The `recoveries` projection identifies recent interrupted jobs only by safe UUID and validated
job type. Repeated lease recovery raises `repeated_lease_recovery`; a final process-interrupted
attempt raises `poison_job_terminal`; ambiguous publishing raises `recovery_requires_review`.
No payload or error text is included.

## Security boundary

Health JSON and Prometheus labels contain only fixed codes, counts, durations, sanitized component identifiers, allowlisted capabilities, and validated job types. They never include job payloads, source content, error text, storage paths, connection URLs, credential values, or credential references. Phase 5 formatter/redaction behavior remains the logging boundary and must stay green in regression validation.
