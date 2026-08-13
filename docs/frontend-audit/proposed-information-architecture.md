# Proposed personal-use information architecture

> **Superseded 2026-08-13 — historical record only.** This proposal was
> written against the pre-newsroom shell and its route names (`/inbox`,
> `/drafts`, `/library`, `/content`, `/runs`, `/media`), none of which
> exist today. The shipped navigation is Today (`/`), Sources
> (`/sources`), Feed (`/feed`), Automations (`/automations`), Operations
> Center (`/operations`), and Settings, defined in
> [`frontend/components/newsroom/newsroom-sidebar.tsx`](../../frontend/components/newsroom/newsroom-sidebar.tsx).
> Keep this file as the record of why that shell was chosen; do not read
> it as a description of the current information architecture.

## Design goal

Optimize the primary shell for one operator completing the common sequence:

```text
Collect → Inspect → Select → Research → Generate → Review → Publish/Export → Track
```

The proposal changes prominence and grouping, not backend capability or route availability.

## Primary navigation

### Today

Purpose: answer three questions quickly.

1. Is the system able to work?
2. What needs my decision now?
3. What is the next useful action?

Recommended content order:

- Compact health/pause banner with contextual recovery link.
- One primary action: Add story, Continue review, or Resolve attention based on persisted state.
- Decision queues: stories to select, drafts to review, publication handoffs due.
- Active/failed jobs only.
- Routine successes collapsed into recent activity.

### Inbox

Purpose: collect, inspect, select, research, and generate.

Recommended default sections:

- Needs decision.
- Ready to generate.
- Research in progress / incomplete.
- All stories and advanced filters.

Keep manual intake and grouping visible. Move repeated secondary actions into the expanded story panel where possible.

### Drafts

Purpose: review all generated packages and exact revisions.

Combine the navigation meaning of Drafts and Review & Publish:

- Needs review.
- Approved / ready for handoff.
- Failed generation requests.
- All drafts/history.

The `/review/[revisionId]` route remains the exact review/handoff detail route.

### Calendar

Purpose: see due Telegram schedules and manual publication plans.

Retain Month/List, timezone, platform, and persisted status filters.

### Library

Purpose: search and retrieve completed or historical persisted records.

Retain all seven record types, but make this clearly read-only and secondary to current work.

## Advanced navigation

### Collection

- Sources
- Raw Content
- Ingestion Runs
- Media

### Automation

- Telegram Automations
- Job Queue

### System

- Diagnostics
- Content Settings
- Retention

All current links and deep routes remain available. Advanced can be collapsed by default only after a visual checkpoint confirms that recovery access is still obvious when attention exists.

## Contextual cross-links

- Source failure on Today → exact source detail, not generic Diagnostics.
- Failed workflow job → exact Job Queue detail.
- Story evidence → original Content/Library record.
- Draft validation/media problem → exact advanced section in the workspace.
- Publication blocker → the exact control, destination, route, or reconciliation action.
- Healthy technical details → Advanced section; unhealthy details → surfaced contextually.

## Terminology

| Current term | Primary-interface wording | Advanced/internal wording |
| --- | --- | --- |
| Content Items | Raw Content | Content item |
| Job Queue | Activity / Jobs | Workflow job |
| Ingestion Runs | Collection Runs | Ingestion run |
| Content pack | Draft package | Content pack |
| Platform variant revision | Revision | Platform variant revision |
| Evidence key / hash | Evidence details | Preserve exact keys/hashes inside expanded audit detail |
| Telegram automations | Automations | Telegram route/dispatch in detail views |

Terminology changes must be applied incrementally and verified against runbooks/tests before implementation.

## Page-level progressive disclosure

### Editorial studio default

- Platform selector.
- Preview.
- Validation summary and blockers.
- Evidence excerpts/links.
- Primary decision controls: edit, approve/reject, handoff.

### Editorial studio expanded sections

- Exact payload metadata.
- Evidence keys and hashes.
- Immutable revision ancestry.
- Copy/export formats.
- Regeneration provider/prompt settings.
- Media source internals.

These sections remain loaded from the same APIs; disclosure is a frontend presentation decision only.

## Responsive model

Keep the mobile bottom bar limited to:

- Today
- Inbox
- Drafts
- Menu

Calendar and Library remain one tap away in Menu. Advanced groups appear after the workflow group. The current focus trap, Escape handling, focus restoration, and 44×44 targets must remain.

## Explicit non-goals

- No route deletion.
- No API, schema, worker, scheduler, job, approval, revision, export, or publishing changes.
- No automatic publication expansion.
- No credential handling changes.
- No merge of backend entities merely because their user-facing concepts overlap.

