# Phase 11 — Story Inbox Large-List Performance

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — HEALTHY-HARDWARE BROWSER BUDGET EXECUTION PENDING
- **Starting revision:** `b8703c2` on `phase-11-story-inbox-performance`
- **Authoritative source:** `solutions.md`, Phase 11
- **Prerequisites:** Phase 7's nightly runner, Phase 8's frozen frontend dependencies, Phase 10's typed cursor contract, and Phase 12's accessibility coverage are present.

The scaling defect was confirmed directly in source. The Inbox requested 200 stories, appended every cursor page into an unbounded DOM, stored selected IDs in an array, performed `includes` for each rendered row, and passed new closures to every non-memoized row on each parent render. The audit's 201-row Vitest case therefore exercised a real scaling problem even though host contention contributed to its timeout.

## Implementation

- The server request and rendered page are capped at 100 stories. A defensive client-side slice also bounds the DOM if a nonconforming backend returns more than requested.
- Cursor navigation replaces the current page instead of appending it. Selection remains global across pages and is capped at 200 IDs.
- Selection is an immutable `ReadonlySet<string>` in React state. Membership and individual toggles are constant-time; arrays are derived only at the bulk API boundary.
- `StoryRow` is memoized. Select, open, research, and state-change handlers are stable ID-based callbacks, so a selection change does not invalidate every unchanged row's props.
- The selection summary is a polite live region and explicitly tells operators that the 200-item cap applies across pages.
- Filter changes cancel stale page results, clear the global selection, and restore the bounded first page. A failed next-page request preserves the current page and exposes a retryable error.
- The old 201-row JSDOM watchdog was replaced by bounded-page/cross-page correctness coverage at the normal test timeout. It proves the 100-row DOM bound, 200-ID cap, selection retention on failed bulk mutation, third-page behavior, filter cancellation, and next-page failure behavior.
- The strict shared browser mock now implements cursor/limit/search behavior and never returns more than 100 stories.
- A production-browser Playwright budget covers 200, 1,000, and 10,000 available stories. It enforces a 100-row DOM, <=1.5 s response-to-usable page, <=100 ms select-page and single-toggle paint feedback, correct page replacement, and a 200-ID cross-page selection.
- The Phase 7 nightly performance job now runs both the correctness suite and the dedicated Chromium budget rather than treating Vitest wall-clock time as a production performance measurement.

Pagination was chosen over virtualization because it meets the explicit <=100 rendered-row acceptance limit without introducing dynamic-row measurement, deep-link focus, or screen-reader semantics risk. No new runtime dependency was needed.

## Files

- `frontend/components/editorial/story-inbox.tsx`
- `frontend/tests/story-inbox.test.tsx`
- `frontend/e2e/story-inbox-performance.spec.ts`
- `frontend/e2e/support/mock-backend.ts`
- `.github/workflows/nightly.yml`
- `backend/tests/test_ci_workflows.py`
- this report

## Code-level evidence

- `STORY_INBOX_PAGE_SIZE` is 100 and is used at both the API boundary and rendered-page boundary.
- `MAX_STORY_SELECTION` is 200 and every individual/page selection path refuses to exceed it.
- Page replacement uses `boundedStoryPage(next.items)`; the previous append-and-deduplicate path is absent.
- Row selection uses `selected.has(story.id)` and `StoryRow` is wrapped in `memo` with stable handlers.
- The browser fixture exposes only the requested cursor slice even when 10,000 stories are available.
- `git diff --check` passes and source scans find no old 200-row request, append-only pagination label, array-length selection state, or `selected.includes` path.

The user identified faulty CPU/RAM and explicitly directed that host-dependent test execution stop. Consequently, Node/V8, Next.js, and Chromium commands were not retried on this host. The new correctness and browser gates are committed for execution on healthy CI hardware; this report does not claim fabricated latency, frame-rate, Vitest, typecheck, or browser results.

## Acceptance and Definition of Done

- [x] Selection membership and updates no longer scale linearly per row.
- [x] Unchanged rows receive stable props and can skip parent selection commits.
- [x] Explicit cursor pagination bounds the rendered DOM to <=100 rows.
- [x] Selection remains global across pages, capped at 200, announced, and retained after a failed bulk action.
- [x] Deep-link evidence behavior remains on the bounded first page; filter and out-of-order cursor behavior retain regression coverage.
- [x] Normal-timeout correctness tests and 200/1k/10k production-browser budgets are encoded in scheduled CI.
- [ ] Healthy-hardware Vitest/typecheck/Chromium execution and recorded 200/1k/10k latency measurements are pending by explicit user direction.
- [ ] Manual 200% zoom and screen-reader confirmation remains part of the Phase 12 release checklist on healthy hardware.

## Risks and rollback

- Cursor navigation is intentionally explicit and page-replacing; operators do not get continuous accumulated scrolling. This is the accepted bounded-memory policy.
- React Query may retain fetched responses in its normal query cache, but the component DOM and component-owned story state remain bounded to one page.
- The nightly latency thresholds should be calibrated only from a stable healthy runner. A failing budget must trigger profiling; it must not be "fixed" by raising the old Vitest timeout.
- Rollback may retain the Set/memo improvements even if the pagination presentation changes. Do not restore append-only DOM growth.

The pre-existing untracked root `AGENTS.md` remains excluded and untouched. No Phase 13–15 behavior was implemented.
