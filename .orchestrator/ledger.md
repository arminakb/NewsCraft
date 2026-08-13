# Orchestration ledger

Append-only history. One dated entry per event: run start, packet dispatch,
worker return, integration, verification, review, triage, fix, PR event,
peer-session agreement, owner ruling, completion. Include SHAs and
command-level evidence, not summaries. `.orchestrator/runs/` is gitignored —
copy key evidence (verdicts, triage results, verification summaries) INTO
this file so it travels. Cross-session agreements are mirrored in the peer
repo's ledger too — say so in the entry.

Entry format:

```
## <UTC timestamp> — <event type>
RUN_ID:
DETAIL:
EVIDENCE:
```

## 2026-08-13T08:55Z — run start + map phase complete
RUN_ID: refactor-2026-08-13
DETAIL: Full-repo refactor ordered by owner. Baseline captured at 8d5129a:
backend pytest 6F/1848P/236S; vitest 2F after npm ci (merge 46b4489 shipped
uninstalled deps framer-motion/@xyflow/react); tsc green after purging
stale .next; quality_baseline all-red (ruff 1, cx 73>53, stmts 36>25,
TS-unused 23, mypy 19, 4 modules >=1000 lines). Map workflow
wf_a03c5b8b-900 (10 Opus agents, 2.29M tokens) produced 361 candidates
(141 bug / 137 redundancy / 83 dead). Owner directives recorded: no Fable
subagents ever; generous OWNED_PATHS.
EVIDENCE: scratchpad gate-*.log; map-digest.json; workflows
wf_5ca07c69-78f (verify, 20 Opus) + wf_79bd1f08-e7d (gate-repair, 2 Opus
worktree fixers) launched.
