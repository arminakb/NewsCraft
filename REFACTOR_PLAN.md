# NewsCraft Maintainability, Correctness, and UX Refactor Plan

**Status:** Current execution plan

**Date:** 2026-07-26

**Product target:** Local, single-operator newsroom pipeline

**Execution style:** Delete first, preserve behavior, refactor in workflow-sized slices

## 1. Authority and scope

This is the current entrypoint for code-quality, correctness, and UX refactoring.

- The approved product behavior in
  `docs/superpowers/specs/2026-07-11-newscraft-content-platform-rescue-design.md`
  remains authoritative.
- Superseded rescue, frontend, Content Settings, and cleanup plans have been
  removed. Their history remains recoverable from Git.
- Completed implementation reports and frontend audit findings remain evidence,
  not competing execution plans.

This plan covers:

- removing dead, duplicated, legacy, and accidental code;
- finding and fixing bugs, logic errors, invalid state transitions, and bad data
  handling;
- reducing the size and complexity of the backend and frontend;
- making daily newsroom work obvious, consistent, responsive, and friendly;
- making tests and static analysis reliable enough to prevent regressions;
- tidying current documentation after behavior and code converge.

This plan does **not** add multi-user SaaS behavior, new publishing platforms,
microservices, a new framework, or a security-hardening programme. Existing
credential, approval, revision, and publishing safeguards must not regress.

## 2. Product behavior that must survive

The primary operator journey is:

```text
Collect or add material
  -> normalize and deduplicate
  -> group evidence into a story
  -> shortlist, reject, or research
  -> generate a content package
  -> inspect and edit an immutable revision
  -> approve the exact revision
  -> publish to Telegram or export a manual package
  -> inspect the durable outcome and recover failures
```

The refactor must preserve these invariants:

1. PostgreSQL remains the source of truth and durable queue.
2. Raw source material and evidence are never silently replaced.
3. Editing an approved revision creates a new pending revision.
4. Approval is bound to an exact revision and content hash.
5. Publishing is idempotent and references only an approved revision.
6. Worker lease expiry and retry cannot produce duplicate publication.
7. Telegram activation and bounded backfill cannot lose new messages.
8. Review remains the default; automatic publication stays explicit.
9. Empty, loading, failure, and unavailable states remain truthful.
10. Technical recovery detail stays available even when it moves out of the
    primary interface.

## 3. Current evidence baseline

The first implementation task must reproduce and commit a small metrics script
so later phases compare against the same definition.

| Measure | Current baseline |
| --- | ---: |
| Backend application | 51,060 lines across 218 Python files |
| Handwritten frontend | 16,858 lines across 115 TS/TSX files |
| Generated OpenAPI types | 11,232 lines, excluded from reduction targets |
| Backend tests | 60,550 lines |
| Frontend unit and E2E tests | 14,139 lines |
| Backend files at least 500 lines | 28 |
| Backend files at least 1,000 lines | 7 |
| Frontend handwritten files at least 300 lines | 20 |
| Frontend handwritten files at least 500 lines | 4 |
| Ruff complex-function findings (`C901`) | 83 |
| Ruff excessive-statement findings | 39 |
| Full-backend mypy baseline | 322 errors in 58 files |
| Strict TS unused-code baseline | 2 production and 3 test findings |

The normal Ruff configuration currently checks style and common correctness
rules but not complexity. Mypy currently covers only a small selected subset of
the application, which hides the full-backend error count.

Largest maintainability hotspots:

| Hotspot | Lines | Main problem |
| --- | ---: | --- |
| `backend/app/automations/telegram/handlers.py` | 2,707 | Nested handler builders combine state decisions, persistence, media, jobs, and transport |
| `backend/app/generation/handlers.py` | 2,065 | Provider invocation, validation, persistence, retry, and result mapping are interleaved |
| `backend/app/retention/service.py` | 1,830 | Candidate planning, database deletion, filesystem deletion, and recovery are coupled |
| `backend/app/publishing/telegram/service.py` | 1,774 | Scheduling, validation, claim fencing, rendering, sending, receipts, and reconciliation are coupled |
| `backend/app/api/telegram_drafts.py` | 1,229 | HTTP schemas and route code contain workflow/state logic |
| `backend/app/api/articles.py` | 1,091 | Filtering, pagination, collections, facets, and response mapping share one module |
| `frontend/features/settings/content-settings-page.tsx` | 1,548 | Several unrelated management tools and dialogs live in one component |
| `frontend/features/packages/api.ts` | 1,026 | Request code, duplicated types, runtime decoding, validation, and encoding are mixed |

Known correctness and quality signals to investigate early:

- content readiness can pass on a 40-character length threshold;
- article search is title-only and facet calculation scans all matching item
  identifiers;
- state and transition checks are repeated across API routes, handlers, and
  services;
- the full mypy run exposes nullable values, weakly typed SQL results, invalid
  literal widening, parser shape uncertainty, and response-shape mismatches;
- PostgreSQL integration tests are skipped when `TEST_DATABASE_URL` is absent;
- one frontend export-action test is flaky under the full concurrent suite;
- the nightly workflow references frontend test files that no longer exist;
- handwritten frontend API types and decoders overlap with the generated
  OpenAPI contract;
- `DraftService` and the minimal legacy SQLite reader remain isolated,
  test-backed legacy paths with no current application workflow.

## 4. Definition of success

### Correctness

- The complete core journey passes against a real PostgreSQL database.
- State-transition tables cover stories, research, generation, revisions, jobs,
  automation routes, and publications.
- Invalid transitions return one consistent domain error and do not partially
  write data.
- Crash, retry, timeout, stale revision, duplicate request, and ambiguous
  Telegram outcome tests pass.
- There are no unresolved critical or high-impact bugs in the core journey.
- The full backend passes mypy. Third-party boundary exceptions must be narrow
  and documented.
- Touched core modules have no Ruff complexity violations.

### Maintainability and size

- Reduce handwritten production code by **10-15%** from the baseline
  (approximately 7,000-10,000 lines) without removing approved workflow
  behavior. A 20% reduction is a stretch target.
- Generated files, tests, migrations, and documentation do not count toward the
  reduction target.
- No application module remains above 1,000 handwritten lines.
- Core workflow functions are normally below 80 lines and have one reason to
  change.
- API routes parse input, call one application operation, and map its result;
  they do not own business transitions.
- Frontend features use one request boundary and one source of API types.
- New abstractions are allowed only when they replace repeated production code
  in at least two real call sites.

LOC is a guardrail, not a reason to compress readable code. Tests may grow where
they expose previously untested behavior.

### User experience

- The primary navigation exposes Today, Inbox, Drafts, Calendar, and Library;
  operational tools are grouped under Advanced.
- Today tells the operator what needs attention and offers the next useful
  editorial action.
- Inbox defaults to actionable stories rather than a long equal-weight stream.
- Draft and exact-review concepts no longer compete as separate workflows.
- Healthy technical metadata, UUIDs, hashes, and provider internals are hidden
  under clearly labelled advanced details.
- Every screen has consistent loading, empty, error, retry, and success
  feedback.
- The full primary journey works at desktop and 390px widths, in Persian RTL
  and mixed-language content, by keyboard and screen reader.

## 5. Execution rules

1. Do not perform a big-bang rewrite.
2. Work on one operator-visible workflow slice at a time.
3. Before changing a risky function, add a characterization or failing
   regression test that proves current intended behavior.
4. Delete obsolete paths before extracting or introducing replacements.
5. Keep migrations and compatibility shims only while a real caller needs
   them. Give every temporary shim a removal task.
6. Do not add generic base services, repository frameworks, event buses, or
   dependency containers.
7. Use a small dataclass or typed command only when it replaces a repeated
   argument cluster or clarifies a state boundary.
8. Separate pure decisions from database and network effects. Test the pure
   decision directly and the effectful boundary with PostgreSQL or a fake
   transport.
