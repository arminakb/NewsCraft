# ADR 0001: Backend-owned workflow graph and compiler

**Status:** Accepted

**Date:** 2026-08-01

**Decision owners:** NewsCraft maintainers

**Related contract:** [Automation Workflow Builder implementation contract](../implementation-notes/automation-workflow-builder-contract.md)

## Context

NewsCraft already executes a durable, source-grounded Telegram workflow, but its definition is a fixed `AutomationRoute` rather than a general graph. The current runtime separates route capture, research/generation, exact revision review, publish intent, credential-bearing publication, and reconciliation across persisted records and capability-specific workers:

- route and dispatch state: [`automations/models.py`](../../backend/app/automations/models.py#L26);
- durable jobs, events, schedules, leases, retries, and pause state: [`jobs/models.py`](../../backend/app/jobs/models.py#L14);
- capability-specific handler registration: [`jobs/registry.py`](../../backend/app/jobs/registry.py#L52);
- immutable generated revisions and exact review: [`generation/models.py`](../../backend/app/generation/models.py#L207) and [`review_decisions.py`](../../backend/app/generation/review_decisions.py#L19);
- publish-intent and publishing-worker separation: [`process_support.py`](../../backend/app/automations/telegram/process_support.py#L49) and [`publication.py`](../../backend/app/publishing/telegram/publication.py#L620).

A visual editor introduces two risks: allowing a diagram library to become the domain schema, and implying that arbitrary visual connections are executable. Either would weaken the existing validation, review, idempotency, worker-capability, or credential boundaries.

## Decision

NewsCraft will use a backend-owned Workflow Graph v1 and a backend compiler between all editor adapters and the existing durable runtime.

```text
desktop canvas / accessible ordered editor
                    |
                    v
       backend-owned Workflow Graph v1
                    |
                    v
     node registry + graph validation
                    |
                    v
 deterministic supported-plan compiler
                    |
                    v
 existing schedules, jobs, events, workers,
 dispatches, revisions, review, and publishing
```

The decision has these binding parts:

1. **Backend authority.** The backend owns node types, config schemas, typed ports, graph invariants, resource readiness, canonicalization, versioning, compilation, activation, and execution. Client checks are advisory.
2. **Library-independent graph.** Canonical JSON contains stable node IDs, allowlisted business node types/config, typed edges, output IDs, and optional layout coordinates. It contains no React Flow objects, viewport/selection state, credentials, prompt bodies, roles/scopes, code, or arbitrary expressions.
3. **Immutable versions.** Every saved AutomationVersion is immutable. Activation pins an exact version. Every run stores the version, graph hash, compiler version, compiled-plan snapshot, and safe resource snapshot so later edits cannot alter running or historical behavior.
4. **Reject unsupported semantics.** The compiler accepts only registered acyclic shapes with one entry and proven mappings. V1 has no general branch/fallback engine, loop, subflow, dynamic job type, webhook/HTTP, SQL, shell/code, filesystem, or credential node.
5. **Thin orchestration.** A minimal orchestration handler may create run/node-run state, enqueue an allowlisted domain job, and advance after persisted results. It may not fetch sources, call research/model providers, resolve publication credentials, or publish.
6. **Capability ownership remains.** Source workers keep initialization/poll/capture. Generation workers keep research/generation. Only publishing workers resolve Telegram credentials and execute `telegram.publish`. The API validates and enqueues; the browser never executes.
7. **Existing safety boundaries remain.** Global/workflow pause, job leases/retry classes, idempotency keys, exact immutable-revision review, evidence/content hashes, durable publish receipts, and reconciliation are composed, not reimplemented.
8. **Explicit persistence links.** AutomationRun and AutomationNodeRun link to WorkflowJob and domain artifacts with nullable foreign keys where reliable querying needs them. WorkflowEvent remains append-only event truth; JSON payload IDs are not the only relationship.
9. **Legacy projection.** Existing AutomationRoute remains the Telegram new-item runtime projection during migration. A migrated Automation uses the same UUID as its route and preserves route state, cursor, dispatch, revision, publish-job, publication, and URL ancestry.
10. **Replaceable editor adapters.** A desktop diagram and an ordered accessible editor both translate through a NewsCraft adapter into the same graph. Changing or removing the diagram library cannot change stored definitions or server execution.

## Schedule and trigger consequence

`WorkflowSchedule` already enqueues its stored job type and payload with a due-time-derived idempotency key ([source](../../backend/app/jobs/scheduler.py#L136)). A Schedule node will therefore target the allowlisted `automation.run.start` job directly; it does not materialize a Telegram route. A scheduled graph must still compile to deterministic input selection.

Telegram new-item remains different: `AutomationRoute` owns activation boundary, polling cursor, source-edit lookback, and next-poll state. Its runtime projection remains required until a future source-trigger abstraction proves equivalent safety.

## Consequences

### Positive

- Definitions can round-trip through OpenAPI and TypeScript without depending on one frontend library.
- Unsupported visual shapes fail before activation with stable node-addressed errors.
- Existing retries, idempotency, review, publication, and reconciliation remain the runtime source of truth.
- Runs remain reproducible after workflow, prompt, provider, profile, or destination changes.
- Desktop, mobile, keyboard, and assistive-technology editors share one contract.
- The diagram dependency can be upgraded or replaced without a data migration.

### Costs

- The registry, validator, canonicalizer, compiler, run persistence, and adapters add backend work before a rich canvas is useful.
- Some visually common workflow concepts remain unavailable until a safe persisted executor exists.
- Legacy route adapters and generalized workflow APIs must coexist through a measured migration period.
- Layout-only edits create a new immutable version under the simple v1 canonical hash policy.

## Security and failure behavior

- New API mutations use the centralized application-principal and `automations:write` boundary; reads use explicit read scopes. Browser-supplied principal/scope headers remain ignored.
- Config accepts resource UUIDs and bounded policy only. Resource secrets are resolved inside their current capability owner, never copied into graphs, runs, events, or browser responses.
- Compiler and orchestrator errors are redacted and stable. Domain errors retain their current code/class and gain only safe node context.
- If a compiler release is faulty, new activation/run start is disabled while legacy projections continue. Persisted graph versions remain intact and are repaired forward; cursors or publication ancestry are never rolled back.

## Alternatives considered

### Persist React Flow nodes and edges

Rejected. Library state includes presentation/transient concerns, does not define NewsCraft resource or execution safety, and would couple backend data to a replaceable UI package.

### Execute the graph in the browser

Rejected. It would bypass durable jobs, restart recovery, capability isolation, centralized authorization, exact review, credential containment, and auditable idempotency.

### Add a general expression/branch engine now

Rejected. Current filters support deterministic pass-or-stop behavior, not persisted alternative-edge semantics. A general evaluator would be new execution architecture rather than an adapter over proven behavior.

### Convert AutomationRoute into the canonical graph

Rejected. The row combines Telegram-specific configuration and runtime cursor state. Keeping it as a projection preserves live behavior while the new definition model stays channel-independent.

### Replace the current job engine

Rejected. WorkflowJob, WorkflowEvent, WorkflowSchedule, leases, pause/retry, worker registries, and idempotency already provide the required durable substrate. The compiler should deepen and compose this module instead of duplicating it.

## Acceptance

Accepted after implementation and Phase 6 verification of frozen node catalog, deferrals, legacy migration/recovery, run-artifact links, PostgreSQL execution, browser adapters, and credential boundaries. Migrations 0027–0028 and `@xyflow/react@12.11.2` implement this decision without changing backend ownership.
