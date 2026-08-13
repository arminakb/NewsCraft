# Phase 1 Implementation Report — Telegram Route Response Boundary

Date: 2026-07-17  
Plan source: `docs/archive/solutions.md`, Phase 1  
Baseline source revision: `7826ebaf04565b0401baacac8f5234ed88764029`

## Status

**COMPLETE.** The Phase 1 production fix, code-level acceptance coverage, and final deployed repetition gate all pass. On source revision `5ad72dc49bdb9189a7629bcf6b68a181d5c1ec15`, ten counted full smoke executions (five fresh-database and five repeated-database) passed all 13 stages with zero Telegram route mutation HTTP 500, zero `AutomationRoute.updated_at`/`MissingGreenlet` failure, and zero duplicate job, revision, export, generation, or Telegram operation. The earlier Phase 9 Diagnostics race and Phase 5 formatter defect were fixed in their own completed phases; no production code was changed during this final verification.

## Sequence and scope

`progress.md` describes the already-completed content-intelligence upgrade and has no unfinished phase. The production-hardening order comes from `docs/archive/solutions.md`. The existing dirty tree already contained the Phase 2 worker execution-boundary implementation and `docs/implementation-reports/phase-02-worker-execution-boundary.md`; that report explicitly named Phase 1 as the next blocker. All existing Phase 2 changes were preserved.

Phase 1 changes only:

- `backend/app/api/telegram_automations.py`
- `backend/tests/test_telegram_route_api.py`
- `backend/tests/postgres/test_telegram_route_api.py` (new)
- this report

## Reproduction before the fix

The new PostgreSQL/ASGI regression was run before changing production code. Results:

- route creation returned 201;
- research-policy, activate, pause, and resume returned 500 after their transaction committed;
- dry-run and backfill returned 202 because they did not update the route row in that run;
- two concurrent activation requests produced one 202 and one 500.

This reproduced the audit's transaction/serialization split. PostgreSQL expired `AutomationRoute.updated_at` after an update because it is generated with `onupdate=func.now()`. FastAPI/Pydantic then synchronously read the live ORM object after `commit`, causing async lazy IO outside `greenlet_spawn` and `MissingGreenlet`.

## Implementation

### Public response materializer

`backend/app/api/telegram_automations.py` now derives the required refresh attributes from `TelegramRouteOut.model_fields`. `_materialize_route_out()`:

1. flushes all pending route/job changes;
2. explicitly refreshes every public route scalar while the async session is active;
3. immediately copies the row into `TelegramRouteOut`.

The schema-derived attribute list makes a future public scalar automatically participate in the async refresh boundary instead of relying on a manually duplicated list.

### Transaction ordering

All seven route mutation paths now construct their complete response before commit:

1. create, including the idempotent-existing path;
2. research-policy update;
3. activate;
4. pause;
5. resume;
6. dry-run;
7. backfill.

Accepted job values (`job_id`, `status`, and `deduplicated`) are also copied into `JobAcceptedOut` before commit. After commit, each endpoint returns only Pydantic values and performs no ORM access. A commit exception still propagates; a prebuilt DTO is never returned as a false success.

No schema migration, API field, idempotency key, route state transition, credential topology, or worker behavior changed.

## Tests added or changed

### Unit boundary coverage

`backend/tests/test_telegram_route_api.py` now proves:

- every `TelegramRouteOut` field is included in the explicit refresh;
- `flush` and `refresh` happen before response copying;
- mutating/invalidating the ORM object during commit cannot change the returned DTO;
- commit failure raises and cannot return a successful response;
- existing direct endpoint tests work with value DTOs rather than ORM identity.

Result: **29 passed**.

### Real PostgreSQL + FastAPI + Pydantic coverage

`backend/tests/postgres/test_telegram_route_api.py` uses the real application router, dependency-overridden production-style async sessions, PostgreSQL, `ASGITransport`, and real Pydantic response serialization. It proves:

- all seven mutations return their documented 2xx response with `updated_at`;
- state is committed and visible from a fresh session;
- activation and backfill retries return the same job and report deduplication;
- concurrent activation serializes on the locked route and returns one consistent job pair;
- only three jobs exist after repeated activation/backfill/dry-run operations;
- destination credential canaries and secret-reference fields are absent from every response.

Result: **2 passed**.

## Validation evidence

### Focused gates

```text
tests/test_telegram_route_api.py                    29 passed
tests/postgres/test_telegram_route_api.py            2 passed
ruff check (three Phase 1 files)                     passed
ruff check .                                         passed
py_compile (three Phase 1 files)                     passed
git diff --check                                     passed
```