9. A code move is not a completed refactor. Every slice must remove duplication,
   reduce branching, fix a demonstrated defect, or improve the operator flow.
10. Each commit contains one behavioral boundary. Large deletions and generated
    contract updates get separate commits.
11. Record production LOC, largest files, complexity findings, and test results
    before and after every phase.
12. Stop and repair the phase if production LOC increases without a documented
    correctness or UX reason.

## 6. Bug classification during the refactor

Use these priorities when new defects are discovered:

| Priority | Examples | Rule |
| --- | --- | --- |
| P0 | Data loss, publishing the wrong revision, duplicate publication, corrupt migration | Fix before continuing the current phase |
| P1 | Lost source items, invalid state transition, stuck jobs, wrong content grouping, incorrect filters | Fix inside the current workflow slice |
| P2 | Broken UI action, misleading status, flaky test, unusable mobile interaction | Fix before the slice is accepted |
| P3 | Cosmetic inconsistency or low-impact cleanup | Batch only when touching the same surface |

Every bug fix must include a regression test at the lowest useful boundary.

## 7. Phased work plan

### Phase 0 — Make the validation signal trustworthy

**Objective:** Know whether a later deletion or refactor changed behavior.

#### R0.1 Add one reproducible quality-baseline command

- Count handwritten production lines while excluding generated files.
- Report files above the size thresholds.
- Run normal Ruff plus complexity reporting.
- Run strict frontend unused-code reporting.
- Run full-backend mypy as an informational baseline.
- Do not make all legacy findings blocking on day one.

#### R0.2 Repair current test infrastructure defects

- Remove or replace references to deleted tests in the nightly workflow.
- Reproduce and fix the concurrent `copy-export-actions` flake.
- Make the PostgreSQL test command start its required test database rather than
  silently reporting a mostly skipped suite.
- Run the existing Playwright suite with the supported local browser settings.

#### R0.3 Pin the five acceptance journeys

Add or consolidate end-to-end acceptance coverage for:

1. RSS/manual collection -> deduplication -> story grouping.
2. Story -> research -> evidence-bound canonical revision.
3. Canonical revision -> multi-platform package -> immutable edit -> approval.
4. Approved Telegram revision -> schedule/publish -> durable receipt.
5. Worker crash/timeout -> lease recovery/retry -> no duplicate publication.

#### R0.4 Capture a representative performance dataset

- Seed enough content, stories, jobs, revisions, and publications to expose slow
  list/facet behavior.
- Record query counts and timings for Today, Inbox, Feed/Raw Content, Drafts,
  Jobs, and Library.
- Treat the known multi-second facet scan as a defect, not a permanent budget.

**Exit gate:** Normal unit tests, PostgreSQL suites, contract checks, build, and
targeted browser tests are green and reproducible. Baseline metrics are recorded.

---

### Phase 1 — Delete before refactoring

**Objective:** Remove code that should not be reorganized at all.

#### R1.1 Prove and delete dead backend paths

- Delete the uncalled `backend/app/workflows/drafts.py` service and its isolated
  tests if no runtime caller appears.
- Remove the minimal legacy SQLite reader and migration test if the operator no
  longer imports `news.db`.
- Audit unused API helpers, response models, job types, handlers, scripts, and
  compatibility routes using imports, route registration, tests, docs, and
  runtime workflow evidence.
- Do not retain a path only because it has a test; a test can preserve dead
  code.

#### R1.2 Choose one collection/export orchestration path

- Keep the daily-bundle command only if it is an actual operator workflow.
- If kept, make it a thin CLI over the canonical ingestion and export services.
- Remove duplicated source collection, extraction, error handling, and
  persistence logic from the CLI.

#### R1.3 Remove frontend duplication and misplaced fixtures

- Enable `noUnusedLocals` and `noUnusedParameters` after fixing the five current
  findings.
- Move `frontend/lib/mock-data.ts` into test fixtures because production routes
  no longer consume it.
- Map all legacy route aliases and redirects. Remove those with no bookmarked,
  documented, or tested caller.
