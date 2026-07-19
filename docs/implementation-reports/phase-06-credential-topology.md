# Phase 6: Credential Topology

Date: 2026-07-18
Baseline commit: `b0cdf0efcc3ad437f8bad30ac8948f11d9e2180c` (`main`)
Scope: Phase 6 only
Final status: **COMPLETE — VERIFIED**

## Outcome

The documented topology violation was reproduced and removed. The API no longer receives provider, Telegram source, Telegram destination, or proxy credentials and no longer has a repository-root mount. Source/generation and publishing workers now receive disjoint credential classes. The scheduler and frontend receive no external capability credentials.

Production credentials are mounted as owner-specific, read-only files under `/run/secrets`; local development may retain worker-scoped environment values. External capability state is observed by the owning worker, stored only as sanitized time-bounded metadata, projected as `available`, `unavailable`, `unknown`, or `stale`, and enforced before work is activated or queued.

## Reproduction and root cause

The baseline rendered topology confirmed three violations:

1. `api.environment` contained uppercase and lowercase proxy variables, `OPENROUTER_API_KEY`, all three MTProto values, and the Telegram destination token.
2. The API mounted the repository root at `/workspace`, making the root `.env` and unrelated repository content indirectly visible.
3. The proxy overlay attached API and scheduler to the outbound proxy network; scheduler also received proxy variables and storage mounts despite owning neither capability.

Focused Compose assertions reproduced these failures before the production edit and now protect the exact allowlists and mount sets in `backend/tests/test_docker_config.py`. An ASGI test also starts the API with all external credentials absent and verifies that configuration endpoints continue to work.

The root cause was a shared Compose environment/mount pattern combined with API handlers that inferred provider and Telegram availability by inspecting local environment values or executable presence. There was no owner-authored, freshness-bounded capability projection, so API-visible `configured` booleans could drift from worker reality.

## Before and after matrix

| Service/process | Before | After |
|---|---|---|
| API | Database; media/export read-write; all proxy variants; provider key; MTProto ID/hash/session; destination token; `/workspace`; proxy network | Database; non-secret readiness/capability settings; media/export read-only. No external credential/proxy keys, no `/workspace`, no `/run/secrets`, no proxy network |
| Source/generation worker | Database; provider and MTProto credentials; broad upper/lower proxy variants; media/export/staging | Database; provider and MTProto credentials; canonical uppercase proxy values; media/export/staging. Production values are owner-only files. No destination token |
| Publishing worker | Database; destination token; broad upper/lower proxy variants; media plus unnecessary staging | Database; destination token; canonical uppercase proxy values; media read-only. Production values are owner-only files. No provider/MTProto credentials and no staging |
| Scheduler | Database; upper/lower proxy variants; media/staging; proxy network | Database and component ID only. No external credentials, proxy, storage, or proxy network |
| Frontend | Internal API base URL | Unchanged internal API base URL only; runtime inspection confirmed no external credential variables or sensitive mounts |
| Migration | No separate service; API startup runs Alembic | Unchanged. It receives only the API service topology, which now has no external capability credentials |
| Backup/restore | No Compose service existed. The documented daily bundle used a repository-root bind | No Compose service added. The documented bundle runs the source/generation worker image with an explicit output bind and no API or repository-root bind |

## Architecture decisions

### Exact service allowlists

`docker-compose.yml` now declares exact environment and volume sets per service. Lowercase proxy variants are removed to eliminate ambiguous precedence. `docker-compose.proxy.yml` attaches only the two outbound workers. API media and export mounts are read-only; publishing media is read-only; scheduler storage mounts are removed.

`docker-compose.production.yml` is an explicit production overlay. It clears raw worker credential/proxy environment values and mounts only the owning worker's files. The source/generation worker receives provider, MTProto, and source-proxy files. The publishing worker receives destination-token and publishing-proxy files. No global secret directory is shared.

### Worker-scoped resolution

`FileSecretResolver` validates reference syntax, uses `O_NOFOLLOW`, requires a regular file with no group/other permission bits, caps reads at 64 KiB, rejects invalid UTF-8 and empty values, and opens the file on every resolution. `WorkerSecretResolver` is file-only in production and permits environment fallback only in development, local, and test environments.

