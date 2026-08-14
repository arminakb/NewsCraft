# Orchestration state

This file must always allow a fresh Fable session to continue the run.
Update at every phase transition. Live git/gh output beats memory; this file
beats conversation memory. If this file is blank but worktrees/PRs exist, a
previous run left no state — rebuild truth per SKILL.md Stage 0 first.

RUN_ID: refactor-2026-08-13
LAST_UPDATED_BY: wingman-host (local session)
OBJECTIVE: Full-codebase refactor — fix all bugs, remove redundancy and
  dead code, decompose oversized modules, make every gate green. Owner:
  "every stone turned", "give me a clean repo".
PHASE: COMPLETE (light-gate scope, 2026-08-14). Heavy battery + cold review pending via HANDOFF-heavy-testing.md
INTEGRATION_BRANCH: agent/finish-refactor-plan
BASE_SHA: 8d5129a (merge of origin/main 46b4489 + orchestrator kit)
CURRENT_HEAD_SHA: 397671c (gate fixes integrated: 3155f34 frontend test fix, 397671c backend gate fix)
PR: https://github.com/arminakb/NewsCraft/pull/19 (opened 2026-08-14; merge ONLY on owner approval after heavy battery per HANDOFF-heavy-testing.md)
MERGE_POLICY: never merge without explicit user approval for the exact PR.

OWNER_DIRECTIVES (verbatim, 2026-08-14): "ok so from now on dont use opus
5 at all .. only sol .. high to max for fix and review .. max only for
reviews . and continue the work . i want this finish today" — ALL
delegated work runs on codex gpt-5.6-sol via .orchestrator/scripts/
(CODEX_FIX_EFFORT=high default, max for hardest scopes; reviews always
max). No Claude subagents of any model.

OWNER_DIRECTIVES (verbatim, 2026-08-13):
- "Wait dont use fable sub agents !! never use fable sub agents" — ALL
  delegated work runs on Opus (workflow agents get model:'opus'); Fable
  orchestrates only. Codex CLI allowed as cold reviewer/fixer.
- "be very careful on which paths u allow implementer or fixer to be able
  to edit .. cuz if u dont let his hands loose it might cripple him" —
  generous OWNED_PATHS; encoded in guardrails + packet template.

REVIEW_PROTOCOL_IN_FORCE:
Opus high workers for map/verify/fix; codex gpt-5.6-sol max cold review
via .orchestrator/scripts/codex-review.sh planned after fix waves
integrate. Review-cycle cap: default 2.

ENVIRONMENT_NOTES:
- Python 3.14.6 OK; uv installed is 0.12.1 but pyproject pins
  required-version ==0.11.29 → uv commands may refuse; bypass with
  backend/.venv/bin/python -m {pytest,mypy,ruff} directly.
- Node 26.4.0/npm 11.17.0 OK. Merge 46b4489 added framer-motion +
  @xyflow/react; npm ci was required. Stale frontend/.next caused 8
  phantom tsc errors (deleted routes drafts/inbox/runs) — rm -rf .next.
- Worker worktrees have no .venv/node_modules: backend workers use main
  checkout venv against worktree cwd; frontend workers symlink main
  checkout node_modules.
- Docker available; test_postgres.sh/test_acceptance.sh own disposable DBs.
- pytest has no --timeout plugin; plain `-q` runs ~22s.

BASELINE_AT_8d5129a (pre-fix evidence):
- backend pytest: 6 failed / 1848 passed / 236 skipped (registry drift x3,
  SessionContext.scalars seeding bug, job-model columns, outbound proxy).
- frontend vitest: 2 failed (articles-page clear-feed tests) after npm ci;
  typecheck green after .next purge.
- quality_baseline --check: ALL RED — ruff 1, complexity 73>53,
  statements 36>25, TS unused 23>0, mypy 19>0, 2 backend + 2 frontend
  modules ≥1000 lines.

ACTIVE_WORKERS: none (owner paused; wf_c0148e94-bb4 stopped cleanly,
  all 7 chain tips merged: 254 files, +12892/-4569 since 647f137).
GATES_AT_PAUSE: backend pytest 1993P/250S rc=0, mypy rc=0, ruff rc=0,
  frontend vitest 603/603 rc=0, tsc rc=0 (next-env.d.ts dev-drift restored).
