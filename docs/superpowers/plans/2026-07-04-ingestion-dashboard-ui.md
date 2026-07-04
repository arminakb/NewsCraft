# NewsCraft Ingestion Dashboard UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-grade frontend that recreates the provided NewsCraft ingestion dashboard screenshot and connects it to the FastAPI ingestion backend.

**Architecture:** Add a new `frontend/` Next.js App Router app. Use server/client boundaries intentionally: static shell/layout as React components, data-heavy dashboard widgets as client components powered by TanStack Query and typed API clients. Keep the dashboard UI operational and dense, matching the screenshot's source-health table, run list, content queue, media strip, and right-side source detail panel.

**Tech Stack:** Next.js App Router, React, TypeScript, Tailwind CSS, shadcn/ui, Radix primitives through shadcn, lucide-react, TanStack Query, TanStack Table, Vitest, Testing Library, Playwright.

---

## Context7 Decisions

Context7 docs checked on 2026-07-04:

- Next.js `/vercel/next.js`: use App Router, Server Components for initial fetches, Client Components for state/effects, and `fetch(url, { cache: "no-store" })` for operational dashboard data.
- shadcn/ui `/shadcn-ui/ui`: use `Sidebar`, `Table`, `Card`, `Badge`, `Button`, `Tabs`, `Sheet`, `Progress`, `Separator`, `ScrollArea`, `Tooltip`, and `DropdownMenu`; shadcn data-table examples compose `@tanstack/react-table`.
- TanStack Query `/tanstack/query`: use `refetchInterval` for live dashboard polling and invalidate queries after mutations like “Run ingest”.
- TanStack Table `/tanstack/table`: use table state for sorting/filtering/pagination; keep server-side pagination later when API supports it.
- Lucide `/lucide-icons/lucide`: use individual React icon imports and consistent `size`, `strokeWidth`, and `absoluteStrokeWidth`.
- Recharts `/recharts/recharts`: keep out of the first build because the screenshot uses progress bars and metric cards, not charts. Add Recharts later for time-series run analytics.

## Visual Target

The UI should reproduce the screenshot as an operational dashboard, not a marketing page.

Primary layout:

- Fixed left sidebar, about `240px` wide.
- Fixed top command/status bar, about `56px` high.
- Main content area with dashboard cards and tables.
- Right source-detail panel, about `440px` wide on desktop.
- Mobile/tablet: source-detail becomes a shadcn `Sheet`; sidebar collapses to an icon rail or drawer.

Key panels:

- Source health table with source type icons, status badges, 24h counts, failed count, last success, next run, and row action chevrons.
- Ingestion runs card with status icons, progress bars, duration, item counts.
- Content queue list/table with thumbnails, source icons, category/language/age/status, and row actions.
- Media extraction strip with thumbnails, format, dimensions, file name, age, size.
- Source details panel with source icon, health badge, tabs, metric cards, metadata rows, edit/disable actions.

## Design System

Use shadcn defaults but tune tokens for the screenshot:

```css
:root {
  --background: 0 0% 100%;
  --foreground: 222 47% 11%;
  --muted: 210 40% 96%;
  --muted-foreground: 215 16% 47%;
  --border: 214 32% 91%;
  --primary: 190 94% 26%;
  --primary-foreground: 0 0% 100%;
  --success: 142 71% 35%;
  --warning: 38 92% 50%;
  --destructive: 0 84% 60%;
}
```

Rules:

- Border radius: `6px` for cards/tables/buttons, matching the screenshot's compact enterprise style.
- Typography: use `Inter` or `Geist Sans`; do not scale font size with viewport width.
- Icons: lucide for app nav/actions; small RSS/Telegram/source icons can use lucide plus colored square/circle wrappers.
- Avoid nested cards. Use bordered panels for top-level dashboard regions; cards only for metrics and repeated media tiles.
- Use compact spacing: `h-9` controls, `text-sm` body, `text-xs` metadata, `px-3 py-2` table cells.

## File Structure

Create:

```text
frontend/
  app/
    layout.tsx
    page.tsx
    globals.css
  components/
    dashboard/
      dashboard-shell.tsx
      app-sidebar.tsx
      top-status-bar.tsx
      source-health-table.tsx
      ingestion-runs-panel.tsx
      content-queue-panel.tsx
      media-strip.tsx
      source-detail-panel.tsx
      status-badge.tsx
      source-icon.tsx
    providers/
      query-provider.tsx
    ui/
      generated shadcn components
  lib/
    api-client.ts
    query-keys.ts
    mock-data.ts
    format.ts
    types.ts
  tests/
    dashboard-shell.test.tsx
    source-health-table.test.tsx
    api-client.test.ts
  e2e/
    dashboard.spec.ts
  package.json
  next.config.ts
  tsconfig.json
  vitest.config.ts
  playwright.config.ts
  components.json
```

Modify:

```text
README.md
docker-compose.yml
backend/app/api/routes.py
backend/app/api/schemas.py
backend/tests/test_api.py
```

Backend changes are included because the current API cannot fully power the screenshot. The frontend can start with mock data, but production connection needs richer dashboard endpoints.

---

### Task 1: Frontend Project Skeleton

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/next.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/page.tsx`
- Create: `frontend/app/globals.css`
- Create: `frontend/components/providers/query-provider.tsx`
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/mock-data.ts`
- Create: `frontend/lib/format.ts`
- Create: `frontend/vitest.config.ts`
- Create: `frontend/playwright.config.ts`

- [ ] **Step 1: Create frontend dependencies**

Use:

```json
{
  "scripts": {
    "dev": "next dev --port 3000",
    "build": "next build",
    "test": "vitest run",
    "test:e2e": "playwright test",
    "lint": "next lint"
  },
  "dependencies": {
    "@tanstack/react-query": "latest",
    "@tanstack/react-table": "latest",
    "class-variance-authority": "latest",
    "clsx": "latest",
    "lucide-react": "latest",
    "next": "latest",
    "react": "latest",
    "react-dom": "latest",
    "tailwind-merge": "latest"
  },
  "devDependencies": {
    "@playwright/test": "latest",
    "@testing-library/jest-dom": "latest",
    "@testing-library/react": "latest",
    "@types/node": "latest",
    "@types/react": "latest",
    "@types/react-dom": "latest",
    "@vitejs/plugin-react": "latest",
    "tailwindcss": "latest",
    "typescript": "latest",
    "vitest": "latest"
  }
}
```

- [ ] **Step 2: Initialize shadcn/ui**

Run from `frontend/`:

```bash
npx shadcn@latest init
npx shadcn@latest add button badge card table tabs sheet separator scroll-area progress tooltip dropdown-menu skeleton input
```

- [ ] **Step 3: Add dashboard mock types**

Create `frontend/lib/types.ts` with:

```ts
export type SourceStatus = "healthy" | "partial" | "failed"
export type SourcePlatform = "rss" | "telegram_public"

export type SourceSummary = {
  id: string
  platform: SourcePlatform
  name: string
  url: string
  category: string
  language: string
  status: SourceStatus
  items24h: number
  new24h: number
  failed24h: number
  lastSuccess: string | null
  nextRun: string | null
  totalItems: number
  media24h: number
  addedAt: string
  parser: string
  deduplication: string
}

export type IngestionRunSummary = {
  id: string
  label: string
  scope: string
  status: "succeeded" | "partial" | "failed"
  progress: number
  duration: string
  items: number
}

export type ContentQueueItem = {
  id: string
  title: string
  thumbnailUrl: string | null
  sourceName: string
  sourcePlatform: SourcePlatform
  category: string
  language: string
  age: string
  status: "new" | "queued"
}

export type MediaTile = {
  id: string
  src: string
  format: string
  dimensions: string
  fileName: string
  age: string
  size: string
}

export type DashboardSnapshot = {
  counts: {
    rssFeeds: number
    telegramChannels: number
    contentItems: number
    mediaAssets: number
    warnings: number
  }
  sources: SourceSummary[]
  runs: IngestionRunSummary[]
  queue: ContentQueueItem[]
  media: MediaTile[]
}
```

- [ ] **Step 4: Add representative mock data**

Create `frontend/lib/mock-data.ts` with screenshot-aligned data:

```ts
import type { DashboardSnapshot } from "./types"

export const dashboardMock: DashboardSnapshot = {
  counts: {
    rssFeeds: 50,
    telegramChannels: 3,
    contentItems: 1284,
    mediaAssets: 912,
    warnings: 18,
  },
  sources: [
    {
      id: "rss_5f8d3c1a",
      platform: "rss",
      name: "TechCrunch",
      url: "https://techcrunch.com/feed/",
      category: "AI, Tech",
      language: "en",
      status: "healthy",
      items24h: 128,
      new24h: 42,
      failed24h: 0,
      lastSuccess: "09:28",
      nextRun: "in 28m",
      totalItems: 8612,
      media24h: 76,
      addedAt: "2024-11-12 14:22",
      parser: "RSS 2.0",
      deduplication: "URL + GUID",
    }
  ],
  runs: [],
  queue: [],
  media: []
}
```

- [ ] **Step 5: Render the shell**

`frontend/app/page.tsx`:

```tsx
import { dashboardMock } from "@/lib/mock-data"
import { DashboardShell } from "@/components/dashboard/dashboard-shell"

export default function Page() {
  return <DashboardShell initialData={dashboardMock} />
}
```

- [ ] **Step 6: Verify**

Run:

```bash
cd frontend
npm install
npm run build
```

Expected: build succeeds with an empty shell or placeholder if components are not complete yet.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: add frontend dashboard skeleton"
```

### Task 2: Static Dashboard Layout Recreation

**Files:**
- Create: `frontend/components/dashboard/dashboard-shell.tsx`
- Create: `frontend/components/dashboard/app-sidebar.tsx`
- Create: `frontend/components/dashboard/top-status-bar.tsx`
- Create: `frontend/components/dashboard/status-badge.tsx`
- Create: `frontend/components/dashboard/source-icon.tsx`
- Test: `frontend/tests/dashboard-shell.test.tsx`

- [ ] **Step 1: Write layout tests**

Test should assert:

```text
sidebar navigation exists
top status bar shows PostgreSQL and Proxy
run ingest button exists
source detail panel region exists
```

- [ ] **Step 2: Build `DashboardShell`**

Layout:

```tsx
<div className="grid min-h-screen grid-cols-[240px_1fr_440px] bg-slate-50">
  <AppSidebar />
  <div className="min-w-0 border-x bg-white">
    <TopStatusBar />
    <main className="space-y-4 p-4">
      <SourceHealthTable />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <IngestionRunsPanel />
        <ContentQueuePanel />
      </div>
      <MediaStrip />
    </main>
  </div>
  <SourceDetailPanel />