Proxy resolution follows the same file boundary for `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`. Simultaneous non-empty environment and file values fail closed as a configuration conflict. `NO_PROXY` remains non-secret routing configuration.

### API without secret authority

API handlers validate reference and provider configuration shape but never resolve credential values. Creating or editing a provider, source, destination, or automation remains possible while a worker is unavailable. Activation, resume, dry-run, backfill, generation/research queueing, immediate/scheduled publication, reconciliation requeue, and scheduler polling require a current healthy observation from the owning capability.

The frontend displays explicit text labels for all four states, including awaiting observation and stale observation. Availability is not communicated by color alone, and provider configuration remains editable while a worker is unavailable.

### Worker-observed capability state

Workers append sanitized `external_capabilities` observations to existing heartbeat metadata. An observation contains only resource type/ID, capability, safe state, sanitized failure code, owner, and observation time. It contains no credential value or raw secret reference.

`CapabilityStatusService` projects:

- `available`: a fresh positive owner observation;
- `unavailable`: a fresh negative owner observation;
- `unknown`: no matching owner observation exists;
- `stale`: the most recent matching observation is at or past its TTL.

The configured TTL is 120 seconds by default. A stale observation is never represented as configured. Missing/stale execution gates use a safe unknown error; fresh negative observations use a safe unavailable error.

## Files changed

Deployment and operator guidance:

- `.env.example`
- `.gitignore`
- `README.md`
- `docker-compose.yml`
- `docker-compose.proxy.yml`
- `docker-compose.production.yml` (new)
- `docs/operations/credential-topology.md` (new)
- `docs/operations/outbound-proxy-policy.md`
- `docs/operations/research-and-generation.md`
- `docs/implementation-reports/phase-06-credential-topology.md` (this report)

Backend:

- `backend/app/api/capabilities.py` (new)
- `backend/app/api/content_packs.py`
- `backend/app/api/generation_schemas.py`
- `backend/app/api/generation_settings.py`
- `backend/app/api/telegram_automations.py`
- `backend/app/api/telegram_destinations.py`
- `backend/app/api/telegram_drafts.py`
- `backend/app/api/telegram_schemas.py`
- `backend/app/api/telegram_sources.py`
- `backend/app/core/config.py`
- `backend/app/core/outbound_proxy.py`
- `backend/app/core/secrets.py`
- `backend/app/generation/default_prompts.py`
- `backend/app/generation/editorial_service.py`
- `backend/app/jobs/credential_capabilities.py` (new)
- `backend/app/jobs/scheduler.py`
- `backend/app/jobs/worker.py`
- `backend/app/research/service.py`

Backend tests:

- `backend/tests/capability_fakes.py` (new)
- `backend/tests/test_credential_capabilities.py` (new)
- `backend/tests/test_secret_resolver.py`
- `backend/tests/test_docker_config.py`
- `backend/tests/test_generation_settings_api.py`
- `backend/tests/test_job_worker.py`
- `backend/tests/test_scheduler.py`
- `backend/tests/test_telegram_configuration_api.py`
- `backend/tests/test_telegram_draft_api.py`
- `backend/tests/test_telegram_reconciliation_api.py`
- `backend/tests/test_telegram_route_api.py`
- `backend/tests/generation/test_multiplatform.py`
- `backend/tests/integration/conftest.py`
- `backend/tests/postgres/test_telegram_process_handler.py`
- `backend/tests/postgres/test_telegram_publish_service.py`
- `backend/tests/postgres/test_telegram_route_api.py`

Frontend:

- `frontend/features/automations/route-builder.tsx`
- `frontend/features/automations/telegram-api.ts`
- `frontend/features/automations/telegram-types.ts`
- `frontend/features/settings/content-settings-page.tsx`
- `frontend/tests/content-settings-page.test.tsx`
- `frontend/tests/telegram-api.test.ts`
- `frontend/tests/telegram-route-builder.test.tsx`
- `frontend/tests/telegram-route-detail.test.tsx`

Pre-existing user changes in `backend/app/core/redaction.py`, the Phase 1/2 reports, task/audit documents, and validation artifacts were preserved and are not claimed as Phase 6 edits.

## Migrations and compatibility

