# Release 0 Truthful Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the validated cleanup already in the worktree and establish a clean, truthful, repeatable baseline before adding scheduling, AI generation, and Telegram publishing.

**Architecture:** Keep the existing FastAPI/PostgreSQL ingestion core and Next.js operations pages, but make every normal frontend route fetch real data immediately, expose the provenance already stored by the backend, remove invented operational values, and make local verification deterministic. This release deliberately avoids new workflow tables or product features; it produces a reliable base for the first Telegram vertical slice.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2, Pydantic 2, PostgreSQL 18, pytest, Ruff, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright, Docker Compose.

## Global Constraints

- Product mode is local and single operator; no authentication or RBAC is introduced.
- Preserve the existing passing ingestion, normalization, media, classification, scoring, and diagnostics behavior.
- Normal runtime must never display mock data or fabricated health, source, schedule, or time values.
- API, frontend, and PostgreSQL host ports bind to `127.0.0.1` by default.
- Secrets and `.superpowers/` companion output remain outside Git.
- Existing unrelated untracked file `refactor.txt` is not staged or deleted.
- Every task uses test-first changes where behavior changes and ends in an independently reviewable commit.

---

### Task 1: Checkpoint the validated cleanup without unrelated artifacts

**Files:**
- Preserve all currently modified and deleted tracked cleanup files shown by `git status --short`.
- Add: `backend/.dockerignore`
- Add: `frontend/lib/empty-data.ts`
- Exclude: `.superpowers/`
- Exclude: `refactor.txt`

**Interfaces:**
- Consumes: the current `refactor-cleanup` worktree with validated runtime-preserving deletions.
- Produces: one isolated cleanup commit and a worktree where later behavioral fixes have a clear diff base.

- [ ] **Step 1: Re-run the cleanup verification baseline**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
cd ../frontend
npm run test
cd ..
docker compose config >/tmp/newscraft-compose-release0.yml
```

Expected:

```text
140 passed
All checks passed!
8 test files passed, 35 tests passed
docker compose config exits 0
```

- [ ] **Step 2: Verify the existing cleanup diff and exclusions**

Run:

```bash
git diff --shortstat
git status --short
```

Expected cleanup evidence before new Release 0 behavior changes:

```text
46 files changed, 666 insertions(+), 8092 deletions(-)
```

Confirm `.superpowers/` and `refactor.txt` are untracked and will remain unstaged.

- [ ] **Step 3: Stage only the validated cleanup**

Run:

```bash
git add -u
git add backend/.dockerignore frontend/lib/empty-data.ts
git diff --cached --name-only
```

Expected: the staged list contains the tracked cleanup plus the two named new runtime files, and does not contain `.superpowers/` or `refactor.txt`.

- [ ] **Step 4: Commit the cleanup checkpoint**

Run:

```bash
git commit -m "refactor: remove dead artifacts and runtime mocks"
```

Expected: commit succeeds and the three excluded paths remain untracked.

---

### Task 2: Make empty placeholders fetch live backend data immediately

**Files:**
- Modify: `frontend/components/dashboard/dashboard-shell.tsx`
- Modify: `frontend/components/dashboard/pages/operations-page-frame.tsx`
- Modify: `frontend/components/dashboard/pages/sources-page.tsx`
- Modify: `frontend/components/dashboard/pages/runs-page.tsx`
- Modify: `frontend/components/dashboard/pages/content-items-page.tsx`
- Modify: `frontend/components/dashboard/pages/media-assets-page.tsx`
- Modify: `frontend/tests/operation-pages.test.tsx`
- Create: `frontend/tests/live-data-queries.test.tsx`

**Interfaces:**
- Consumes: existing `getDashboardSnapshot()`, `getDashboardSummary()`, `getSources()`, `getIngestRuns()`, `getContentItems()`, and `getMediaAssets()` API functions.
- Produces: optional `enableQueries?: boolean` component props defaulting to `true`; empty arrays/counts are `placeholderData`, never fresh `initialData`.

- [ ] **Step 1: Write failing live-query regression tests**

Create `frontend/tests/live-data-queries.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, waitFor } from "@testing-library/react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { ContentItemsPage } from "@/components/dashboard/pages/content-items-page"
import { DiagnosticsPage } from "@/components/dashboard/pages/diagnostics-page"
import { MediaAssetsPage } from "@/components/dashboard/pages/media-assets-page"
import { RunsPage } from "@/components/dashboard/pages/runs-page"
import { SourcesPage } from "@/components/dashboard/pages/sources-page"
import { emptyDashboardSnapshot } from "@/lib/empty-data"
import {
  getContentItems,
  getDashboardSnapshot,
  getDashboardSummary,
  getDiagnostics,
  getIngestRuns,
  getMediaAssets,
  getSources,
} from "@/lib/api-client"

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")
  return {
    ...actual,
    getDashboardSnapshot: vi.fn(async () => emptyDashboardSnapshot),
    getDashboardSummary: vi.fn(async () => emptyDashboardSnapshot.counts),
    getContentItems: vi.fn(async () => []),
    getDiagnostics: vi.fn(async () => ({ status: "ok", checks: {}, sourceHealth: {}, problemSources: [] })),
    getIngestRuns: vi.fn(async () => []),
    getMediaAssets: vi.fn(async () => []),
    getSources: vi.fn(async () => []),
  }
})