</div>
```

Responsive behavior:

```text
desktop >= 1280px: three-column layout
tablet 768-1279px: sidebar + content, detail in Sheet
mobile < 768px: sidebar drawer, stacked panels, detail in Sheet
```

- [ ] **Step 3: Build sidebar**

Use lucide icons:

```text
Database for Sources
Clock for Runs
Newspaper/Text for Content Items
Image for Media
Settings for Settings
ChevronLeft for Collapse
Rss and Send for count card
```

- [ ] **Step 4: Build top status bar**

Use compact status cells:

```text
PostgreSQL Healthy
Proxy Active
Last run 09:32
Run ingest button
```

- [ ] **Step 5: Verify**

Run:

```bash
cd frontend
npm run test
npm run build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/components/dashboard frontend/tests
git commit -m "feat: recreate ingestion dashboard shell"
```

### Task 3: Source Health Table

**Files:**
- Create: `frontend/components/dashboard/source-health-table.tsx`
- Test: `frontend/tests/source-health-table.test.tsx`

- [ ] **Step 1: Write source table tests**

Assert:

```text
renders five source rows
shows Healthy, Partial, and Failed badges
selecting a row calls onSelectSource with the source id
tabs show All, RSS, Telegram counts
```

- [ ] **Step 2: Implement with TanStack Table**

Use `@tanstack/react-table` with shadcn `Table`.

Columns:

```text
type icon
source name + url
status badge
items24h
new24h
failed24h
lastSuccess
nextRun
chevron action
```

- [ ] **Step 3: Match visual details**

Use:

```text
RSS icon in orange rounded square
Telegram icon in blue circle
green/orange/red badge variants
green number for new count
red number for failed count
row height 48px
```

- [ ] **Step 4: Verify**

Run:

```bash
cd frontend
npm run test -- source-health-table
npm run build
```

- [ ] **Step 5: Commit**

```bash
git add frontend/components/dashboard/source-health-table.tsx frontend/tests/source-health-table.test.tsx
git commit -m "feat: add source health table"
```

### Task 4: Operational Panels

**Files:**
- Create: `frontend/components/dashboard/ingestion-runs-panel.tsx`
- Create: `frontend/components/dashboard/content-queue-panel.tsx`
- Create: `frontend/components/dashboard/media-strip.tsx`
- Test: `frontend/tests/dashboard-panels.test.tsx`

- [ ] **Step 1: Write panel tests**

Assert:

```text
runs panel renders latest runs and progress bars
content queue renders thumbnails, source, category, language, age, status
media strip renders six media tiles with format and dimensions
```

- [ ] **Step 2: Build runs panel**

Use shadcn `Progress`, lucide status icons, and compact rows.

- [ ] **Step 3: Build content queue panel**

Use a compact list/table hybrid because the screenshot combines thumbnails with tabular metadata.

Filters:

```text
All
AI
Tech
Economy
Farsi
```

- [ ] **Step 4: Build media strip**

Horizontal scroll on small screens. Fixed tile sizes:

```text
thumbnail aspect ratio 16:9
format badge top-left
dimensions top-right
filename + age + size below
```

- [ ] **Step 5: Verify and commit**

```bash
cd frontend
npm run test
npm run build
git add frontend/components/dashboard frontend/tests/dashboard-panels.test.tsx
git commit -m "feat: add ingestion dashboard panels"
```

### Task 5: Source Detail Panel

**Files:**
- Create: `frontend/components/dashboard/source-detail-panel.tsx`
- Test: `frontend/tests/source-detail-panel.test.tsx`

- [ ] **Step 1: Write source detail tests**

Assert:

```text
panel renders selected source name and health
metric cards render items, new, failed, total, media, last success
tabs render Overview, Settings, History, Logs
feed URL link has external-link affordance
edit and disable actions exist
```

- [ ] **Step 2: Implement desktop panel**

Use:

```text
sticky right panel
header with source icon/name/health and close button
tabs
metric cards grid
metadata definition list
actions
```

- [ ] **Step 3: Implement tablet/mobile Sheet variant**

Same component content, wrapped by shadcn `Sheet` when viewport is narrow.

- [ ] **Step 4: Verify and commit**

```bash
cd frontend
npm run test
npm run build
git add frontend/components/dashboard/source-detail-panel.tsx frontend/tests/source-detail-panel.test.tsx
git commit -m "feat: add source detail panel"
```

### Task 6: API Client And Live Data Polling

**Files:**
- Create: `frontend/lib/api-client.ts`
- Create: `frontend/lib/query-keys.ts`
- Modify: `frontend/components/providers/query-provider.tsx`
- Modify: dashboard components to use queries
- Test: `frontend/tests/api-client.test.ts`

- [ ] **Step 1: Write API client tests**

Mock `fetch` and assert:

```text
GET /sources maps to SourceSummary[]
POST /sources/seed returns upserted count
POST /ingest/run sends platforms/source_ids
GET /content-items maps ContentQueueItem[]
network errors produce typed ApiError
```

- [ ] **Step 2: Implement API client**

Use:

```ts
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
```

Functions:

```ts
getSources()
seedSources()
runIngest(input)
getContentItems()
```

- [ ] **Step 3: Add TanStack Query provider**

Configure:

```ts
staleTime: 10_000
refetchInterval: 30_000 for dashboard snapshot queries
```

- [ ] **Step 4: Wire “Run ingest” mutation**

On success invalidate:

```text
sources
runs
content-items
media
dashboard-summary
```

- [ ] **Step 5: Verify and commit**

```bash
cd frontend
npm run test
npm run build
git add frontend/lib frontend/components/providers frontend/components/dashboard
git commit -m "feat: connect dashboard to ingestion API"
```

### Task 7: Backend Dashboard API Support

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/routes.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Extend backend API tests**

Add tests for:

```text
GET /dashboard/summary
GET /ingest/runs
GET /media-assets
GET /sources/{source_id}
```

- [ ] **Step 2: Add schemas**

Add:

```text
DashboardSummaryOut
IngestRunSummaryOut
MediaAssetListOut
SourceDetailOut
```

- [ ] **Step 3: Add routes**

Routes:

```text
GET /dashboard/summary
GET /ingest/runs
GET /media-assets
GET /sources/{source_id}
```

Keep queries simple first: latest 100 rows, aggregate counts in Python if SQL gets too complex.

- [ ] **Step 4: Verify**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_api.py -q
.venv/bin/python -m ruff check .
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/api backend/tests/test_api.py
git commit -m "feat: add dashboard API endpoints"
```

