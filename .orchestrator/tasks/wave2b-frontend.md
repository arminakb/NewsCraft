TASK_ID: wave2b-frontend
BASE_SHA: 377c805

OBJECTIVE:
Fix every CONFIRMED finding assigned to the frontend vertical: 62 items
(6 P1 / 23 P2 / 33 P3) across routing/proxy, data fetching, feature
pages, shared components, and redundancy/dead-code. Findings file (read
first — it is the work list):
/home/wingman/code/NewsCraft/.orchestrator/runs/refactor-2026-08-13/verify/wave2b-frontend-items.json
Includes the confirmed P1 hop-by-hop header defect in the backend proxy
route and the manual-publishing-checklist test flakiness. Each item
carries verdict, severity, evidence, and a proposed smallest-safe repair.
You may choose a better fix, but the defect is confirmed and must be
addressed (or reported SKIPPED with a concrete reason).

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
- frontend/** (whole vertical, including frontend/tests/** and
  frontend/e2e/**) EXCEPT the sibling-owned paths in NON_GOALS

PRE_ASSIGNED_IDENTIFIERS: NONE

READ_ONLY_DEPENDENCIES:
- contracts/openapi.json and backend/app/api/** (API truth — frontend
  adapts to backend, never the reverse in this packet)
- frontend/lib/api/generated.ts (generated + sibling-owned: read-only)

INTERFACES:
- No backend calls added or removed unless a confirmed item says the
  call is dead/wrong; route paths stay as-is.

INVARIANTS:
- npm ci only, never npm install; do not change package.json/lock unless
  a confirmed item explicitly requires it (none do).
- The Next proxy route must keep streaming/status forwarding behavior
  while fixing the confirmed header handling defect.
- Do not weaken any existing test assertion; flaky tests get proper
  waitFor-style fixes (see commit 3155f34 for the established pattern).

DECISIONS_ALREADY_MADE:
- Severity floors already applied; verdicts final. Items already fixed
  after the map (e.g. articles-page clear-feed tests in 3155f34) →
  NO_CHANGE_NEEDED with the sha.

NON_GOALS:
- Sibling-owned: frontend/features/operations/** and
  frontend/lib/api/generated.ts — do NOT edit; 24 deferred items
  touching them live in wave2b-frontend-deferred.json and are NOT yours.
- Decomposing articles-page.tsx (~1111 lines) and the other ≥1000-line
  frontend modules — Wave 3; fix defects in place.
- Anything under backend/**, scripts/**, contracts/**.

ACCEPTANCE_CRITERIA:
- Every P1/P2 item FIXED, NO_CHANGE_NEEDED (with evidence), or SKIPPED
  (concrete reason; expect near-zero). P3: fix when bounded.
- Proxy-route fix covered by a unit test exercising the header behavior.
- Full frontend suite + typecheck + strict unused-code check green.

VERIFICATION_COMMANDS (your worktree has no node_modules: create it via
`ln -s /home/wingman/code/NewsCraft/frontend/node_modules <your worktree>/frontend/node_modules`
— if a command then fails for symlink reasons rather than real findings,
report that command as ORCHESTRATOR-RERUN, do not run npm install):
- cd <your worktree>/frontend && npm run test  (exit 0)
- cd <your worktree>/frontend && npm run typecheck  (exit 0)
- cd <your worktree>/frontend && ./node_modules/.bin/tsc --noEmit --incremental false --noUnusedLocals --noUnusedParameters  (exit 0)

EXPECTED_COMMIT_MESSAGE:
fix(frontend): repair confirmed proxy, state, and cleanup findings

OUTPUT_CONTRACT:
Return the standard opus-fixer report with commit SHA(s) (worktree branch
only; never push). Report per-item outcomes keyed by findings-file refs.