describe("live data queries", () => {
  beforeEach(() => vi.clearAllMocks())

  it("fetches the dashboard immediately when empty data is only a placeholder", async () => {
    renderWithClient(<DashboardShell initialData={emptyDashboardSnapshot} />)

    await waitFor(() => expect(getDashboardSnapshot).toHaveBeenCalledTimes(1))
  })

  it("fetches content immediately when the route starts with an empty placeholder", async () => {
    renderWithClient(<ContentItemsPage initialItems={[]} />)

    await waitFor(() => expect(getContentItems).toHaveBeenCalledTimes(1))
    expect(getDashboardSummary).toHaveBeenCalledTimes(1)
  })

  it.each([
    ["sources", <SourcesPage initialSources={[]} />, getSources],
    ["runs", <RunsPage initialRuns={[]} />, getIngestRuns],
    ["media", <MediaAssetsPage initialMedia={[]} />, getMediaAssets],
    ["diagnostics", <DiagnosticsPage />, getDiagnostics],
  ])("fetches %s immediately when the route starts empty", async (_name, page, request) => {
    renderWithClient(page)

    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
  })
})

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000 } },
  })
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
}
```

- [ ] **Step 2: Run the new tests and verify the regression**

Run:

```bash
cd frontend
npx vitest run tests/live-data-queries.test.tsx
```

Expected: FAIL because normal test-mode queries are disabled and empty `initialData` suppresses the immediate request.

- [ ] **Step 3: Replace fresh initial data with query placeholders**

In `frontend/components/dashboard/dashboard-shell.tsx`, make normal queries enabled by default and replace `initialData`:

```tsx
export function DashboardShell({
  initialData,
  enableQueries = true,
}: {
  initialData: DashboardSnapshot
  enableQueries?: boolean
})
```

Replace the dashboard query with:

```tsx
const dashboardQuery = useQuery({
  queryKey: queryKeys.dashboardSnapshot,
  queryFn: getDashboardSnapshot,
  placeholderData: initialData,
  enabled: enableQueries,
  refetchInterval: 30_000,
})
```

In `frontend/components/dashboard/pages/operations-page-frame.tsx`, add `enableQueries = true` to the destructured props and `enableQueries?: boolean` to the prop type, then replace the summary query with:

```tsx
const countsQuery = useQuery({
  queryKey: queryKeys.dashboardSummary,
  queryFn: getDashboardSummary,
  placeholderData: emptyDashboardCounts,
  enabled: enableQueries,
})
```

In `frontend/components/dashboard/pages/sources-page.tsx`, use:

```tsx
export function SourcesPage({
  initialSources = [],
  enableQueries = true,
}: {
  initialSources?: SourceSummary[]
  enableQueries?: boolean
})
```

Replace the source list query with:

```tsx
const sourcesQuery = useQuery({
  queryKey: queryKeys.sources,
  queryFn: getSources,
  placeholderData: initialSources,
  enabled: enableQueries,
})
```

In the source detail query, replace `enabled: Boolean(selectedSourceId) && process.env.NODE_ENV !== "test"` with `enabled: Boolean(selectedSourceId) && enableQueries`, and replace `initialData: selectedSource` with `placeholderData: selectedSource`.
Pass `enableQueries={enableQueries}` to `OperationsPageFrame`.

In `frontend/components/dashboard/pages/runs-page.tsx`, use:

```tsx
export function RunsPage({
  initialRuns = [],
  enableQueries = true,
}: {
  initialRuns?: IngestionRunSummary[]
  enableQueries?: boolean
})
```

Replace the runs query with:

```tsx
const runsQuery = useQuery({
  queryKey: queryKeys.runs,
  queryFn: getIngestRuns,
  placeholderData: initialRuns,
  enabled: enableQueries,
})
```

Pass `enableQueries={enableQueries}` to `OperationsPageFrame`.

In `frontend/components/dashboard/pages/content-items-page.tsx`, use:

```tsx
export function ContentItemsPage({
  initialItems = [],
  enableQueries = true,
}: {
  initialItems?: ContentQueueItem[]
  enableQueries?: boolean
})
```

Replace the content list query with:

```tsx
const contentQuery = useQuery({
  queryKey: [...queryKeys.contentItems, filters],
  queryFn: () => getContentItems(filters),
  placeholderData: initialItems,
  enabled: enableQueries,
})
```

In the content detail query, replace `enabled: Boolean(selectedItemId) && process.env.NODE_ENV !== "test"` with `enabled: Boolean(selectedItemId) && enableQueries`, and replace `initialData: selectedListItem` with `placeholderData: selectedListItem`.
Pass `enableQueries={enableQueries}` to `OperationsPageFrame`.

In `frontend/components/dashboard/pages/media-assets-page.tsx`, use:

```tsx
export function MediaAssetsPage({
  initialMedia = [],
  enableQueries = true,
}: {
  initialMedia?: MediaTile[]
  enableQueries?: boolean
})
```

Replace the media query with:

```tsx
const mediaQuery = useQuery({
  queryKey: queryKeys.media,
  queryFn: getMediaAssets,
  placeholderData: initialMedia,
  enabled: enableQueries,
})
```

Pass `enableQueries={enableQueries}` to `OperationsPageFrame`.

Update `frontend/tests/operation-pages.test.tsx` to pass `enableQueries={false}` to `SourcesPage`, `RunsPage`, `ContentItemsPage`, and `MediaAssetsPage`. Add a `getDashboardSummary` mock returning `dashboardMock.counts` for the existing diagnostics-page test. These component tests intentionally render fixed fixtures; `live-data-queries.test.tsx` owns the normal-runtime query behavior.

- [ ] **Step 4: Run focused and full frontend tests**

Run:

```bash
cd frontend
npx vitest run tests/live-data-queries.test.tsx tests/dashboard-shell.test.tsx tests/operation-pages.test.tsx
npm run test
```

Expected: focused tests pass and the full suite passes with 41 tests.

- [ ] **Step 5: Commit immediate live queries**

Run:

```bash
git add frontend/components/dashboard/dashboard-shell.tsx \
  frontend/components/dashboard/pages/operations-page-frame.tsx \
  frontend/components/dashboard/pages/sources-page.tsx \
  frontend/components/dashboard/pages/runs-page.tsx \
  frontend/components/dashboard/pages/content-items-page.tsx \
  frontend/components/dashboard/pages/media-assets-page.tsx \
  frontend/tests/live-data-queries.test.tsx frontend/tests/operation-pages.test.tsx