### Task 8: Visual Polish And Responsive QA

**Files:**
- Create: `frontend/e2e/dashboard.spec.ts`
- Modify: dashboard components/CSS as needed

- [ ] **Step 1: Write Playwright checks**

Assert at desktop viewport:

```text
sidebar visible
top status bar visible
source table visible
right detail panel visible
media strip visible
no horizontal overflow
```

Assert at mobile viewport:

```text
content stacks
right detail panel is not permanently visible
source detail opens as Sheet after row click
run ingest button remains reachable
```

- [ ] **Step 2: Run screenshot checks**

Run:

```bash
cd frontend
npm run test:e2e
```

Store failing screenshots only under Playwright output; do not commit output folders.

- [ ] **Step 3: Final polish checklist**

Confirm:

```text
text does not overflow buttons/cards
right panel does not overlap main content
media thumbnails have stable aspect ratio
status badges fit long labels
keyboard focus visible on nav, tabs, buttons, rows
color is not one-note teal/blue
```

- [ ] **Step 4: Commit**

```bash
git add frontend
git commit -m "feat: polish ingestion dashboard responsive UI"
```

### Task 9: Docker And README Frontend Integration

**Files:**
- Modify: `docker-compose.yml`
- Modify: `README.md`
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: Add frontend Dockerfile**

Use multi-stage Next.js build.

- [ ] **Step 2: Add Compose service**

Add:

```yaml
frontend:
  build:
    context: ./frontend
  environment:
    NEXT_PUBLIC_API_BASE_URL: http://localhost:8000
  ports:
    - "3000:3000"
  depends_on:
    - api
```

- [ ] **Step 3: Update README**

Add:

```bash
docker compose up frontend api postgres
```

and local dev:

```bash
cd frontend
npm install
npm run dev
```

- [ ] **Step 4: Verify**

Run:

```bash
cd frontend
npm run build
cd ../backend
.venv/bin/python -m pytest -q
cd ..
git status --short
```

- [ ] **Step 5: Commit**

```bash
git add frontend/Dockerfile frontend/.dockerignore docker-compose.yml README.md
git commit -m "feat: dockerize ingestion dashboard frontend"
```

## Recommended Execution Order

1. Task 1: Frontend skeleton and shadcn setup.
2. Task 2: Static dashboard shell.
3. Task 3: Source health table.
4. Task 4: Runs/content/media panels.
5. Task 5: Source detail panel.
6. Task 6: API client and polling.
7. Task 7: Backend dashboard API support.
8. Task 8: Responsive visual QA.
9. Task 9: Docker/README frontend integration.

## Self-Review

Spec coverage:

- Screenshot layout: Tasks 2-5.
- Data tables and filters: Tasks 3-4.
- Right detail panel: Task 5.
- Run ingest behavior: Task 6.
- Backend data gaps: Task 7.
- Responsive behavior: Task 8.
- Docker integration: Task 9.

Placeholder scan:

- No placeholder markers or unspecified file paths remain.

Type consistency:

- `SourceSummary`, `ContentQueueItem`, `MediaTile`, and `DashboardSnapshot` are introduced before component tasks use them.
- Backend dashboard endpoints are explicitly separated from existing ingestion API endpoints.
