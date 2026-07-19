Read `solutions.md` completely as the authoritative production-hardening plan.

Implement **Phase 10 only: Frontend/Backend Contract Drift and Stale Deterministic Fixtures**.

Use **GPT-5.6 Sol xhigh** for this phase.

Work in a clean branch or worktree created from the committed Phase 8 revision.

The following phases are already implemented and must remain intact:

* Phase 1: Telegram route response boundary
* Phase 2: Worker execution boundary
* Phase 3: Restart supervision
* Phase 4: Outbound proxy policy
* Phase 5: Safe access logging
* Phase 6: Credential topology
* Phase 8: Dependency locking and reproducible builds
* Phase 9: Readiness and operational health

Do not implement Phase 7 CI, Phase 11 performance work, or any other phase.

## Objective

Eliminate contract drift between:

* FastAPI/Pydantic backend schemas
* generated or handwritten frontend TypeScript types
* frontend API mappers
* deterministic backend fixtures
* Vitest mocks
* Playwright route mocks
* real deployed API behavior

The backend contract must become the authoritative source of truth.

The current known symptom is that Playwright passes only 21/33 tests because deterministic browser fixtures and route mocks no longer match the actual backend contract.

Do not assume the audit is fully current. Inspect the current repository and reproduce the failures before changing production code.

## Required workflow

### 1. Inspect and reproduce

Before modifying production code:

1. Run the current:

   * backend contract/schema tests
   * frontend TypeScript typecheck
   * full Vitest suite
   * Playwright mocked suite
   * available live-stack Playwright smoke tests
2. Capture the exact failing Playwright tests and distinguish:

   * contract-shape mismatch
   * missing endpoint mock
   * stale enum or status value
   * nullability mismatch
   * date/time serialization mismatch
   * pagination mismatch
   * renamed field
   * changed capability-state behavior
   * frontend implementation bug
   * unrelated performance timeout
3. Inspect:

   * FastAPI OpenAPI generation
   * Pydantic response/request schemas
   * handwritten frontend wire types
   * frontend domain types
   * frontend mappers
   * test factories
   * deterministic backend fixtures
   * Playwright route interception
   * MSW or other mock systems if present
   * duplicated endpoint fixtures
4. Produce a contract inventory containing:

   * endpoint
   * request schema
   * response schema
   * backend source
   * frontend consumer
   * current mock source
   * observed drift
5. Reproduce at least one failure that passes TypeScript but fails at runtime because the mock contract is stale.

Do not fix failures before documenting their confirmed cause.

### 2. Write a concise implementation plan

Before changing production code, provide a concise plan covering:

* authoritative contract source
* OpenAPI normalization
* frontend type-generation strategy
* generated versus handwritten type boundaries
* frontend mapping layer
* deterministic fixture strategy
* Playwright mock consolidation
* drift-detection tests
* migration approach
* rollback risks

Do not begin unrelated frontend refactoring.

## Architecture requirements

### A. Backend OpenAPI is authoritative

Use the backend-generated OpenAPI schema as the canonical wire-contract source.

Requirements:

* generation must be deterministic,
* operation IDs must be stable,
* schema ordering must be stable where possible,
* environment-specific values must not enter the artifact,
* credential values and secret references must never appear,
* generated schema must represent the actual deployed FastAPI routes,
* schema generation must not require live external credentials,
* generation must work from a clean checkout.

If the current OpenAPI contains unstable or duplicate operation IDs, fix only the necessary API metadata.

Do not redesign unrelated endpoints.

### B. Commit a canonical OpenAPI artifact

Generate and commit a canonical repository artifact, for example:

`api/openapi.json`

or another clearly justified location.

The artifact must:

* be generated through a documented command,
* use deterministic formatting,
* contain no local absolute paths,
* contain no timestamps unless intentionally normalized,
* contain no secret values,
* be reproducible from the same source revision.

Running the generation command twice must produce no diff.

### C. Generate frontend wire types

Generate frontend wire types from the canonical OpenAPI artifact using one reviewed generator compatible with the locked Phase 8 toolchain.

