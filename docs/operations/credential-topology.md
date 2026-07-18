# Credential topology and rotation

NewsCraft keeps external authority out of the public API. Database rows contain validated
credential reference names where needed, never credential values. Only the worker that owns a
capability can resolve the referenced value and report whether it is currently usable.

## Service matrix

| Service | External credential access | Storage access |
| --- | --- | --- |
| API | None | Database; read-only media and exports |
| Source/generation worker | OpenRouter, Telegram MTProto source session, source-worker proxy | Read/write media, exports, and staging |
| Publishing worker | Telegram destination bot token, publishing-worker proxy | Read-only media |
| Scheduler | None | Database only |
| Frontend | None | Backend URL only |

The base Compose file supports local development with explicitly scoped environment values.
`docker-compose.production.yml` clears those raw values, sets `APP_ENV=production`, and mounts
individual read-only files at `/run/secrets/<REFERENCE>`. It never mounts a shared secret
directory. The API has no repository-root bind mount, secret mount, proxy environment, or
worker credential environment.

## Capability observations

Each worker includes sanitized `external_capabilities` records in its durable runtime
heartbeat. A record contains only resource type/ID, capability, `available` or `unavailable`,
and an allowlisted failure code. The API projects it as:

- `available`: the owning worker observed usable authority within the TTL;
- `unavailable`: a fresh owning-worker observation reported a safe failure code;
- `unknown`: no valid owning-worker observation exists;
- `stale`: the last valid observation is older than
  `CAPABILITY_OBSERVATION_TTL_SECONDS` (120 seconds by default).

Responses include only the sanitized owner component ID, observation/expiry timestamps, and
failure code. They never include values or reference names. Route activation, dry run,
backfill, resume, content generation/research, scheduling, immediate publication, and a
`not_published` reconciliation requeue require a fresh available observation. Configuration
creation and editing remain available without external credentials.

## Preparing production files

Create all paths referenced by `docker-compose.production.yml`; empty proxy files select direct
mode. Files must be regular, non-symlink files with no group/other permission bits.

```bash
install -d -m 0700 secrets/source secrets/publishing
install -m 0400 /dev/null secrets/OPENROUTER_API_KEY
install -m 0400 /dev/null secrets/TELEGRAM_SOURCE_EDITOR_API_ID
install -m 0400 /dev/null secrets/TELEGRAM_SOURCE_EDITOR_API_HASH
install -m 0400 /dev/null secrets/TELEGRAM_SOURCE_EDITOR_SESSION
install -m 0400 /dev/null secrets/TELEGRAM_DESTINATION_NEWS_TOKEN
install -m 0400 /dev/null secrets/source/HTTP_PROXY
install -m 0400 /dev/null secrets/source/HTTPS_PROXY
install -m 0400 /dev/null secrets/source/ALL_PROXY
install -m 0400 /dev/null secrets/publishing/HTTP_PROXY
install -m 0400 /dev/null secrets/publishing/HTTPS_PROXY
install -m 0400 /dev/null secrets/publishing/ALL_PROXY
```

Populate values through the approved secret manager or deployment mechanism without printing
them to terminal output or logs. Validate only the rendered environment names and mount
targets:

```bash
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
```

## Rotation and revocation

1. Atomically replace only the owning worker's host secret file, preserving mode `0400`.
2. Recreate only that worker:
   `docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --no-deps --force-recreate worker-source-generation`
   or the equivalent `worker-publishing` command.
3. Wait for a fresh worker heartbeat and confirm the relevant capability changes to
   `available`. Do not infer success from configuration shape.
4. Revoke the old credential at its provider after the new observation succeeds.

Revocation is the same process with an empty/revoked file. Provider revocation affects
generation/research only; MTProto revocation affects source ingestion only; destination-token
revocation affects publishing only. The API, scheduler, frontend, and unrelated worker do not
need a restart. A lost worker heartbeat becomes stale and blocks new execution after the TTL.

## Canary verification

Use unique synthetic canaries for provider, source, destination, source-proxy, and
publishing-proxy categories in an isolated validation stack. Inspect counts only—never print
matching content. Required results are zero matches in API environment/filesystem, database
text/JSON, workflow jobs/results/attempt errors, events/history, diagnostics/logs, exports, and
frontend payloads. Each canary may appear only in the owning worker environment for local mode
or its owning `/run/secrets` file for production mode.
