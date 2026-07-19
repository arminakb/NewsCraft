# Phase 10 — Frontend and Backend Contract Drift

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — BROWSER EXECUTION OMITTED BY USER DIRECTION
- **Starting revision:** `308ff92` on `phase-10-contract-drift`
- **Model:** GPT-5 Codex
- **Authoritative source:** `solutions.md`, Phase 10
- **Prerequisites:** Phase 8 frozen dependency graph and Phase 7 blocking `contracts`/`browser-mocked` jobs are present.

The defect was confirmed directly. `frontend/e2e/accessibility.spec.ts` mocked obsolete `GET /diagnostics`, omitted `GET /telegram/reconciliation`, and returned 501 for the real requests. Backend/frontend wire types and route fixtures were handwritten with no canonical generated artifact or drift gate.

## Architecture decisions

- `backend/scripts/export_openapi.py` imports the FastAPI application without entering lifespan, adds a deterministic `newscraft-openapi-v1` metadata header, sorts JSON, and writes `contracts/openapi.json`.
- `openapi-typescript` 7.13.0 is exact-pinned and generates the runtime-free `frontend/lib/api/generated.ts` artifact with alphabetized output.
- TypeScript was intentionally changed from 6.0.3 to 5.9.3 because the pinned generator declares peer support for TypeScript 5.x. Clean generation and strict application typecheck pass with 5.9.3; the peer conflict was not bypassed with `--force` or `--legacy-peer-deps`.
- Operations diagnostics, history, reconciliation-list, job-accepted, and retention wire aliases now come from generated Pydantic schemas. Existing camelCase domain types and explicit mappers remain intact.
- Generated optional fields are explicitly normalized to domain `null` values instead of leaking `undefined` into UI state.
- `frontend/e2e/support/mock-backend.ts` centralizes the migrated deterministic route registry. AJV 8.20.0 plus `ajv-formats` validates operation/status response schemas, and undocumented operations/statuses fail closed.
- The stale diagnostics mock is replaced by the real `/operations/diagnostics` schema and `/telegram/reconciliation` is explicitly covered.
- Every mocked Playwright source now retains a fail-closed unmatched-request boundary; the dashboard catch-all was tightened and the editorial fallback now uses 501.
- The CI contract job regenerates OpenAPI/types, runs backend ASGI/schema and frontend mapper/runtime-schema suites, typechecks, then requires a zero artifact diff.

AJV 8.17.1 was initially selected but `npm audit` identified `GHSA-2g4f-4pwh-qvx6`; it was immediately raised to 8.20.0. The final audit returned to the two already registered moderate PostCSS paths and no high/critical finding.

No database migration was required.

## Changed files

- `backend/scripts/export_openapi.py`
- `backend/tests/test_openapi_contract.py`
- `contracts/openapi.json`, `contracts/README.md`
- `frontend/lib/api/generated.ts`
- `frontend/features/operations/api.ts`
- `frontend/e2e/support/mock-backend.ts`
- `frontend/e2e/accessibility.spec.ts`
- `frontend/e2e/dashboard.spec.ts`
- `frontend/e2e/editorial-studio.spec.ts`
- `frontend/tests/openapi-contract.test.ts`
- `frontend/tests/operations-api.test.ts`
- `frontend/package.json`, `frontend/package-lock.json`
- `.github/workflows/ci.yml`
- `backend/tests/test_ci_workflows.py`
- this report

## Validation evidence

- Deterministic OpenAPI regeneration: byte-identical SHA-256 `01d240e9a3b2fb5cc53a72db2865cee058e548acca987aff3a0dc61aa0c9bbe5`.
- Deterministic TypeScript regeneration: byte-identical SHA-256 `c94a8efbde044a8c56f377aae659822d2f9f0d560701bd943af94cbd15240a78`.
- Canonical OpenAPI size: 303,472 bytes before later report-only changes; no credential field canary matched.
- Backend deterministic/schema/ASGI checks: **3 passed**, validating actual 200 liveness and 422 request-validation responses against the committed OpenAPI schema.
- Backend contract plus CI policy checks: **6 passed**.
- Final exported-index backend contract/CI/lock regression: **14 passed**; actionlint, Ruff, format, and byte-for-byte OpenAPI regeneration also passed from the staged snapshot.
- Frontend focused generated-schema, mapper, diagnostics, reconciliation, and outcome suites: **5 files, 17 tests passed**.
- Full Vitest regression before the final two test-only policy assertions: **49 files, 378 tests passed**. The final focused Phase 10 set including those assertions passed 17/17.
- Frontend strict typecheck: passed.
- Playwright collection after the completion audit: **60 tests in 7 files**;
  every intended browser test remains discoverable.