Requirements:

* generated files must be clearly marked,
* generated files must not be manually edited,
* the generator command and exact version must be documented,
* generated output must be deterministic,
* generated wire types must represent requests, responses, enums, nullable fields, and pagination accurately,
* frontend code must not depend directly on arbitrary OpenAPI internals when a stable adapter boundary is more appropriate.

Do not introduce multiple competing generators.

### D. Separate wire types from domain/view types

Generated types should represent the API wire format.

Handwritten types may remain for UI/domain behavior, but conversion must happen in explicit mappers.

Requirements:

* every mapper has typed input and output,
* no unchecked `as unknown as ...` contract bypasses,
* no broad `any` at API boundaries,
* nullable and optional fields are handled explicitly,
* unknown enum values fail safely or map to an explicit fallback,
* date/time parsing remains timezone-safe,
* capability states introduced in Phase 6 remain accessible and truthful.

Do not force UI components to consume raw generated schemas when a domain model is clearer.

### E. Consolidate deterministic fixtures

Create one canonical deterministic fixture/factory system based on generated wire types.

Use it for:

* Vitest API mocks
* Playwright route mocks
* deterministic backend fixture responses where applicable
* frontend component test setup
* contract examples

Requirements:

* fixture objects must typecheck against generated wire types,
* missing required fields must fail tests,
* extra invalid fields should be detected where runtime validation is used,
* fixtures must use realistic states from the current backend,
* credentials and raw secret references must never appear,
* timestamps must be deterministic,
* identifiers must be stable,
* pagination metadata must be internally consistent.

Do not maintain separate copied JSON responses across many Playwright files.

### F. Consolidate Playwright route mocks

Move mocked route behavior into a centralized typed layer.

Requirements:

* every intercepted endpoint is registered explicitly,
* unhandled API requests fail the test immediately,
* HTTP method and path must both match,
* query parameters must be validated where relevant,
* request bodies must be checked against current schemas where practical,
* responses must come from typed canonical factories,
* tests may override specific fixture fields without copying the full response,
* error responses must also follow the current backend error contract,
* duplicate route definitions must be removed.

Do not silently return generic 200 responses for unknown routes.

### G. Runtime contract validation

Add development/test runtime validation at important API boundaries where useful.

Suitable approaches may include generated runtime schemas or a small explicit validation layer.

At minimum, ensure that:

* deterministic mocks are validated,
* critical API responses used by the frontend can be validated during tests,
* contract failures produce safe and understandable errors,
* production performance is not significantly degraded.

Do not add a large runtime dependency without justification.

### H. Contract drift commands

Add repository commands such as:

* generate OpenAPI
* generate frontend types
* generate or validate fixtures
* check contract drift

A contract check must:

1. regenerate artifacts,
2. compare with committed output,
3. fail when differences remain,
4. leave the working tree unchanged when contracts are current.

Phase 7 will later make these commands mandatory in CI, but do not implement the CI workflow now.

## Current failure handling

Investigate all current Playwright failures individually.

For every failure, classify it as:

* fixed by contract synchronization,
* actual frontend bug fixed within Phase 10,
* backend contract bug fixed within Phase 10,
* unrelated Phase 11 performance issue,
* environment limitation,
* intentionally obsolete test removed with justification.

Do not delete or skip failing tests merely to reach green status.

Do not increase timeouts to hide stale fixtures or incorrect behavior.

If the single Vitest timeout is caused by an actual performance issue, leave it documented for Phase 11. If it is caused by stale contract setup or unnecessary mock retries, fix it in Phase 10.

## Required tests

Add or update tests for:

### OpenAPI determinism

* generation succeeds without external credentials,
* two generations are byte-identical,
* committed artifact matches current backend,
* operation IDs are unique,
* no local paths, timestamps, credential values, or secret references appear.

### Generated frontend types

* generation is deterministic,
* generated files contain the expected critical models,
* nullability and required fields match backend schemas,
* enums match backend values,
* generated output contains no `any` where the generator can provide a concrete type,
* manually editing generated output is detected by regeneration.

