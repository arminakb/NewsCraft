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