- Backend Ruff checks and format checks passed for the exporter/contract tests.
- Final npm audit after AJV remediation: 2 moderate PostCSS paths, 0 high, 0 critical; the existing time-bounded risk-register entry remains accurate.

Representative commands:

```text
PYTHONPATH=. python scripts/export_openapi.py --output ../contracts/openapi.json
npm@11.17.0 install --package-lock-only --ignore-scripts
npm@11.17.0 ci --ignore-scripts
npm run api:generate
npm run typecheck
npm test -- --run <Phase 10 suites>
npm test
npx playwright test --list
python -m pytest -p no:cacheprovider -q tests/test_openapi_contract.py tests/test_ci_workflows.py
ruff check scripts/export_openapi.py tests/test_openapi_contract.py tests/test_ci_workflows.py
ruff format --check scripts/export_openapi.py tests/test_openapi_contract.py tests/test_ci_workflows.py
npm@11.17.0 audit --json
```

Failed/limited commands are not represented as passes:

- The first npm lock refresh failed because `openapi-typescript` 7.13.0 rejects TypeScript 6.x. The supported exact TypeScript 5.9.3 selection resolved the peer tree and passed typecheck.
- The first generated-type compile exposed four real optional-versus-null mapper assumptions. Each mapper now normalizes `undefined` to `null`; the next typecheck passed.
- AJV 8.17.1 introduced a moderate advisory. Updating to 8.20.0 removed it before finalization.
- A final combined generator/typecheck/Vitest rerun terminated in Node/V8 with `Trace/breakpoint trap` during TypeScript startup. Earlier identical generation/typecheck runs passed repeatedly; no code failure was emitted. Per the user's faulty CPU/RAM warning, it was classified as an environment limitation and not stress-retried.
- Full Chromium execution and a no-mock Compose browser run were intentionally omitted after the user identified faulty CPU/RAM and directed code-focused work. Only deterministic collection, runtime schema unit tests, mapper tests, and TypeScript checks are claimed locally.

## Acceptance criteria and Definition of Done

- [x] Canonical OpenAPI and generated wire types are committed and deterministic.
- [x] Covered operations transports use generated schemas while retaining tested wire/domain mappers.
- [x] Shared migrated mocks validate exact operation/status bodies; missing required fields and undocumented paths/statuses fail.
- [x] Every JSON response in every mocked E2E suite passes through the shared
  OpenAPI validator; concrete UUID paths resolve to their documented templates,
  undocumented statuses fail, and deliberate unmatched requests remain the
  sole 501 sentinel.
- [x] The manual-publication-plan lookup documents and validates its exercised
  404 response as well as 200/422; all 60 tests collect.
- [x] Actual ASGI 200 and 422 samples validate against OpenAPI.
- [x] CI regeneration/diff, contract tests, typecheck, and mocked browser jobs are blocking.
- [x] Public-schema tests exclude the internal credential names in scope.
- [ ] Chromium 33/33 and no-mock critical flow execution are pending healthy CI hardware by explicit user direction.

## Remaining risks, cleanup, and rollback

- Some backend endpoints still generate `unknown` success bodies because their routes lack explicit Pydantic response models. They remain documented technical debt; migrated operations/reconciliation endpoints are generated and checked. Add response models endpoint-by-endpoint before deleting their corresponding handwritten projections.
- Specialized scenario state machines retain their local state, but their JSON
  responses use the same strict registry as the shared fixture. This keeps the
  scenario coverage without creating a second contract boundary.
- The browser execution result must come from healthy CI hardware before a production release.
- Generated `.next`, temporary npm audit JSON, and package-manager logs are not committed. No live credential or external side effect was used.
- Rollback reverts the Phase 10 commit, including both generated artifacts and the compatible tool versions together.

The pre-existing untracked root `AGENTS.md` remains intentionally excluded and untouched. No Phase 11–15 behavior was implemented.
