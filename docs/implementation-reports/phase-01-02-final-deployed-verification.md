# Phase 1 and Phase 2 Final Deployed Verification

Date: 2026-07-17  
Acceptance sources: `docs/archive/solutions.md` and the Phase 1, Phase 2, Phase 5, and Phase 9 implementation reports  
Strict result: **COMPLETE — 10/10 counted deployed executions passed all 13 stages**

## Scope

This was a verification-only gate for:

- Phase 1: Telegram route response boundary;
- Phase 2: worker execution boundary;
- the already-complete Phase 5 access-log boundary and Phase 9 operational-health behavior needed by the deployed gate.

No production code, schema, Compose policy, smoke assertion, or additional production-hardening phase was changed. Phase 3, Phase 4, Phase 6, and all other phases were not started.

The acceptance sources read before execution were:

- `docs/archive/solutions.md`;
- `docs/implementation-reports/phase-01-telegram-route-response-boundary.md`;
- `docs/implementation-reports/phase-02-worker-execution-boundary.md`;
- `docs/implementation-reports/phase-05-safe-access-logging.md`;
- `docs/implementation-reports/phase-09-readiness-and-operational-health.md`.

## Exact verified release state

- Git branch: `main`.
- Commit revision: `5ad72dc49bdb9189a7629bcf6b68a181d5c1ec15`.
- The built tree included the pre-existing uncommitted Phase 5 change in `backend/app/core/redaction.py`; the pre-documentation tracked diff SHA-256 was `cce47651335be3864b537869a04fc07875d7bf7d53e5056bc5216203ec912da4`.
- Backend image: `newscraft-backend:local`, image ID `sha256:c6e00d4faa629fa2cd74be60d8ec0fd13aa931f60909b2885a2fdf4492f8d09b`.
- Frontend image ID: `sha256:6eae3874ddbe32803edcf276157e89f83f342fbdd648f7ad8804ea07bd5baf6a`.
- PostgreSQL 18 image ID: `sha256:4aabea78cf39b90e834caf3af7d602a18565f6fe2508705c8d01aa63245c2e20`.
- Host: Linux `7.1.2-3-cachyos`, x86_64, glibc 2.43; timezone `Asia/Tehran`.
- Docker client/server: `29.6.1`; Docker Compose: `5.1.4`.
- Backend runtime: Python `3.14.6`, FastAPI `0.139.0`, SQLAlchemy `2.0.51`, Uvicorn `0.51.0`.
- Compose project: `phase12finalgate`.
- Provider/mode: deterministic `fake` provider and Telegram `dry-run`.
- `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, all three source-editor variables, and `TELEGRAM_DESTINATION_NEWS_TOKEN` were removed from every deployment command. No real provider or Telegram credential was used.

The machine-readable aggregate is:

`/tmp/newscraft-phase01-02-final-gate/final-verification.json`

## Deployment and execution topology

Five cohorts were used. Each cohort started with newly created PostgreSQL, media, export, and staging volumes. Its first counted execution was therefore fresh-database. The same containers and database were retained for the second counted execution. The result is exactly ten counted full executions: five fresh and five repeated-database.

The smoke driver contains one fixed, globally unique fixture source (`example_channel`). Before each repeated execution, only the prior fixture source's username/config key was rotated to `arch_<run-suffix>` in the disposable database. All jobs, events, stories, revisions, generation rows, exports, dispatches, routes, and other accumulated state were retained. This setup avoids the driver's unrelated 409 collision while preserving the repeated-database duplicate and coexistence test. No smoke assertion or accepted state was changed.

The first counted run used the documented CLI polling interval. Counted runs 2–10 used the driver's existing `main(..., poll_interval_seconds=0.01)` parameter. Faster observation avoids the already documented Phase 10 timing drift in which a valid dry-run dispatch advances from `generating` to `pending_review` before the client reads it; the accepted status set remained unchanged.

## Exact commands

Configuration and initial clean build/start:

```bash
env -u OPENAI_API_KEY -u OPENROUTER_API_KEY \
  -u TELEGRAM_SOURCE_EDITOR_API_ID -u TELEGRAM_SOURCE_EDITOR_API_HASH \
  -u TELEGRAM_SOURCE_EDITOR_SESSION -u TELEGRAM_DESTINATION_NEWS_TOKEN \
  docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml config --quiet

