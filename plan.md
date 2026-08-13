# NewsCraft Guided Visual Workflow Builder

## Six-Phase Production Implementation Plan

## 1. Plan status and intent

- **Purpose:** Transform the existing Telegram-focused Automations area into a production-ready, guided visual workflow builder for reusable news-generation and publishing workflows.
- **Canonical product area:** `/automations`.
- **Implementation shape:** Six ordered phases with independently verifiable exit gates.
- **Primary product principle:** A domain-specific **Guided Visual Workflow Builder**, not a general-purpose no-code platform.
- **Architecture principle:** The canvas is an editor for a backend-owned definition. It never becomes a browser-side workflow runtime.
- **Reference image:** `ref/26cbe0a6-85f9-44d6-bd4d-3f085e9080dd.png` (1536×1024) — **artifact not retained.** The `ref/` directory was never tracked and is absent from the tree and from Git history, so this input cannot be re-read. It was inspiration for hierarchy, panel composition, node legibility, and responsive adaptation only; the shipped editor is the reference for those now.
- **Completion rule:** The work is not complete if the frontend is still mocked, a dry run can publish, a graph bypasses durable jobs, or PostgreSQL/browser acceptance has not exercised the real path.

This plan is based on the current checkout, including its existing uncommitted work. Every implementation phase must preserve unrelated changes and must not rewrite applied migrations.

### Phase status

Update this table at each phase exit gate. It is the only status record in
this plan; the evidence column owns the detail.

| Phase | Status | Evidence |
| --- | --- | --- |
| 1 — Architecture audit and contract freeze | Complete | [`automation-workflow-builder-contract.md`](docs/implementation-notes/automation-workflow-builder-contract.md) — "Accepted and implemented through Phase 6" (2026-08-01) |
| 2 — Canonical workflow domain, versioning, templates, APIs | Complete | same contract; Phase 6 Dependencies below record Phases 1–5 as complete with no mocked runtime seams |
| 3 — Compiler, durable execution, dry run, activation, worker integration | Complete | same contract; Phase 6 Dependencies below |
| 4 — Workflow library, templates, guided visual builder, responsive accessibility | Complete | same contract; Phase 6 Dependencies below |
| 5 — Test Studio, Runs, version history, Operations links, Draft seam | Complete | [`automation-workflow-builder-phase-5.md`](docs/implementation-notes/automation-workflow-builder-phase-5.md) — "Implemented on 2026-08-01" |
| 6 — Security, prompt safety, performance, compatibility, release acceptance | Exit gate passed; quality-baseline debt open | [`automation-workflow-builder-phase-6.md`](docs/implementation-notes/automation-workflow-builder-phase-6.md) — "Phase 6 release exit gate passed on 2026-08-01. The repository-wide quality-baseline gate remains blocked by inherited Phase 1–5 complexity and file-size debt" |

---

## 2. Existing architecture findings

> **Pre-implementation snapshot (recorded before Phase 1; annotated
> 2026-08-13).** Everything in section 2 describes the checkout *as it was
> when the plan was written* and is no longer an accurate description of
> the code. It is retained as the record of what the six phases started
> from. The binding parts of this plan are sections 3, 4, 5 and 6 — read
> those, not this one, for current obligations. Individual statements that
> are now demonstrably false are corrected in place below.

### 2.1 Backend and persistence already in place

NewsCraft already has a strong execution spine that should be extended rather than replaced:

- `AutomationRoute` in `backend/app/automations/models.py` is the current Automation definition. It is Telegram-specific and directly stores source, destination, editorial/brand profile, prompt version/policy, provider profile, filters, research policy, media policy, publishing policy, polling, retry, cursor, enabled, and pause state.
- `AutomationDispatch` is the current per-source-item execution/provenance record. It links a route to the captured source item, story revision, generation run, generated platform revision, publish job, and safe failure state.
- `WorkflowJob`, `WorkflowEvent`, `WorkflowSchedule`, `AutomationControl`, and `RuntimeHeartbeat` in `backend/app/jobs/models.py` provide durable queues, events, schedules, global pause/dry-run controls, worker observations, retries, leases, progress, and stable idempotency keys.
- `Scheduler.tick()` in `backend/app/jobs/scheduler.py` materializes due source schedules and due ready Automation routes as jobs. It respects global pause, capability readiness, row locks, and deterministic idempotency keys.
- `JobHandlerRegistry` in `backend/app/jobs/registry.py` enforces capability separation:
  - source handlers own `telegram.route.initialize`, `telegram.route.poll`, `telegram.route.backfill`, and `telegram.route.dry_run`;
  - generation handlers own `telegram.route.process`, content-pack generation/regeneration, exports, and retention;
  - the publishing worker alone owns `telegram.publish` and Telegram destination/proxy checks.
- Generation already persists `GenerationRun`, `GenerationAttempt`, `ContentPack`, `PlatformVariant`, and immutable `PlatformVariantRevision` records with evidence, validation results, approval state, prompt snapshots, model identity, and usage.
- Exact approval and publishing already bind to a specific revision ID and content hash. The publishing boundary uses durable `PublishJob`, operation receipts, payload hashes, idempotency, reconciliation, and `Publication` records.
- `LLMProvider` is the current operator-managed provider model. It writes through to a same-ID `AIProviderProfile` compatibility projection used by the existing runtime. Secrets remain encrypted and outside Automation definitions.
- `BrandProfile` is the persistence name for the user-facing Editorial profile concept. Automation routes already keep an explicit profile ID.
- Prompt templates have immutable `PromptTemplateVersion` rows with checksum and activation audit metadata.
- Telegram destinations carry readiness, administrator, health, optional proxy, dependency, and encrypted-secret state.
- `ApplicationPrincipalResolver`, the mutation middleware, and the existing scope registry already define `automations:*`, `jobs:*`, `providers:*`, `destinations:*`, and `prompts:*`. The same-origin Next.js proxy strips client-supplied principal/scope headers.

### 2.2 Current end-to-end Automation execution

The current Telegram route is a fixed, durable pipeline rather than an arbitrary graph:

```text
Activation request
  → POST /telegram/automations/{route_id}/activate
  → telegram.route.initialize job
  → source worker records a new-only cursor boundary
  → scheduler detects a due, enabled, unpaused, ready route
  → telegram.route.poll job
  → source worker fetches and captures stable source evidence
  → AutomationDispatch is created idempotently
  → telegram.route.process job
  → generation worker optionally researches and generates
  → GenerationRun / GenerationAttempt / ContentPack / PlatformVariant
  → immutable PlatformVariantRevision with evidence and validation
  → pending exact human review by default
  → operator approves an exact revision and content hash
  → durable Telegram publish intent and telegram.publish job
  → publishing worker resolves worker-scoped credentials and sends
  → publish receipts, Publication, WorkflowEvents, and safe outcome
```

