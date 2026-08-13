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

## 2026-08-13 ~11:56 — frontend gate verification on integrated branch (3155f34)
- Integrated articles-page test fix verified in full suite: both clear-feed tests green.
- TS unused-code check: 0 findings (gate-tsunused.log, rc=0) — confirms baseline's "23" were environmental tsc errors, since fixed via npm ci + .next purge.
- Full vitest: 577/578; single failure tests/manual-publishing-checklist.test.tsx ("persists canonical checklist progress…") — flaky under parallel load (1609ms vs ~300ms isolated; passes repeatedly in isolation, rc=0). NOT a regression from 3155f34 (untouched file, was green at baseline run). Recorded as CONFIRMED P2 test-flakiness finding in scratchpad map/orchestrator-observed.json for the Wave-2 fix packets.
- Note to self: one flakiness re-check used `tail | …; $status` after a pipe — invalid evidence per guardrails; superseded by exit-code-gated rerun (gate-manualpub.log, rc=0).

## 2026-08-13 ~12:20 — backend gate fix verified + integrated; /tmp-wipe recovery; Wave-2a prep
- Cherry-picked backend fixer commit as 397671c after full-diff inspection. Key production fix: SafeHttpClient no longer falls back to ambient proxy env (restores documented direct_pinned_ssrf pinning; independently confirmed research/safe_fetch.py relies on the pinned default and worker/icon-discovery inject explicit policies). Re-ran gates myself at 397671c: pytest 1854P/238S rc=0, mypy rc=0, ruff rc=0.
- Both gate-repair worktrees + branches removed after integration.
- INCIDENT: /tmp wipe (session restart) destroyed scratchpad map corpus; verify wave wf_5ca07c69-78f returned INPUT MISSING for 13 slices — verifiers correctly refused to fabricate. Recovered all 10 subsystem maps + 7 real verdict sets (item counts match slices exactly) from workflow journals (~/.claude/.../subagents/workflows/*/journal.jsonl). Durable copies now in .orchestrator/runs/refactor-2026-08-13/{map,verify}/. Relaunched verification for the 13 lost slices as wf_6404763c-11d (13 Opus verifiers, durable input paths).
- Recovered verdicts: 143 CONFIRMED (21 P1/60 P2/65 P3). backend-ingest and backend-ops verticals fully verified (bugs+cleanup) → dispatching Wave-2a: 2 worktree-isolated Opus fixers at max effort (concurrency/locking in scope), packets wave2a-ingest (48 items) and wave2a-ops (34 items), zero path overlap (checked programmatically).

## 2026-08-13 ~13:45 — verify complete (372 confirmed), wave2a failure + redispatch, wave2 full dispatch
- verify-r2 (wf_6404763c-11d) returned all 13 lost slices: +229 CONFIRMED (33 P1/100 P2/96 P3), 68 REJECTED. Master list: runs/refactor-2026-08-13/verify/confirmed-all.json (372 confirmed total). Notable new P1s: security middleware mutation_rule default-ALLOW (unlisted mutating routes skip auth/CSRF/audit — sources, collections, drafts, stories, exports...), sources.py except-TypeError swallowing the automation-dependency 409 guard, frontend proxy forwarding hop-by-hop headers.
- One verifier (intent-history-bugs) completed under an unavailable safety classifier — its output treated as ordinary untrusted claims (all verdicts independently re-checked at fix time as usual).
- INCIDENT 2: wave2a fixers (wf_1bd98a85-263) exhausted context without committing or reporting; ops worktree silently on wrong base 46b4489. Discarded ~420 uncommitted lines + 3 orphan files; worktrees/branches removed. Packets hardened (WORKING_DISCIPLINE: base reset, commit-per-fix, 25%-context stop, mandatory report; P3s split out) — recorded as permanent packet-template practice.
- Dispatched wave2 (wf_6312237a-39c): 5 Opus max fixers on disjoint verticals from base 377c805 — ingest 28, ops 22, publish 39, frontend 62, core-security 17 items. Path disjointness verified programmatically before dispatch.
