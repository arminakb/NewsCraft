# Frontend current state

> **Superseded 2026-08-13 — historical record only.** The route inventory
> below describes the pre-newsroom shell. `/inbox`, `/drafts`, `/library`,
> `/content`, `/runs`, and `/media` no longer exist; `/jobs`,
> `/diagnostics`, `/calendar`, and `/settings/content` are redirect stubs.
> The live navigation is Today (`/`), Sources (`/sources`), Feed (`/feed`),
> Automations (`/automations`), Operations Center (`/operations`), and
> Settings, defined in
> [`frontend/components/newsroom/newsroom-sidebar.tsx`](../../frontend/components/newsroom/newsroom-sidebar.tsx).
> Do not use this file as a current-route reference.

Audit date: 2026-07-21

## Scope and protection boundary

This phase inspected the existing Next.js frontend and its live Compose-backed API. It did not change application behavior, API contracts, backend code, database state, workers, migrations, scheduler behavior, approval rules, or publishing boundaries.

The only persistent changes from this audit are the files in `docs/frontend-audit/`.

## Supported live environment

Repository documentation identifies Docker Compose as the supported full-stack path. The stack was started with:

```bash
docker compose up -d postgres api frontend worker-source-generation worker-publishing scheduler
```

Verified URLs:

- Frontend: <http://localhost:3000>
- API: <http://localhost:8000>
- Frontend liveness: <http://localhost:3000/health>
- API liveness: <http://localhost:8000/health>
- API readiness: <http://localhost:8000/health/ready>

Verification results:

- `postgres`, `api`, `frontend`, `worker-source-generation`, `worker-publishing`, and `scheduler` were healthy.
- The one-shot `migrate` service exited successfully with status 0.
- `GET /health` returned `{"status":"ok"}`.
- `GET /health/ready` returned `ready`; database, schema, media storage, and export storage checks were healthy.
- Frontend `/` and `/health` returned HTTP 200.
- The stack remains running for review.

The Compose frontend is a production-style container, not a source-mounted hot-reload container. `docker-compose.dev.yml` currently only adds backend source mounts, so frontend file changes require a rebuild/recreate unless the frontend is run locally with `npm run dev`.

## Live data and operational truth

The UI was not empty during inspection:

- 51 sources: 50 RSS and 1 public Telegram source.
- 3,142 content items.
- 1,941 media assets.
- At least 50 grouped stories in the first `/stories` page.
- 1 content pack with an approved Telegram revision.
- 42 jobs returned by `/jobs`; current operations summary showed 1 queued, 0 running, 38 succeeded, and 3 failed.

The system was globally paused. Runtime components were healthy, but product-level diagnostics were degraded:

- Eight RSS sources were marked broken after connection failures.
- One Telegram source was `unknown`.
- Telegram destination checks failed because the destination secret was unavailable.
- A Telegram route dry run failed because the route was not ready.

These are real persisted states, not frontend rendering defects. The frontend exposes them on Today, Diagnostics, Sources, and Job Queue.

## Architecture

- Framework: Next.js App Router, React, TypeScript.
- Data fetching: TanStack Query.
- Tables: TanStack Table.
- Styling: Tailwind CSS with local shadcn-style primitives and Base UI.
- Icons: Lucide.
- API boundary: browser requests use `/api/backend`; `frontend/app/api/backend/[...path]/route.ts` proxies to `API_INTERNAL_BASE_URL` (Compose: `http://api:8000`).
- Root composition: `frontend/app/layout.tsx` mounts the query, notice, tooltip, dirty-navigation, and newsroom shell providers.
- Global shell: `frontend/components/newsroom/newsroom-shell.tsx` owns the single main landmark, persistent header, desktop sidebar, and mobile bottom navigation.
- Feature organization: operational dashboard pages remain under `components/dashboard`; newer workflows are organized under `features/*`; editorial components are under `components/editorial`.

There are two overlapping frontend eras:

1. Ingestion operations: Sources, Content, Ingestion Runs, Media, and the older `/diagnostics` data.
2. Newsroom/editorial operations: Today, Inbox, Jobs, Automations, Drafts, exact Review, Calendar, Library, Content Settings, retention, and `/operations/*` diagnostics.

Both expose important backend capability. The overlap is an information-architecture problem, not evidence that either area can be deleted.

## Route inventory