Dry runs enter through a durable `telegram.route.dry_run` job, carry `force_review=true`, remain cursor-independent, mark the generated content as dry-run material, and do not create a live publication path.

### 2.3 Existing capability map

| Requested concept | Current support | Plan treatment |
| --- | --- | --- |
| Manual execution | Supported through API-enqueued durable jobs | Expose as a Manual trigger and Test Studio dry run |
| Feed/content trigger | Supported for Telegram polling/capture; generic content events are not a graph runtime | Adapt the proven Telegram route trigger first; add other triggers only after Phase 1 evidence |
| Schedule | Supported by `WorkflowSchedule` and the scheduler | Compile a Schedule trigger to durable schedule rows |
| Content filtering | Existing route filters plus Content Item score, canonical content type/topic/language, rewrite readiness, and media fields | Add an allowlisted deterministic filter node |
| Research | Existing bounded durable research and route research modes | Add a bounded Research node using ready provider profiles |
| Generation | Existing canonical/package generation and platform variants | Add schema-bound Generate nodes using current services/jobs |
| Validation | Existing schema, evidence, media, and platform validation | Expose deterministic checks first; label AI evaluation separately |
| Human review | Existing exact immutable-revision approval | Make it a first-class node and retain review-first defaults |
| Draft output | Existing content packs and platform revisions; current UI deep-link is `/review/{revisionId}` | Add Save to Drafts semantics and generated-revision links without redesigning Drafts |
| Telegram publishing | Existing reviewed, idempotent publishing-worker boundary | Compile only approved publish intents to the current boundary |
| Instagram/X/blog | Existing manual content-package/export/checklist flow | Output manual packages only; never imply direct publication |
| Branching/conditions | Content-filter decisions exist, but no general persisted branch executor exists | Defer general branching; allow only a compiler-proven terminal fallback path if Phase 1 validates it |
| Multiple outputs | Content packs can contain multiple platform variants | Support bounded terminal package outputs, not arbitrary fan-out |
| Loops/subflows/webhooks/HTTP/code | Not safely supported | Explicitly out of scope |
| Workflow versions | Prompt/revision immutability exists; Automation definitions themselves are mutable rows | Add immutable Automation versions and active-version pinning |
| Run and node-run projections | Jobs, events, dispatches, generation runs, and publications exist but are fragmented | Add Automation Run/Node Run projections linked to existing truth |
| Templates | No canonical workflow-template model | Add safe versioned seeds with ownership and idempotent upgrades |

### 2.4 Frontend already in place

- Next.js 16 App Router, React 19, TypeScript 5.9, TanStack Query 5, Tailwind CSS 4, Base UI/shadcn primitives, and Lucide icons are already established.
- The current pages are `/automations`, `/automations/new`, `/automations/[routeId]`, and `/automations/[routeId]/history`. *(Snapshot only. The shipped tree also has `/automations/runs`, `/automations/templates`, and the `/automations/telegram/**` compatibility subtree.)*
- Current Automation UI consists of a Telegram route card list, a long form that creates a source and route, a route detail page, dry run/backfill actions, dispatch history, and a history timeline.
- The Automation API client and query keys are Telegram-route-specific. They already use the same-origin `/api/backend/...` path through `apiRequest`.
- Reusable primitives already exist for Button, Card, Dialog, Tooltip, Table, Badge/StatusBadge, Alert, inputs, Select, progress, skeleton/loading/error/empty states, page headers, dirty-navigation handling, and notices.
- `ProviderBrandIcon` and the Content Settings Telegram destination cards can be reused for safe resource presentation.
- There is no current repository UI primitive for Tabs, Sheet/Drawer, Menu, or a schema-generated Form, and there is no diagram dependency in `frontend/package.json`. *(Snapshot only. `frontend/package.json` now pins `"@xyflow/react": "12.11.2"`, added by the builder canvas work; see [`automation-workflow-builder-xyflow-decision.md`](docs/implementation-notes/automation-workflow-builder-xyflow-decision.md).)*
- Existing Automation tests cover safe options, conservative review defaults, dry-run durability messaging, pause/resume, prompt pinning, destination readiness, and browser flows. The current Playwright mock backend already models Telegram Automation routes and can be extended rather than replaced.

### 2.5 Gaps that the implementation must close

*(Snapshot only. These gaps were closed by Phases 1–6 — `backend/app/automations/definitions/` now holds the node registry, compiler, execution, and versioned workflow models, and the frontend has the library, Templates and Runs views. Kept as the record of what the phases were commissioned to fix; per the Phase status table above, the remaining open item is quality-baseline debt, not these gaps.)*

1. The current `AutomationRoute` cannot represent a versioned node graph.
2. Current route mutation means active and historical executions are not pinned to an immutable Automation version.
3. Current options return mostly ready resources; the builder also needs unavailable/disabled/stale resources so saved references can remain visible and actionable.
4. The current frontend assumes a fixed Telegram form and has no workflow library, Templates view, generalized Runs view, node registry, inspector schema, or mobile ordered editor.
5. Existing history joins events/jobs/dispatches, but it does not provide a first-class Automation Run with node-level execution state.
6. Current `follow_active` prompt policy is a legacy behavior. New workflow versions must pin exact prompt versions; legacy rows need a compatibility policy rather than silent semantic change.
7. The current Content Settings UI does not expose every persisted resource uniformly. Phase 1 must resolve the exact Editorial profile management surface before the builder links to it.
8. Existing auto-publish capability must not become a template default or a shortcut around exact review and safety gates.

---

## 3. Target architecture

### 3.1 Definition, compiler, and runtime separation

```text
React Flow desktop adapter / accessible ordered editor
                    │
                    ▼
       backend-owned Workflow Graph v1
   (stable IDs, typed ports, validated configs)
                    │
                    ▼
       node registry + graph validator
                    │
                    ▼
   compiler to a supported executable plan
                    │
                    ▼
existing durable jobs, events, schedules, workers,
dispatches, generation artifacts, review, and publishing
```

The browser may prevent obvious invalid connections, but the backend is authoritative for graph shape, configuration, readiness, activation, and execution.

### 3.2 Proposed persistence model

Exact table names should be finalized in Phase 1, but the contract must contain these concepts:

- **Automation** — stable workflow identity, name, description, lifecycle, ownership, active version pointer, editable draft version pointer, archived timestamp, optimistic-concurrency token, and timestamps.
- **AutomationVersion** — immutable version number, schema version, canonical graph JSON, normalized content hash, compiler version, compiled-plan snapshot, validation summary, creation actor/reason, and timestamps. An active version is never edited in place.
- **AutomationRuntimeProjection** — optional link from a version to the existing Telegram `AutomationRoute`/schedule projection. Existing `AutomationRoute` remains the execution adapter during compatibility migration rather than becoming the graph schema.
- **AutomationRun** — workflow/version IDs, trigger kind/metadata, dry-run flag, status, current node, root workflow job, safe resource snapshot, started/finished timestamps, Draft/revision/publication links, and safe error fields.
- **AutomationNodeRun** — run ID, stable node ID, attempt, status, linked workflow job/generation/research/publish records, timing, redacted input/output summaries, evidence references, usage/cost when reliable, and safe error/retry metadata.
- **AutomationTemplate** — stable seed key/version, ownership (`system_managed` or `operator_managed`), graph seed, description, complexity, supported-capability requirements, and archived state.
- **Explicit foreign keys** from jobs/dispatches where reliable queries require them; do not depend exclusively on IDs hidden in JSON payloads.

Required database behavior:

- one active version pointer per Automation;
- unique version numbers and normalized graph hashes per Automation;
- immutable active/archived version rows;
- run and node-run indexes for workflow, status, time, dry-run/live, and linked job;
- dependency-aware resource deletion extended to Automation versions and active/running snapshots;
- idempotency keys for version save, activation, template duplication, run start, per-node execution, and publish intent;
- safe forward migration of every existing `AutomationRoute` into a legacy-compatible Automation/version without changing its cursor, pause state, next poll, dispatch ancestry, or URL reachability.

### 3.3 Workflow Graph v1

The canonical JSON must be business-oriented and independent of React Flow:

```json
{
  "schema_version": 1,
  "entry_node_id": "trigger-1",
  "nodes": [
    {
      "id": "trigger-1",
      "type": "manual",
      "config": { "story_revision_id": "..." }
    }
  ],
  "edges": [
    {
      "source_node_id": "trigger-1",
      "source_port": "content",
      "target_node_id": "filter-1",
      "target_port": "content"
    }
  ],
  "output_node_ids": ["draft-1"],
  "metadata": {
    "layout": {
      "trigger-1": { "x": 80, "y": 120 }
    }
  }
}
```

Rules:

- stable, opaque node IDs;
- allowlisted node types and config schemas;
- typed ports and compatibility rules;
- one entry node in v1;
- no cycles or unrestricted expressions;
- bounded node and edge counts appropriate to 5-, 15-, and 30-node workflows;
- graph layout metadata may be stored, but library-specific node/edge objects and transient selection/viewport state are not canonical business data;
- configs contain resource IDs and safe bounded policy, never credentials, prompt text copies, authorization headers, or environment details;
- new workflow versions pin prompt-version IDs and the compiler records prompt checksums;
- the backend returns stable node-addressed errors and warnings.

### 3.4 Initial node catalog

The server node registry determines what is visible. The Phase 1 capability matrix may narrow this list further.

| Family | V1 nodes | Runtime mapping |
| --- | --- | --- |
| Trigger | Manual; Collection article added; New Source Item; Schedule | API-enqueued run; collection/source events; `WorkflowSchedule` |
| Select/filter | Content filter using allowlisted score, canonical content type/topic/language, rewrite readiness, source, term, media, and max-count fields | Deterministic backend query/filter service |
| Research | AI Research (optional, bounded) | Existing durable research provider/service and evidence snapshot |
| Generate | Generate content/package with bounded multi-platform variants | Existing canonical/package generation handlers and platform schemas |
| Validate | Evidence, required fields, length/platform format, source attribution, media requirement, duplicate guard where already implemented | Existing deterministic validators; bounded model evaluation only when explicitly labeled |
| Review | Human Review | Exact immutable revision approval state |
| Output | Save to Drafts; Telegram publish after approval; manual Instagram/X/blog package | Existing content pack/revision, Telegram publish boundary, and manual export/checklist flow |