- Remove unused components, types, formatters, query keys, and mutation wrappers.

#### R1.4 Establish one frontend API boundary

- Keep one small `request` helper for transport and normalized errors.
- Use generated OpenAPI types as the default compile-time contract.
- Retain handwritten runtime validation only at genuinely untrusted or
  publication-critical boundaries.
- Migrate `api-client.ts`, `editorial-api.ts`, and feature-local clients one
  endpoint at a time; delete each old function immediately after its last caller
  moves.
- Do not create another parallel API-client layer.

#### R1.5 Tidy planning and generated artifacts

- Keep one current plan entrypoint and one operator handoff.
- Do not add a second active roadmap for work already governed by this plan.
- Ensure generated reports, screenshots, backups, exports, media, caches, and
  local databases are ignored rather than tracked.

**Exit gate:** All approved workflows still pass, no dead route is registered,
and handwritten production LOC is at least 5% below baseline.

---

### Phase 2 — Collect and triage correctly

**Objective:** Make incoming material reliable and make the next editorial
decision obvious.

**Primary backend scope:**

- `app/sources`
- `app/ingestion`
- `app/normalization`
- `app/content`
- `app/stories`
- `app/api/articles.py`
- related API routes and repositories

#### R2.1 Fix source-content quality logic

- Replace the length-only readiness decision with explicit reasons: missing
  body, navigation/promotional text, extraction failure, duplicate fragment,
  insufficient facts, or unsupported content.
- Use simple source-specific policy data only where actual sources require
  different minimums; do not create a policy framework for hypothetical feeds.
- Add a small Persian/English fixture corpus containing full articles, excerpts,
  promos, link lists, malformed dates, missing titles, and duplicate updates.
- Ensure every rejection or degraded item has a visible, stable reason.

#### R2.2 Make normalization and deduplication deterministic

- Centralize URL, timestamp, title, and fingerprint normalization.
- Test timezone-naive, timezone-aware, malformed, edited, and repeated source
  items.
- Verify database uniqueness and transaction boundaries under concurrent
  ingestion.
- Remove repeated fallback rules from individual parsers and repositories.

#### R2.3 Simplify story grouping and editorial transitions

- Define allowed Story states and transitions in one module.
- Keep grouping/scoring decisions pure where possible; persistence belongs in
  one repository transaction.
- Replace large argument lists with one typed command only where the same values
  travel through multiple layers.
- Return a typed result explaining grouped, skipped, duplicate, or conflicted
  items.

#### R2.4 Replace article query branching with a query object

- Parse filters once at the route boundary.
- Build one SQL query path for filters, stable sorting, cursor pagination, and
  counts.
- Add indexed title/body full-text search.
- Compute facets in SQL instead of loading every matching content ID.
- Test stable pagination while new rows arrive and while sort keys tie.

#### R2.5 Repair Today and Inbox

- Today shows health compactly, then the highest-priority operator decision and
  a direct Add story/Continue review/Resolve failure action.
- Inbox defaults to Needs decision, with Ready to generate and Research
  incomplete views.
- Reduce repeated row buttons; keep the primary action visible and move
  secondary actions into expanded detail.
- Keep Raw Content, source details, and ingestion runs under Advanced.
- Decide whether Feed is a distinct monitoring tool. If it duplicates Inbox or
  Library, merge the useful filters and remove the extra workflow.

**Exit gate:** A mixed-source dataset can be collected, normalized, deduplicated,
grouped, filtered, searched, shortlisted, and rejected without incorrect state
or multi-second list/facet queries.

---

### Phase 3 — Research, generate, and review one exact truth

**Objective:** Remove the most complex generation code while protecting evidence
and revision invariants.

**Primary backend scope:**

- `app/research`
- `app/generation/handlers.py`
- `app/generation/editorial_service.py`
- `app/api/content_packs.py`
- generation-related sections of `app/api/telegram_drafts.py`

#### R3.1 Write explicit state and result types

- Define the allowed ResearchRun, GenerationRun, ContentPack, VariantRevision,
  and approval transitions.