git commit -m "fix: fetch live dashboard data from empty placeholders"
```

---

### Task 3: Expose truthful provenance and remove invented operational facts

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/test_api_content_intelligence.py`
- Modify: `frontend/lib/api-client.ts`
- Modify: `frontend/lib/format.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/mock-data.ts`
- Modify: `frontend/components/dashboard/source-icon.tsx`
- Modify: `frontend/components/dashboard/source-health-table.tsx`
- Modify: `frontend/components/dashboard/top-status-bar.tsx`
- Modify: `frontend/components/dashboard/dashboard-shell.tsx`
- Modify: `frontend/components/dashboard/source-detail-panel.tsx`
- Modify: `frontend/components/dashboard/pages/content-items-page.tsx`
- Modify: `frontend/tests/api-client.test.ts`
- Modify: `frontend/tests/dashboard-shell.test.tsx`
- Create: `frontend/tests/format.test.ts`
- Modify: `frontend/tests/operation-pages.test.tsx`
- Modify: `frontend/tests/source-detail-panel.test.tsx`
- Modify: `frontend/tests/source-health-table.test.tsx`

**Interfaces:**
- Consumes: `ContentItem.content_text`, `authors`, `published_at`, `primary_source_id`, and `classification_metadata` already stored by ingestion.
- Produces: those fields in `ContentItemOut`; `ContentQueueItem.contentText`, `publishedAt`, `authors`, and truthful source identity; `TopStatusBar.connectionState` and `lastRunLabel` props.

