# Frontend refactor roadmap

Every milestone is a review checkpoint. Do not continue into the next subjective milestone without operator feedback.

## Phase 0 — Stabilize validation signals

Objective: make failures attributable before UI refactoring.

- Resolve the React/Vitest `React.act` test-runtime incompatibility.
- Resolve `mobile-nav.test.tsx` importing `node:` in the browser-transformed test context.
- Update deterministic browser fixtures for `GET /telegram/reconciliation`.
- Update Diagnostics E2E expectations to the current rendered contract.
- Configure this host to run Playwright reliably (prefer one worker when Chromium uses `--single-process`).

Backend impact: None.

Checkpoint: unit and targeted E2E baseline is trustworthy.

## Phase 1 — Group navigation without removing access

Objective: reduce the 15-item scan while preserving every route.

- Add visible Workflow and Advanced group labels.
- Keep existing route labels and destinations for the first iteration.
- Place Today, Inbox, Drafts, Review & Publish, Calendar, and Library in Workflow.
- Place Jobs, Automations, Sources, Content, Ingestion Runs, Media, Diagnostics, Content Settings, and Retention in Advanced subsections.
- Preserve active state, keyboard order, mobile dialog focus behavior, and deep links.
- Do not collapse or hide Advanced in the first review build.

Expected files:

- `frontend/components/newsroom/newsroom-sidebar.tsx`
- `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- `frontend/tests/navigation.test.tsx`
- `frontend/tests/mobile-nav.test.tsx`
- relevant Playwright navigation/accessibility specs

Backend impact: None.

Checkpoint URL: `/` at desktop and 390px.

## Phase 2 — Make Today a workflow launchpad

Objective: show the next editorial decision without weakening operational truth.

- Keep global pause/dry-run state visible but compact.
- Add contextual Add story / Continue review / Resolve attention action.
- Prioritize decision queues over routine success history.
- Link each failure to the narrowest recovery surface.
- Preserve manual intake availability while automation is paused.

Backend impact: Read-only API usage change unless existing intake modal is reused directly.

Checkpoint URL: `/` with paused, active, empty, attention, and populated fixtures.

## Phase 3 — Focus the Inbox

Objective: reduce repetitive actions and surface actionable stories.

- Establish an evidence-backed default view such as Needs decision.
- Make completeness, recency, language, and recommended next action scannable.
- Keep bulk selection and pagination.
- Move secondary per-row actions into expanded detail where safe.
- Preserve deep links to exact evidence and research runs.

Backend impact: Existing mutations only; possible read-only query filter changes.

Checkpoint URL: `/inbox` with empty, mixed-language populated, loading, error, and selected states.

## Phase 4 — Unify draft/review navigation semantics

Objective: make Drafts the single list entry for generated work while keeping exact review routes.

- Add Needs review, Ready for handoff, Failed requests, and All sections.
- Treat Review & Publish as a filtered state within Drafts rather than a competing top-level concept, subject to operator approval.
- Keep `/review/[revisionId]` and all deep links intact.
- Verify legacy Telegram drafts remain reachable.

Backend impact: Read-only API usage/filter change; existing mutation UI unchanged.

Checkpoint URLs: `/drafts`, `/drafts/[packId]`, `/review/[revisionId]`.

## Phase 5 — Progressive disclosure in the editorial studio

Objective: emphasize the exact review decision while retaining audit/recovery detail.

- Default to preview, validation/blockers, evidence excerpts, editing, and decision controls.
- Collapse healthy payload metadata, hashes, provider/prompt provenance, export formats, regeneration settings, and media internals into labeled sections.
- Automatically expand a section when it contains a failure or required action.
- Preserve exact revision ID, content hash, immutable child creation, stale-conflict handling, and dirty-navigation fencing.

Backend impact: Existing mutation UI change only; no contract change.

Checkpoint URL: a populated `/drafts/[packId]` and `/review/[revisionId]` on desktop/mobile.

## Phase 6 — Contextual diagnostics and terminology

Objective: keep technical details near the problem while reducing primary-interface jargon.

- Add precise recovery links from Today and affected records.
- Rename primary labels only after route semantics are verified.
- Keep raw identifiers in Advanced details and copyable audit fields.
- Reassess whether dedicated Runs and Media navigation entries are still necessary; do not remove them without endpoint/access/test verification.

Backend impact: None or read-only API usage change.

Checkpoint: all affected routes plus recovery drills.

## Recommended first bounded change

Implement **Phase 1 only**: add Workflow and Advanced grouping to desktop and mobile navigation while keeping every existing link visible and keeping labels/routes unchanged.

Why this is first:

- It directly addresses the most obvious cognitive-load issue.
- It is presentation-only with no backend impact.
- It is easy to compare before/after.
- It does not require deciding the final landing page or hiding any capability.
- It creates the hierarchy needed for later Today and Inbox improvements.

Validation plan for that iteration:

```bash
cd frontend
npm run typecheck
npm run test -- tests/navigation.test.tsx tests/mobile-nav.test.tsx tests/newsroom-shell.test.tsx
npm run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/armin/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npx playwright test e2e/dashboard.spec.ts e2e/accessibility.spec.ts --workers=1
```

Manual review:

1. Open `/` at desktop width and confirm the workflow hierarchy is immediately understandable.
2. Open every existing navigation destination once.
3. At 390px, open Menu and confirm the same grouping and scroll access.
4. Verify active states on `/review/[revisionId]`, `/settings/content`, and `/settings/retention`.
5. Verify keyboard focus, Escape, backdrop close, and focus restoration.

