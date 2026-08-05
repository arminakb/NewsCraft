# Automation Workflow Builder implementation contract

**Status:** Accepted and implemented through Phase 6

**Date:** 2026-08-01

**Scope:** Binding v1 contract implemented by migrations 0027–0028, backend compiler/runtime, and replaceable editor adapters.

## Purpose

This contract fixes the supported boundary for the first NewsCraft visual workflow builder. It is based on the current Telegram automation, durable-job, editorial, review, and publishing implementation. The browser is an editor and observer; PostgreSQL and backend services remain authoritative for definitions, validation, versioning, execution, review, and publication.

Terminology follows [`CONTEXT.md`](../../CONTEXT.md): source material becomes an operator-reviewed, source-grounded publishing workflow. A workflow definition is an **Automation**; an immutable saved definition is an **AutomationVersion**; one execution is an **AutomationRun**.

The companion decisions are:

- [ADR 0001: Backend-owned workflow graph and compiler](../adr/0001-backend-owned-workflow-graph-and-compiler.md)
- [`@xyflow/react` dependency decision](automation-workflow-builder-xyflow-decision.md)

## Frozen decisions

1. Workflow Graph v1 is backend-owned, business-oriented JSON. React Flow objects are never the persistence or execution contract.
2. V1 execution is a directed acyclic graph with one entry. It supports proven linear stages, a deterministic pass-or-stop content filter, and bounded terminal content-package outputs. It does not support a general branch or fallback executor.
3. A Schedule trigger may enqueue the future generic `automation.run.start` job directly through `WorkflowSchedule`; it does not need a synthetic Telegram route. Telegram new-item capture still requires an `AutomationRoute` runtime projection because that row owns the new-only cursor and polling state.
4. New AutomationVersions pin exact prompt-version IDs and checksums. Backfilling a legacy `follow_active` route does not mutate the route, queued jobs, or running work.
5. Migrated Telegram routes keep `AutomationRoute.id` as the public `Automation.id`. Both legacy and generalized URLs use the same UUID; no redirect table is required.
6. AutomationRun and AutomationNodeRun use explicit nullable foreign keys for durable jobs and artifacts. JSON payload IDs remain execution snapshots, not the only query relationship.
7. Editorial Profiles are not restored to Settings as part of this project. The builder selects existing/default profiles through a safe resource catalog. Restoring profile management requires a separate product decision.
8. `@xyflow/react` is deferred until a Phase 4 compatibility spike. It is a replaceable client presentation adapter, not an execution dependency.

## Verified current runtime

### Live Telegram path

