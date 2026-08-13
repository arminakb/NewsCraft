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
PHASE: verify+gate-repair (parallel)
INTEGRATION_BRANCH: agent/finish-refactor-plan
BASE_SHA: 8d5129a (merge of origin/main 46b4489 + orchestrator kit)
CURRENT_HEAD_SHA: see git log (rules commit on top of 8d5129a)
PR: none
MERGE_POLICY: never merge without explicit user approval for the exact PR.

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

ACTIVE_WORKERS:
- workflow wf_5ca07c69-78f "verify-newscraft-findings": 20 Opus verifiers
  over map digest slices in scratchpad/map/ (read-only, main checkout).
- workflow wf_79bd1f08-e7d "gate-repair": 2 Opus fixers, worktree-isolated:
  fix:backend-gates owns backend/**, fix:frontend-gates owns frontend/**.

INTEGRATION_QUEUE: (gate-repair worktree branches, pending diff inspection)

PER_PR_STATE: none

VERIFICATION_EVIDENCE: baseline logs in session scratchpad gate-*.log

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