No database or Alembic migration was required. Observations reuse the existing runtime-heartbeat metadata JSON. Existing `configured` response fields remain for compatibility but are derived only from current worker-observed state. The new structured state is additive.

Local development remains compatible with worker-scoped environment values. Production operators must prepare mode-0400 source files and add `docker-compose.production.yml`. The local Compose implementation warns that secret `mode` is not enforced by Compose for bind-backed files; the resolver therefore independently enforces host/mounted permissions and fails closed.

## Tests added or extended

- Exact rendered environment, secret, mount, proxy-network, and production-overlay assertions for every service.
- API startup/configuration behavior with all external credentials absent.
- Secure file permissions, symlink rejection, maximum size, production environment rejection, scoped roots, rotation, and category-isolation tests.
- Provider/source/destination observation tests covering available, unavailable, invalid, missing, stale, unknown, TTL boundary, owner mismatch, and heartbeat loss.
- Activation/resume/scheduling/generation/research/publication gates for fresh, unavailable, unknown, and stale states.
- Heartbeat and worker tests proving safe metadata and owner-scoped resolver injection.
- Frontend mapping and component tests for all four states, explicit text, editable unavailable configuration, and non-activating route creation.
- Regression updates for direct endpoint and integration harnesses to supply explicit fake worker capability state.

## Commands and exact results

The significant validation commands were:

```text
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.proxy.yml config --quiet

docker run --rm --network host \
  -v /home/armin/Documents/NewsCraft:/repo \
  -v /tmp/newscraft-alembic:/repo/backend/.venv/bin/alembic:ro \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins:/usr/lib/docker/cli-plugins:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -w /repo/backend \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  -e ENRICHMENT_PROVIDER=none -e LLM_PROVIDER=none \
  newscraft-backend:local python -m pytest -p no:cacheprovider -q

docker run --rm -v /home/armin/Documents/NewsCraft:/repo \
  -w /repo/backend newscraft-backend:local ruff check .
docker run --rm -v /home/armin/Documents/NewsCraft:/repo \
  -w /repo/backend newscraft-backend:local python -m compileall -q app tests

npm run typecheck
npx vitest run --maxWorkers=1
npm run build
docker compose build api
docker compose build frontend
```

Results:

- Base, production, and proxy Compose renders: PASS.
- Full backend: **1,757 passed**, one upstream Starlette/httpx deprecation warning, 0 failed, in 546.01 seconds.
- Focused corrected acceptance/PostgreSQL subset: **59 passed**.
- Isolated dispatch-sequence migration regression: **1 passed**.
- Ruff: all checks passed.
- Python compile: passed.
- Frontend typecheck: passed.
- Frontend tests: **47 files, 370 tests passed** with one worker. The default concurrent run hit the pre-existing story-inbox 10-second timeout; that file passed alone (13/13), and the serialized full run passed.
- Frontend production build: passed; 17 static/dynamic route entries generated.
- Backend and frontend container builds: passed.
- `git diff --check`: passed.

The host repository contained an empty, non-executable `backend/.venv/bin/alembic`; the full suite used a temporary mounted Alembic shim so the migration regression executed instead of failing on the runner fixture. The shim was removed after validation.

## Deployed topology evidence

An isolated `newscraft-phase6` Compose project was built from the final source and started without publishing host ports. PostgreSQL, API, source/generation worker, publishing worker, scheduler, and frontend all reached healthy state.

Runtime name/mount inspection showed:

- API external credential/proxy names: `[]`.
- API mounts: `/data/media` and `/data/exports`, both `ro`; `/workspace` absent; `/run/secrets` absent.
- Source/generation expected names: provider key, three MTProto values, uppercase proxy values, and `NO_PROXY`; unexpected sensitive names: `[]`; data mounts limited to media/export/staging.
- Publishing expected names: destination token, uppercase proxy values, and `NO_PROXY`; unexpected sensitive names: `[]`; only media mounted.
- Scheduler external names: `[]`; data mounts: `[]`.
- Frontend external names: `[]`; data/secret/workspace mounts: `[]`.

In production-overlay verification, all raw sensitive environment values were empty. Source/generation mounted exactly seven owner files and publishing exactly four owner files. Every file was observed as mode `0400`. Credential files resolved only in the owning worker; intentionally empty proxy files resolved as unconfigured/direct.