- [ ] **Step 1: Write failing backend provenance response test**

Add to `backend/tests/test_api_content_intelligence.py`:

```python
def test_content_item_schema_exposes_generation_evidence_and_source_metadata():
    source_id = uuid4()
    item = SimpleNamespace(
        id=uuid4(),
        item_type="telegram_post",
        title="Source post",
        summary="Short summary",
        content_text="Complete source post body",
        content_html_sanitized="<p>Complete source post body</p>",
        canonical_url="https://t.me/source/42",
        language_code="fa",
        direction="rtl",
        authors=["Source Channel"],
        published_at=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        primary_source_id=source_id,
        status="new",
        score=80,
        tags=["news"],
        metrics={},
        sort_at=datetime(2026, 7, 11, 8, 0, tzinfo=UTC),
        primary_image_id=None,
        primary_media=None,
        content_type="news",
        rewrite_bucket="daily_news",
        is_rewrite_ready=True,
        rewrite_ready_reason="ready",
        rewrite_blockers=[],
        classification_reasons=["news signal"],
        classification_metadata={"source_name": "Source Channel", "source_platform": "telegram_public"},
        source_tier="tier_b",
        freshness_bucket="fresh",
        quality_status="needs_review",
        score_breakdown={},
    )

    payload = ContentItemOut.model_validate(item).model_dump()

    assert payload["content_text"] == "Complete source post body"
    assert payload["content_html_sanitized"] == "<p>Complete source post body</p>"
    assert payload["authors"] == ["Source Channel"]
    assert payload["published_at"] == datetime(2026, 7, 11, 8, 0, tzinfo=UTC)
    assert payload["primary_source_id"] == source_id
    assert payload["classification_metadata"]["source_name"] == "Source Channel"
```

The module already imports `UTC`, `datetime`, `SimpleNamespace`, `uuid4`, and `ContentItemOut`; do not duplicate those imports.

- [ ] **Step 2: Run the backend test and verify it fails**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_content_intelligence.py::test_content_item_schema_exposes_generation_evidence_and_source_metadata -q
```

Expected: FAIL because `ContentItemOut` does not expose the evidence and provenance fields.

- [ ] **Step 3: Extend `ContentItemOut` with stored evidence fields**

Add these fields to `ContentItemOut` in `backend/app/api/schemas.py`:

```python
content_text: str | None = None
content_html_sanitized: str | None = None
authors: list[str] = Field(default_factory=list)
published_at: datetime | None = None
primary_source_id: UUID | None = None
classification_metadata: dict[str, Any] = Field(default_factory=dict)
```

Run the focused test again and expect PASS.

- [ ] **Step 4: Write failing frontend mapping and truthfulness tests**

Extend `frontend/tests/api-client.test.ts` with:

```tsx
it("maps real source provenance and complete content without inventing RSS", async () => {
  stubFetch([
    {
      id: "item-telegram-42",
      item_type: "telegram_post",
      title: "Source post",
      summary: "Short summary",
      content_text: "Complete source post body",
      canonical_url: "https://t.me/source/42",
      language_code: "fa",
      direction: "rtl",
      authors: ["Source Channel"],
      published_at: "2026-07-11T08:00:00Z",
      status: "new",
      sort_at: "2026-07-11T08:00:00Z",
      classification_metadata: {
        source_name: "Source Channel",
        source_platform: "telegram_public",
      },
    },
  ])

  await expect(getContentItems()).resolves.toEqual([
    expect.objectContaining({
      sourceName: "Source Channel",
      sourcePlatform: "telegram_public",
      contentText: "Complete source post body",
      direction: "rtl",
      authors: ["Source Channel"],
      publishedAt: "2026-07-11T08:00:00Z",
    }),
  ])
})