General conditions, fallback branching, delays, run-until-node, isolated-node retries, and comparison are included only if Phase 1 proves a safe existing execution mapping. The canonical, exhaustive list of what the API must reject is “Explicit deferrals and prohibited nodes” in [`automation-workflow-builder-contract.md`](docs/implementation-notes/automation-workflow-builder-contract.md#explicit-deferrals-and-prohibited-nodes); it governs on any disagreement with this plan.

### 3.5 Diagram-library decision

Use `@xyflow/react` as a **client-only, controlled desktop/tablet presentation adapter**, subject to a short compatibility spike in Phase 4. Its official API supports controlled nodes/edges, custom nodes and typed handles, viewport/zoom/snap controls, focusable nodes/edges, keyboard selection/movement, ARIA customization, and visible-node rendering. The package and lockfile must be pinned together.

Constraints on its use are recorded, in a form written after the spike and superseding the planning list, in [`automation-workflow-builder-xyflow-decision.md`](docs/implementation-notes/automation-workflow-builder-xyflow-decision.md) — "Intended adapter boundary", "Phase 4 spike gates", and "Rejected uses". That document governs on any disagreement with this plan.

If the spike fails React 19/Next 16 compatibility, keyboard/assistive-technology acceptance, light/dark theming, or 30-node performance, implement the same adapter interface with a custom constrained ordered canvas. The backend graph and all APIs remain unchanged.

Relevant official evaluation sources:

- https://reactflow.dev/learn
- https://reactflow.dev/api-reference/react-flow
- https://reactflow.dev/learn/advanced-use/accessibility
- https://reactflow.dev/learn/advanced-use/ssr-ssg-configuration

### 3.6 Visual direction from the reference

Adopt the reference’s useful product ideas:

- strong Automations header and a single primary action;
- Workflows, Runs, and Templates as clear top-level views;
- desktop three-panel builder with a legible center canvas and a collapsible bottom Test Studio;
- visually distinct node families, compact resource summaries, readiness state, and an inspector that uses progressive disclosure;
- clear Save, Test, and Activate hierarchy;
- vertical mobile workflow cards rather than a compressed free-form canvas;
- restrained canvas controls and optional minimap only for larger graphs.

Do not copy its pixels, palette, unsupported features, or concept-art density. Preserve NewsCraft’s current typography, radii, semantic light/dark tokens, navigation, Buttons, status badges, Lucide icon language, and responsive shell. Use semantic node accents—green trigger/success, purple AI/editorial, blue deterministic checks, amber output/publishing, red blocking failure, neutral skipped/inactive—with icon/text/status shape so color is never the sole signal. Avoid neon glow, animated edges by default, tiny text, nested border noise, decorative metrics, and raw JSON.

---

## 4. Six implementation phases

## Phase 1 — Architecture audit and contract freeze

### Goal

Create a verified implementation contract that distinguishes reusable runtime capability from requested-but-unsupported visual behavior before installing a diagram dependency or writing migrations.

### Scope

1. Trace and document one complete live path and one dry-run path through:
   - Telegram route API;
   - route initialization/new-only boundary;
   - scheduler;
   - capture and `AutomationDispatch` creation;
   - research/generation;
   - immutable revision creation;
   - exact review;
   - publish intent;
   - publishing worker;
   - publication/reconciliation.
2. Inventory current models, schemas, endpoints, safe errors, events, idempotency keys, pause/retry behavior, worker capabilities, tests, migrations, OpenAPI generation, and acceptance scripts.
3. Inventory frontend routes, Automation components/API/query keys, Settings resource components, Operations Center links, shared primitives, accessibility patterns, responsive shell, test fixtures, and Playwright coverage.
4. Produce `docs/implementation-notes/automation-workflow-builder-contract.md` containing:
   - what exists and can be reused;
   - requested concept → backend capability mapping;
   - graph/schema/versioning decision;
   - legacy-route compatibility strategy;
   - initial node registry and typed ports;
   - explicit deferrals and prohibited generic nodes;
   - API diff and stable error catalog;
   - authorization matrix;
   - resource readiness contract;
   - migration and rollback/forward-recovery plan.
5. Resolve these specific decisions with code evidence:
   - whether Schedule can start the generic run directly or must materialize a runtime projection;
   - whether any conditional/fallback branch is safe in v1;
   - how a legacy `follow_active` route becomes a pinned version without changing running work;
   - whether Editorial profiles require a restored Content Settings management surface;
   - how Automation Run links relate to `WorkflowJob`, `WorkflowEvent`, `AutomationDispatch`, research/generation records, revisions, and publications;
   - whether `AutomationRoute.id` remains the public Automation ID for migrated routes or is mapped through a stable redirect.
6. Write an ADR for the graph/compiler boundary and a short dependency decision record for `@xyflow/react`; do not install it yet.

### Dependencies

- None. This is the required discovery gate for all later phases.
- Read current `CONTEXT.md`, applicable docs, and any newly added ADRs before finalizing terminology.

### Expected outcomes

- A reviewable, source-linked contract with no speculative node types.
- A frozen Workflow Graph v1 and node-registry contract suitable for Pydantic, OpenAPI, and TypeScript generation.
- A migration approach that preserves every active route, cursor, dispatch, Draft/revision, publish job, and publication.
- A precise list of features intentionally deferred from the visual reference.
- Estimated change surfaces and named test targets for Phases 2–6.

### Verification criteria

- The contract names the actual job types, models, events, route endpoints, source/generation/publishing ownership, and existing tests that prove each claimed capability.
- The current live and dry-run traces are reproduced with repository fake fixtures or existing focused tests; no paid provider or real Telegram credential is used.
- The capability matrix explicitly marks linear, branch, multiple-output, condition, schedule, manual, content-trigger, research, validation, review, draft, and publish support as existing, extension, or deferred.
- The security review confirms no proposed API accepts provider keys, Telegram tokens, raw prompt bodies, client-controlled roles/scopes, or worker credentials.
- The contract is approved before a graph migration or diagram package is added.
- `git diff --check` passes for the documentation-only phase.

### Phase exit gate

No Phase 2 schema or Phase 4 canvas work starts until the contract, migration strategy, node catalog, and deferral list agree with the current runtime.

---

## Phase 2 — Canonical workflow domain, versioning, templates, and APIs

### Goal

Make PostgreSQL authoritative for versioned workflow definitions, backend validation, safe templates, resource readiness, and lifecycle operations while preserving legacy Telegram routes.

### Scope

1. Add forward-only migrations for Automation, AutomationVersion, AutomationTemplate, AutomationRun, and AutomationNodeRun concepts plus required links/indexes.
2. Backfill existing `AutomationRoute` rows into legacy-compatible Automation definitions and immutable v1 versions:
   - preserve existing public IDs or maintain deterministic mappings/redirects;
   - preserve active/paused state, cursor, poll schedule, dispatch lineage, and destination/provider/prompt/profile references;
   - do not reactivate archived/disabled records;
   - resolve `follow_active` only for the new version snapshot while keeping already queued work on its stored prompt/checksum;
   - keep the existing route row as a compiled runtime projection during migration.
3. Implement backend modules with deep boundaries, for example:
   - `app/automations/definitions/models.py`;
   - `schemas.py` for graph/config/version/lifecycle contracts;
   - `registry.py` for node types, typed ports, config JSON Schemas, validation rules, UI hints, and runtime capability mapping;
   - `validation.py` for whole-graph invariants and resource readiness;
   - `service.py` for CRUD, version creation, duplication, archive, conflict handling, and audit events;
   - `templates.py` for deterministic idempotent system seeds.
4. Implement backend graph validation:
   - schema version and node/edge limits;
   - stable unique IDs;
   - supported node/config validation;
   - exactly one entry and at least one output;
   - typed ports and predecessor/successor rules;
   - no cycles/unbounded loops;
   - required Human Review boundary under current policy;
   - resource existence, enabled state, capability readiness, prompt-version availability, destination health, secret-store availability, and worker capability availability;
   - node-addressed errors/warnings with stable safe codes.
5. Expose or adapt API endpoints only where existing routes are insufficient:
   - workflow list/detail/create/update draft/archive;
   - versions list/detail/create/restore-as-draft;
   - node catalog and batched resource/readiness summaries;
   - validate, duplicate, activate, pause;
   - templates list and create-from-template;
   - runs endpoints may be scaffolded here and populated in Phase 3.
6. Require optimistic concurrency using an explicit revision/ETag/updated-version token. Return `automation_version_conflict` rather than overwriting.
7. Keep read/write authorization at the centralized `ApplicationPrincipalResolver` boundary:
   - reads require the appropriate read scopes;
   - mutations require `automations:write`;
   - catalog resource metadata is additionally limited by provider/destination/prompt read policy;
   - browser-supplied scope headers remain ignored;
   - every response is an allowlisted, secret-free schema.
8. Seed only backend-supported templates. Initial safe candidates are Breaking News to Telegram, Research-first Draft, Daily Digest if scheduling/grouping compiles safely, Manual Draft Generator, and Blank Workflow. Seeds are versioned, idempotent, ownership-aware, inactive, and never overwrite operator changes.
9. Regenerate `contracts/openapi.json` and `frontend/lib/api/generated.ts`; add generalized API/query-key modules without removing legacy adapters until compatibility tests pass.

### Dependencies

- Phase 1 contract, node matrix, versioning decision, and migration design.
- Current Settings readiness semantics and centralized auth behavior.

### Expected outcomes

- The backend can persist, retrieve, duplicate, validate, version, and archive a workflow graph without a frontend.
- Existing Telegram routes remain operable and appear as migrated Workflows.
- Active versions are immutable; editing produces a separate draft.
- Templates create editable inactive drafts.
- The resource catalog exposes safe metadata for ready and non-ready saved references without secrets or N+1 browser queries.
- Stable safe errors identify the node and recovery action.

### Verification criteria

- Unit tests cover graph schema, node registry, config validation, typed ports, invalid edges, missing trigger/output, cycles, size bounds, review policy, unknown nodes, and secret-shaped input rejection.
- Service/API tests cover CRUD, duplicate, archive/dependency conflicts, template seeding/idempotency/ownership, version immutability, restore-as-draft, optimistic conflicts, authorization, redaction, and stable errors.
- Migration tests run upgrade from the current head, backfill representative active/paused/disabled legacy routes, and prove cursor/dispatch/publication provenance is unchanged. Applied migration files are untouched and Alembic has one head.
- PostgreSQL tests prove unique active pointers, immutable versions, concurrency conflicts, dependency-aware provider/prompt/destination deletion, and bounded pagination.
- OpenAPI regeneration leaves no manual TypeScript drift.
- Focused commands pass:

```bash
cd backend
.venv/bin/python -m pytest tests/test_automation_workflow_schema.py -v
.venv/bin/python -m pytest tests/api/test_automations.py -v
.venv/bin/python -m pytest tests/test_automation_workflow_migration.py -v
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/python -m pytest tests/postgres/test_automation_definitions.py -v
.venv/bin/alembic upgrade head
```

### Phase exit gate

A workflow created and validated through the API must round-trip canonically, reject unsupported graphs server-side, and coexist with every legacy route before runtime compilation begins.

---

## Phase 3 — Compiler, durable execution, dry run, activation, and worker integration

### Goal

Compile validated graphs into the existing durable runtime and execute the v1 workflow end to end without weakening worker, review, publication, pause, retry, or idempotency boundaries.

### Scope

1. Build a deterministic compiler:

```text
Workflow Graph v1
  → normalized supported stages
  → resource/capability requirements
  → existing route/schedule/job commands
  → execution plan with stable node IDs
```

2. Reject graphs that cannot map to an existing safe handler. Do not add a generic expression engine or a browser-executed fallback.
3. Create a run-start application service that, in one transaction where practical:
   - locks and loads the persisted Automation version;
   - revalidates graph and required resource readiness;
   - records immutable safe references/settings in an execution snapshot;
   - creates an AutomationRun and initial node states;
   - enqueues the root durable job with a stable idempotency key;
   - records a redacted audit/WorkflowEvent.
4. Add minimal orchestration job types only where needed. Orchestration may enqueue existing domain jobs and advance persisted node state; it must not perform source I/O, model calls, or publication itself.
5. Preserve capability ownership:
   - source work remains on the source-capable worker;
   - research/generation and graph stage advancement remain on generation-capable workers;
   - only the publishing worker resolves Telegram credentials and publishes;
   - the API validates and enqueues but does not run provider/publishing operations.
6. Implement trigger adapters:
   - Manual creates a durable run from selected safe input references;
   - Schedule compiles to `WorkflowSchedule` and scheduler-enqueued work;
   - Telegram new-item uses the existing new-only cursor/capture route projection;
   - any other feed/content trigger is deferred until it has a deterministic persisted event seam.
7. Persist node-level transitions—pending, queued, running, succeeded, warning, failed, skipped, waiting for review—with linked job and artifact IDs. Derive views from actual persisted states, not frontend guesses.
8. Implement dry run as a backend invariant:
   - all run/start and downstream commands carry a server-owned dry-run flag;
   - publishing compilation is disabled for dry-run runs regardless of client input;
   - generated output remains reviewable and evidence-bound;
   - dry run records the exact workflow version and node results;
   - refreshing or closing the browser does not affect the run.
9. Implement Human Review and publishing continuation:
   - a review node waits on an exact immutable revision;
   - approval is still bound to revision ID and content hash;
   - continuation revalidates that same revision, active controls, destination route snapshot, and capability status;
   - Telegram publication uses the existing publish-intent/publishing-worker path and receipts;
   - Instagram/X/blog remain manual package outputs.
10. Implement activation as a transactional gate:
    - only a saved, validated version may activate;
    - required resources and workers must be ready;
    - enforce a successful dry run if adopted by the Phase 1 policy decision;
    - atomically update the active-version pointer and runtime projection;
    - preserve the Telegram new-only boundary;
    - pin all new runs to the active version;
    - do not mutate existing runs when a new version activates.
11. Preserve route pause, global pause/dry-run controls, lease recovery, retry classification, safe errors, and publication reconciliation.
12. Add redacted domain events for workflow/version save, validate, run start/complete/fail, activation attempt/success, pause, review boundary, and publication boundary. Reuse Operations Center rather than creating another log store.

### Dependencies

- Phase 2 canonical graph, immutable versions, node registry, run persistence, and API contracts.
- Existing job, generation, research, review, publishing, and capability services.

### Expected outcomes

- A supported graph executes as durable jobs and events with browser-independent progress.
- Manual, scheduled, and Telegram new-item workflows reuse the same versioned run model.
- Every run and node can be traced to the exact version, resources, evidence, provider/model, prompt version/checksum, Draft/revision, job, and publication outcome.
- Dry run cannot publish even under a malicious or stale client.
- Human review and the separate publishing worker remain mandatory wherever current policy requires them.

### Verification criteria

- Compiler unit tests prove supported graphs normalize deterministically and unsupported branch/cycle/node/config shapes fail with stable codes.
- PostgreSQL journeys prove:
  - create → save version → validate → durable dry run → generated reviewable revision → no publish job/publication;
  - trigger → research/generation → pending review → exact approval → publish job → publishing worker → one Publication;
  - activation creates the correct new-only boundary and does not backfill old items;
  - active-version switching is atomic and old runs remain pinned;
  - global/route pause prevents new work and resume does not duplicate it;
  - API, scheduler, source/generation worker, and publishing-worker restarts recover without duplicate Drafts or Publications;
  - lease expiry/reclaim and repeated idempotency keys converge on one logical run/node result;
  - resource changes do not silently substitute providers, prompt versions, profiles, or destinations.
- Worker registry tests prove the publishing worker cannot load research/generation handlers and the source/generation worker cannot load `telegram.publish`.
- Redaction tests inject canaries into invalid configs/provider/Telegram errors and prove no API, job, event, run, node-run, audit, or log projection leaks them.
- Focused commands pass:

```bash
cd backend
.venv/bin/python -m pytest tests/test_automation_compiler.py -v
.venv/bin/python -m pytest tests/test_automation_runs.py -v
.venv/bin/python -m pytest tests/test_telegram_route_handlers.py tests/test_telegram_process_handler.py -v
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/python -m pytest tests/postgres/test_automation_execution.py -v
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/python -m pytest tests/postgres/test_telegram_process_handler.py tests/postgres/test_telegram_publish_service.py -v
```

### Phase exit gate

One template-derived workflow must complete a real fake-provider PostgreSQL dry run, survive a process restart, create an exact reviewable revision, and prove zero publication before the visual builder is considered integrated.

---

## Phase 4 — Workflow library, templates, guided visual builder, and responsive accessibility

### Goal

Replace the Telegram form-first experience with a professional workflow library and schema-driven editor connected to the real Phase 2/3 contracts.

### Scope

1. Establish deep-linkable routes inside the same product area:
   - `/automations` — Workflows (default);
   - `/automations/runs` — Runs;
   - `/automations/templates` — Templates;
   - `/automations/new` — template selection, not an empty canvas;
   - `/automations/[automationId]` — draft/active workflow editor;
   - preserve or redirect `/automations/[routeId]/history` to the relevant run/history view.
2. Build the Workflows library:
   - name, description, lifecycle, trigger, main provider, output/destination, review mode, last run/outcome, active version, and readiness;
   - reliable success rate only when backed by a defined denominator/window;
   - safe open/edit/test/activate/pause/duplicate/view runs/archive actions;
   - destructive actions secondary, confirmed, and dependency-aware;
   - polished empty state with “Start from a template” and “Create a blank workflow.”
3. Build the Templates view and New workflow experience from server data. Creating a template copy always produces an inactive editable draft.
4. Add only the missing shared primitives justified by repeated use—Tabs, Sheet/Drawer, overflow Menu, and schema Field wrappers—using existing Base UI/shadcn conventions. Do not produce wrapper-only component sprawl.
5. Add generalized Automation API modules and TanStack Query keys for workflows, versions, templates, catalog/resources, validation, activation/pause, and runs. Keep legacy keys only for compatibility paths.
6. Implement one canonical client graph state with:
   - backend graph/config data;
   - local layout metadata;
   - selection;
   - undo/redo history;
   - dirty state and last-saved version token;
   - normalized validation messages;
   - no credentials or raw prompts.
7. Run the `@xyflow/react` spike, then pin it and update `package.json` plus lockfile if it passes:
   - controlled graph only;
   - custom memoized NewsCraft nodes;
   - type-safe handles derived from the registry;
   - zoom, fit, snap, keyboard focus/movement, deletion, selection, and optional minimap;
   - dynamic client import and bounded rendering;
   - no automatic animated edges;
   - library CSS imported in the Tailwind 4-compatible global order.
8. Implement the desktop/tablet three-panel editor:
   - searchable/grouped node library on the left;
   - canvas in the center;
   - schema-generated node inspector on the right;
   - collapsible Test Studio placeholder wired to real run APIs in Phase 5;
   - sticky header with breadcrumb/name, lifecycle/readiness, Save, Test, and Activate/Pause hierarchy.
9. Generate inspector controls from the node registry config schema and UI hints. Reuse provider logos and Telegram destination presentation. Show selected resource readiness as Ready, Disabled, Stale, Unavailable, or Not configured; retain broken saved references and link to the exact Settings section rather than silently replacing them.
10. Implement continuous client validation for fast feedback, but always display server validation as authoritative. Invalid connections are blocked or immediately explained with the affected ports/nodes and a recovery action.
11. Implement state safety:
    - explicit Save draft;
    - unsaved indicator and `useDirtyNavigation` confirmation;
    - server-version conflict dialog with reload/copy options;
    - no silent overwrite;
    - autosave deferred unless reliability is proven; layout-only debounce must not activate or mutate business config.
12. Implement the mobile editor as an ordered vertical list using the same graph state:
    - step cards and explicit connectors;
    - Add step bottom sheet;
    - node settings full-height sheet;
    - Move up/down and choose input/output controls;
    - no free-form tiny canvas;
    - no essential hover-only or drag-only action.
13. Apply the reference direction through existing tokens: restrained surfaces, clear node hierarchy, one primary action, compact operational information, semantic node-family accents, visible focus, 44px targets, reduced motion, and light/dark parity.

### Dependencies

- Phase 2 APIs/catalog/version concurrency.
- Phase 3 validate/test/activate endpoints and persisted execution semantics.
- Phase 1 diagram decision record.

### Expected outcomes

- `/automations` opens an understandable workflow library rather than a blank canvas or a Telegram-only table.
- A user can create a blank/template draft, add/select/reorder/delete compatible nodes, edit real resource-backed settings, save, validate, and activate through backend truth.
- Desktop uses a visual canvas; mobile and keyboard users have a fully equivalent ordered workflow editor.
- Existing visual language and navigation remain coherent in light and dark modes.
- The canvas is code-split and does not load run history or heavy Test Studio content at startup.

### Verification criteria

- Component tests cover Workflows list/empty/error/loading states, Templates, template/blank creation, node library, add/delete/duplicate/reorder/select, valid/invalid connections, inspector schema fields, resource readiness, Settings links, undo/redo, dirty navigation, save conflicts, backend validation, activation/pause, and no secret/raw-error rendering.
- Accessibility tests use roles/names rather than utility-class assertions and prove:
  - complete keyboard editing;
  - visible focus and logical order;
  - screen-reader node/edge descriptions and live validation messages;
  - accessible alternative to drag/edge creation;
  - dialog/sheet focus trap and restoration;
  - status text beyond color;
  - reduced-motion support.
- Responsive tests cover 390px vertical editing, 768px, 1024px collapsible panels, and 1440px three-panel layout with no page-level horizontal overflow or clipped controls.
- Performance checks render and edit 5-, 15-, and 30-node workflows, keep common interactions responsive, confirm memoized node updates, and record the canvas bundle impact.
- The dependency spike verifies the pinned package against React 19, Next.js 16 production build, Tailwind 4 CSS order, controlled state, custom nodes, theme tokens, and Playwright keyboard behavior.
- Focused commands pass:

```bash
cd frontend
env -u NODE_ENV npm run test -- --run tests/automation-workflows-page.test.tsx
env -u NODE_ENV npm run test -- --run tests/automation-builder.test.tsx
env -u NODE_ENV npm run test -- --run tests/automation-builder-accessibility.test.tsx
npm run typecheck
npm run build
```

### Phase exit gate

A user must be able to build the supported v1 flow without drag-and-drop, save it as a backend draft version, reload it without loss, see accurate readiness/validation, and never see or submit a credential value.

---

## Phase 5 — Test Studio, Runs, version history, Operations links, and Draft seam

### Goal

Turn testing and run history into a coherent operational experience backed by the persisted Automation Run/Node Run model and existing Jobs, Draft/revision, and publication records.

### Scope

1. Implement the bottom Test Studio as a lazy-loaded feature:
   - safe input selection from existing Feed/Inbox/content records or deterministic fixtures;
   - Validate only and Full dry run first;
   - Run until step, retry node, and compare outputs only when Phase 3 exposes safe durable contracts—otherwise hide them rather than simulate them;
   - display the exact persisted workflow version before starting.
2. Track active tests through TanStack Query with request cancellation and bounded polling only while a run is non-terminal. Refreshing the browser must resume from the run ID.
3. Show node-level persisted results:
   - status and timing;
   - safe input/output summary;
   - evidence references;
   - provider/model and prompt version;
   - usage/cost only when reliable;
   - retryability and safe error;
   - related Job/Operations Center link;
   - no raw prompt/provider response/stack trace/credential/authorization data.
4. Implement Runs view with bounded pagination and filters for workflow, state, dry-run/live, date range, and failed only. Columns include workflow/version, trigger, start, duration, current stage, outcome, mode, Draft/revision, Job, Publication, and safe failure code.
5. Implement run detail as a deep-linkable drawer/page:
   - desktop can overlay the graph with execution state;
   - mobile uses a vertical step timeline;
   - every displayed state comes from persisted node-run truth;
   - links go to the existing Jobs/Operations Center and exact review/publication surfaces.
6. Add immutable version history:
   - view graph/config diff safely;
   - identify active and run-pinned versions;
   - duplicate or restore an old version only into a new draft;
   - never rewrite historical versions.
7. Implement the minimal Draft integration seam without a Drafts redesign:
   - backend request accepts workflow ID, active version, input content IDs, and allowlisted safe parameters;
   - generated output retains workflow/run/node provenance;
   - Test Studio and run details link directly to the generated exact revision (`/review/{revisionId}` in the current frontend);
   - add “Create with workflow” to a future/current Drafts entry point only if that surface exists and can use the same contract cleanly; otherwise document it as the next UI consumer.
8. Extend Operations history taxonomy and projections to include workflow/version/run/node events while continuing to link raw operational detail to Jobs instead of duplicating logs.
9. Add clear safe-error mapping: node name, cause, next action, and Settings/Operations link. Deduplicate banners so one failure is not repeated at page, panel, node, and toast level.

### Dependencies

- Phase 3 persisted run/node execution and durable dry-run behavior.
- Phase 4 workflow builder, graph renderer/ordered editor, shared panels, and query modules.

### Expected outcomes

- A user can start a real durable dry run, leave/refresh, return, inspect each executed node, and open the generated exact revision.
- Runs provide a product-level view while Operations Center remains the operational job truth.
- Historical runs and Drafts remain pinned to their original workflow versions and resource snapshots.
- Version history is inspectable and restorable without mutation of history.

### Verification criteria

- Frontend tests cover Test Studio inputs/modes, durable job acknowledgement, refresh resume, node results, safe errors, links, Runs filters/pagination, run detail graph/timeline, version history, restore-as-draft, and generated-revision navigation.
- API/PostgreSQL tests prove bounded run queries, exact linkage among run → node → jobs → research/generation → revision → publish job/publication, and redaction at every projection.
- A browser test creates from a template, configures safe fixtures, saves, validates, dry-runs, watches node states, opens the generated revision, returns to the workflow, activates, pauses, opens Runs, and follows the related Job link.
- Mobile and keyboard browser tests can start and inspect the same dry run without using canvas drag behavior.
- Dry-run tests assert at the database and UI layers that no `PublishJob`/`Publication` is produced.
- Focused commands pass:

```bash
cd backend
.venv/bin/python -m pytest tests/api/test_automation_runs.py -v
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  .venv/bin/python -m pytest tests/postgres/test_automation_run_projection.py -v

cd ../frontend
env -u NODE_ENV npm run test -- --run tests/automation-test-studio.test.tsx
env -u NODE_ENV npm run test -- --run tests/automation-runs.test.tsx
npm run test:e2e -- e2e/automation-workflow-builder.spec.ts
```

### Phase exit gate

The complete template → edit → validate → durable dry run → node results → exact generated revision → activate/pause → run history → Operations Job journey must pass in a deterministic browser test against the real backend contract.

---

## Phase 6 — Security, prompt safety, performance, compatibility, and release acceptance

### Goal

Harden the complete production slice, prove migration and restart safety, update operational documentation, and release only when backend, PostgreSQL, worker, frontend, browser, accessibility, and visual checks pass together.

### Scope

1. Perform a security boundary review:
   - centralized principal/scopes on every read/mutation;
   - same-origin/browser header-spoof protection;
   - no credential-bearing fields in graph/catalog/version/run APIs;
   - allowlisted node schemas/operators/destination behavior;
   - no HTTP/SQL/shell/code/filesystem/credential nodes;
   - SSRF-safe future integration posture;
   - redacted errors/audit/events/jobs/run summaries;
   - dependency-aware deletion and authorization regression tests.
2. Enforce prompt-injection boundaries:
   - system policy, operator template, structured config, source evidence, and user input remain separate message/data channels;
   - source content cannot modify graph, destination, credentials, review policy, tools, or publication behavior;
   - prompt versions are referenced by ID/checksum and governed by Content Settings;
   - model output is schema-validated, bounded, and unable to grant itself tools or iterations.
3. Harden runtime reproducibility:
   - immutable execution snapshots contain safe IDs/settings only;
   - active runs follow the documented resource-disable/change policy without silent substitution;
   - old versions/runs remain interpretable after template/resource updates;
   - worker restarts and lease recovery preserve exactly-once material effects through existing idempotency/receipt mechanisms.
4. Performance and reliability work:
   - batched resource readiness and bounded lists;
   - no full run history on editor startup;
   - dynamic canvas/Test Studio/run detail imports;
   - memoized nodes and localized inspector updates;
   - request cancellation and polling only for active states;
   - 5/15/30-node render/edit/save/validate measurements;
   - no save per keystroke; debounced operations only where proven;
   - bundle analysis and regression budget.
5. Visual/accessibility QA using the reference only as a comparison for hierarchy and experience:
   - 1440 light/dark;
   - 1024 light/dark;
   - 768;
   - 390 portrait and a small-phone landscape case;
   - canvas/node readability, inspector width, Test Studio, errors, sheets/dialogs, no horizontal overflow, touch targets, visible focus, screen-reader order, and reduced motion.
6. Preserve compatibility:
   - migrated Telegram routes keep their URLs/actions or documented redirects;
   - current smoke and Automation browser fixtures are upgraded rather than deleted;
   - old active routes continue polling/publishing through the proven runtime projection;
   - archive/delete remains dependency-aware;
   - only one Alembic head exists and fresh installs plus upgrades both work.
7. Update documentation:
   - architecture/compiler and node-registry contract;
   - workflow author/operator guide;
   - template governance;
   - safe error/recovery guide;
   - worker/capability/deployment changes;
   - migration/rollback-forward recovery notes;
   - release report with exact commands/results and clearly separated pre-existing failures.
8. Update deterministic smoke/acceptance so it creates a versioned workflow from a seeded template, proves dry-run safety, exact approval, publication-worker-only send, pause/resume, version pinning, and restart recovery.

### Dependencies

- Phases 1–5 complete with no mocked runtime seams.
- Disposable migrated PostgreSQL and deterministic fake provider/Telegram fixtures.

### Expected outcomes

- A focused, production-safe v1 builder supports the real editorial workflow end to end.
- Existing Telegram automation behavior and historical provenance survive migration.
- No arbitrary automation or credential boundary has been introduced.
- Performance, responsive behavior, accessibility, observability, and operational recovery are documented and proven.
- The final report distinguishes pass/fail/block status and unrelated dirty-worktree/environment noise.

### Verification criteria

Run the repository-pinned environments and record exact results. The gate itself is not restated here: the registered gate lives in [`CLAUDE.md`](CLAUDE.md) (“Gates”), and the exact focused command sequence used for this work — including the `DATABASE_URL`-qualified `alembic current`/`alembic check` invocations and the isolated acceptance ports — is recorded verbatim under “Exact commands” in [`automation-workflow-builder-phase-6.md`](docs/implementation-notes/automation-workflow-builder-phase-6.md#exact-commands). Never run a bare `alembic upgrade head`: the test scripts own disposable databases, and an unqualified upgrade migrates whatever the default settings resolve to.

Release assertions:

- Fresh PostgreSQL migration and upgrade-from-current fixtures both pass.
- Manual dry run produces a reviewable revision and zero publication records.
- Reviewed Telegram journey produces one publication through the publishing worker.
- API, scheduler, source/generation worker, and publishing worker restart scenarios recover with no duplicate Draft/revision or Publication.
- New-only activation, route pause, global pause, dry-run control, retry, idempotency, and reconciliation remain correct.
- Browser coverage uses same-origin `/api/backend/...`, not direct-only backend calls.
- Axe finds no serious/critical violations on Workflows, Templates, builder, Test Studio, Runs, and run detail at desktop/mobile widths.
- Visual captures pass in all specified sizes/themes with no overflow/clipping.
- Secret canaries do not appear in HTML, JS-visible data, APIs, logs, events, jobs, audits, reports, screenshots, or source control.
- `package.json` and lockfile agree; OpenAPI and generated TypeScript are current; one Alembic head exists.

### Phase exit gate

Release only after the real PostgreSQL and browser journeys pass. If Docker, browser, or another external environment blocks a gate, report it as blocked with evidence; do not describe the feature as complete.

---

## 5. Cross-phase delivery rules

### 5.1 Vertical slices and compatibility

- Each phase ends in a coherent, testable state and preserves current route behavior.
- Keep legacy Telegram API adapters until the generalized API has migration and browser proof.
- Prefer adapters over rewrites: the compiler should call existing domain services/jobs, not duplicate provider, research, generation, validation, approval, or publishing logic.
- Avoid long-lived frontend mocks. Phase 4 may use typed test fixtures, but acceptance must use the real Phase 2/3 contracts.
- Hide unsupported Test Studio actions and nodes rather than presenting non-functional controls.

### 5.2 Security invariants

- Provider/Telegram credentials never enter Automation requests, graph JSON, browser state, query caches, events, logs, or snapshots.
- The browser never supplies trusted roles/scopes.
- New Automation reads/mutations use the centralized application-principal boundary and existing scopes.
- Dry runs cannot compile or enqueue publication.
- Source/generation workers cannot publish; publishing workers cannot research or construct AI dependencies.
- All source material is untrusted data and cannot alter workflow policy or permissions.

### 5.3 UX invariants

- The Workflows library is the default entry, not an empty canvas.
- One clear primary action per view.
- The builder is usable without mouse, drag-and-drop, or hover.
- Mobile uses an ordered vertical editor, not a squeezed desktop canvas.
- Resource breakage is explicit and actionable; no silent fallback selection.
- Status is conveyed through text/icon/shape as well as semantic color.
- Existing NewsCraft tokens and components take precedence over reference-image pixels or third-party default themes.

### 5.4 Scope explicitly deferred from v1

Node types and execution semantics deferred or prohibited in v1 — webhooks and arbitrary HTTP, SQL/shell/code/filesystem/environment/credential nodes, loops, recursion, subflows, generic branching, dynamic tools, marketplace integrations, real-time collaboration, and direct Instagram/X/blog publication — are enumerated canonically in “Explicit deferrals and prohibited nodes” of [`automation-workflow-builder-contract.md`](docs/implementation-notes/automation-workflow-builder-contract.md#explicit-deferrals-and-prohibited-nodes). The remaining product-scope deferrals owned by this plan are:

- unrestricted expressions beyond the allowlisted safe-config fields;
- hundreds of node types or graphs larger than the measured 30-node target;
- empty Variables/Connections tabs;
- a full unrelated Drafts redesign;
- decorative analytics or success-rate claims without reliable data.

---

## 6. Final definition of done

The six phases are complete only when all of the following are true:

1. Workflows, Runs, and Templates are real, useful, deep-linkable views under `/automations`.
2. A workflow can be created from a safe template or blank draft and edited through the guided visual/ordered editor.
3. The server owns a versioned graph, registry, validation, compilation, activation, and execution snapshot.
4. Invalid nodes/configs/connections/graphs are rejected before activation and fail safely if submitted directly.
5. Every new run is pinned to an immutable workflow and prompt version.
6. Existing Settings resources are selected by safe ID/readiness metadata; credentials never appear.
7. A durable dry run survives refresh/restart, creates reviewable material, and cannot publish.
8. Test Studio and Runs show persisted node results and link to Jobs/Operations Center and the exact generated revision.
9. Human Review is first-class and exact approval remains bound to revision ID/content hash.
10. Telegram sends occur only in the publishing worker with current idempotency, receipts, reconciliation, and audit.
11. Existing Automation routes and historical dispatch/publication provenance survive migration.
12. Desktop, tablet, mobile, keyboard, screen-reader, reduced-motion, light, and dark behavior pass their acceptance checks.
13. Security, redaction, prompt-injection, dependency, authorization, performance, OpenAPI, migration, static, PostgreSQL, browser, and repository hygiene gates pass.
14. The final implementation report records exact commands/results, migrations/files changed, supported/deferred nodes, remaining limitations, and unrelated pre-existing failures separately.
