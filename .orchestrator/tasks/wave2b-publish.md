TASK_ID: wave2b-publish
BASE_SHA: 377c805

OBJECTIVE:
Fix every CONFIRMED finding assigned to the publishing/jobs vertical: 39
items (8 P1 / 16 P2 / 15 P3) covering the job queue (leases, retries,
idempotency), automations/workflow engine, Telegram automated + manual
publishing paths, exports, and redundancy/dead-code inside the vertical.
Findings file (read first — it is the work list):
/home/wingman/code/NewsCraft/.orchestrator/runs/refactor-2026-08-13/verify/wave2b-publish-items.json
Each item carries verdict, severity, evidence, and a proposed
smallest-safe repair from a read-only verifier. You may choose a better
fix, but the defect is confirmed and must be addressed (or reported
SKIPPED with a concrete reason).

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
- backend/app/jobs/**
- backend/app/automations/**
- backend/app/workflows/**
- backend/app/publishing/**
- backend/app/manual_publication/**
- backend/app/exports/**
- backend/app/daily_bundle/**
- backend/tests/** files covering the modules above (create new test
  files freely) — EXCEPT sibling-owned test paths in NON_GOALS

PRE_ASSIGNED_IDENTIFIERS:
- If (and only if) a fix requires a new Alembic migration, use revision
  id 0030_wave2b_publish, at most ONE migration file. Set down_revision
  to the current head you see; the orchestrator re-chains ids at
  integration if siblings also added migrations.

READ_ONLY_DEPENDENCIES:
- backend/app/generation/**, backend/app/content/**, backend/app/stories/**
  (editorial vertical — a later worker owns these)
- backend/app/retention/**, backend/app/operations/** (sibling worker)
- backend/app/ingestion/**, backend/app/sources/**,
  backend/app/source_collections/** (sibling worker)
- backend/app/core/**, backend/app/api/**, backend/app/db/**
- plan.md, docs/** for intent

INTERFACES:
- Job payload shapes, job type names, and public API responses must not
  change; internal signatures inside OWNED_PATHS may.

INVARIANTS:
- Queue idempotency and crash recovery: a re-delivered or crash-recovered
  job must never double-publish; leases/retries stay contract-compatible
  with backend/tests/postgres/** expectations.
- Telegram/external-service boundaries: no new outbound call paths; never
  log secrets.
- No test may target a real database; use existing disposable-DB fixtures.
- Do not weaken any existing test assertion to make a fix pass.

DECISIONS_ALREADY_MADE:
- Severity floors per guardrails are already applied; do not relitigate.
- Verdicts are final. If an item was already fixed by commits after the
  map (git log 8d5129a..HEAD touched automations/definitions/service.py,
  jobs/handlers.py among others), report NO_CHANGE_NEEDED with the sha.

NON_GOALS:
- The 2 deferred items in wave2b-publish-deferred.json (they touch
  generation/** and retention/** owned elsewhere) — do not fix.
- Decomposing jobs/repository.py (~893) / process_dispatch.py (~902) /
  definitions/service.py (~973) — Wave 3; fix defects in place.
- Sibling-owned test paths — do NOT edit: backend/tests/operations/**,
  backend/tests/retention/**, backend/tests/postgres/test_retention_service.py,
  backend/tests/test_models.py, and ingestion/sources/media test files.
- Anything under frontend/**, scripts/**.

ACCEPTANCE_CRITERIA:
- Every P1/P2 item FIXED, NO_CHANGE_NEEDED (with evidence), or SKIPPED
  (concrete blocking reason; expect near-zero). P3: fix when bounded.
- Each idempotency/crash-recovery fix gets a regression test that fails
  on the old code (state how you proved that).
- Full backend suite green.

VERIFICATION_COMMANDS:
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m pytest tests -q  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m mypy  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m ruff check .  (exit 0)

EXPECTED_COMMIT_MESSAGE:
fix(publishing): repair confirmed queue, automation, and publish defects

OUTPUT_CONTRACT:
Return the standard opus-fixer report with commit SHA(s) (worktree branch
only; never push). Report per-item outcomes keyed by findings-file refs.