it("does not invent a next run before the scheduler exists", async () => {
  stubFetch([{ id: "source-1", platform: "rss", name: "Feed", feed_url: "https://example.com/rss", fetch_interval_minutes: 1440 }])

  const [source] = await getSources()

  expect(source).toEqual(expect.objectContaining({ fetchIntervalMinutes: 1440 }))
  expect(source).not.toHaveProperty("nextRun")
})
```

Update `frontend/tests/dashboard-shell.test.tsx` to assert `Backend connected` for populated data and `Backend unavailable` after query failure, and remove assertions for hard-coded `PostgreSQL` and `Proxy` cells.

Update `frontend/tests/source-detail-panel.test.tsx` to assert a real `Fetch interval` row and to assert there are no `Settings`, `History`, or `Logs` tabs.

Add table-driven mapping cases to `frontend/tests/api-client.test.ts` for `rss`, `atom`, `telegram_public`, `google_news`, `gdelt`, `hackernews`, and an unsupported value. Assert the six supported values survive unchanged and the unsupported value becomes `unknown`; no value may be silently relabeled as RSS or Telegram. Also assert mapped sources do not expose invented `parser` or `deduplication` fields. Add a source-detail case that renders an unknown platform as `Unknown source`.

Add API-client regression cases proving `last_success_at` retains its calendar date and an ingestion run label uses its actual formatted date rather than always starting with `Today`.

Create `frontend/tests/format.test.ts` with a table-driven assertion that `formatPlatform` returns `RSS`, `Atom`, `Telegram`, `Google News`, `GDELT`, `Hacker News`, and `Unknown` for the corresponding seven inputs.

In the content-page case in `frontend/tests/operation-pages.test.tsx`, add `contentText: "Complete source post body"`, `direction: "rtl"`, `sourceName: "Source Channel"`, `sourcePlatform: "telegram_public"`, `authors: ["Source Channel"]`, and `publishedAt: "2026-07-11T08:00:00Z"` to the selected fixture. After clicking `View details`, assert the complete text appears in a paragraph with `dir="rtl"` and assert the source name, Telegram platform label, author, publication timestamp, and canonical URL are visible.

- [ ] **Step 5: Run the focused frontend tests and verify they fail**

Run:

```bash
cd frontend
npx vitest run tests/api-client.test.ts tests/dashboard-shell.test.tsx tests/source-detail-panel.test.tsx
```

Expected: FAIL on invented source identity, next-run text, static status cells, and fake detail tabs.

- [ ] **Step 6: Add truthful frontend types and mapping**

In `frontend/lib/types.ts`, replace the `SourcePlatform` declaration with:

```tsx
export type SourcePlatform = "rss" | "atom" | "telegram_public" | "google_news" | "gdelt" | "hackernews" | "unknown"
```

Remove `nextRun` from `SourceSummary` and add `fetchIntervalMinutes: number` after `lastSuccess`. The backend has no scheduler due-time field yet.
Remove `parser` and `deduplication` from `SourceSummary`; neither value is supplied by the backend, so the frontend must not invent it.

Add these fields immediately after `scoreBreakdown` in `ContentQueueItem`:

```tsx
contentText?: string | null
direction?: "ltr" | "rtl" | null
authors?: string[]
publishedAt?: string | null
```

In the private `BackendContentItem` type in `frontend/lib/api-client.ts`, add:

```tsx
content_text?: string | null
direction?: "ltr" | "rtl" | null
authors?: string[]
published_at?: string | null
classification_metadata?: Record<string, unknown>
```

In `mapSource`, use `formatDateTime` instead of `formatTime` for `last_success_at`/`last_fetch_at`, replace `const interval = row.fetch_interval_minutes ?? 30` with `const interval = row.fetch_interval_minutes ?? 1440`, delete the `nextRun` return property, insert `fetchIntervalMinutes: interval` after `lastSuccess`, and delete the `parser` and `deduplication` return properties.

In `mapContentItem`, insert these declarations immediately after `category`:

```tsx
const metadata = row.classification_metadata ?? {}
const sourceName = typeof metadata.source_name === "string" ? metadata.source_name : "Unknown source"
const sourcePlatform = normalizePlatform(
  typeof metadata.source_platform === "string" ? metadata.source_platform : "unknown"
)
```

Replace the existing `sourceName: "NewsCraft"` and `sourcePlatform: "rss"` entries with `sourceName` and `sourcePlatform`, then add these properties immediately after `scoreBreakdown`:

```tsx
contentText: row.content_text ?? null,
direction: row.direction ?? null,
authors: row.authors ?? [],
publishedAt: row.published_at ?? null,
```

Replace `normalizePlatform` with:

```tsx
function normalizePlatform(platform: string): SourcePlatform {
  switch (platform) {
    case "rss":
    case "atom":
    case "telegram_public":
    case "google_news":
    case "gdelt":
    case "hackernews":
      return platform
    default:
      return "unknown"
  }
}
```

In `frontend/lib/format.ts`, map the known platform values to `RSS`, `Atom`, `Telegram`, `Google News`, `GDELT`, and `Hacker News`; return `Unknown` otherwise. In `frontend/components/dashboard/source-icon.tsx`, retain the Telegram and RSS/Atom icons, add neutral service-appropriate icons for Google News, GDELT, and Hacker News, and use `CircleHelp` for `unknown`; do not visually label any non-RSS source as RSS.

Replace `formatRunLabel` in `frontend/lib/api-client.ts` with `return formatDateTime(value)`. A real timestamp may be formatted for display, but it must never be labeled `Today` without comparing the date.

Add `fetchIntervalMinutes: 30` to every source fixture in `frontend/lib/mock-data.ts` and remove its `nextRun`, `parser`, and `deduplication` values. The fixture remains test-only; normal routes continue to use `frontend/lib/empty-data.ts` and the live API.

In `frontend/components/dashboard/source-health-table.tsx`, remove the `Next run` column. In `frontend/tests/source-health-table.test.tsx`, assert that no `Next run` column header is rendered.

- [ ] **Step 7: Replace fabricated header and source detail content**

Replace `TopStatusBar` with a truthful connection contract in `frontend/components/dashboard/top-status-bar.tsx`:

```tsx
"use client"