RESUME_NEXT_SESSION (in order):
1. Relaunch remaining round3 batches: workflow script
   workflows/scripts/wave2-round3-wf_1c1eb787-b9d.js with ALL STARTS set
   to current branch HEAD (everything is integrated; sweeps are
   idempotent — agents NO_CHANGE_NEEDED already-done items). Chains/batch
   counts unchanged. Remaining: roughly latter batches of ingest/ops/
   publish/frontend/editorial; core+intent likely near-complete.
2. Then deferred items: verify/wave2b-*-deferred.json + wave2c-deferred.json
   (~59 items) — single sweep, any ownership (no concurrent siblings).
3. Wave 3: module decomposition (health.py 1089, api/articles.py 1034,
   articles-page.tsx ~1111, +1), complexity 73>53 / statements 36>25
   budgets, HTTP-stack consolidation, contracts-config + tests-ci
   confirmed items.
4. Full gate battery incl. scripts/test_postgres.sh, test_acceptance.sh,
   quality_baseline.py --check, npm run build + test:e2e.
5. codex-review.sh cold review vs BASE_SHA 8d5129a; triage; fix cycle.
NO merge of any PR without owner approval.
VERIFY_COMPLETE: all 20 slices verified. 372 CONFIRMED total
  (54 P1 / 160 P2 / 161 P3 incl. orchestrator-observed flake), 136
  REJECTED. confirmed-all.json is the master list. Deferred-for-conflict
  items in wave2b-*-deferred.json (45 items) go to Wave 2c with
  backend-editorial (40 items) after current workers finish.
INCIDENT 2 (wave2a first attempt, wf_1bd98a85-263): both fixers burned
  full context without returning reports or committing; one worktree was
  created on the wrong base (46b4489) and the worker did not check.
  Partial work discarded. Countermeasures now in every packet:
  WORKING_DISCIPLINE (base verify/reset, commit-per-fix, stop at 25%
  context and report PARTIAL, always return structured report) and
  severity-split batches (P3 batches deferred).

INTEGRATION_QUEUE: empty (gate-repair integrated: 3155f34 + 397671c; worktrees removed)

PER_PR_STATE: none

VERIFICATION_EVIDENCE: gates re-run by orchestrator at 397671c:
  backend pytest 1854 passed/238 skipped rc=0; mypy rc=0 (280 files);
  ruff rc=0; frontend vitest 577/578 (1 pre-existing flake in
  manual-publishing-checklist, passes in isolation, recorded as P2
  finding); TS-unused 0 findings rc=0.
INCIDENT (2026-08-13): host /tmp wipe destroyed the session scratchpad
  (map corpus + verify inputs). All artifacts recovered from workflow
  journals on home disk. Durable artifacts now live in
  .orchestrator/runs/refactor-2026-08-13/ (map/, verify/) — NEVER stage
  cross-agent handoff files in /tmp again.
RECOVERED_VERDICTS: 7 of 20 slices (both backend-ingest + backend-ops
  slices complete, backend-core-cleanup, backend-editorial-cleanup,
  frontend-core-bugs): 143 CONFIRMED (21 P1 / 60 P2 / 65 P3 incl.
  orchestrator-observed flake) in
  .orchestrator/runs/refactor-2026-08-13/verify/confirmed-recovered.json.

REVIEW_CYCLE: 0 of 2
TRIAGE_ARTIFACT: scratchpad/map-digest.json (361 candidates: 141 bug /
  137 redundancy / 83 dead-code) from map workflow wf_a03c5b8b-900.

PEER_SESSIONS: none

NEXT_ACTION:
1. Collect verify workflow results → triage CONFIRMED items into fix waves.
2. Inspect gate-repair diffs, re-run gates on main checkout, integrate.
3. Wave 2: confirmed bug fixes (parallel Opus fixers, disjoint verticals).
4. Wave 3: redundancy/dead-code removal + module decomposition
   (health.py 1089, api/articles.py 1034, articles-page.tsx 1111) +
   complexity/statement budget burn-down.
5. Full gate battery incl. test_postgres.sh + test_acceptance.sh + build.
6. codex-review.sh cold review; triage; fix cycle (cap 2).
7. Update ledger; report with evidence. NO merge/push without owner ask.

BLOCKERS: none
