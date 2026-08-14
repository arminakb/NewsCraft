TASK_ID: wave2c-intent
BASE_SHA: (chain-managed — your prompt's START_SHA is authoritative)

OBJECTIVE:
Bring the repository's planning/decision documentation back in sync with
the code: stale claims in plan.md, README.md, CONTEXT.md, docs/** where
the CONFIRMED finding shows the doc contradicts current code or records a
completed item as pending (or vice versa). Your batch file (in your
prompt) lists up to 6 items with evidence. FACTUAL SYNC ONLY: correct
what is stale with minimal edits; never make new design decisions, never
delete decision records, never rewrite intent. If an item would require a
design judgment, SKIP it with reason "orchestrator-decision" — the
orchestrator authors those personally.

WORKING_DISCIPLINE (mandatory):
- FIRST ACTION: git reset --hard <START_SHA from your prompt>; confirm.
- Commit after EACH logical doc fix with its own message.
- Already fixed earlier in the chain → NO_CHANGE_NEEDED with sha.
- At ~25% context remaining: stop, commit, report PARTIAL.
- The structured report is mandatory even on failure.

OWNED_PATHS:
- plan.md, CONTEXT.md, README.md, AGENTS.md
- docs/**

PRE_ASSIGNED_IDENTIFIERS: NONE

READ_ONLY_DEPENDENCIES:
- The entire codebase (verify current behavior before correcting a doc).

INTERFACES: N/A (docs only)

INVARIANTS:
- Never touch code, tests, configs, or contracts/ — docs only.
- Preserve decision history: mark superseded decisions as superseded with
  a date rather than deleting them.
- Do not restructure documents; smallest factual correction wins.

DECISIONS_ALREADY_MADE:
- Verdicts final. Cite the code (file:line) justifying each correction in
  your commit message body.

NON_GOALS:
- Any item touching non-doc paths → SKIPPED "sibling-owned path".
- Rewriting plan.md structure or inventing new plan items.

ACCEPTANCE_CRITERIA:
- Every batch item FIXED / NO_CHANGE_NEEDED / SKIPPED with reason.
- git diff --check clean (no whitespace damage).

VERIFICATION_COMMANDS:
- git diff --check  (exit 0)
- git status --porcelain shows only files under OWNED_PATHS

EXPECTED_COMMIT_MESSAGE:
docs: sync <doc> with current <subsystem> behavior

OUTPUT_CONTRACT:
Structured report with head_sha; per-item outcomes keyed by batch refs.
Worktree branch only; never push.