Configuration endpoints remained available with no API credential values. Public provider and automation projections returned only safe `available`/`unavailable` states; unit and contract tests directly cover `unknown` and `stale` projections.

## Canary and leak sweep

No real credential was used. Eight distinct synthetic values covered the provider key, MTProto ID/hash/session, destination token, and three authenticated proxy variables. Values were generated in-process and never printed.

Count-only deployed sweeps reported:

- API environment hits: 0.
- Scheduler environment hits: 0.
- Logs for API, both workers, and scheduler: 0.
- API configuration response hits: 0.
- Database text/JSON hits across all public tables (including jobs, events/history, attempts, and heartbeat metadata): 0.
- Media, export, and staging file hits: 0.
- Safe marker/reference hits in API settings/options responses: 0.
- Source-worker canaries across seven liveness/readiness/diagnostics/metrics/history routes: 0.
- Publishing-worker canaries across the same seven routes: 0.

The frontend container had no canary-bearing environment or mounts and consumes the already-swept API boundary. No backup service or backup artifact exists in this topology, so backup-content scanning was not applicable. Temporary test artifacts and secret fixtures were securely removed.

## Rotation, revocation, and isolation evidence

The production resolver reopens files on every access. A controlled deployed comparison changed the provider file in place; the owning resolver reported `resolver_rotation_detected True` without an API restart or secret exposure.

An isolated OpenRouter profile was enabled after the worker observed the mounted provider file:

1. Public generation state reached `available`.
2. The owner file was emptied; the source/generation resolver reported it unconfigured.
3. On the next worker heartbeat, the public generation state became `unavailable`.
4. Publishing worker, scheduler, and API remained healthy.
5. Restoring the owner file returned public generation state to `available`, again without restarting the API.

Unit tests repeat missing/revoked/rotated isolation for provider, MTProto source, destination token, source proxy, and publishing proxy classes, including cross-owner resolution failures.

## Acceptance checklist

- [x] API environment contains zero provider, Telegram source, Telegram destination, or authenticated-proxy values.
- [x] API cannot access repository-root `.env`, worker secret files, or a broad repository mount.
- [x] Source/generation and publishing workers receive only documented owner credentials.
- [x] Scheduler and frontend receive no external capability credentials.
- [x] API availability decisions no longer inspect its environment or local executable state.
- [x] Capability state is worker-observed, time-bounded, sanitized, and explicitly represents available/unavailable/unknown/stale.
- [x] Configuration endpoints remain usable without giving API execution authority.
- [x] Current owner capability state gates activation, scheduling, generation/research, and publication paths.
- [x] Deployed canary sweeps found zero durable/output/log/diagnostic leaks.
- [x] Provider revocation affected generation state only; unrelated services stayed healthy.
- [x] Rotation/revocation/recovery required no API restart and no API secret access.
- [x] Phase 1, 2, 4, 5, and 9 regressions are green in the 1,757-test backend suite.
- [x] Base, production, and proxy Compose configurations render successfully.
- [x] All isolated containers, networks, volumes, database containers, secret files, and validation shims were removed.

## Remaining risks and unverified external behavior

- Real OpenRouter, Telegram, and authenticated-proxy authentication was intentionally not exercised. The observer proves presence, ownership, reference shape, and MTProto API-ID shape; upstream rejection is still handled by the owning execution path.
- No live Telegram publication was performed, as required.
- The platform's bind-backed Compose secrets do not enforce the declared `mode`; operator-side `0400` preparation remains mandatory. Runtime enforcement fails closed if permissions broaden.
- Capability state is intentionally eventually consistent up to the worker heartbeat/TTL window. Execution gates reject unknown, stale, or unavailable observations.
- There is no backup/restore service in the current Compose topology to deploy or scan. If one is introduced later, it needs its own credential/mount matrix and canary validation.

These items do not leave a Phase 6 acceptance criterion unverified; they are external-integration or absent-component limitations.

## Cleanup and scope confirmation

Both isolated deployment passes were removed with their networks and named volumes. The temporary PostgreSQL test container, secret fixtures, Compose override, and Alembic shim were also removed; a final resource query returned no Phase 6 containers or volumes.

No Phase 3, Phase 7, Phase 10, or unrelated refactor was implemented. No commit was created.
