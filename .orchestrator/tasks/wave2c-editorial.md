TASK_ID: wave2c-editorial
BASE_SHA: (chain-managed — your prompt's START_SHA is authoritative)

OBJECTIVE:
Fix CONFIRMED findings in the editorial vertical: content scoring and
classification, story grouping, feed queries, research/evidence flow,
generation providers and prompt handling, and the codex gateway. Your
batch file (given in your prompt) lists up to 6 items with verdict,
severity, evidence, and a proposed smallest-safe repair. The defects are
confirmed; you may choose a better fix than proposed.

WORKING_DISCIPLINE (mandatory):
- FIRST ACTION: git reset --hard <START_SHA from your prompt>; confirm
  with git log --oneline -1.
- Commit after EACH logical fix with its own conventional message.
- If an item is already fixed by an earlier commit (git log 8d5129a..HEAD),
  report NO_CHANGE_NEEDED with the sha.
- At ~25% context remaining: stop new items, verify, commit, report
  PARTIAL (rest SKIPPED "context-budget").
- The structured report is mandatory even on failure.

OWNED_PATHS:
- backend/app/content/**
- backend/app/generation/**
- backend/app/llm_providers/**
- backend/app/research/** EXCEPT completeness.py
- backend/app/feed/**
- backend/app/stories/** EXCEPT models.py
- backend/app/codex_gateway/**
- backend/tests/** files covering the modules above (create new test
  files freely) — EXCEPT sibling-owned test paths in NON_GOALS

PRE_ASSIGNED_IDENTIFIERS:
- Migration id 0032_wave2c_editorial if strictly required; at most ONE.

READ_ONLY_DEPENDENCIES:
- backend/app/jobs/**, backend/app/automations/**, backend/app/api/**,
  backend/app/core/**, backend/app/ingestion/**, backend/app/stories/models.py,
  backend/app/research/completeness.py (sibling chains own these)
- plan.md, docs/** for intent

INTERFACES:
- Public API responses, job payload shapes, and provider wire formats must
  not change; internal signatures inside OWNED_PATHS may.

INVARIANTS:
- Generation fake-mode/test-provider behavior stays deterministic for tests.
- Never log secrets or provider keys.
- No test may target a real database; use existing disposable-DB fixtures.
- Do not weaken any existing test assertion to make a fix pass.

DECISIONS_ALREADY_MADE:
- Severity floors applied; verdicts final; do not relitigate.

NON_GOALS:
- Items whose paths fall outside OWNED_PATHS (they were routed to sibling
  chains or deferred — skip silently if one slipped into your batch,
  outcome SKIPPED "sibling-owned path").
- Module decomposition beyond what fixes require — Wave 3.
- Sibling-owned test paths: backend/tests/operations/**,
  backend/tests/retention/**, backend/tests/test_models.py, and
  ingestion/sources/media/jobs/automations test files.

ACCEPTANCE_CRITERIA:
- Every batch item FIXED, NO_CHANGE_NEEDED (evidence), or SKIPPED
  (concrete reason). Full backend suite green.

VERIFICATION_COMMANDS:
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m pytest tests -q  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m mypy  (exit 0)
- cd <your worktree>/backend && /home/wingman/code/NewsCraft/backend/.venv/bin/python -m ruff check .  (exit 0)

EXPECTED_COMMIT_MESSAGE:
fix(editorial): <specific defect repaired>

OUTPUT_CONTRACT:
Structured report with head_sha = git rev-parse HEAD; per-item outcomes
keyed by batch refs. Worktree branch only; never push.
