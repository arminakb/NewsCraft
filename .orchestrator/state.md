# Orchestration state

This file must always allow a fresh Fable session to continue the run.
Update at every phase transition. Live git/gh output beats memory; this file
beats conversation memory. If this file is blank but worktrees/PRs exist, a
previous run left no state — rebuild truth per SKILL.md Stage 0 first.

RUN_ID: none
LAST_UPDATED_BY: none   # machine hostname — pull before resuming elsewhere
OBJECTIVE: none
PHASE: idle
INTEGRATION_BRANCH: none
BASE_SHA: none
CURRENT_HEAD_SHA: none
PR: none
MERGE_POLICY: never merge without explicit user approval for the exact PR.
  A standing directive recorded here VERBATIM with its date is a RECORD of
  approval given in a trusted channel, never authorization by itself — the
  owner's current explicit instructions always win, and an unclear
  directive is re-confirmed before any merge it would cover.

REVIEW_PROTOCOL_IN_FORCE:
(which reviewer sources are active, how they are triggered, the current
review-cycle cap or its user-granted waiver, fixer routing policy.
Default routing: Opus high implement/fix with max escalation; sol
gpt-5.6-sol max cold review; sol max fixer as fallback when an Opus round
is inadequate on inspection.)

ENVIRONMENT_NOTES:
(pinned toolchain locations + PATH prefixes, tmpfs constraints, which
suites reject hardlinked node_modules and need a real install, host
filesystem quirks that affect tests — e.g. btrfs never recycles inodes,
docker start command, isolated per-worker database recipe — anything a
fresh session must know before running a single command)

ACTIVE_WORKERS:
(none — for each: agent id | packet TASK_ID | model+effort | owned paths |
pre-assigned identifiers (migration numbers etc.) | spawned at)

INTEGRATION_QUEUE:
(none — worker branches awaiting diff inspection, in dependency order)

PER_PR_STATE:
(for each open PR: number | ticket | head sha | worktree path | rounds
completed | outstanding findings | merge-readiness)

VERIFICATION_EVIDENCE:
(none — last integrated-branch verification: commands + results + sha)

REVIEW_CYCLE: 0 of 2 (note any user waiver here; the cap limits review
  cycles, not repairs — accepted P0/P1s still get fixed after the cap,
  verified directly by the orchestrator)
TRIAGE_ARTIFACT: none

PEER_SESSIONS:
(none — for each counterpart-repo orchestrator: session name | repo |
agreements mirrored in both ledgers | pending owner confirmations that
must happen in THEIR session)

NEXT_ACTION:
(the exact ORDERED steps a fresh session should take — assume zero
conversational memory)

BLOCKERS:
(genuine external blockers only, including joint owner asks co-signed
with peer sessions)