Tests were run in `newscraft-backend:local` because the checkout's `backend/.venv` directory is empty. The isolated PostgreSQL service used `newscraft_test` on port 55432 and was stopped after validation.

### Complete backend suite

The complete backend run produced:

```text
1652 passed, 2 environment-packaging failures, 1 warning
```

The two failed test processes were rerun with their expected host tools:

- dispatch migration test: passed after initializing the disposable database through Alembic and supplying its hard-coded `.venv/bin/alembic` executable path;
- Docker Compose config test: passed after mounting the host Docker CLI/plugin into the test container.

Combined result under the required tooling: **1,654 passed; zero product-code failures**. The warning is the pre-existing Starlette/httpx deprecation warning.

### Deployed acceptance

An isolated `phase1acceptance` Compose project was built from the final tree with all provider and Telegram credential environment variables unset.

Fresh-volume run 1 passed every deterministic smoke stage:

```text
health
configure
manual_intake
collect
research
generate_four_platforms
edit_and_approve
telegram_dry_run
export
manual_plan
pause_and_resume
history
diagnostics
```

It verified route activation/configuration, bounded backfill validation, route pause/resume, dry-run duplicate prevention, healthy worker/scheduler diagnostics, and secret absence. No worker exited or required lease recovery.

Three same-database deployed route-mutation cycles then passed. Each cycle exercised idempotent create, research-policy update, activate, pause, resume, dry-run, and backfill, and asserted a complete timestamped response with no secret boundary value.

A second fresh-volume full smoke run passed every Phase 1-relevant operation and all worker flows. Its only failure was the final Diagnostics invariant:

```text
component_observation_from_future
```

The endpoint captures `generated_at` before querying component heartbeats; a heartbeat can commit between those operations and therefore be newer than the snapshot. This belongs to Phase 9. The same run also reproduced the known Phase 5 Uvicorn access-formatter exception, without changing the HTTP response. Both are out of scope here. The isolated stack and volumes were removed after the run.

### Final deployed verification gate

The deferred final gate was completed on 2026-07-17. Five isolated cohorts each ran once on newly created volumes and once more against the retained database. All ten counted executions passed all 13 stages, cleanup, and a 15-assertion post-run audit. Phase 1-specific deployed evidence was:

- every create, activate, bounded-backfill validation, dry-run replay, pause, and resume response remained successful and timestamped;
- bounded logs contained zero route-mutation HTTP 500, `MissingGreenlet`, traceback, formatter failure, or secret-reference canary;
- every route row had a materialized `updated_at`;
- every repeated operation retained its idempotency/duplicate-prevention cardinality;
- all containers remained running and healthy with restart count zero;
- all isolated deployment resources were removed afterward.

Exact commands, environment/image metadata, all ten smoke paths, all ten machine-audit paths, non-counting attempt classifications, and cleanup evidence are recorded in `docs/implementation-reports/phase-01-02-final-deployed-verification.md`. The aggregate machine-readable result is `/tmp/newscraft-phase01-02-final-gate/final-verification.json`.

## Acceptance matrix

| Criterion | Result |
| --- | --- |
| All seven mutations return documented 2xx responses on PostgreSQL | PASS |
| No post-commit route/job ORM access in mutation paths | PASS |
| Generated `updated_at` is explicitly refreshed in async context | PASS |
| Commit failure cannot escape as 2xx | PASS |
| Activation/backfill retries preserve idempotency | PASS |
| Concurrent activation returns one consistent route/job pair | PASS |
| Public response schema and secret boundary are unchanged | PASS |
| Three same-database deployed route-mutation reruns | PASS |
| User-specified final gate: ten complete deployed executions including fresh and repeated databases | **PASS — 10/10 complete; 5 fresh and 5 repeated; 130/130 stages** |

## Definition of done

- [x] Every route mutation returns a pre-materialized DTO.
- [x] No response path touches a route/job ORM instance after commit.
- [x] PostgreSQL/ASGI tests cover success, commit failure, retry, and concurrency.
- [x] API schema and secret boundary are unchanged.
- [x] Ten complete deployed smoke runs pass, including clean/fresh and retained same-database executions, with zero route 500 or post-commit ORM response failure.

## Rollback

No migration is involved. Revert the endpoint materializer/refactor and its focused tests together. Do not partially revert by returning live ORM rows from any one mutation.

## Final phase determination

Phase 1 is **COMPLETE**. The final verification did not start or implement Phase 3, Phase 4, Phase 6, or any other phase.
