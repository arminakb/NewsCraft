TASK_ID: wave2a-ops
BASE_SHA: e5023b4

OBJECTIVE:
Fix every CONFIRMED finding in the operations/retention vertical from the
verified refactor triage: 34 items (5 P1 / 17 P2 / 12 P3) covering
retention phase accounting, table-lock scope during filesystem deletion,
health/diagnostics, the SQL-vs-Python completeness rule divergence, and
redundancy/dead-code inside the vertical. Findings file (read first, it
is the packet's work list):
/home/wingman/code/NewsCraft/.orchestrator/runs/refactor-2026-08-13/verify/wave2a-ops-items.json
Each item carries verdict, severity, evidence, and a proposed smallest-safe
repair. The repairs are proposals from a read-only verifier: you are the
implementer and may choose a better fix, but the defect itself is
confirmed and must be addressed (or reported SKIPPED with a concrete
reason).

OWNED_PATHS:
- backend/app/operations/**
- backend/app/retention/**
- backend/app/diagnostics/**
- backend/app/operator_settings/**
- backend/app/api/articles.py, backend/app/api/operations.py,
  backend/app/api/stories.py
- backend/app/research/completeness.py
- backend/app/db/model_registry.py, backend/app/stories/models.py,
  backend/alembic/env.py, backend/app/core/config.py (only where a
  confirmed item requires)
- backend/tests/operations/**, backend/tests/retention/**,
  backend/tests/postgres/test_retention_service.py,
  backend/tests/test_models.py, plus any OTHER existing test that covers
  your modules and any new test files you create — EXCEPT sibling-owned
  paths in NON_GOALS
- frontend/features/operations/**, frontend/lib/api/generated.ts ONLY if
  a confirmed item's contract fix requires regenerating types (state how
  you regenerated)
- scripts/quality_baseline.py ONLY if a confirmed item names it

PRE_ASSIGNED_IDENTIFIERS:
- If (and only if) a fix requires a new Alembic migration, use revision id
  0029_wave2a_ops with down_revision 0028_wave2a_ingest if that file
  exists on your branch, else the current head. At most ONE new migration
  file. (A sibling worker may create 0028 in ITS worktree — you will not
  see it; using the literal id 0029_wave2a_ops keeps the ids collision-free
  and the orchestrator will chain down_revisions at integration.)

READ_ONLY_DEPENDENCIES:
- backend/app/jobs/** (queue/lease contracts)
- backend/app/core/safe_http.py, backend/app/api/schemas.py
- plan.md, docs/** for intent

INTERFACES:
- Public API response shapes must not change unless the confirmed item is
  itself a contract defect; then contracts/openapi.json must be
  regenerated the way the repo does it (find the generator; do not hand
  edit).

INVARIANTS:
- Retention must never delete data outside its computed plan; fixes to
  phase accounting must be provably conservative (err toward retaining).
- No LOCK TABLE held across long filesystem operations after your fix —
  that is the point of the confirmed P1.
- No test may target a real database; use existing disposable-DB fixtures.
- Do not weaken any existing test assertion to make a fix pass.

DECISIONS_ALREADY_MADE:
- Severity floors per guardrails are already applied; do not relitigate.
- Verdicts are final: CONFIRMED items are real. If already fixed by
  commits after the map (git log 8d5129a..HEAD), report NO_CHANGE_NEEDED
  with the fixing sha.
- For the SQL-vs-Python completeness divergence: the PYTHON rule
  (research/completeness.py) is canonical; make the SQL agree with it.

NON_GOALS:
- Decomposing health.py (1089 lines) / api/articles.py (1034) below the
  1000-line ceiling — Wave 3 owns decomposition; fix defects in place.
- Sibling-owned (wave2a-ingest) paths — do NOT edit:
  backend/app/ingestion/**, backend/app/sources/**, backend/app/media/**,
  backend/app/normalization/**, backend/app/discovery/**,
  backend/app/source_collections/**, and their test files.
- Anything under frontend/** beyond frontend/features/operations/** and
  the generated-types exception above.

ACCEPTANCE_CRITERIA:
- Every P1 and P2 item is FIXED, NO_CHANGE_NEEDED (with evidence), or
  SKIPPED (with a concrete blocking reason — expect zero or near-zero).
  P3: fix when bounded; SKIP-with-reason acceptable.
- The retention lock-scope fix and phase-accounting fix each get a
  regression test that fails on the old code (state how you proved that).
- Full backend suite green.

VERIFICATION_COMMANDS:
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m pytest tests -q  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m mypy  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m ruff check .  (exit 0)
- If frontend/features/operations/** changed: cd /home/wingman/code/NewsCraft/frontend && npm run test && npm run typecheck against your changes copied? NO — instead symlink node_modules into your worktree frontend and run there (exit 0); if the symlink trick fails, report the frontend tests as ORCHESTRATOR-RERUN.

EXPECTED_COMMIT_MESSAGE:
fix(operations): repair confirmed retention, health, and contract defects

OUTPUT_CONTRACT:
Return the standard opus-fixer report with the resulting commit SHA(s)
(commit only to your worktree branch; never push or open a PR). Report
per-item outcomes keyed by the findings-file refs.
