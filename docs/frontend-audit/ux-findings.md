# UX findings

> **Superseded 2026-08-13 — historical record only.** These findings were
> recorded against the pre-newsroom shell: the 15-destination navigation
> and the `/inbox`, `/drafts`, `/library`, `/content`, `/runs`, `/media`
> routes they cite no longer exist. The shipped navigation is Today,
> Sources, Feed, Automations, Operations Center, and Settings
> ([`newsroom-sidebar.tsx`](../../frontend/components/newsroom/newsroom-sidebar.tsx)).
> Individual findings may still be open, but every route and screen
> reference below must be re-checked against the current shell first.

## Summary

The frontend is functionally broad and unusually careful about durable truth, exact revisions, failure states, RTL content, and guarded publication. Its primary usability problem is hierarchy: daily editorial actions, implementation-level diagnostics, automation administration, and destructive settings are presented with similar weight.

## High-priority findings

### 1. The first screen does not expose the editorial starting point

Evidence:

- `/` begins with Automation controls.
- When paused, Resume automations is the visually dominant action.
- Add story and Group pending content only exist after navigating to Inbox.
- The subtitle says Today shows “the work that needs an operator,” but it does not explain the normal workflow.

Impact: a first-time operator may reasonably conclude that resuming automation is required before doing any useful work, even though manual intake remains available while paused.

Recommendation: make the next editorial action visible from Today. Do not change pause semantics.

### 2. Navigation has 15 equal-weight destinations

Evidence:

- Desktop sidebar shows all 15 links in one long list with only one separator before Sources.
- The mobile Menu dialog repeats all 15 links.
- Primary work, read-only history, raw ingestion, diagnostics, configuration, and retention are peers.

Impact: high recognition and scanning cost; unclear distinction between “do today’s work” and “operate/debug the system.”

Recommendation: preserve every route but group them as Workflow and Advanced. Do not delete or silently hide recovery functions.

### 3. The Inbox is a very long, visually repetitive stream

Evidence:

- The populated screenshot spans many viewport heights.
- Each story repeats Shortlist, Reject, Research more, and Open editorial studio.
- Completeness and evidence counts are present, but priority and recommended next action are not dominant.
- The default feed mixes languages, topics, and completion states.

Impact: selection fatigue; the operator must evaluate too many equal candidates before finding actionable stories.

Recommendation: introduce a focused default such as Needs decision / Ready to generate, retain filters and pagination, and move secondary actions into the expanded story detail.

### 4. The editorial studio exposes every expert control at once

Evidence:

- One page shows preview, exact payload internals, citations, copy/export, evidence, evidence hashes, immutable revision history, editor, buttons, media assignments, approval/rejection, regeneration provider/prompt inputs, and media plan.
- Long hashes and backend provenance are visually prominent even when validation passes.

Impact: the main decision—Is this exact revision ready?—is diluted by audit and regeneration details.

Recommendation: keep exact truth accessible, but disclose advanced evidence hashes, export options, regeneration settings, and media internals contextually. Preserve exact revision/hash semantics.

### 5. Workflow concepts are split across overlapping labels

Examples:

- Content versus Inbox versus Library Originals.
- Drafts versus Review & Publish versus exact Review.
- Job Queue versus Ingestion Runs.
- Diagnostics versus source health on Sources.

Impact: operators must learn backend object boundaries before they can predict where a record lives.

Recommendation: use workflow language in primary navigation; explain technical record types inside Advanced pages.

## Medium-priority findings

### Today is dominated by retrospective operational data

Recent successes can become a long list, while the next useful editorial action is absent. Collapse routine successes behind a count or “View activity”; keep failures and active work visible.

### Technical identifiers leak into primary work

The editorial studio subtitle shows a pack UUID; evidence keys, snapshot IDs, hashes, provider type, model, and schema gate appear inline. These are valuable for audit/recovery but should be secondary unless a mismatch or failure exists.

### Status duplication does not establish a triage owner

Queue/attention appears in the header/sidebar, Today, Jobs, and Diagnostics. Keep the cross-links but choose Today as the human triage summary, Jobs as execution truth, and Diagnostics as system health/recovery.

### Primary actions vary unpredictably by page

Sources has Seed sources and Run ingest; Inbox has Group pending and Add story; Today has Resume automations; Content repeats Approve per row. Page-level guidance is sparse, so operators must infer the safe order.

### Route-level loading UI is inconsistent

Most loading is component-local. There are no App Router `loading.tsx` files. Existing local states are truthful, but navigation can briefly show old shell content without a page-level transition indicator.

## Strengths to preserve

- One main landmark and a working skip link.
- Active navigation states and deep-linkable routes.
- Focus-managed mobile navigation and dialogs.
- No horizontal overflow in live desktop or 390px inspection.
- 44×44 mobile Inbox action targets are covered by Playwright.
- Persisted language/direction boundaries support Persian and mixed-language content.
- Loading, empty, error, and retry states are generally distinct.
- API failures do not invent successful state.
- Dirty-navigation protection prevents losing unsaved exact edits.
- Immutable revision lineage and exact hash approval are visible.
- Approximation previews are labeled honestly.
- Manual-only publishing boundaries for Instagram/X/blog are explicit.
- Global pause, route readiness, destination health, dry-run, research, and media blockers fail closed.

## Live defect and test observations

- No browser console errors were observed.
- No failed live API responses were observed during the ten-route audit.
- The current Diagnostics/source errors are persisted product data, not rendering failures.
- The unit suite is not currently a reliable UI regression signal because of the React test-runtime mismatch.
- E2E fixtures have drifted from the frontend’s reconciliation and Diagnostics requests/copy.
- Multi-worker single-process Chromium is unstable on this host; one-worker runs should be used for dependable local browser evidence until the environment is corrected.

