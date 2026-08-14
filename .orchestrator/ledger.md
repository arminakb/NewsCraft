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

## 2026-08-13 ~15:05 — wave2 partial salvage integrated; gates green; round3 chained batches
- wave2 attempt 2 (wf_6312237a-39c): all 5 fixers again ended without reports (transcripts stop mid-tool-call — subagent context ceiling, nudge arrives too late), BUT commit-per-fix discipline salvaged 6 complete fixes. Inspected all diffs, cherry-picked: eca253e default-deny mutation rules (+route-coverage test), 99e1b8c retention phase-tags + lock release before deletion, 836a9d6 automation failure projection own-transaction, 7fdf8d6 telegram client yield placement, f23b4cf proxy header sanitisation + upstream pin, c6be7c8 editor graph echo reconcile.
- Gates re-run by orchestrator at c6be7c8: backend 1866P/240S + 8/8 CI-guard tests after restoring dev-regenerated next-env.d.ts (pre-existing drift; single failure was that), mypy rc=0, ruff rc=0; frontend vitest 583/583 rc=0 (flaky checklist test passed), tsc rc=0.
- Uncommitted partial work in worktrees (4+1+1+3 dirty files) discarded; worktrees removed.
- Round 3: remaining 194 confirmed items (incl. wave2a P3 batches) split into 35 batches of ≤6, chained per vertical (5 parallel chains, sequential within), each agent resumes from predecessor's last commit sha. Manifest: runs/refactor-2026-08-13/round3/manifest.json.

## 2026-08-13 ~15:45 — ROOT CAUSE of all fixer report failures found and fixed
- Every "fixer finished without a report" across wave2a/wave2/round3 had one mechanical cause, not worker indiscipline: the kit's agent definitions cap maxTurns (fixer 60) — all dead agents show ~60-68 tool uses — and omit StructuredOutput from the tools allowlist, so schema'd workflow calls could never return reports even when agents survived. Fixed all four agent defs: StructuredOutput added, maxTurns raised (fixer/implementer 200, investigator/test-runner 120).
- round3 batch-1 agents (5) each committed real fixes before hitting the cap: 9 commits salvageable across chains (ingest conflict-safe identity/media writes; articles SQL coverage rule; publishing intent namespacing + schedule replay x2; frontend camelize fix + telegram client dedup x2; security shared principal seam x2). Chains relaunch from these salvaged heads with the fixed agent type.

## 2026-08-13 ~16:20 — agentType retired for this session; chains relaunched from salvage
- Attempt with edited agent defs proved the runtime caches agent definitions at session start: fixers still died at cached maxTurns:60 (transcripts cut mid-work; one agent finishing under the cap successfully reported via nudge, confirming the mechanism). Edited defs will bind in future sessions; for THIS session all workflow fixers now run as default subagents (no agentType) with role carried in the prompt.
- Salvaged 10 more commits (chains advanced ~2 each): media SSRF-boundary fetch, deterministic duplicate binding + merge record, readiness clock after heartbeats, model-registry of record + metadata guard, retention preview-token policy module, unified dispatch-provenance walk, source-dependency-count failure no longer swallowed, single authorization seam, filter query serialization, display-timezone date filters.
- Relaunched (wf_b8457128-6f8) from chain heads ingest 9c09fcd / ops 6bc27c8 / publish bebda2a / frontend 8d047c5 / core 069c7a1; batch1 re-runs are idempotent NO_CHANGE_NEEDED sweeps.

## 2026-08-13 ~17:30 — session restart; 52-commit salvage; 7-chain relaunch; lessons exported
- Previous session died mid-round3 (wf_b8457128-6f8). Reconstructed from journal + worktree ancestry: 16 agents ran, 11 structured reports ALL gates_passed=true (default-subagent plumbing works). Chains had advanced 52 commits total: ingest +14 (d60b5b8), publish +12 (cd9650e), frontend +12 (9e1d16e), ops +7 (fdc2ace), core +7 (a651d3e). Chain branches retained; worktrees pruned.
- Relaunched as wf_c0148e94-bb4 with chains starting AT the salvaged tips (idempotent NO_CHANGE sweeps cover re-run batches), plus two NEW chains: wave2c-editorial (35 items, 6 batches, owns content/generation/llm_providers/research-completeness/feed/stories-models/codex_gateway) and wave2c-intent (22 pure-docs sync items, 4 batches, factual-sync-only mandate). 14 items deferred to final round (cross-chain paths). 7 chains ≈ up to 45 agents.
- Owner asked for repo-agnostic lessons: appended sections 9–15 to /home/wingman/code/LESSONS.md (plumbing canary, commit-per-fix salvage, batch sizing/chains, /tmp volatility, INPUT-MISSING honesty, verify-before-fix yield, ownership routing).