| Route | Current screen | Classification | Notes |
| --- | --- | --- | --- |
| `/` | Today | Primary | Operational summary and global controls; not yet a clear workflow start. |
| `/inbox` | Editorial Inbox | Primary | Intake, grouping, story inspection, selection, research, and generation. |
| `/drafts` | Drafts | Primary | Durable generation requests, packs, and legacy Telegram drafts. |
| `/drafts/[packId]` | Multi-platform editorial studio | Primary detail | Preview, evidence, edit, revisions, approval, export, media, and handoff. |
| `/review/[revisionId]` | Exact revision review | Primary detail | Exact revision decision and publish/manual handoff. |
| `/calendar` | Publication calendar | Primary/secondary | Telegram schedules and manual publication plans. |
| `/library` | Library | Secondary | Read-only persisted originals, stories, evidence, research, drafts, exports, publications. |
| `/jobs` | Job Queue | Operational/recovery | Durable job truth, retry, cancel, payload/result/events. |
| `/automations` | Telegram automations | Operational | Route list and destination health. |
| `/automations/new` | New Telegram automation | Configuration | Source, destination, schedule, research, and publishing policy. |
| `/automations/[routeId]` | Automation detail | Operational/recovery | Cursor, policy, health, pause/resume, dry run, backfill, dispatches. |
| `/automations/[routeId]/history` | Automation history | Diagnostic | Cursor-paginated durable history. |
| `/sources` | Sources | Advanced operations | Seed, ingest, health filtering, and source detail. |
| `/content` | Content Items | Advanced/raw queue | Low-level captured-item classification and approval. |
| `/runs` | Ingestion Runs | Diagnostic | Ingestion activity and status. |
| `/media` | Media Assets | Diagnostic | Extracted/downloaded media inspection. |
| `/diagnostics` | Diagnostics | Operational/recovery | Runtime components, queue truth, attention, source checks, and reconciliation. |
| `/settings/content` | Content Settings | Configuration | Brands, prompts, providers, destinations, credential references. |
| `/settings/retention` | Retention | Destructive administration | Policy, preview token, typed confirmation, bounded cleanup job. |

## Rendered behavior

The real UI was inspected in Chromium at 1440×1000 and 390×844.

- Desktop and narrow layouts had no horizontal page overflow.
- The mobile shell uses Today, Inbox, and Menu as its bottom navigation. Menu opens a focus-managed dialog containing all 15 destinations.
- No browser console warnings or errors occurred during live route inspection.
- Four aborted Next.js RSC requests occurred while the audit rapidly navigated between pre-rendered detail routes. They were navigation aborts, not HTTP failures or failed API requests.
- Today accurately displayed pause state, queue counts, three failed jobs, and recent successes.
- Inbox rendered a large populated list and exposed story details, Research more, and Generate Telegram pack.
- Sources rendered a populated table and source detail panel.
- Content rendered a populated table with View details and Approve actions.
- Drafts linked to the existing content pack and exact revision.
- The editorial studio rendered an approved Telegram revision, evidence, immutable history, editor, export, regeneration, media plan, and handoff.
- Exact review correctly showed publishing controls loading and the global-pause blocker.
- Calendar rendered the current month with an empty event window.
- Diagnostics rendered real degraded state and recovery links.

## Existing state handling

The codebase includes distinct loading, empty, error, and retry states in Today, Inbox, Jobs, Calendar, Library, Diagnostics, Retention, Sources, Content, Runs, and Media. Existing Playwright fixtures also cover empty and error states. The main problem is not absence of feedback; it is that feedback, diagnostics, primary work, and configuration are often presented at the same hierarchy level.

## Validation baseline

| Check | Result | Classification |
| --- | --- | --- |
| `npm run typecheck` | Passed | Clean baseline. |
| `npm run test` | Failed: 93 passed, 265 failed; 9 files passed, 38 failed | Existing test-runtime incompatibility. Most failures are `TypeError: React.act is not a function`; `mobile-nav.test.tsx` also fails resolving `node:`. |
| `npm run build` | Passed outside the restricted sandbox | First sandbox run failed because Turbopack could not bind an internal helper port; unrestricted rerun compiled, typechecked, and generated all 17 static/dynamic routes. |
| Live Chromium audit | Passed | Ten real routes plus two detail interactions and mobile navigation; no console errors and no horizontal overflow. |
| `npm run test:e2e` | 13 passed, 20 failed | Mixed baseline: successful core flows plus environment instability and stale test fixtures. |

Successful E2E coverage included the desktop Today/Job Queue workflow, manual intake → research → generation → exact approval, desktop RTL flow, mobile navigation without overflow, 44×44 Inbox targets, and desktop critical-path axe checks.

Known E2E baseline failures include:

- Four-worker execution with `--single-process` Chromium caused many `Target page, context or browser has been closed` failures. This is environmental.
- Accessibility and Telegram fixtures do not handle the newer `GET /telegram/reconciliation` request.
- Diagnostics fixtures still wait for obsolete `System checks` copy.
- One mobile Telegram automation flow timed out at Create and activate.

No test was changed or weakened.