import { CircleAlert, CircleCheck, LoaderCircle, Play } from "lucide-react"

import { Button } from "@/components/ui/button"

type ConnectionState = "checking" | "connected" | "unavailable"

export function TopStatusBar({
  onRunIngest,
  isRunning = false,
  connectionState,
  lastRunLabel,
}: {
  onRunIngest: () => void
  isRunning?: boolean
  connectionState: ConnectionState
  lastRunLabel: string | null
}) {
  const status = {
    checking: { label: "Checking backend", Icon: LoaderCircle, className: "text-slate-500" },
    connected: { label: "Backend connected", Icon: CircleCheck, className: "text-emerald-700" },
    unavailable: { label: "Backend unavailable", Icon: CircleAlert, className: "text-red-700" },
  }[connectionState]

  return (
    <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b bg-white px-4 py-2">
      <h1 className="text-lg font-semibold">NewsCraft</h1>
      <div className="flex items-center gap-4 text-sm">
        <span className={`inline-flex items-center gap-2 ${status.className}`}>
          <status.Icon className="size-4" aria-hidden="true" />
          {status.label}
        </span>
        <span className="hidden text-muted-foreground lg:inline">{lastRunLabel ?? "No ingestion runs yet"}</span>
        <Button onClick={onRunIngest} disabled={isRunning} className="h-9 min-w-32 gap-2 rounded-md bg-primary">
          <Play className="size-4" aria-hidden="true" />
          {isRunning ? "Running" : "Run ingest"}
        </Button>
      </div>
    </header>
  )
}
```

In `DashboardShell`, derive and pass:

```tsx
const connectionState = dashboardQuery.isError
  ? "unavailable"
  : dashboardQuery.isFetching && hasNoDashboardData(data)
    ? "checking"
    : "connected"