- Use one domain error vocabulary for missing evidence, stale revision,
  invalid provider result, validation failure, and capability unavailable.
- Map those errors to HTTP and job outcomes at the edges.

#### R3.2 Split generation orchestration by actual operation

Create small operation modules for:

- canonical story generation;
- package generation;
- variant regeneration;
- immutable manual edit;
- validation and quarantine;
- exact approval/rejection.

Each operation should visibly perform:

```text
load and validate context
  -> call one provider boundary when needed
  -> validate the typed result
  -> persist one atomic outcome
  -> enqueue the explicit next job, if any
```

Do not introduce a generic workflow engine. Reuse existing repositories and
services when their contract is already correct.

#### R3.3 Remove duplicated provider/result handling

- Resolve provider profiles and capability status in one place.
- Normalize provider errors, model identity, usage, cost, and invalid output
  once.
- Centralize JSON-schema/result decoding per generated artifact.
- Keep fake, OpenRouter, and Codex adapters thin and behaviorally equivalent at
  the application boundary.

#### R3.4 Make API routes thin

- Move revision transition logic out of `telegram_drafts.py`.
- Move content-pack response construction to small typed mappers.
- Routes should validate input, call one operation, and return its result.
- Remove compatibility endpoints once every frontend and test caller uses the
  canonical endpoint.

#### R3.5 Consolidate Drafts and Review UX

- Drafts becomes the list for Needs review, Ready for handoff, Failed, and All.
- Exact `/review/[revisionId]` deep links remain valid.
- The default editor shows preview, validation blockers, evidence excerpts,
  editing, and decision controls.
- Hashes, raw payloads, provider/prompt provenance, media internals, and export
  internals move into contextual advanced sections.
- Automatically open an advanced section when it contains the current blocker.

**Exit gate:** Research, generation, editing, regeneration, approval, and stale
conflict behavior pass unit, PostgreSQL, contract, and browser tests. Generation
hotspots have no complexity violations and no file in this slice exceeds 800
lines.

---

### Phase 4 — Telegram automation and publishing without branching chaos

**Objective:** Preserve crash safety and exact publication while reducing the
largest backend hotspot.

**Primary backend scope:**

- `app/automations/telegram/handlers.py`
- `app/automations/telegram/repository.py`
- `app/publishing/telegram/service.py`
- `app/publishing/telegram/handlers.py`
- remaining Telegram draft/reconciliation API code

#### R4.1 Separate route decisions from effects

Extract pure, table-tested decisions for:

- route activation boundary;
- new-only versus bounded backfill eligibility;
- polling cursor advancement;
- album/media policy;
- review versus auto-publish policy;
- retry versus terminal failure;
- reconciliation-required outcomes.

Database reads/writes, Telegram fetches, file materialization, job enqueueing,
and publication calls stay in explicit effectful steps around those decisions.

#### R4.2 Replace nested handler factories with named operations

- Use one small dependencies object only for dependencies shared by several
  handlers.
- Give initialize, poll, capture, process, schedule, publish, and reconcile
  separate named functions/modules.
- Remove closure-captured state and repeated capability/profile lookups.
- Keep job registry wiring declarative and short.

#### R4.3 Consolidate publication validation

- Load and validate the exact revision/destination context once.
- Keep rendering, transport, receipt persistence, and ambiguous-outcome
  reconciliation separate.
- Use one idempotency and claim-fence implementation for immediate and scheduled
  publication.
- Test process termination before send, during send, after remote success, and
  before local receipt persistence.

#### R4.4 Simplify automation UI

- Present route readiness and the next corrective action before technical
  details.
- Use a short guided create/edit flow with conservative defaults.
- Keep activation, dry run, pause/resume, bounded backfill, and reconciliation
  explicit.
- Hide cursors, message coordinates, capability timestamps, and raw job payloads
  under Advanced unless they are causing a failure.

**Exit gate:** Activation, polling, capture, generation dispatch, dry run,
reviewed publication, retry, and reconciliation pass with no source-message
loss or duplicate publication. The 2,707-line handler module and 1,774-line
publishing service no longer exist as monoliths.

