TASK_ID: wave2a-ingest
BASE_SHA: 377c805

OBJECTIVE:
Fix every CONFIRMED finding in the ingestion vertical from the verified
refactor triage: 28 items (8 P1 / 20 P2; the 20 P3 items run in a later batch) covering the collection
pipeline — dedup/identity handling, media asset persistence, feed fetch
error handling, icon discovery, and redundancy/dead-code inside the
vertical. Findings file (read first, it is the packet's work list):
/home/wingman/code/NewsCraft/.orchestrator/runs/refactor-2026-08-13/verify/wave2a-ingest-items-p12.json
Each item carries verdict, severity, evidence, and a proposed smallest-safe
repair. The repairs are proposals from a read-only verifier: you are the
implementer and may choose a better fix, but the defect itself is
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
- backend/app/ingestion/**
- backend/app/sources/**
- backend/app/media/**
- backend/app/normalization/**
- backend/app/discovery/**
- backend/app/source_collections/**
- backend/tests/** EXCEPT the sibling-owned test files listed in NON_GOALS
  (you may create new test files and edit any existing test that covers
  your modules)
- backend/alembic/versions/** ONLY for the single pre-assigned migration
  below

PRE_ASSIGNED_IDENTIFIERS:
- If (and only if) a fix requires a new Alembic migration (e.g. the
  media_assets.url_hash index or an item_identities uniqueness repair),
  use revision id 0028_wave2a_ingest with down_revision set to the current
  head; at most ONE new migration file for this packet.

READ_ONLY_DEPENDENCIES:
- backend/app/core/** (incl. safe_http.py — recently fixed, do not touch)
- backend/app/jobs/** (queue contracts)
- backend/app/api/** except: you MAY edit backend/app/api/schemas.py and
  backend/app/api/source_collections.py only if a confirmed item requires
  it (no sibling owns them this wave)
- plan.md, docs/** for intent

INTERFACES:
- Public API responses and job payload shapes must not change; internal
  repository/service signatures inside OWNED_PATHS may.

INVARIANTS:
- Idempotency of ingestion (re-running a collection must not duplicate
  content items, identities, or media assets).
- No test may target a real database; use the existing disposable-DB
  fixtures.
- SafeHttpClient stays the pinned SSRF path; never reintroduce ambient
  proxy env fallback.
- Do not weaken any existing test assertion to make a fix pass.

DECISIONS_ALREADY_MADE:
- Severity floors per guardrails (data integrity/concurrency/idempotency
  >= P1) are already applied in the findings file; do not relitigate.
- Verdicts are final: CONFIRMED items are real. If you discover a
  CONFIRMED item was already fixed by commits after the map (git log
  8d5129a..HEAD), report it NO_CHANGE_NEEDED with the fixing sha.

NON_GOALS:
- Design-smell item "two competing outbound-HTTP stacks" (safe_http vs
  the other client): cross-cutting consolidation deferred to Wave 3 —
  SKIP it and say so in the report.
- Module decomposition of icon_discovery.py (~908 lines) beyond what your
  fixes naturally require — Wave 3.
- Sibling-owned (wave2a-ops) test files — do NOT edit:
  backend/tests/operations/**, backend/tests/retention/**,
  backend/tests/postgres/test_retention_service.py,
  backend/tests/test_models.py
- Anything under frontend/**, scripts/**, backend/app/operations/**,
  backend/app/retention/**.

ACCEPTANCE_CRITERIA:
- Every P1 and P2 item in the findings file is FIXED, NO_CHANGE_NEEDED
  (with evidence), or SKIPPED (with a concrete blocking reason — expect
  zero or near-zero of these). P3 items: fix when the repair is bounded;
  SKIP-with-reason is acceptable.
- Each concurrency/idempotency fix gets a regression test that fails on
  the old code (state in the report how you proved that: e.g. git stash
  the fix and rerun).
- Full backend suite green.

VERIFICATION_COMMANDS:
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m pytest tests -q  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m mypy  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m ruff check .  (exit 0)

EXPECTED_COMMIT_MESSAGE:
fix(ingestion): repair confirmed dedup, media, and fetch-loop defects

OUTPUT_CONTRACT:
Return the standard opus-fixer report with the resulting commit SHA(s)
(commit only to your worktree branch; never push or open a PR). Report
per-item outcomes keyed by the findings-file refs.