env -u OPENAI_API_KEY -u OPENROUTER_API_KEY \
  -u TELEGRAM_SOURCE_EDITOR_API_ID -u TELEGRAM_SOURCE_EDITOR_API_HASH \
  -u TELEGRAM_SOURCE_EDITOR_SESSION -u TELEGRAM_DESTINATION_NEWS_TOKEN \
  docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d --build --wait \
  postgres api worker-source-generation worker-publishing scheduler frontend
```

Fresh-volume reset between cohorts:

```bash
docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  down -v --remove-orphans

docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  up -d --wait \
  postgres api worker-source-generation worker-publishing scheduler frontend
```

Documented CLI smoke used for counted run 1:

```bash
python3 scripts/smoke.py \
  --base-url http://127.0.0.1:8000 \
  --provider fake --telegram-mode dry-run \
  --output-dir /tmp/newscraft-phase01-02-final-gate/cohort-01/fresh
```

Unchanged 13-stage driver with its supported faster polling parameter, used for counted runs 2–10:

```bash
python3 -c 'import runpy; ns=runpy.run_path("scripts/smoke.py",run_name="phase12_gate"); raise SystemExit(ns["main"](["--base-url","http://127.0.0.1:8000","--provider","fake","--telegram-mode","dry-run","--output-dir","<cohort-output>"],poll_interval_seconds=0.01))'
```

Repeated-database fixture-key setup, with the actual source UUID and smoke suffix from each fresh artifact:

```bash
docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  exec -T postgres psql -U newscraft -d newscraft -v ON_ERROR_STOP=1 \
  -c "UPDATE sources SET telegram_username='arch_<run-suffix>' WHERE id='<source-id>'; UPDATE telegram_source_configs SET channel_ref='arch_<run-suffix>' WHERE source_id='<source-id>';"
```

Per-run deployed audit and final aggregation:

```bash
python3 /tmp/newscraft-phase12-audit.py \
  --report <smoke-artifact> \
  --project phase12finalgate \
  --compose-file /home/armin/Documents/NewsCraft/docker-compose.yml \
  --acceptance-file /home/armin/Documents/NewsCraft/docker-compose.acceptance.yml

python3 /tmp/newscraft-phase12-aggregate.py
```

Final cleanup:

```bash
docker compose -p phase12finalgate \
  -f docker-compose.yml -f docker-compose.acceptance.yml \
  down -v --remove-orphans