### Mappers

Cover at least:

* Telegram route models
* capability state
* source configuration
* destination configuration
* content/generation settings
* drafts and reconciliation
* pagination
* nullable fields
* unknown enum values
* timestamp parsing
* backend validation-error mapping

### Fixtures

* all canonical fixtures satisfy generated wire types,
* intentionally removing a required field fails validation,
* invalid enum values fail or map through an explicit tested fallback,
* no secret value or reference appears,
* timestamps and IDs are deterministic.

### Playwright routing

* all expected routes are registered,
* unknown route fails immediately,
* wrong method fails,
* malformed request body fails,
* query mismatch fails where relevant,
* successful and error responses follow current schemas,
* route overrides remain typed.

### Regression

Run the completed-phase regressions for:

* Phase 1 API response serialization
* Phase 2 worker execution
* Phase 3 restart/health contracts
* Phase 4 proxy diagnostics
* Phase 5 redaction
* Phase 6 capability projections
* Phase 8 locked builds
* Phase 9 operational diagnostics

## Validation requirements

Run the Phase 10 commands from `solutions.md`, plus:

### Backend

* canonical OpenAPI generation
* OpenAPI regeneration with zero diff
* backend schema/API tests
* full backend suite
* Ruff lint
* targeted Ruff formatting
* Python compilation
* `git diff --check`

### Frontend

* frozen `npm ci`
* frontend type generation
* second generation with zero diff
* full TypeScript typecheck
* full Vitest suite
* full mocked Playwright suite
* production build
* contract-check command
* working-tree drift check

### Deployed/live-stack validation

Using an isolated stack:

1. Start the current production-style backend and frontend.
2. Run the browser smoke suite without route mocks where supported.
3. Verify critical screens against actual API responses:

   * automation list/detail
   * route builder
   * Telegram sources
   * Telegram destinations
   * generation settings
   * capability state
   * diagnostics
4. Confirm frontend behavior matches mocked-suite behavior.
5. Verify no secret values or references enter browser responses, generated schemas, fixtures, screenshots, traces, or logs.
6. Clean up all isolated deployment resources.

## Acceptance criteria

Do not mark Phase 10 complete unless directly verified:

* Backend OpenAPI is the authoritative wire-contract source.
* A deterministic canonical OpenAPI artifact is committed.
* Frontend wire types are deterministically generated from it.
* Handwritten frontend API wire types are removed or reduced to justified adapter/domain types.
* API mappers are explicit and tested.
* Deterministic fixtures are centralized and typed.
* Playwright route mocks are centralized and reject unhandled requests.
* OpenAPI and generated-type regeneration produce zero diff.
* Full frontend typecheck passes.
* Full Vitest suite passes, excluding only a proven unrelated Phase 11 issue if clearly documented.
* Full mocked Playwright suite passes.
* Live-stack browser smoke passes for supported critical screens.
* No contracts, fixtures, traces, or logs contain credential values or raw secret references.
* Completed Phase 1, 2, 3, 4, 5, 6, 8, and 9 behavior remains green.
* No Phase 7 CI or unrelated phase is implemented.
* Temporary resources are cleaned up.

If any failure remains, document the exact owning phase and evidence. Do not claim strict completion when a Phase 10-owned contract or mocked-browser failure remains.

## Final report

Create:

`docs/implementation-reports/phase-10-contract-drift.md`

Include:

* reproduced failures
* root-cause classification for every original Playwright failure
* before-and-after contract architecture
* canonical OpenAPI location
* type generator and exact version
* generated files
* mapper strategy
* fixture architecture
* Playwright mock architecture
* changed files
* tests added
* exact commands executed
* exact test counts
* mocked and live-browser results
* deterministic-generation evidence
* secret-leak sweep
* acceptance-criteria checklist
* remaining risks
* unverified items
* confirmation that no other phase was implemented
* strict final status

Do not create a commit unless explicitly instructed.

Stop after Phase 10 implementation, validation, and reporting.
