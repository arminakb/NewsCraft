# .orchestrator/

Working state for the Fable orchestration run.

- state.md / ledger.md / deferred-p2.md / tasks/ — TRACKED in git (cross-
  machine continuity depends on them; commit with `chore(orchestrator):`).
- runs/ — gitignored; per-run review/fix artifacts (review.json, fix.json,
  events, prompts, meta). Copy anything that matters into ledger.md.
- prompts/ — templates materialized by the scripts. Fill the marked
  per-project spots once ({{PROJECT_FULL_GATE}}, {{ENV_CONSTRAINTS}});
  the remaining {{…}} tokens ({{BASE_SHA}}, {{HEAD_SHA}},
  {{REQUIRED_TESTS}}, {{COMMIT_MESSAGE}}, {{ACCEPTED_FINDINGS}},
  {{DECISIONS_ALREADY_MADE}}) are filled per run/packet at dispatch.
- scripts/ — invoke the MAIN checkout's copy by absolute path from inside
  the worktree whose diff you target (they self-locate prompts/schemas
  and write runs/ under the kit, not the target worktree).
- test.md — the Opus-vs-Codex fixer bake-off protocol and results log.

Remember to add `.orchestrator/runs/` to the repo .gitignore at install.