| Step | Current behavior and ownership | Evidence |
| --- | --- | --- |
| Configure | `POST /telegram/automations` validates safe resource IDs and creates a disabled, not-initialized `AutomationRoute`. The row stores source, destination, profile, prompt policy/version, provider, filters, review/publish policy, polling, retry, cursor, and pause state. | [`telegram_automations.py`](../../backend/app/api/telegram_automations.py#L278), [`AutomationRoute`](../../backend/app/automations/models.py#L26) |
| Activate | `POST /telegram/automations/{id}/activate` checks worker capability, marks initialization state, and enqueues `telegram.route.initialize`. It performs no source or publishing network call. | [`telegram_automations.py`](../../backend/app/api/telegram_automations.py#L436), [`JobType`](../../backend/app/jobs/types.py#L38) |
| Establish new-only boundary | The source-capable worker snapshots the activation boundary, captures arrivals that occur during initialization, and only then marks the route ready. Continuations are bounded and idempotent. | [`initialize_route`](../../backend/app/automations/telegram/route_operations.py#L86), [`test_initialize_captures_boundary_posts_and_arrivals_before_marking_ready`](../../backend/tests/test_telegram_route_handlers.py#L28) |
| Poll | `SchedulerService.tick` locks due routes and enqueues `telegram.route.poll` with `telegram-route-poll:{route_id}:{due_time}`. Global pause stops new scheduling. | [`scheduler.py`](../../backend/app/jobs/scheduler.py#L106) |
| Capture | Polling validates route state, fetches forward pages, captures source edits before new messages, and advances the cursor only after durable capture. Capture creates source/content/story/evidence/revision records and `AutomationDispatch`, then enqueues `telegram.route.process`. | [`poll_route`](../../backend/app/automations/telegram/route_operations.py#L459), [`_capture`](../../backend/app/automations/telegram/route_fetch.py#L93), [`AutomationDispatch`](../../backend/app/automations/models.py#L107) |
| Research and generation | The generation-capable worker owns `telegram.route.process`. Research may create a durable `research_story` continuation. Prompt resolution records an exact prompt-version ID and checksum in the job payload before provider execution. | [`registry.py`](../../backend/app/jobs/registry.py#L110), [`_resolve_process_prompt`](../../backend/app/automations/telegram/process_support.py#L349), [`test_follow_active_resolves_once_and_persists_exact_job_prompt_snapshot`](../../backend/tests/test_telegram_process_handler.py#L54) |
| Immutable Draft | Generation persists `GenerationRun`/`GenerationAttempt`, `ContentPack`, `PlatformVariant`, and immutable `PlatformVariantRevision` rows with content hashes, evidence, validation, and approval state. | [`generation/models.py`](../../backend/app/generation/models.py#L113), [`PlatformVariantRevision`](../../backend/app/generation/models.py#L207) |
| Review | Manual approval/rejection addresses an exact revision. Approval locks the revision and verifies the submitted expected content hash against both the stored hash and recomputed content. | [`review_decisions.py`](../../backend/app/generation/review_decisions.py#L19), [`content_packs.py`](../../backend/app/api/content_packs.py#L317) |
| Publish intent | Auto-approved processing or an exact reviewed-draft request creates one `PublishJob`, links it to the dispatch, and enqueues `telegram.publish` with `telegram-publish:{destination_id}:{revision_id}:{content_hash}`. No remote send occurs at intent creation. | [`enqueue_telegram_publish_intent`](../../backend/app/automations/telegram/process_support.py#L49), [`draft_publication.py`](../../backend/app/publishing/telegram/draft_publication.py#L146) |
| Publish | Only a publishing-capable worker registers `telegram.publish` and resolves the Telegram credential. The service revalidates revision identity, approval, content/evidence/media hashes, route provenance, destination, pause state, and durable operation receipts before sending. | [`registry.py`](../../backend/app/jobs/registry.py#L143), [`publish_telegram`](../../backend/app/publishing/telegram/publication.py#L620), [`publishing/models.py`](../../backend/app/publishing/models.py#L134) |
| Publication/reconciliation | A successful exact send creates one `Publication`. Ambiguous or interrupted delivery is not generically retried; durable receipt evidence enters the explicit reconciliation flow, which can record published or not-published outcomes idempotently. | [`reconciliation_operation.py`](../../backend/app/publishing/telegram/reconciliation_operation.py#L418), [`test_reconciliation_case_projection_is_strict_ordered_and_secret_free`](../../backend/tests/test_telegram_publish_service.py#L199) |

### Dry-run path

1. `POST /telegram/automations/{id}/dry-run` enqueues `telegram.route.dry_run` with a hash-derived idempotency key and `force_review=true` ([source](../../backend/app/api/telegram_automations.py#L511)).
2. The source worker requires a ready route, fetches one bounded source message, and captures it with dispatch kind `dry_run` ([source](../../backend/app/automations/telegram/route_operations.py#L674)). Its source key includes the dry-run job ID, so replay of one job deduplicates while separate test runs remain separate ([source](../../backend/app/automations/telegram/repository.py#L298)).
3. Capture does not advance the live route cursor. The normal research/generation path is reused, but review policy always resolves to pending review for dry-run work ([source](../../backend/app/automations/telegram/decisions.py#L101)).
4. The generated revision remains a real, inspectable immutable Draft with explicit dry-run provenance. Scheduling and publishing reject it; therefore no `PublishJob`, remote send, `Publication`, or reconciliation case can be produced. This is the required proof through the publication boundary, not a simulated success.

The focused fake-fixture tests reproduced activation, initialization, poll ordering, dry-run cursor independence, prompt pinning, fail-closed auto publication, evidence validation, reconciliation projection, and scheduling idempotency. No paid provider or Telegram credential was used.

## Current inventory

### Persistence and durable behavior

| Area | Reusable records and behavior |
| --- | --- |
| Route/capture | [`AutomationRoute` and `AutomationDispatch`](../../backend/app/automations/models.py#L26), including route/source uniqueness, dispatch kind/status, artifact links, safe errors, cursor, pause, retry, and next-poll state |
| Jobs | [`WorkflowJob`, `WorkflowEvent`, `WorkflowSchedule`, `AutomationControl`, `RuntimeHeartbeat`](../../backend/app/jobs/models.py#L14), including unique idempotency keys, leases, attempts, scheduling, pause sensitivity, progress, and safe error class/code/message |
| Generation | [`BrandProfile`, prompt templates/versions, provider profiles, generation runs/attempts, content packs, variants, and revisions](../../backend/app/generation/models.py#L15) |
| Publishing | [`Destination`, `PublishJob`, `PublishAttempt`, `Publication`, and durable operation receipts`](../../backend/app/publishing/models.py#L61) |
| Review | Exact revision approval/rejection and exact hash checks in [`review_decisions.py`](../../backend/app/generation/review_decisions.py#L19) |

`WorkflowJob` error classes remain `retryable`, `needs_review`, and `permanent` ([source](../../backend/app/jobs/types.py#L25)). Lease expiry is requeued by the scheduler; retry identity is preserved by job idempotency. Route pause defers source work before a network call, while global pause stops scheduling and is rechecked before auto-publish.

Worker capability ownership is fixed:

- **source:** route initialize, poll, backfill, and dry run;
- **generation:** route processing, content-pack generation/regeneration, export, retention, and research when a research resolver is present;
- **publishing:** destination/proxy checks and `telegram.publish`, including credential resolution.

The registry enforces those divisions in [`build_default_registry`](../../backend/app/jobs/registry.py#L52). A workflow orchestrator may enqueue these jobs and persist transitions, but may not absorb their network or credential capabilities.

Current idempotency identities are part of the reusable contract:

| Operation | Key |
| --- | --- |
| Route activation | `telegram-route-initialize:{route_id}:{requested_at}` |
| Due route poll | `telegram-route-poll:{route_id}:{due_time}` |
| Generic schedule | `schedule:{schedule_id}:{due_time}` |
| Dry run | `telegram-route-dry-run:{route_id}:{normalized_request_hash}` |
| Backfill | `telegram-route-backfill:{route_id}:{normalized_bounds_hash}` |
| Captured dispatch processing | `telegram-process:{route_id}:{dispatch_source_key}` |
| Publish intent/job | `telegram-publish:{destination_id}:{revision_id}:{content_hash}` |

Continuation jobs add stable route/root-job/sequence or forward-state digests rather than reusing a consumed job identity. The concrete key construction is visible in [`telegram_automations.py`](../../backend/app/api/telegram_automations.py#L436), [`scheduler.py`](../../backend/app/jobs/scheduler.py#L106), [`route_fetch.py`](../../backend/app/automations/telegram/route_fetch.py#L203), [`repository.py`](../../backend/app/automations/telegram/repository.py#L248), and [`process_support.py`](../../backend/app/automations/telegram/process_support.py#L49).

### Current endpoints

- Route list/options/create/detail, prompt/research policy, activate, pause, resume, dry run, backfill, and dispatch list: [`telegram_automations.py`](../../backend/app/api/telegram_automations.py#L184).
- Content-pack creation/listing, revision creation/regeneration, and exact approve/reject: [`content_packs.py`](../../backend/app/api/content_packs.py#L120).
- Telegram publication outcomes/context, exact publish/schedule, publish-job detail, and reconciliation: [`telegram_drafts.py`](../../backend/app/api/telegram_drafts.py#L181).
- Deterministic article selection already has allowlisted language, topic, content type, source, coverage, image, score, date, collection, sort, and limit semantics in [`ArticleFilters` and `ArticleQuery`](../../backend/app/api/articles.py#L62). Workflow code must extract/reuse this domain query instead of calling an API handler internally.

Current Telegram request schemas use bounded Pydantic fields and `extra="forbid"` in [`telegram_schemas.py`](../../backend/app/api/telegram_schemas.py#L112). Destination/proxy credential schemas are not reusable graph configs: Workflow Graph v1 imports only safe resource IDs and policy fields. Existing output materializers redact safe error data and omit credential references.

### Events and safe errors

Current event history is append-only `WorkflowEvent` data. Reusable event families include:

- job lifecycle: `job.enqueued`, `job.claimed`, `job.heartbeat`, `job.succeeded`, `job.retried`, `job.cancelled`, and `job.lease_expired`;
- source/capture: `telegram.source.captured` and source-edit events;
- research/generation: `research.*`, generation completed/failed, and review-required events;
- revision/review: `content_pack.revision.*`, `telegram.revision.*`, and `telegram.revision.publish_requested`;
- publication: `telegram.publish.requested`, `telegram.publish.scheduled`, `telegram.publish.blocked`, `telegram.publish.succeeded`, `telegram.publish.reconciled_published`, and `telegram.publish.reconciled_not_published`;
- control: `automation.control_updated` and `schedule.invalid`.

Representative stable runtime error codes that must retain their current meaning include `route_not_ready`, `route_not_initialized`, `activation_changed`, `source_configuration_missing`, `generation_prompt_integrity_failed`, `generation_provider_configuration_changed`, `citation_integrity`, `media_integrity`, `platform_validation_failed`, `telegram_revision_hash_drift`, `telegram_publish_gate_blocked`, `telegram_publish_plan_drift`, `telegram_publish_ambiguous`, and `telegram_publish_reconciliation_required`. API and run projections expose only redacted code/message data; raw exceptions, request payloads, and credentials are excluded.

### Migrations, contracts, and acceptance

- The current Alembic head is `0026_remove_operator_sessions`; job/schedule, Telegram route, and dispatch sequence foundations are migrations `0005`, `0006`, and `0007` ([versions](../../backend/alembic/versions)). Applied migrations must not be rewritten.
- [`backend/scripts/export_openapi.py`](../../backend/scripts/export_openapi.py) deterministically exports [`contracts/openapi.json`](../../contracts/openapi.json).
- [`test_openapi_contract.py`](../../backend/tests/test_openapi_contract.py), [`openapi-contract.test.ts`](../../frontend/tests/openapi-contract.test.ts), and the CI contract-drift step keep backend and generated TypeScript aligned.
- [`scripts/test_acceptance.sh`](../../scripts/test_acceptance.sh), [`scripts/test_postgres.sh`](../../scripts/test_postgres.sh), and [`scripts/smoke.py`](../../scripts/smoke.py) own the credential-free acceptance path described in [`release-acceptance.md`](../operations/release-acceptance.md).

## Capability matrix

“Existing” means a current backend behavior can be reused. “Extension” means Graph v1 may expose it only after the named bounded adapter/compiler work exists. “Deferred” means the server registry must not advertise it.

| Requested concept | Classification | V1 contract |
| --- | --- | --- |
| Linear workflow | Existing + extension | The fixed Telegram route is already linear; the compiler may express only proven ordered stages. |
| Branch/fallback | Deferred | No persisted general branch executor exists. Rejected filters end as `skipped`; they do not select another edge. |
| Multiple output | Existing, bounded | Content packs may create a bounded set of platform revisions and manual packages. Arbitrary fan-out and multiple direct publishers are excluded. |
| Condition | Existing, terminal only | The exact Telegram include/exclude term, minimum text length, and media-required predicate may pass or stop. No expression language or alternative branch. |
| Schedule | Existing + extension | `WorkflowSchedule` directly enqueues its allowlisted job type. V1 will use `automation.run.start`; a scheduled graph must also have compiler-valid deterministic input selection. |
| Manual trigger | Existing + extension | Existing content-pack requests prove manual durable generation. The run-start API adds the workflow/version snapshot. |
| Content trigger | Existing for Telegram | `telegram_new_item` reuses `AutomationRoute` initialization, cursor, polling, and capture. Other feeds/events are deferred. |
| Content selection | Existing query + extension | Extract the deterministic `ArticleFilters`/`ArticleQuery` service. Only allowlisted fields and bounded result counts are accepted. |
| Research | Existing | Reuse `research_story`, its bounded provider policy, evidence snapshots, and review-required states. |
| Generation | Existing | Reuse exact provider/profile/prompt snapshots and current content-pack/Telegram handlers. |
| Validation | Existing, fixed gates | Evidence, content hash, required fields, platform shape, attribution, media, and publish-plan checks remain server-owned. No arbitrary model evaluator. |
| Human review | Existing | Wait on exact immutable revision and expected content hash. Current policy cannot be weakened by graph configuration. |
| Save to Drafts | Existing | Immutable revision persistence is the Draft output; this node is a visible terminal marker, not a second storage system. |
| Telegram publish | Existing | Requires an approved exact Telegram revision and the separate publishing worker. |
| Instagram/X/blog output | Existing manual package only | Generate/export a reviewable manual package. Direct publication is deferred. |

## Workflow Graph v1

### Canonical shape

```json
{
  "schema_version": 1,
  "entry_node_id": "trigger-1",
  "nodes": [
    {
      "id": "trigger-1",
      "type": "telegram_new_item",
      "config": { "source_id": "00000000-0000-0000-0000-000000000000" }
    }
  ],
  "edges": [
    {
      "source_node_id": "trigger-1",
      "source_port": "story",
      "target_node_id": "generate-1",
      "target_port": "story"
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

The Pydantic/OpenAPI/TypeScript contract is frozen as follows:

- `schema_version` is the integer literal `1`.
- Node IDs are opaque, case-sensitive strings matching `[A-Za-z0-9][A-Za-z0-9_-]{0,127}` and are unique.
- A graph has 1–30 nodes, 0–60 edges, exactly one entry node, and at least one output node.
- Every edge contains only source node/port and target node/port. The tuple is unique; both nodes and ports must exist; port type and cardinality must match.
- Cycles, self-edges, unreachable nodes, unknown fields, unknown node types, and unbounded config collections are invalid.
- `output_node_ids` contains existing terminal nodes only.
- Node config schemas use `extra="forbid"`. They contain UUID resource references and bounded safe policy only—never credentials, prompt bodies, authorization headers, roles/scopes, environment names, filesystem paths, code, or executable expressions.
- Layout is an optional map keyed by existing node ID with finite bounded `x`/`y` numbers. Viewport, selection, measured dimensions, React Flow objects, and other transient UI state are not canonical.
- Canonicalization sorts object keys, nodes by ID, edges by their four-part tuple, output IDs, and layout keys before UTF-8 JSON SHA-256 hashing. The compiled plan has a separate hash and compiler version.
- The server returns all validation findings together as `{code, severity, message, node_id?, edge_index?, field_path?, recovery_action?}`. Messages and recovery actions are allowlisted/redacted.

Every AutomationVersion is immutable after insertion. Editing or restoring creates a new version and moves `draft_version_id` with an optimistic Automation revision token. Activation atomically moves `active_version_id`; existing runs keep their original version, graph hash, compiler version, compiled-plan snapshot, and resource snapshot.

### Initial server node registry

Port values are nominal references to persisted server artifacts; graph edges never transport browser-provided object payloads.

| Node type | Inputs | Outputs | Safe config | Runtime mapping/status |
| --- | --- | --- | --- | --- |
| `manual` | — | `story: story.revision_ref` | exact `story_revision_id` | Run-start wrapper over current manual content-pack flow; extension. |
| `telegram_new_item` | — | `story: story.revision_ref` | `source_id` plus polling/runtime projection policy | Existing route initialization, poll, capture, and dispatch. |
| `schedule` | — | `tick: run.signal` | daily/interval schedule, timezone, bounded catch-up policy | `WorkflowSchedule` → `automation.run.start`; extension. |
| `select_content` | `tick?: run.signal` | `stories: story.revision_set_ref` | allowlisted article filters, deterministic sort, `max_count` 1–200 | Extract current `ArticleQuery`; extension. Required for a schedule that needs newsroom content. |
| `filter_content` | `story: story.revision_ref` | `accepted: story.revision_ref` | include/exclude terms, `min_text_characters`, `require_media` | Existing deterministic Telegram predicate. False is terminal `skipped`, not a branch. |
| `research` | `story: story.revision_ref` | `story: story.researched_revision_ref` | provider profile ID and current bounded research policy | Existing `research_story`; optional. |
| `generate_content_pack` | `story: story.revision_ref` or `story.researched_revision_ref` | `drafts: draft.revision_set_ref` | brand/profile/provider IDs, platform allowlist, exact prompt-version IDs/checksums | Existing content-pack generation; bounded multiple outputs. |
| `generate_telegram` | `story: story.revision_ref` or `story.researched_revision_ref` | `draft: draft.telegram_revision_ref` | brand/profile/provider IDs, exact Telegram prompt-version ID/checksum, current media/attribution policy | Existing `telegram.route.process` generation/finalization. |
| `validate` | `drafts: draft.revision_set_ref` | `valid: draft.validated_revision_set_ref` | allowlisted validator IDs only | Fixed evidence/platform/attribution/media gates. Compiler-owned; not independently retryable. |
| `human_review` | `draft: draft.telegram_revision_ref` | `approved: draft.approved_telegram_revision_ref` | no bypass flag; optional safe instructions only | Exact current approval/hash boundary. Waiting is persisted. |
| `save_drafts` | `drafts: draft.revision_set_ref` or `drafts: draft.validated_revision_set_ref` | — | none | Terminal marker for already-persisted immutable revisions. |
| `manual_package` | `drafts: draft.revision_set_ref` | `package: export.manual_package_ref` | platform allowlist | Existing export/checklist path; no external publish. |
| `telegram_publish` | `draft: draft.approved_telegram_revision_ref` | `publication: publication.telegram_ref` | destination ID plus existing quiet-hours/retry policy | Existing durable publish intent and publishing worker. |

Registry advertisement is capability-aware. An extension node remains hidden or non-activatable until its validator, compiler mapping, and focused tests exist. `human_review` is mandatory before `telegram_publish` unless the current server auto-approval policy independently proves all gates and records explicit operator confirmation; a client cannot remove that boundary.

### Explicit deferrals and prohibited nodes

The following are outside Workflow Graph v1 and must not appear as disabled teaseware or be accepted by the API:

- general conditions, switch/case, fallback edges, merge semantics, arbitrary fan-out, loops, recursion, subflows, delays, run-until-node, and isolated-node retry;
- webhooks, arbitrary HTTP, SQL, shell/code execution, filesystem access, environment lookup, credential/secret lookup, dynamic tools, or marketplace nodes;
- browser execution, client-supplied job types, client-supplied roles/scopes, prompt text copies, provider keys, Telegram tokens, or worker credentials;
- direct Instagram, X, blog, or other non-Telegram publication;
- live collaboration, imported generic workflow templates, comparison mode, animated-edge decoration, or raw JSON editing.

## Generalized API diff

Legacy `/telegram/automations` endpoints remain available through the compatibility period. The new allowlisted API adds:

| Method/path | Purpose | Phase |
| --- | --- | --- |
| `GET /automations` / `POST /automations` | List/create inactive workflow definitions | 2 |
| `GET /automations/{id}` / `PATCH /automations/{id}` | Detail and optimistic metadata/draft-pointer update | 2 |
| `POST /automations/{id}/archive` | Dependency-aware archive; never destructive delete | 2 |
| `GET /automations/{id}/versions` / `POST /automations/{id}/versions` | List and create immutable versions | 2 |
| `GET /automations/{id}/versions/{version}` | Fetch one secret-free graph/version | 2 |
| `POST /automations/{id}/versions/{version}/restore-as-draft` | Copy an old immutable version into a new draft version | 2 |
| `POST /automations/{id}/versions/{version}/validate` | Authoritative graph/resource validation | 2 |
| `POST /automations/{id}/activate` / `pause` / `resume` | Lifecycle commands | 2–3 |
| `GET /automation-node-catalog` | Capability-aware registry/config schema/UI hints | 2 |
| `POST /automation-resource-catalog` | Batched safe summaries for requested/saved resource IDs | 2 |
| `GET /automation-templates` / `POST /automation-templates/{key}/create` | Safe system templates and idempotent duplication | 2 |
| `POST /automations/{id}/runs` | Manual or dry-run start against an exact version | 3 |
| `GET /automations/{id}/runs` / `GET /automation-runs/{id}` | Paginated run and node-run read models | 3 |

Create/version/activate/run-start requests require idempotency keys. Metadata and draft changes require `expected_revision` or `If-Match`; stale writes return `automation_version_conflict`. Pagination is bounded and cursor-based. API response schemas are explicit allowlists.

### Stable generalized error catalog

| HTTP | Code | Meaning |
| --- | --- | --- |
| 401 | `authentication_required` | No server-resolved application principal. |
| 403 | `insufficient_permission` | Principal lacks a required scope. |
| 404 | `automation_not_found`, `automation_version_not_found`, `automation_run_not_found` | Addressed safe resource is absent or not visible. |
| 409 | `automation_version_conflict` | Optimistic token/ETag is stale. |
| 409 | `automation_version_immutable` | An existing version was targeted for mutation. |
| 409 | `automation_dependency_conflict` | Archive/resource change would break active or running work. |
| 409 | `automation_run_conflict` | The same idempotency key has different normalized input. |
| 422 | `graph_schema_version_unsupported`, `graph_too_large`, `graph_entry_invalid`, `graph_cycle`, `graph_unreachable_node` | Whole-graph shape is invalid. |
| 422 | `node_type_unsupported`, `node_config_invalid`, `edge_port_invalid`, `edge_cardinality_invalid`, `graph_output_invalid` | Node/edge contract is invalid; finding identifies node/edge/field. |
| 422/409 | `automation_resource_unavailable`, `automation_capability_unavailable` | Referenced resource or required worker capability is not ready. |
| 409 | `automation_activation_invalid` | Draft is invalid, lacks required review/output, or cannot compile. |
| 422 | `automation_run_input_invalid` | Manual/scheduled input does not match the entry contract. |
| 409 | `automation_paused` | Start/activation is prevented by current global/workflow control. |

Runtime node failures keep their existing stable domain code and class. The generalized projection adds node ID and a safe recovery action; it does not rename underlying publication/research/generation errors.

## Authorization and secret boundary

| Operation | Required scope |
| --- | --- |
| Workflow, version, template, validation, run, and node-run reads | `automations:read` |
| Create/edit/version/duplicate/archive/validate/activate/pause/resume/run start | `automations:write` |
| Job deep-link/detail or retry/cancel | `jobs:read` / `jobs:write` |
| Provider safe resource summaries | `providers:read` |
| Destination safe resource summaries | `destinations:read` |
| Prompt-version safe summaries | `prompts:read` |
| Editorial-profile safe summaries | `settings:read` |

All new mutations must be added to the centralized mutation rule in [`security/middleware.py`](../../backend/app/security/middleware.py#L43) and resolved through [`ApplicationPrincipalResolver`](../../backend/app/security/application_principal.py#L75). Local-owner mutations retain same-origin enforcement; profile mode remains fail-closed. The same-origin frontend proxy deletes browser-supplied `x-newscraft-principal-type` and `x-newscraft-scopes` headers ([source](../../frontend/app/api/backend/[...path]/route.ts#L41)).

Graph/API schemas accept only safe IDs and bounded policy. They never accept or return provider keys, Telegram bot tokens, proxy credentials, raw prompt bodies, authorization headers, application roles/scopes, environment settings, or worker credentials. The publishing worker remains the only component that resolves Telegram publication secrets.

## Resource readiness contract

The current Telegram options endpoint returns only ready/enabled providers and destinations. That is correct for a new legacy route but insufficient for an editor reopening a saved graph. The generalized batched catalog must preserve broken saved references and return only:

```json
{
  "id": "uuid",
  "kind": "destination",
  "display_name": "Newsroom channel",
  "state": "ready",
  "reason_code": null,
  "capabilities": ["telegram_publish"],
  "referenced_by_active_version": true,
  "manage_href": "/settings?section=telegram"
}
```

`state` is one of `ready`, `disabled`, `stale`, `unavailable`, or `not_configured`. Missing resources are represented by the requested ID plus `unavailable`; they are never silently substituted. The endpoint batches all requested and current-version IDs, applies per-resource read scopes, and exposes no secret-presence detail beyond a coarse readiness result.

Save may retain an unavailable resource in an invalid draft. Validation reports it at the referencing node. Activation and every run start recheck existence, enabled state, health/capability freshness, prompt version/checksum, secret-store readiness, and required worker heartbeat. A resource change never rewrites an existing AutomationVersion or running snapshot.

Editorial Profiles remain selectable from existing records. Current backend profile management and default-selection behavior is documented in [`editorial-profile-behavior.md`](../content-settings/editorial-profile-behavior.md), while the current Settings navigation intentionally has no Editorial Profiles section ([source](../../frontend/features/settings/settings-sections.ts#L14)). This project does not restore that surface implicitly.

## Run and artifact linkage

`AutomationRun` has explicit foreign keys to `automation_id`, `automation_version_id`, and nullable unique `root_workflow_job_id`, plus trigger kind/metadata, dry-run flag, status/current node, immutable safe resource snapshot, timestamps, and safe error fields.

`AutomationNodeRun` is unique on `(automation_run_id, node_id, attempt)` and has nullable indexed foreign keys to the records that actually exist for that node: `workflow_job_id`, `automation_dispatch_id`, `research_run_id`, `generation_run_id`, `platform_variant_revision_id`, `publish_job_id`, and `publication_id`. It also stores status/timing, redacted input/output summaries, usage/cost where reliable, retry metadata, and safe errors.

`WorkflowJob` and `AutomationDispatch` receive nullable `automation_run_id`/`automation_node_run_id` foreign keys where they are created by the new compiler. `WorkflowEvent` continues to link through `workflow_job_id` and remains the append-only event truth; run views project events instead of copying them. Legacy history may temporarily derive relationships from dispatch and redacted JSON payload IDs, but new execution may not depend exclusively on JSON joins.

## Legacy migration and recovery

The next migration is additive and forward-oriented:

1. Create Automation, immutable AutomationVersion, AutomationTemplate, AutomationRuntimeProjection, AutomationRun, and AutomationNodeRun tables plus nullable run/node-run links and indexes. Do not change or drop current route/job/generation/publishing columns.
2. For each `AutomationRoute`, insert `Automation.id = AutomationRoute.id` and one legacy-compatible AutomationVersion. Store the existing route row as the runtime projection; do not copy or reset its cursor, next poll, activation state, pause time, retry time, dispatches, revisions, publish jobs, or publications.
3. Preserve active/paused/disabled lifecycle. Do not activate any record during migration. Adapters keep old `/telegram/automations/{same_uuid}` URLs working while new `/automations/{same_uuid}` reads the generalized definition.
4. Validate one-to-one backfill counts, public IDs, active/draft pointers, projection links, resource IDs, route state/cursor timestamps, dispatch ancestry, and publication ancestry before enabling generalized writes.

For a legacy `follow_active` route, the new version resolves and stores the currently active `telegram_rewrite` prompt-version ID and checksum at backfill time. The migration also records legacy prompt-policy provenance. It does **not** change `AutomationRoute.prompt_policy`, its current prompt fields, or any queued/running job. Jobs that already contain an exact snapshot continue unchanged; older queued jobs retain the current one-time `follow_active` resolution and persist that snapshot when they begin. Only new generic runs are pinned to the AutomationVersion. If no valid active prompt exists, the generalized version is retained as invalid/inactive while the legacy route continues unchanged.

Recovery policy:

- before generalized writes, a tested downgrade may remove only empty new tables/links;
- after any generalized definition or run exists, disable the new endpoints/compiler with a release flag and continue serving legacy projections; repair forward with a new migration;
- never roll back by deleting migrated route projections, rewriting applied migrations, resetting cursors, changing prompt snapshots, or removing dispatch/generation/publication ancestry;
- retain compatibility adapters until migration parity, PostgreSQL journeys, real browser journeys, and an explicit later removal decision all pass.

## Frontend reuse and UX contract

The existing frontend surface is reusable as follows:

| Area | Current source and reuse |
| --- | --- |
| Routes | `/automations`, `/automations/new`, `/automations/{routeId}`, and `/automations/{routeId}/history` in [`frontend/app/automations`](../../frontend/app/automations); retain URL reachability while generalized IDs reuse legacy route UUIDs. |
| Automation API/types | [`telegram-api.ts`](../../frontend/features/automations/telegram-api.ts) and [`telegram-types.ts`](../../frontend/features/automations/telegram-types.ts); keep as legacy adapters until generalized API parity passes. |
| Components | Route list, conservative route builder, route detail, and research outcome in [`features/automations`](../../frontend/features/automations); reuse lifecycle/status/error presentation, not the fixed form as the graph schema. |
| Query keys | Telegram route/options/dispatch/publication keys in [`query-keys.ts`](../../frontend/lib/query-keys.ts#L14); add separate `automations`, versions, catalog, templates, runs, and node-run keys without aliasing incompatible response shapes. |
| Settings resources | Current sections for providers, Codex, Telegram, Date & Time, Retention, and Prompts in [`settings-sections.ts`](../../frontend/features/settings/settings-sections.ts#L14); reuse exact deep links and provider/destination presentation. |
| Operations | [`operations-center.tsx`](../../frontend/features/operations/operations-center.tsx), [`history-timeline.tsx`](../../frontend/features/operations/history-timeline.tsx), and [`reconciliation-panel.tsx`](../../frontend/features/operations/reconciliation-panel.tsx); add explicit run/job/artifact deep links and retain focus restoration. |
| Primitives | Button, Card, Dialog, form controls, StatePanel, StatusBadge, Table, Tooltip, PageHeader, and semantic tokens in [`components/ui`](../../frontend/components/ui). |
| Responsive shell | [`newsroom-shell.tsx`](../../frontend/components/newsroom/newsroom-shell.tsx) owns the inner scrolling region, responsive navigation, safe areas, and mobile target sizing; the builder must not introduce a competing page scroll container. |
| Tests | API, builder, detail, Operations, shell, and mobile tests in [`frontend/tests`](../../frontend/tests), plus desktop/mobile and ambiguous-delivery coverage in [`telegram-automation.spec.ts`](../../frontend/e2e/telegram-automation.spec.ts). |

The first generalized UI has Workflows, Runs, and Templates only. It does not add empty Connections or Variables tabs. Desktop/tablet may use a three-panel node catalog/canvas/inspector. Mobile and all assistive-technology paths use a complete ordered-card editor with Add next step, choose input/output, move up/down, delete, and inspect actions; no operation requires dragging. The heavy canvas is dynamically loaded and the ordered editor remains the canonical accessible fallback.

Required UI behavior:

- server validation is authoritative; client validation gives immediate but non-final feedback;
- visible focus, full keyboard operation, logical focus restoration, `aria-live` status changes, and non-color status labels/icons;
- minimum 44px pointer targets, no horizontal page overflow at 320/375/390/414px, and reduced-motion support;
- existing light/dark semantic tokens, typography, radii, Lucide icons, and shell/navigation are preserved;
- semantic accents may distinguish trigger/success, AI/editorial, deterministic checks, publishing, blocking failure, and inactive/skipped states, but color is never the only signal;
- saved unavailable resources remain visible and actionable; there is no silent fallback;
- no credential field, raw prompt body, raw graph JSON editor, neon glow, default animated edges, or tiny canvas-only text.

Existing frontend tests cover secret-free API options, conservative builder defaults, route detail lifecycle, pause/resume/dry-run behavior, Operations focus/status, shell accessibility, mobile navigation, and desktop/mobile Telegram browser journeys. The generalized suite extends these patterns instead of replacing them.

## Named implementation and test surfaces

Phase 2 owns definition models/schemas/registry/validation/service/templates, the additive migration, generalized APIs, OpenAPI generation, TypeScript/query keys, and compatibility adapters. Phase 3 owns compiler/run-start/orchestration, run links, job registry additions, schedule and Telegram trigger adapters, pause/retry/idempotency integration, and live/dry-run PostgreSQL journeys. Phase 4 owns the client adapter, ordered editor, inspector, workflow/runs/templates views, and browser/accessibility/performance proof.

At minimum, later tests must cover:

- graph canonicalization, schema bounds, node config, typed ports/cardinality, entry/output, cycles/unreachable nodes, secret-shaped input rejection, and stable node-addressed errors;
- immutable versions, optimistic conflicts, templates, resource readiness/redaction, authorization, migration parity, and unchanged legacy cursor/artifact ancestry;
- deterministic compilation, unsupported branch rejection, run/node-run links, active-version pinning, schedule direct start, Telegram new-only capture, global/workflow pause, lease recovery, and idempotent replay;
- exact review, dry-run non-publishability, one durable publish intent, publishing-worker isolation, ambiguous-delivery reconciliation, and canary redaction;
- generated OpenAPI parity, mobile ordered editing, keyboard-only creation, screen-reader status/focus, 30-node canvas performance, dark/light themes, and 320–1440px overflow checks.

## Phase 1 verification record

Executed on 2026-08-01:

```bash
cd backend
timeout 60s env PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider \
  tests/test_telegram_route_api.py::test_activation_enqueues_initialization_without_backfill_or_network \
  tests/test_telegram_route_api.py::test_backfill_and_dry_run_enqueue_without_mutating_live_cursor \
  tests/test_telegram_route_handlers.py::test_initialize_captures_boundary_posts_and_arrivals_before_marking_ready \
  tests/test_telegram_route_handlers.py::test_poll_captures_source_edits_before_new_live_messages_in_ascending_order \
  tests/test_telegram_route_handlers.py::test_backfill_and_dry_run_are_review_only_and_cursor_independent \
  tests/test_telegram_process_handler.py::test_follow_active_resolves_once_and_persists_exact_job_prompt_snapshot \
  tests/test_telegram_process_handler.py::test_auto_publish_gate_is_fail_closed \
  tests/test_telegram_publish_service.py::test_service_evidence_validator_accepts_exact_nonempty_snapshot_without_http_errors \
  tests/test_telegram_publish_service.py::test_reconciliation_case_projection_is_strict_ordered_and_secret_free \
  tests/test_telegram_publish_service.py::test_reviewed_schedule_creates_identical_durable_due_times_and_one_redacted_event
# 18 passed in 1.60s

cd ../frontend
env -u NODE_ENV npm run test -- --run \
  tests/telegram-api.test.ts \
  tests/telegram-route-builder.test.tsx \
  tests/telegram-route-detail.test.tsx \
  tests/operations-center.test.tsx \
  tests/newsroom-shell.test.tsx \
  tests/mobile-nav.test.tsx
# 6 files, 42 tests passed in 4.47s
```

The focused commands selected existing tests for activation without network, dry-run/cursor separation, initialization boundary capture, poll ordering, prompt snapshot pinning, fail-closed auto-publication, evidence/reconciliation safety, schedule idempotency, API/query behavior, conservative builder defaults, route detail, Operations Center, shell, and mobile navigation. No credential or external network was used; no diagram dependency was installed; no migration was written or run.

Phase 2 and Phase 4 remain blocked on approval of this contract, node catalog, migration/recovery strategy, deferral list, ADR, and dependency decision.