---

### Phase 5 — Settings, diagnostics, jobs, and retention

**Objective:** Make occasional operations understandable without letting them
dominate daily editorial work.

#### R5.1 Split Content Settings by responsibility

- Keep a single settings route if that is easiest for the operator, but move
  Editorial profiles, Providers, Codex, Telegram destinations/proxies, and
  Prompt governance into separate feature modules.
- Reuse small Field, Dialog, Status, and Secret primitives only where behavior
  is truly identical.
- Remove duplicated request/mutation/loading code through the canonical feature
  API pattern.
- Show a setup checklist for missing provider, profile, destination, or prompt
  prerequisites.

#### R5.2 Clarify operational ownership

- Today owns human attention.
- Jobs owns durable execution and retry truth.
- Diagnostics owns system health and recovery evidence.
- Sources owns source-specific health.
- Link each failure directly to the narrowest repair action instead of
  repeating the full status everywhere.

#### R5.3 Refactor retention last

- Preserve preview-before-delete and all reference fences.
- Separate candidate planning, database execution, filesystem execution, and
  recovery/finalization.
- Use the same candidate representation for preview and execution so the two
  cannot drift.
- Test interrupted database and filesystem phases against real PostgreSQL and
  temporary media/export directories.

#### R5.4 Finish static typing by domain

- Expand mypy coverage one completed package at a time.
- Resolve nullable/SQL/result-shape errors at their source instead of adding
  broad ignores or casts.
- Allow narrow adapter-level ignores only for demonstrably incorrect third-party
  stubs.

**Exit gate:** An operator can configure dependencies, understand a failure,
retry or reconcile work, preview retention, and complete cleanup without reading
raw identifiers or backend terminology. Content Settings is no longer a
1,500-line component, and full-app mypy is green.

---

### Phase 6 — Global UI consistency and usability

**Objective:** Make the completed vertical slices feel like one product.

#### R6.1 Simplify information architecture

Primary:

- Today
- Inbox
- Drafts
- Calendar
- Library

Advanced:

- Sources / Raw Content / Collection Runs / Media
- Automations / Jobs
- Diagnostics / Content Settings / Retention

Preserve deep links and recovery access. Remove a top-level destination only
after its capability is reachable from the new hierarchy.

#### R6.2 Standardize interaction language

- Use operator language in primary UI and exact backend vocabulary in Advanced.
- Use one status vocabulary and one color/icon meaning per status.
- Use one primary action per card or panel.
- Make destructive, external, automatic, and irreversible actions visually and
  verbally distinct.
- Replace vague errors with a short cause, current durable state, and next
  action.

#### R6.3 Standardize states without a new design system

Use the existing UI stack and a small set of shared patterns for:

- page heading and primary action;
- loading skeleton;
- honest empty state;
- inline and page-level error;
- retry/progress feedback;
- confirmation dialog;
- status badge;
- advanced disclosure.

Do not build a separate component library project.

#### R6.4 Validate real operator tasks

Run the full workflow at desktop and 390px:

1. Add a manual story.
2. Find an ingested story and make an editorial decision.
3. Research and generate a package.
4. Edit and approve the exact revision.
5. Export or publish it.
6. Diagnose and recover one failed job.

Verify keyboard order, focus restoration, screen-reader names, Persian RTL,
mixed-language text, long titles, empty data, slow data, and failed requests.

**Exit gate:** The six tasks complete without dead ends, hidden required actions,
horizontal overflow, misleading success, or exposure of unnecessary technical
detail.

---

### Phase 7 — Consolidate and close

**Objective:** Leave a smaller repository with one truthful maintenance path.

#### R7.1 Remove transitional code

- Delete every migration shim, old API function, route alias, duplicate type,
  temporary mapper, and compatibility test whose last caller moved during
  Phases 1-6.
- Search docs, tests, API schema, frontend imports, and route registration before
  each deletion.

#### R7.2 Make quality gates permanent

Blocking gates:

- normal Ruff checks and formatting;
- complexity checks for application code;
- full-app mypy;
- TypeScript strict typecheck plus unused-code checks;
- OpenAPI generation/contract drift check;
- backend unit and PostgreSQL integration suites;
- frontend unit tests with no known flake;
- production frontend build;
- primary Playwright workflow and accessibility tests;
- Compose configuration, migration, deterministic acceptance, and restore
  drill.

#### R7.3 Rewrite current documentation from the final code

- Update README workflow and commands.
- Replace stale branch/handoff claims.
- Keep one current architecture/product description.
- Keep runbooks only for behavior that still exists.
- Do not reintroduce completed planning artifacts as active work queues.
- Record final before/after LOC, complexity, typing, performance, and test
  results.

**Exit gate:** All gates pass from a clean checkout, documentation matches the
running product, and this plan has a completed result section rather than being
replaced by another overlapping plan.

## 8. Recommended implementation order

Do not attack files from largest to smallest. Use this order because it follows
operator value and limits the blast radius:

1. R0 validation signal.
2. R1 proven deletions and frontend API boundary.
3. R2 collection, content quality, stories, and Inbox.
4. R3 research, generation, revisions, and Drafts.
5. R4 Telegram automation and publishing.
6. R5 settings, operations, and retention.
7. R6 global UI pass.
8. R7 transitional deletion and final gates.

Within a phase, use this loop:

```text
reproduce defect or characterize invariant
  -> delete obsolete path
  -> isolate pure decision
  -> simplify effectful orchestration
  -> update the narrow UI
  -> run focused tests
  -> run phase gates
  -> record metrics and commit
```

## 9. Validation matrix

| Change area | Focused proof | Phase proof |
| --- | --- | --- |
| Pure state/validation logic | table-driven unit tests | full backend unit suite |
| Repository/query/migration | PostgreSQL integration tests | empty-db migration plus all PostgreSQL suites |
| Job/worker behavior | fake clock/transport plus lease tests | deterministic crash/retry acceptance |
| Telegram publication | fake transport and receipt assertions | staging dry run and authorized qualification when available |
| API contracts | route tests and OpenAPI snapshot | regenerate client with no unexplained diff |
| Frontend data layer | feature API/query tests | full Vitest and typecheck |
| UI workflow | component tests | primary Playwright journey at desktop/mobile |
| Accessibility/RTL | focused semantic tests | axe, keyboard, focus, Persian RTL browser run |
| Retention/files | candidate and fence tests | disposable backup/restore and interrupted-phase drill |

Minimum repository-wide commands at a phase gate:

```bash
cd backend
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
.venv/bin/mypy app
.venv/bin/python -m pytest tests -q

cd ../frontend
npm run api:generate
npm run typecheck
npm run test
npm run build
npm run test:e2e

cd ..
git diff --check
docker compose config
```

PostgreSQL, deterministic acceptance, and restore commands from the current
runbooks remain mandatory at the relevant phase gates. `docker compose config`
alone is not runtime proof.

## 10. First bounded implementation batch

Start with this batch only:

1. Add the repeatable LOC/complexity/type baseline command.
2. Repair the stale nightly test references.
3. Reproduce and eliminate the export-actions test flake.
4. Make the PostgreSQL suite start its required test database and fail when the
   database is unavailable instead of silently skipping the proof.
5. Add or consolidate the five critical acceptance journeys.
6. Re-run all Phase 0 gates and record the result.

Do not begin moving the large handler modules until this batch is green. It
creates the safety net required for aggressive deletion and simplification.

## 11. Planning estimate

For one focused engineer, expect:

- trustworthy baseline and deletion pass: 1-2 weeks;
- collect/triage and generation/review slices: 3-5 weeks;
- Telegram automation/publishing and operations: 3-5 weeks;
- global UX, transitional deletion, and final proof: 2-3 weeks.

The whole plan is approximately 9-15 focused engineering weeks. The first
operator-visible improvements should land during Phase 2; completion should not
be delayed for one giant final merge.
