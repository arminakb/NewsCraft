# Finding triage template

For every finding in a Codex review, append a block like this to the current
run's triage file (`.orchestrator/runs/<run-id>/triage.md`). No finding may
skip triage, and no finding reaches a fixer without ACCEPTED status.

```markdown
FINDING: <reviewer's location + issue, verbatim>
SEVERITY_CLAIMED: P0 | P1 | P2
SEVERITY_FLOOR_APPLIED: <P1 if it touches auth/privacy/data
  integrity/migrations/contracts/concurrency/idempotency/external
  boundaries, else as claimed>
MY_VERIFICATION: <what I read or ran to check it — file:line, command output>
VERDICT: ACCEPTED | REJECTED | DEFERRED-P2 | NEEDS-EVIDENCE
REASON: <evidence for the verdict, one or two sentences>
DISPOSITION: <fix in this cycle | deferred-p2.md entry | investigator
  dispatched | none>
```

Rules:

- ACCEPTED requires that YOU confirmed the failure mechanism, not just that
  it sounds plausible.
- REJECTED requires evidence of why the reviewer is wrong, not just
  disagreement.
- NEEDS-EVIDENCE must convert to ACCEPTED or REJECTED before the review
  cycle closes — reproduce it or dispatch an opus-investigator.
- DEFERRED-P2 items get one line each in `.orchestrator/deferred-p2.md` with
  the run id and date.