<TopStatusBar
  onRunIngest={() => ingestMutation.mutate()}
  isRunning={ingestMutation.isPending}
  connectionState={connectionState}
  lastRunLabel={data.runs[0]?.label ?? null}
/>
```

In `source-detail-panel.tsx`, delete the inert `tabs` constant and tablist. Delete the fabricated `Last run`, `Next run`, `Schedule`, `Parser`, and `Deduplication` rows, then add:

```tsx
<Row label="Fetch interval" value={`Every ${source.fetchIntervalMinutes} minutes`} />
```

Keep `Last success` only in the existing metrics area, using the real API-derived value. Do not render a next-run clock until Release 1 introduces the scheduler.
Replace the identity line `{formatPlatform(source.platform)} feed - {source.url}` with `{formatPlatform(source.platform)} source - {source.url}` so Telegram and unknown sources are not called feeds.

In `content-items-page.tsx`, import `formatPlatform`, render `selectedItem.contentText` in the detail region, and set its paragraph `dir={selectedItem.direction ?? "auto"}`. Add these truthful detail rows before the existing score rows:

```tsx
<DetailRow label="Source" value={selectedItem.sourceName} />
<DetailRow label="Platform" value={formatPlatform(selectedItem.sourcePlatform)} />
<DetailRow label="Authors" value={selectedItem.authors?.join(", ") || "-"} />
<DetailRow label="Published" value={selectedItem.publishedAt ?? "-"} />
```

Keep the existing canonical `URL` row. Do not synthesize missing authors or publication dates.

- [ ] **Step 8: Run backend and frontend focused/full verification**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_api_content_intelligence.py tests/test_api.py -q
.venv/bin/ruff check app/api/schemas.py tests/test_api_content_intelligence.py
cd ../frontend
npx vitest run tests/api-client.test.ts tests/dashboard-shell.test.tsx tests/source-detail-panel.test.tsx tests/operation-pages.test.tsx
npm run test
```

Expected: all focused checks and full frontend suite pass.

- [ ] **Step 9: Commit truthful provenance and status**

Run:

```bash
git add backend/app/api/schemas.py backend/tests/test_api_content_intelligence.py \
  frontend/lib/api-client.ts frontend/lib/format.ts frontend/lib/types.ts frontend/lib/mock-data.ts \
  frontend/components/dashboard/source-icon.tsx frontend/components/dashboard/source-health-table.tsx \
  frontend/components/dashboard/top-status-bar.tsx \
  frontend/components/dashboard/dashboard-shell.tsx \
  frontend/components/dashboard/source-detail-panel.tsx \
  frontend/components/dashboard/pages/content-items-page.tsx \
  frontend/tests/api-client.test.ts frontend/tests/dashboard-shell.test.tsx frontend/tests/format.test.ts \
  frontend/tests/operation-pages.test.tsx frontend/tests/source-detail-panel.test.tsx \
  frontend/tests/source-health-table.test.tsx
git commit -m "fix: show truthful content provenance and runtime status"
```

---

### Task 4: Stabilize local verification and localhost exposure

**Files:**
- Modify: `frontend/tsconfig.json`
- Modify: `frontend/package.json`
- Modify: `backend/tests/test_docker_config.py`
- Modify: `docker-compose.yml`
- Modify: `.gitignore`
- Modify: `README.md`

**Interfaces:**
- Consumes: installed TypeScript and existing Docker Compose services.
- Produces: `npm run typecheck`; API/frontend/PostgreSQL host bindings on loopback; ignored visual-companion artifacts; documented Release 0 verification commands.

- [ ] **Step 1: Write failing Docker loopback binding tests**

Add `import json` and `import subprocess` to `backend/tests/test_docker_config.py`, then add:

```python
def _compose_config() -> dict:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_local_service_ports_bind_to_loopback():
    compose = _compose_config()

    assert compose["services"]["postgres"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert compose["services"]["api"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert compose["services"]["frontend"]["ports"][0]["host_ip"] == "127.0.0.1"
```

