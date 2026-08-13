# Task packet template

Copy into `.orchestrator/tasks/<TASK_ID>.md` and include the complete
packet verbatim in the worker invocation (or an absolute path the worker
can read). Every field is mandatory — "NONE" is an acceptable value, an
absent field is not. Set BASE_SHA to the current integration-branch HEAD,
spawn the worker from it, and only THEN commit the packet together with the
dispatch state and ledger entry (committing first would advance HEAD past
BASE_SHA and the worker would correctly return BLOCKED).

```markdown
TASK_ID: <plan id>
BASE_SHA: <committed sha the worker must branch from>

OBJECTIVE:
<one paragraph: what to build and the user-visible outcome>

OWNED_PATHS:
- <glob or path the worker may modify>
- <its test paths>

PRE_ASSIGNED_IDENTIFIERS:
- <migration/sequence numbers, registry slots, route names the
  orchestrator has reserved for THIS packet — parallel workers must never
  pick their own; write NONE if none apply>

READ_ONLY_DEPENDENCIES:
- <files the worker must read but never modify>

INTERFACES:
- <endpoints/functions/events this task implements or consumes, exactly>

INVARIANTS:
- <things that must remain true: tenant isolation, response envelopes,
  idempotency, backward compatibility, read-only external boundaries...>

DECISIONS_ALREADY_MADE:
- <approved contract changes, lock orderings, prior-round choices the
  worker must not relitigate; NONE if empty>

NON_GOALS:
- <adjacent work the worker must NOT do, including paths owned by sibling
  workers running concurrently>

ACCEPTANCE_CRITERIA:
- <observable, testable outcomes; boundary-level behavior must be proven
  through the real boundary, not an adapter in isolation>

VERIFICATION_COMMANDS:
- <exact commands the worker must run, exit-code gated>

EXPECTED_COMMIT_MESSAGE:
<conventional commit message>

OUTPUT_CONTRACT:
Return the standard opus-implementer report with the resulting commit SHA
(commit only to your exclusive worktree branch; never push or open a PR).
```

Most multi-agent failures are packet failures: ambiguous ownership, missing
invariants, unstated non-goals, unassigned scarce identifiers. If a worker
returns BLOCKED or violates scope, fix the packet before blaming the worker.
