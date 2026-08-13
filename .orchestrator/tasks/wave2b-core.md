TASK_ID: wave2b-core
BASE_SHA: 377c805

OBJECTIVE:
Fix every CONFIRMED finding assigned to the backend core/security
vertical: 17 items (4 P1 / 9 P2 / 4 P3). The headline item is the P1
default-allow security hole: security/middleware.py mutation_rule
returns None for every unlisted mutating route, skipping authentication,
same-origin/CSRF checks, and audit for POST/PUT/PATCH/DELETE on sources,
source-collections, article-collections, telegram drafts/sources,
stories, ingest, content, content-packs, calendar, and exports routes.
Findings file (read first — it is the work list):
/home/wingman/code/NewsCraft/.orchestrator/runs/refactor-2026-08-13/verify/wave2b-core-items.json
Each item carries verdict, severity, evidence, and a proposed
smallest-safe repair. You may choose a better fix, but the defect is
confirmed and must be addressed (or reported SKIPPED with a concrete
reason).

WORKING_DISCIPLINE (mandatory):
- FIRST ACTION: `git log --oneline -1`. If HEAD is not BASE_SHA, run
  `git reset --hard <BASE_SHA>` (the object store is shared; this works)
  and confirm. Never work from a different base.
- Work items in severity order (P1 first). Commit after EACH logical fix
  with its own conventional message — many small commits are expected;
  never leave fixes uncommitted.
- Budget your context: when roughly 25% of your context remains, STOP
  starting new items, run the verification commands, commit, and return
  your report. Unattempted items get outcome SKIPPED with detail
  "context-budget". An honest partial report with committed work is
  success; an unreturned report is failure.
- Your FINAL message must be the structured report (StructuredOutput
  tool). Do this even if verification commands fail — report the failure
  honestly instead of not reporting.

OWNED_PATHS:
- backend/app/security/**
- backend/app/main.py
- backend/app/db/** EXCEPT model_registry.py (sibling-owned)
- backend/app/core/** EXCEPT config.py and safe_http.py
- backend/app/api/** EXCEPT articles.py, operations.py, stories.py,
  schemas.py, source_collections.py (sibling-owned this wave)
- backend/tests/** files covering the modules above (create new test
  files freely) — EXCEPT sibling-owned test paths in NON_GOALS

PRE_ASSIGNED_IDENTIFIERS:
- Migration id 0031_wave2b_core if (and only if) strictly required; at
  most ONE. Unlikely for this packet — prefer no schema change.

READ_ONLY_DEPENDENCIES:
- backend/app/core/config.py, backend/app/core/safe_http.py
- backend/app/api/{articles,operations,stories,schemas,source_collections}.py
- All feature modules (ingestion, sources, jobs, automations, ...)
- docs/content-settings/target-architecture.md (documents the intended
  every-mutation-requires-origin contract), plan.md

INTERFACES:
- Response envelopes and status codes for ALREADY-COVERED routes must
  not change. Newly covered routes gaining 401/403/409 where they
  previously passed unauthenticated is the intended contract restoration
  — update affected tests accordingly, never by deleting their
  assertions.

INVARIANTS:
- Default-deny: after your fix, every mutating route yields a non-None
  mutation rule; add the route-table enumeration test the findings file
  proposes so new routers cannot regress this.
- Authorization/privacy/API-contract changes are P1 territory: be
  surgical, prove behavior with tests, and document any route whose
  effective policy changed in your report.
- No test may target a real database; use existing fixtures.
- Do not weaken any existing test assertion to make a fix pass.

DECISIONS_ALREADY_MADE:
- Severity floors already applied; verdicts final. Items already fixed
  after the map → NO_CHANGE_NEEDED with the sha.
- The CORS-ordering finding was REJECTED (same-origin proxy topology);
  the optional middleware-order swap is NOT in scope.

NON_GOALS:
- The 19 deferred backend-core items in wave2b-core-deferred.json (they
  touch sibling-owned files: api/articles.py, api/schemas.py,
  api/source_collections.py, api/stories.py, api/operations.py,
  core/config.py, operations/**, source_collections/**) — not yours.
- Sibling-owned test paths: backend/tests/operations/**,
  backend/tests/retention/**, backend/tests/test_models.py, and
  ingestion/sources/media/jobs/automations test files.
- Anything under frontend/**, scripts/**.

ACCEPTANCE_CRITERIA:
- Every P1/P2 item FIXED, NO_CHANGE_NEEDED (with evidence), or SKIPPED
  (concrete reason; expect near-zero). P3: fix when bounded.
- The middleware fix ships with: (a) the enumeration test over app.routes
  asserting non-None rules for all mutating methods; (b) at least one
  test proving a previously-uncovered route now enforces same-origin and
  scope; (c) a report listing every route whose policy changed.
- Full backend suite green.

VERIFICATION_COMMANDS:
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m pytest tests -q  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m mypy  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m ruff check .  (exit 0)

EXPECTED_COMMIT_MESSAGE:
fix(security): enforce default-deny mutation rules and core API repairs

OUTPUT_CONTRACT:
Return the standard opus-fixer report with commit SHA(s) (worktree branch
only; never push). Report per-item outcomes keyed by findings-file refs.