```

Post-cleanup `docker ps -a`, volume, and network filters for `phase12finalgate` returned no resources. The pre-existing `newscraft-postgres-test-1` service was not changed.

## Results

| Gate | Result |
| --- | --- |
| Counted complete smoke runs | **PASS — 10/10** |
| Database modes | **PASS — 5 fresh, 5 repeated** |
| Ordered smoke stages | **PASS — 130/130** |
| Machine audit assertions | **PASS — 150/150** |
| Telegram route mutation HTTP 500 | **PASS — 0** |
| `AutomationRoute.updated_at` / `MissingGreenlet` | **PASS — 0** |
| Worker/scheduler exits or restarts | **PASS — 0; every inspected service remained running/healthy with restart count 0** |
| Runner-exception jobs / expired-lease recovery | **PASS — 0 / 0** |
| Duplicate job keys / generation input hashes / generation attempt numbers | **PASS — 0 / 0 / 0** |
| Per-run pack revision cardinality | **PASS — exactly 4 variants and 5 distinct revisions; no duplicate revision number or content hash** |
| Export cardinality | **PASS — exactly one succeeded export job/artifact identity per counted run; all manifest/download checksums passed** |
| Telegram cardinality | **PASS — exactly one album-preserving dry-run dispatch per counted run; no publish link, publish job, operation receipt, or publication** |
| Uvicorn formatter errors | **PASS — 0 `Logging error` or formatter-shape failures** |
| Diagnostics timestamp race | **PASS — 0; every component observation was at or before `generated_at`** |
| Liveness/readiness/operational health | **PASS — HTTP 200 and valid `alive`/`ready`/`healthy` projections after every run** |
| Worker and scheduler diagnostics | **PASS — source/generation worker, publishing worker, and scheduler healthy in every smoke and post-run audit** |
| Secret values/references in responses or bounded logs | **PASS — 0 canary, credential-reference, database-URL, or `secret_ref` matches** |

Each smoke also passed its built-in response, state, approval, stale-hash rejection, Telegram replay deduplication, export checksum/download, control restoration, history secret-absence, and Diagnostics invariants. A run was counted only when the smoke report had `status: succeeded`, all 13 stages were present and successful, cleanup succeeded, and all 15 sidecar assertions passed.

## Counted smoke artifacts

| Run | Mode | Smoke artifact | Audit sidecar |
| --- | --- | --- | --- |
| 1 | Fresh | `/tmp/newscraft-phase01-02-final-gate/cohort-01/fresh/smoke-20260717T193954907805Z-ed4b5a71.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-01/fresh/audit-smoke-20260717T193954907805Z-ed4b5a71.json` |
| 2 | Repeated | `/tmp/newscraft-phase01-02-final-gate/cohort-01/repeated/smoke-20260717T194517989101Z-3140215a.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-01/repeated/audit-smoke-20260717T194517989101Z-3140215a.json` |
| 3 | Fresh | `/tmp/newscraft-phase01-02-final-gate/cohort-02/fresh/smoke-20260717T195154998914Z-9744a057.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-02/fresh/audit-smoke-20260717T195154998914Z-9744a057.json` |
| 4 | Repeated | `/tmp/newscraft-phase01-02-final-gate/cohort-02/repeated/smoke-20260717T195205831818Z-33424997.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-02/repeated/audit-smoke-20260717T195205831818Z-33424997.json` |
| 5 | Fresh | `/tmp/newscraft-phase01-02-final-gate/cohort-03/fresh/smoke-20260717T195334448873Z-ca5c0b1d.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-03/fresh/audit-smoke-20260717T195334448873Z-ca5c0b1d.json` |
| 6 | Repeated | `/tmp/newscraft-phase01-02-final-gate/cohort-03/repeated/smoke-20260717T195343832986Z-f70c66a1.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-03/repeated/audit-smoke-20260717T195343832986Z-f70c66a1.json` |
| 7 | Fresh | `/tmp/newscraft-phase01-02-final-gate/cohort-04/fresh/smoke-20260717T195456348277Z-c093b5be.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-04/fresh/audit-smoke-20260717T195456348277Z-c093b5be.json` |
| 8 | Repeated | `/tmp/newscraft-phase01-02-final-gate/cohort-04/repeated/smoke-20260717T195508243636Z-5271c8a0.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-04/repeated/audit-smoke-20260717T195508243636Z-5271c8a0.json` |
| 9 | Fresh | `/tmp/newscraft-phase01-02-final-gate/cohort-05/fresh/smoke-20260717T195622190851Z-27ce397a.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-05/fresh/audit-smoke-20260717T195622190851Z-27ce397a.json` |
| 10 | Repeated | `/tmp/newscraft-phase01-02-final-gate/cohort-05/repeated/smoke-20260717T195633873741Z-a1fc185c.json` | `/tmp/newscraft-phase01-02-final-gate/cohort-05/repeated/audit-smoke-20260717T195633873741Z-a1fc185c.json` |

## Non-counting attempts

Five attempts were explicitly excluded:

| Evidence | Classification |
| --- | --- |
| `cohort-01/fresh/smoke-20260717T193736659590Z-035b8aca.json`: health `transport_failure` | Local execution sandbox blocked localhost; no deployed stage was counted. |
| `cohort-01/fresh/smoke-20260717T193747275059Z-50b2b672.json`: `telegram_dry_run_status_invalid` | Known unrelated Phase 10 transitional-status timing drift. |
| `cohort-01/repeated/smoke-20260717T194209494283Z-a2ff9640.json`: configure HTTP 409 | Fixed fixture source collided on the retained database; validation-driver limitation. |
| `cohort-01/repeated/smoke-20260717T194245996204Z-2b548cae.json`: `new_post_only_activation_head_invalid` | Discarded validation-only unique-source workaround did not match the fixed HTML fixture channel. |
| `cohort-01/repeated/smoke-20260717T194433353300Z-678320ad.json`: `telegram_dry_run_status_invalid` | Known unrelated Phase 10 transitional-status timing drift. |

No partial or failed attempt contributed to the 10/10 result. The failures did not demonstrate a Phase 1 or Phase 2 regression, so production code was not modified and the gate continued until ten fully successful executions existed.

## Final determination

Phase 1 and Phase 2 satisfy every applicable implementation and deployed acceptance criterion in the user-specified final gate. Both strict statuses are **COMPLETE**. This result does not start, implement, or claim completion of any other production-hardening phase.