## 2026-08-13 ~18:20 — owner pause: chains stopped, integrated, gates green, pushed
- Owner going to sleep; stopped wf_c0148e94-bb4 mid-run (22 reports in). Chain tips at stop: ingest +10 (5e7e25c), ops +11 (6c88151), publish +8 (63d74b2), frontend +7 (ca60b0b), core +3 (dee6789), editorial +8 (c4ad20e), intent +21/COMPLETE (120ec2d) — counts relative to relaunch starts; includes ~120 chain commits total across both runs.
- Merged all 7 chain branches (--no-ff, path-disjoint, zero conflicts): 254 files, +12892/-4569. Full quick gates re-run by orchestrator: backend 1993P/250S, mypy, ruff, vitest 603/603, tsc — ALL rc=0. quality_baseline/--check, postgres, acceptance, build, e2e deliberately deferred to resume (recorded in state NEXT actions).
- All chain worktrees and branches removed (content merged). Resume plan written in state.md.

## 2026-08-14 — sol sweeps integrated; owner pivot to light-gates-only; heavy testing handed off
- All 5 sol vertical sweeps integrated (frontend 37, publish 19, ops 21, editorial 27, ingest 25 FIXED; 5 CNF all ownership-scoped). Merges clean; sol workers cannot commit in sandbox (EROFS) as LESSONS predicted — orchestrator committed after inspection.
- Orchestrator-personal seam fixes: dual alembic heads chained (0036/0037), SCHEMA_HEAD synced, edited-content preservation narrowed to explicit excerpt re-parses, prompt render validation switched to subset semantics (payload metadata is legitimately non-rendered), openapi + generated.ts regenerated, retention-preview test stub aligned to the real RetentionPolicyInput contract, postgres expectations updated (icon fields, principal-derived actor_id, enriched trigger payload).
- Owner (2026-08-14): machine cannot run heavy tests — "lets just clean the repo and fix bugs .. create hand off prompt to do heavy testing later". Heavy battery (postgres/acceptance/build/e2e/cold review) deferred to .orchestrator/HANDOFF-heavy-testing.md. Light gates at b919d0e: backend 2011P/250S, mypy 0, ruff 0, vitest 599/599, tsc 0, ts-unused 0.
- Wave 3 structural cleanup dispatched (3 sol fixers, worktrees w3-{ops,complexity,frontend}): decompose health.py/api-articles.py/source-collections-panel.tsx below 1000 lines; eliminate C901/PLR0915 in the named top-offender files.

## 2026-08-14 — RUN COMPLETE (light-gate scope): repo clean, all fix waves integrated
- w3-split integrated: process_dispatch 815 / publication 989 / route_operations 985 lines; import surfaces preserved via re-exports.
- CLOSING GATES at final head (exit-code-gated): backend pytest 2011P/250S rc=0; mypy rc=0 (299 files); ruff rc=0; quality_baseline.py --check rc=0 (FIRST fully-green run: complexity+statement budgets met, zero ≥1000-line modules, 0 TS-unused); frontend vitest rc=0; tsc rc=0.
- Totals for the run: 372 verified findings dispositioned (Opus chain waves ~120 commits + sol sweeps 109 FIXED + orchestrator seam/migration fixes), 4 oversized modules decomposed, complexity debt burned 71→budget, dead code removed (framer-motion dependency dropped, jobs/news-cards modules deleted), security P1s closed (default-deny mutation rules, SSRF pinning, proxy header sanitization, principal-derived audit actors).
- Heavy verification + sol-max cold review handed off per owner instruction: .orchestrator/HANDOFF-heavy-testing.md. NO merge without owner approval.
