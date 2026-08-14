# Fixer bake-off: Opus (high) vs Codex gpt-5.6-sol (max)

Purpose: decide fix-routing with data instead of habit. Default routing:
Opus high is the default fixer (max for cross-cutting/concurrency); sol/max
is the fallback when an Opus round is judged inadequate on inspection or by
the verification review. Run this bake-off the first time a review round
produces 2+ comparable ACCEPTED findings, then rerun occasionally as models
change. Results go in the table at the bottom; the winner becomes the
default for that fix category in SKILL.md Stage 8.

## Protocol

1. Pick a finding set: 1–3 ACCEPTED findings of the SAME category
   (mechanical/scoped, or cross-cutting/concurrency). Both arms get the
   identical packet text (finding bodies + environment constraints + the
   same mandatory gates + the same relevant-test list + the same
   pre-assigned identifiers).
2. Prepare two clean worktrees from the SAME base commit:
   - `git worktree add ../fix-arm-opus <BASE_SHA>`
   - `git worktree add ../fix-arm-codex <BASE_SHA>`
3. Dispatch both arms in parallel:
   - **Opus arm**: spawn the `opus-fixer` agent (model claude-opus-5,
     effort high) with the packet, worktree = fix-arm-opus.
   - **Codex arm**: `.orchestrator/scripts/codex-fix.sh ../fix-arm-codex
     <packet-file> <BASE_SHA> <run-id>` with CODEX_FIX_EFFORT=max (the
     default; the script refuses a dirty worktree, the main checkout, or a
     HEAD that is not exactly BASE_SHA).
4. Record for each arm:
   - WALL_CLOCK: dispatch → report (from your ledger timestamps).
   - TOKENS: Opus — subagent usage report from the task notification;
     Codex — sum token counts from
     `.orchestrator/runs/<run-id>/fix-events.jsonl` (each event carries
     usage) or the final usage line in fix-stderr.log.
   - GATES: did the packet's gates pass on YOUR re-run (not their claim)?
     Sandboxed arms often cannot reach databases or bind listeners —
     distinguish sandbox-blocked from failing.
   - DIFF_QUALITY (you judge, after full inspection): scope discipline
     (only implicated files?), smallest-safe-repair (or over-engineered?),
     regression-test quality (does the test fail without the fix? does it
     cross the REAL boundary?), idiom match with surrounding code.
   - REVIEW_VERDICT: from inside EACH arm's worktree, run the MAIN
     checkout's `.orchestrator/scripts/codex-review.sh <BASE_SHA> <run-id>`
     by absolute path with DISTINCT run-ids; count findings the reviewer
     raises against each fix.
5. Integrate the WINNING diff only (or merge the best parts, noting it).
   Remove both bake-off worktrees afterward.

## Scoring

Winner per axis; overall winner needs quality ≥ tie AND (faster OR
cheaper). Quality beats speed and cost — a fast wrong fix costs a full
review round (~30+ min wall clock plus a reviewer pass).

## Results log

| date | repo | category | findings | arm | wall clock | tokens | gates | review findings vs fix | quality notes | winner |
| ---- | ---- | -------- | -------- | --- | ---------- | ------ | ----- | ---------------------- | ------------- | ------ |
|      |      |          |          |     |            |        |       |                        |               |        |

## Prior evidence

**Run 1 (2026-08-11, Codex-only, no Opus arm):** gpt-5.6-sol at xhigh fixed
~95 verified findings across ~15 rounds; ~90% of diffs accepted after
inspection without modification; typical scoped fix 3–8 min wall clock;
failure modes were targeted-test-only gating and occasional formatter
skips — hence the mandatory-gate lines in every packet.

**Run 2 (2026-08-13, sequential rounds, not a parallel bake-off):** Round 1:
three parallel Opus fixers (2× max, 1× high) on 4 verified P1s — all
returned DONE with fails-without-fix mutation proofs and clean scope, BUT
the cycle-2 sol/max verification review found 5 real seams in the round:
an idempotency key that never crossed the real server normalization (the
fixer tested the adapter directly), non-atomic quota/workflow transactions,
a 409 path that delayed rather than prevented a duplicate, an unlocked
recheck race, and an over-permissive legacy-shape normalizer. Round 2:
sol/max fixer closed all five cleanly in one pass (21 files) — its only
defect was a hanging regression test caused by a test-harness idempotency-
key collision, which an Opus max debug round diagnosed and repaired.
LESSONS ENCODED IN v3: mandate real-boundary regression tests in packets;
pre-assign migration numbers (both arms independently minted the same
number); the verification review is what converges quality — each arm
catches the other's seams; sandbox-blocked gates are not failures.
