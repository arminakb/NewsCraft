# Automation workflow authoring and recovery

NewsCraft Automations are versioned, backend-owned newsroom workflows. The visual canvas and ordered editor edit the same Workflow Graph v1; neither executes work in the browser. Durable jobs, capability-specific workers, exact revision review, publish receipts, and reconciliation remain runtime truth.

## Author workflow

1. Open `/automations` and choose **New workflow**.
2. Start from a server-managed template. Copies are inactive drafts; template updates never mutate existing workflows.
3. Configure steps with saved resource IDs. Unavailable, disabled, or stale resources remain visible with a repair link. NewsCraft never silently substitutes another resource.
4. Use ordered editor when drag-and-drop is unavailable. Every supported edit has keyboard controls.
5. Save draft. Each save creates immutable `AutomationVersion`; it never edits active or historical version in place.
6. Run server validation. Activation remains disabled until saved version and current resources pass authoritative validation.
7. Use Test Studio for **Validate only** or full dry run. Dry runs skip publication and produce persisted run/node-run truth.
8. Activate only reviewed configuration. Runs pin exact workflow version, graph/plan hash, compiler version, prompt-version IDs, and prompt checksums.

Workflows, versions, runs, and node results deep-link under `/automations`. Jobs and operational attempts stay under `/operations`; exact generated revisions open under `/review/{revisionId}`.

Migrated Telegram route operations remain available under `/automations/telegram`. This compatibility surface owns legacy route creation, cursor details, dry run, pause/resume, backfill, and durable route history; versioned workflow editing remains under `/automations`.

## Supported v1 boundary

Supported families are manual, Feed collection article-added, Telegram new-item, and schedule triggers; deterministic selection/filtering; bounded research; content/package or Telegram generation; fixed validation; Human Review; Save to Drafts; manual Instagram/X/blog packages; and reviewed Telegram publication. Feed collection triggers fire only for a newly inserted article membership and enqueue a version-pinned durable run; repeated membership writes are idempotent.

Not supported: arbitrary HTTP/webhooks, SQL, shell/code, filesystem/environment/credential nodes, unrestricted expressions, loops, recursion, subflows, dynamic tools or permissions, generic branching, and direct Instagram/X/blog publication. Catalog response is authoritative; unavailable node types are hidden or non-activatable.

## Prompt and source-content safety

Prompt policy, operator templates, structured workflow config, persisted source evidence, and operator input keep separate ownership:

- workflows reference prompt-version IDs and SHA-256 checksums, never prompt bodies;
- prompt bodies are governed in Content Settings and resolved by generation services;
- persisted evidence is rendered only into designated evidence fields and is explicitly treated as untrusted data;
- evidence text cannot change graph, destination, credentials, review policy, worker capability, tools, iteration budgets, or publication behavior;
- model output must match bounded platform schemas and deterministic evidence/platform validation before an immutable revision is reviewable;
- exact approval binds revision ID and content hash; only publishing workers can resolve Telegram credentials and send.

Treat any source instruction to ignore policy, reveal secrets, select tools, or publish as source material. Do not copy it into workflow config or prompt governance.

## Template governance

- `system_managed` templates use stable `seed_key` plus monotonically increasing `seed_version`.
- Seed upgrades are idempotent and additive. Never overwrite an existing seed row.
- Duplicating a template creates operator-owned inactive workflow and immutable version 1.
- Safe defaults require review and never enable direct publication.
- Removing or narrowing capability creates new seed version; existing workflows and run snapshots remain interpretable.
- Archive template version instead of deleting historical seed identity.

## Resource change policy

- Draft validation reads current resource readiness.
- New activation and new run start fail closed when required resource is missing, disabled, stale, inactive, or checksum-mismatched.
- Active run keeps saved version and safe resource snapshot; no silent fallback or mid-run prompt substitution occurs.
- Historical graph, compiled plan, IDs, and checksums remain queryable after resource/template changes. Credentials and prompt bodies never enter snapshot.
- Dependency-aware resource deletion must account for Automation definitions and active/running projections.

## Safe errors and recovery

| Symptom/code | Meaning | Recovery |
| --- | --- | --- |
| `automation_resource_unavailable` | Saved resource missing, disabled, stale, or checksum changed | Open linked Settings section, repair or choose explicit replacement, save new version, validate again |
| `automation_version_conflict` | Another editor saved newer revision | Keep local graph, reload server draft or create recovery copy; never overwrite blindly |
| `automation_compiled_plan_stale` | Saved plan does not match current compiler | Disable new activation/run start, preserve version, create repaired forward version |
| `automation_paused` | Workflow or global control paused execution | Inspect pause reason in Operations, resume only after dependency health is ready |
| run `failed` | Durable node/job reached safe terminal error | Follow related Job link; retry through existing job policy when marked retryable |
| run `waiting_for_review` | Exact immutable revision needs operator decision | Open exact revision, review evidence/content hash, approve or reject |
| ambiguous Telegram send | Remote outcome uncertain after crash | Use Telegram reconciliation; never blind-retry publication |

Errors, events, jobs, audit records, and run projections expose stable safe codes/messages only. Never paste raw provider payloads, request headers, stack traces, or credential values into graph notes or incident reports.

## Restart and rollback-forward

Workers recover expired leases through existing retry/idempotency rules. Root run and per-node links preserve version ancestry. Material effects stay guarded by generation idempotency, exact revision hashes, publish intent keys, remote receipts, and reconciliation.

Migration recovery is forward-only:

1. Stop new activation/run start if compiler or projection defect is found.
2. Keep legacy Telegram polling/publishing projection active when safe.
3. Preserve cursors, dispatch ancestry, revisions, publications, workflow versions, and runs.
4. Add corrective Alembic migration or new immutable version; do not downgrade data-bearing Automation migrations in production.
5. Re-run fresh-install, upgrade, PostgreSQL recovery, and browser acceptance gates before re-enabling.

## Release checks

Run `scripts/test_acceptance.sh` for template copy, version-pinned dry run, redacted run projection, exact approval/publication, and crash recovery on disposable PostgreSQL. Run frontend unit/type/build and Playwright gates for keyboard editing, Axe, reduced motion, 5/15/30-node performance, viewport/theme matrix, and same-origin API use. See [Phase 6 report](../implementation-notes/automation-workflow-builder-phase-6.md) for exact evidence.