- [ ] **Step 2: Run the Docker test and current type check to verify failures**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_docker_config.py::test_local_service_ports_bind_to_loopback -q
cd ../frontend
npx tsc --noEmit --incremental false
```

Expected: Docker test fails because ports have no host IP, and TypeScript reports the deprecated `baseUrl` option.

- [ ] **Step 3: Bind Compose ports to loopback**

Change only the host port strings in `docker-compose.yml`:

```yaml
postgres:
  ports:
    - "127.0.0.1:5432:5432"

api:
  ports:
    - "127.0.0.1:8000:8000"

frontend:
  ports:
    - "127.0.0.1:3000:3000"
```

- [ ] **Step 4: Add a supported frontend type-check command**

Remove `"baseUrl": "."` from `frontend/tsconfig.json`; keep the existing `paths` mapping.

Add this script to `frontend/package.json`:

```json
"typecheck": "tsc --noEmit --incremental false"
```

Do not claim `next lint` works. Remove the stale `"lint": "next lint"` script; frontend linting will be introduced with an explicit ESLint configuration in the Newsroom release rather than retaining a broken command.

- [ ] **Step 5: Ignore companion output and document honest gates**

Add to `.gitignore`:

```gitignore
# Superpowers visual brainstorming sessions
.superpowers/
```

In `README.md`, replace the unsupported feature bullet `Supports approval and draft workflows for downstream post generation.` with `Supports manual content-item approval; AI generation, editorial revisions, scheduling, and publishing are planned in the content-platform rescue.` Also note that content responses now expose complete text, authors, publication time, source ID, and classification metadata.

Replace the frontend check list with:

````markdown
Useful frontend checks:

```bash
npm run test
npm run typecheck
npm run build
npm run test:e2e
```

The app is local-only by default. Compose binds PostgreSQL, API, and frontend host ports to `127.0.0.1`.
````

- [ ] **Step 6: Run focused verification**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/test_docker_config.py -q
cd ../frontend
npm run typecheck
npm run test
npm run build
cd ..
docker compose config >/tmp/newscraft-compose-release0-final.yml
```

Expected: Docker tests, type check, frontend tests, build, and Compose config all succeed.

- [ ] **Step 7: Run browser verification with the known local Chromium workaround**

Run:

```bash
cd frontend
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/wingman/.cache/puppeteer/chrome-headless-shell/linux-150.0.7871.24/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npm run test:e2e
```

Expected: Playwright passes at desktop and mobile viewports.

- [ ] **Step 8: Commit verification and local exposure fixes**

Run:

```bash
git add frontend/tsconfig.json frontend/package.json backend/tests/test_docker_config.py \
  docker-compose.yml .gitignore README.md
git commit -m "chore: stabilize local verification baseline"
```

---

### Task 5: Prove Release 0 is clean and ready for feature isolation

**Files:**
- Verify only; no production file changes expected.

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: evidence that the baseline is ready for a separate Release 1 worktree and no companion/generated artifacts are tracked.

- [ ] **Step 1: Run the complete backend gate**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
```

Expected: all backend tests pass and Ruff prints `All checks passed!`.

- [ ] **Step 2: Run the complete frontend gate**

Run:

```bash
cd frontend
npm run test
npm run typecheck
npm run build
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/home/wingman/.cache/puppeteer/chrome-headless-shell/linux-150.0.7871.24/chrome-headless-shell-linux64/chrome-headless-shell \
PLAYWRIGHT_CHROMIUM_SINGLE_PROCESS=1 \
npm run test:e2e
```

Expected: unit tests, type check, build, and browser tests pass.

- [ ] **Step 3: Verify migrations, Compose, and Git hygiene**

Run:

```bash
cd ..
cd backend && PYTHONPATH=. .venv/bin/alembic upgrade head --sql >/tmp/newscraft-release0-alembic.sql && cd ..
docker compose config >/tmp/newscraft-release0-compose.yml
git diff --check
git status --short --branch
git ls-files .superpowers
```

Expected:

- Alembic offline SQL and Compose config exit successfully.
- `git diff --check` produces no output.
- `git ls-files .superpowers` produces no output.
- Only the explicitly preserved untracked planning artifacts may remain.

- [ ] **Step 4: Record the verified baseline commit**

Run:

```bash
git log -5 --oneline
```

Expected: the cleanup, live-query, truthful provenance, and verification commits are visible and Release 0 requires no additional commit.
