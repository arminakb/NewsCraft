# NewsCraft Frontend Reference Migration Plan

## Document Status

- **Purpose:** Multi-session implementation plan for aligning the NewsCraft frontend with the provided visual references.
- **Scope:** Frontend only.
- **Backend changes:** Prohibited unless explicitly authorized in a later task.
- **Reference directory:** `/home/armin/Documents/NewsCraft/refrencess/`
- **Execution model:** One phase per working session, with independent validation and commit boundaries.
- **Primary constraint:** Preserve NewsCraft’s existing routes, workflows, business logic, data flow, and page responsibilities.

---

# 1. Objective

Rebuild the NewsCraft frontend’s visual system so that it matches the provided reference implementation as closely as reasonably possible while preserving the product’s existing functionality and information architecture.

The reference files are authoritative for:

- Application shell
- Left sidebar
- Light and dark color systems
- Typography
- Spacing
- Borders and dividers
- Border radius
- Shadows
- Icon sizing and stroke weight
- Hover, focus, active, selected, disabled, loading, and error states
- Cards
- Tables
- Forms
- Dialogs
- Tooltips
- Responsive density
- Overall visual polish

The references are **not** authoritative for:

- Mock data
- Demo routes
- Workspace names
- Subscription plans
- Fake badges
- Example navigation labels
- Placeholder dashboards
- Logout behavior
- Sample projects
- Unrelated reference functionality

Adapt the visual language to NewsCraft. Do not replace NewsCraft with the demo application.

---

# 2. Global Rules

## 2.1 Preserve functionality

Do not change:

- Backend code
- API contracts
- Database models
- Data-fetching behavior
- Mutation behavior
- Existing routes
- Page responsibilities
- Domain logic
- Existing workflows
- Authentication behavior
- Ingestion workers
- Scheduling behavior
- Publishing behavior

## 2.2 Repository safety

Before every phase:

```bash
git status
git log --oneline -10
```

Rules:

- Do not reset the repository.
- Do not discard unrelated changes.
- Do not use destructive Git commands.
- Do not overwrite uncommitted work without review.
- Do not modify backend files.
- Search repository-wide usage before deleting shared frontend code.
- Keep the application runnable at the end of every phase.

## 2.3 Visual fidelity

The final result must be visually faithful to the reference package, not merely inspired by it.

Avoid:

- Default-looking Tailwind components
- Random colors
- Inconsistent spacing
- Oversized typography
- Heavy shadows
- Excessive gradients
- Unnecessary borders
- Inconsistent radii
- Misaligned icons
- Detached controls
- Page-level horizontal overflow
- Navigation scrollbars on standard desktop layouts

## 2.4 Accessibility

Every phase must preserve or improve:

- Semantic HTML
- Keyboard navigation
- Visible focus states
- Screen-reader labels
- Dialog focus management
- Escape-key handling
- Accessible tooltips
- Color contrast
- Touch target sizes
- Reduced-motion behavior where appropriate
- Browser zoom behavior

---

# 3. Required Project Tracking

Create and maintain this section throughout the migration.

## Current progress

- **Completed phases:** Phase 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, Phase 6
- **Current phase:** Phase 7 pending
- **Last completed commit:** None; migration work remains in the existing uncommitted frontend worktree
- **Known issues:** Baseline unit tests emit existing React `act(...)` warnings
- **Next phase:** Phase 7 — Final Validation and Cleanup

## Route inventory

- `/` — Today
- `/sources` — Sources
- `/calendar` — Publication calendar
- `/feed` — Library / Feed
- `/jobs` — Job queue and job detail panel
- `/automations` — Automation routes
- `/automations/new` — New automation route
- `/automations/[routeId]` — Automation detail
- `/automations/[routeId]/history` — Automation history
- `/diagnostics` — Diagnostics
- `/settings/content` — Settings
- `/settings/retention` — Retention
- `/review/[revisionId]` — Exact revision review
- `/api/backend/[...path]` — frontend API proxy route; not a page
- `/health` — frontend health endpoint; not a page
- `/_not-found` — framework not-found route
- `/inbox` redirects temporarily to `/`
- `/runs` redirects temporarily to `/sources`
- Drafts is not a surviving route; it was removed before this migration.
- No route-local `loading.tsx`, `error.tsx`, or `not-found.tsx` files exist. Loading, error, and empty states are implemented inside feature/page components.

## Test baseline

- **Unit tests:** `npm test -- --reporter=default` — 51 files passed, 391 tests passed. Existing async React `act(...)` warnings appeared in operation, article, and variant-editor tests.
- **TypeScript:** `npm run typecheck` — passed.
- **Production build:** `npm run build` — passed with Next.js 16.2.11; 12 static pages generated and all routes collected. Initial sandboxed attempt failed because Turbopack could not bind an internal port; the authorized rerun passed.
- **E2E:** `npx playwright test` — all 71 Chromium tests passed in 2.7 minutes. Coverage checks Jobs, automation creation/detail/history, review, Diagnostics, Retention, theme behavior, the complete responsive shell matrix, page overflow, and serious/critical axe violations.
- **Accessibility:** desktop/mobile and light/dark axe checks passed with no serious or critical violations for Today, Automations, Calendar, Diagnostics, diagnostics states, and critical flows. Tablet portrait/landscape now also pass dedicated light/dark shell axe checks.
- **Theme:** saved light/dark preference survives reload; new users follow system preference before hydration; desktop and mobile toggles expose accessible labels, state, tooltips, and theme-specific icons.
- **Route smoke tests:** direct mobile/desktop navigation, the 900px breakpoint, dynamic workflow routes, and `/inbox` plus `/runs` redirects passed in the E2E suite.

## Reference checklist

- `refrencess/Screenshot_20260728_011851.png` — reviewed at native 842×604 resolution; establishes left sidebar, dark neutral surfaces, low-contrast dividers, compact rows, and restrained shadows.
- `refrencess/Component.tsx` — reviewed all 429 lines; canonical React/Tailwind sidebar preview and interaction examples.
- `refrencess/usage.tsx` — reviewed all 429 lines; functionally equivalent to `Component.tsx` with formatting differences.
- `refrencess/STYLE.md` — reviewed all 899 lines; contains integration guidance, the same sidebar implementation twice, dependency guidance, and visual class details.
- Reference mock routes, workspace switcher content, plan name, fake counts, logout, demo search, and placeholder dashboard were explicitly excluded.

## Design-token matrix

| Token | Reference evidence | Migration target |
| --- | --- | --- |
| Page background | Screenshot outer canvas `#121212`; `bg-background` | Semantic `--background` |
| Sidebar background | Screenshot dominant `#1e1e1e`; `bg-card/50` | Semantic `--sidebar` |
| Card background | `bg-card`; screenshot `#1e1e1e` surfaces | Semantic `--card` |
| Popover background | `bg-card` with low-contrast border | Semantic `--popover` |
| Muted background | `bg-black/5`, dark `bg-white/5`; screenshot `#272727` | Semantic `--muted` / interactive tokens |
| Primary foreground | Screenshot near `#e3e3e3`; `text-foreground` | Semantic `--foreground` |
| Secondary foreground | `text-foreground/80` and `/90` | Derived foreground opacity |
| Muted foreground | `text-muted-foreground` at `/30`, `/50`, `/60`, `/70`; screenshot grays `#707070`–`#828282` | Semantic `--muted-foreground` |
| Border | `border-border/50`; screenshot `#2c2c2c` | Semantic `--border` |
| Input | Dark `bg-white/5`, `border-white/10` | Semantic `--input` |
| Active navigation | Light `bg-black/5`; dark `bg-white/10` | Semantic active-navigation state |
| Hover | Light `bg-black/5`; dark `bg-white/5` | Semantic hover-navigation state |
| Focus ring | Reference uses primary/foreground focus treatment but no fixed raw value | Semantic `--ring`; visible 2px ring |
| Destructive | Not specified by reference package | Preserve NewsCraft semantic destructive role |
| Success | Not specified by reference package | Preserve NewsCraft semantic success role |
| Warning | Not specified by reference package | Preserve NewsCraft semantic warning role |
| Error | Not specified separately from destructive | Preserve NewsCraft semantic error/destructive roles |
| Radius scale | 4px keyboard hints, 6px nav/logo, 8px controls, 12px panels, full avatars/badges | `4 / 6 / 8 / 12 / full` |
| Shadow scale | `shadow-xs`, `shadow-sm`, `shadow-xl`, `shadow-2xl`; normal surfaces stay restrained | Four semantic shadow tiers |
| Typography | 10px hints/badges, 11px metadata/groups, 13px nav, 14px body/input, 16px small heading; weights 400/500/600 | Compact dashboard type scale |
| Icon size | 14px chevrons, 16px nav, 18px controls, 24px empty-state icon | Semantic icon scale |
| Icon stroke | 1.5px standard; 2px only for small disclosure chevrons | Lucide outline system |
| Spacing | 2, 4, 6, 8, 10, 12, 16, 24, 32px | 2/4px base rhythm with 8px grouping |
| Transition | 100ms popover, 200ms hover/dialog, 300ms expand/sidebar | Fast/standard/structural motion tokens; respect reduced motion |

## Frontend structure and shared component inventory

- **Application frame:** `app/layout.tsx` owns providers and skip link; `newsroom-shell.tsx` owns sidebar, header, main landmark, content scroll, and mobile navigation.
- **Navigation:** `newsroom-sidebar.tsx` is canonical route data plus desktop navigation; `mobile-newsroom-nav.tsx` reuses that data; `newsroom-header.tsx` presents live automation-control state.
- **Theme:** semantic light/dark variables live in `app/globals.css`; `ThemeProvider` owns runtime state and persistence; the root layout applies saved or system preference before hydration.
- **Configuration:** Tailwind v4 CSS theme mapping lives in `app/globals.css`; `tailwind.config.ts` holds content paths; `components.json` maps shadcn aliases to `components/ui`.
- **Shared UI primitives:** Alert, Badge, Button/IconButton variants, Card/Panel, Checkbox/Radio, Dialog, Input, PageHeader, Progress, Select, Separator, Skeleton, state panels, status badge, Table, Textarea, Tooltip.
- **Shared presentation:** operations page frame, source table/detail/dialog/status components, editorial workspaces/editors/timelines/evidence, notice/query providers, direction boundary, shell/header/sidebar/mobile navigation.
- **Tables:** shared `components/ui/table.tsx` is used by source health and Jobs; other dense structures remain feature-specific.
- **Dialogs:** shared Base UI Dialog primitives now provide portal, scrim, focus trap, Escape handling, focus restoration, title/description, and footer structure; settings dialogs use them. Specialized source, article, job, and editorial dialogs retain their tested feature-local behavior.
- **Loading/empty/error/status:** shared Alert, Skeleton, EmptyState, LoadingState, ErrorState, and semantic StatusBadge primitives are available; Today, Calendar, Jobs, Automations, settings, source health, and job status paths use them where their existing APIs permit.
- **Reserved primitives:** Progress is used by Today. Separator currently has no imports outside its own file and remains reserved; do not delete it without a later repository-wide review.

## Mobile navigation baseline

- Below 900px, fixed five-slot bottom navigation shows Today, Sources, Calendar, Library, and Menu.
- Menu opens an accessible two-column modal containing every surviving top-level route.
- Modal locks body scroll, focuses its first link, traps Tab, closes on Escape/backdrop/route selection, and restores trigger focus.
- At desktop widths below 640px viewport height, CSS intentionally swaps to the mobile pattern to prevent sidebar clipping.

## Visual gap analysis

- Phase 0 baseline had a 92px right navigation rail, contradicting the required left-sidebar reference and Phase 1 layout.
- Phase 3 shared-component migration is complete; page-local token migration remains intentionally incremental for Phases 4–6.
- Shared primitives use semantic tokens consistently; several feature components still contain page-local raw color classes for later page phases.
- Forms, tables, settings dialogs, status badges, notices, page headers, skeletons, and common loading/empty states now follow the reference system. Specialized feature-local dialogs retain their existing tested focus behavior.
- Desktop header and individual pages retain their current layouts; only global shell/sidebar belongs to Phase 1.
- Reference has no mobile pattern, so NewsCraft’s tested bottom bar/modal pattern remains authoritative on small viewports.
- Black draggable `N` source is Next.js 16’s development indicator, not the NewsCraft logo component. It is disabled with supported `devIndicators: false` in `frontend/next.config.ts`; application errors remain intact.

## Phase 4 implementation notes

- Today now uses shared loading, error, empty, progress, and semantic status treatments while preserving live job queries and decision routes.
- Sources now uses denser responsive actions, table columns, health states, detail presentation, and shared form controls; source creation, deletion, selection, and health mutations are unchanged.
- Drafts remains intentionally absent because it was removed before this migration. Reintroducing it would contradict the route inventory and route-preservation rule.
- Calendar now uses compact shared controls, explicit status badges, semantic event accents, and a page-bounded horizontally scrollable month grid with a mobile affordance.
- Library now uses compact cards and metadata, shared state feedback and filter inputs, responsive controls, and a mobile-accessible collection strip instead of hiding collection workflows below 900px.
- Phase 4 page tests cover shared state usage, responsive source columns, calendar status tones, mobile collection controls, and page overflow.

## Phase 5 implementation notes

- Jobs now uses a compact responsive shared table, tabular timestamps, semantic status and error treatments, and the shared Base UI modal for detail focus management, scroll locking, Escape handling, and trigger restoration.
- Automations now uses shared form controls, semantic enabled/readiness/action states, compact route cards, bounded responsive dispatch tables, and shared loading, empty, and error feedback across list, builder, detail, and history routes.
- Diagnostics and durable history now use shared state panels while preserving persisted runtime truth, Tehran timestamps, attention links, and structured metadata.
- Retention now uses shared controls and semantic alerts, including an explicit permanent-cleanup warning and clearly differentiated destructive action after server-authoritative preview and typed confirmation.
- Settings sections now use semantic light/dark status surfaces, consistent nested radii and borders, shared field styling, accessible required indicators, and existing guarded dialogs without changing any settings mutation.
- Review and reconciliation routes now use shared alerts, inputs, selects, textareas, and status badges while preserving exact-revision hashes, publication blockers, durable job state, and operator evidence requirements.
- Phase 5 validation passed 391 unit tests, TypeScript, production build, and all 63 Chromium E2E cases; the expanded critical-path loop covers desktop and 390px mobile overflow plus serious/critical axe checks.

## Phase 6 implementation notes

- Responsive shell checks now cover 1440×900 desktop, 1280×720 laptop, 768×1024 tablet portrait, 1024×768 tablet landscape, 375×812 mobile portrait, and 844×390 mobile landscape.
- Mobile navigation now reserves bottom safe-area space, bounds its modal above the fixed bottom bar, and scrolls only its route grid when landscape height is constrained.
- E2E coverage verifies no page-level overflow, the 900px navigation boundary, desktop sidebar height, 44px mobile targets, landscape dialog bounds, focus trapping/restoration, keyboard tooltips, visible focus outlines, reduced motion, and 200% text sizing.
- Semantic success, warning, destructive, and matching surface tokens replaced remaining page-local red/amber/green status treatments across global controls, collection workflows, editorial review, and package publishing. Intentional source/platform brand colors remain unchanged.
- Dedicated tablet portrait/landscape axe checks pass in light and dark mode with no serious or critical violations.
- Phase 6 validation passed 51 unit-test files and 391 tests, TypeScript, the Next.js production build with 12 static pages, and all 71 Chromium E2E tests.

## Phase 7 implementation notes

- Reviewed the complete migration diff and confirmed that no backend or contract files changed.
- `git diff --check` passed; no debug instrumentation, stale deleted-route imports, reference mock data, or generic raw status colors remain. The RSS source icon intentionally retains its brand orange.
- TypeScript's existing `noUnusedLocals` and `noUnusedParameters` checks passed. Progress remains used by Today; Separator remains intentionally reserved under the Phase 3 inventory decision.
- Compared the current desktop Library, sidebar, and shared collection dialog captures with the native reference screenshot. Layout, density, semantic surfaces, borders, shadows, icon treatment, and modal hierarchy remain coherent; no new redesign was introduced.
- Final validation passed 51 unit-test files and 391 tests, TypeScript, the Next.js production build with 12 static pages, and all 71 Chromium E2E tests.
- The first unit-suite run had one load-sensitive Jobs test timeout. The same test passed in isolation, in six concurrent isolated runs, and in the complete rerun, where it took 1.303 seconds. No product-code change was made for this test-environment timing flake.

---

# 4. Phase 0 — Reference Audit and Migration Baseline

## Goal

Create a reliable implementation map before making broad visual changes.

## Required work

1. Inspect every file under:

```text
/home/armin/Documents/NewsCraft/refrencess/
```

2. Review all available:

- Screenshots
- Markdown documents
- React components
- TypeScript files
- CSS
- Assets
- Example layouts
- Theme definitions
- Interaction patterns

3. Audit the current frontend structure:

- Application shell
- Navigation
- Route definitions
- Global styles
- Tailwind configuration
- shadcn/ui configuration
- Shared components
- Theme handling
- Page layouts
- Table components
- Dialog components
- Status components
- Loading and empty states

4. Identify the real source of the draggable black `N` overlay.

5. Record the existing mobile navigation behavior.

6. Build a design-token matrix from the references.

## Design-token matrix

Document:

- Page background
- Sidebar background
- Card background
- Popover background
- Muted background
- Primary foreground
- Secondary foreground
- Muted foreground
- Border color
- Input color
- Active navigation color
- Hover color
- Focus ring
- Destructive color
- Success color
- Warning color
- Error color
- Radius scale
- Shadow scale
- Typography scale
- Icon sizes
- Icon stroke weights
- Spacing scale
- Transition timing

## Deliverables

- Updated `plan.md`
- Route inventory
- Reference checklist
- Shared component inventory
- Current visual gap analysis
- Baseline test results
- Identified source of the `N` overlay
- No broad redesign yet

## Acceptance criteria

- Every reference file has been reviewed.
- Every remaining frontend route is listed.
- Existing shared components are mapped.
- Test baseline is recorded.
- Backend files remain unchanged.
- No destructive changes are introduced.

## Suggested commit

```text
docs(frontend): add reference migration audit and baseline
```

---

# 5. Phase 1 — Application Shell and Left Sidebar

## Goal

Correct the global application layout and navigation before theming individual pages.

## Required work

### 5.1 Move sidebar to the left

Desktop layout must be:

```text
Left sidebar | Main content
```

Requirements:

- Sidebar is the first layout column.
- Main content is the second layout column.
- Do not use `direction`, transforms, mirroring, or reverse-order hacks.
- Verify in both light and dark mode.

### 5.2 Sidebar structure

Use only real NewsCraft destinations.

Do not copy mock reference entries.

Expected navigation order should be based on product importance and current routes.

Each regular navigation item must include:

- Icon
- Label
- Active state
- Hover state
- Focus state
- Pressed state where relevant
- Correct route behavior

### 5.3 Sidebar sizing

The sidebar must:

- Fit all regular navigation items on standard desktop heights
- Avoid horizontal scrolling
- Avoid vertical scrolling at standard desktop heights
- Avoid clipped labels
- Avoid wrapped labels
- Avoid icon compression
- Avoid page-level overflow

Adjust:

- Sidebar width
- Item height
- Icon size
- Label size
- Padding
- Gaps
- Group spacing

### 5.4 Settings control

Settings must be:

- Inside the same sidebar
- Icon only
- Gear icon
- No visible text
- Positioned at the bottom
- Accessible via `aria-label="Settings"`
- Supported by tooltip
- Visually subtle
- Clearly interactive

Do not place it inside a separate card, bordered block, or detached footer.

### 5.5 Theme toggle placement

Add a theme-toggle control directly above Settings.

At this phase, the final theme implementation may still be incomplete, but the control location and layout must be correct.

### 5.6 Remove the black `N` overlay

If it is an application component:

- Remove the component.
- Remove related imports.
- Remove related state and handlers.
- Remove related styles.

If it is a framework development indicator:

- Disable it using supported configuration.
- Do not hide it with fragile CSS.
- Preserve normal error handling.

### 5.7 Mobile behavior

Do not force the full desktop sidebar into small viewports.

Preserve or improve the existing mobile navigation pattern.

## Deliverables

- Correct application shell
- Left sidebar
- Working navigation
- Settings icon placement
- Theme-toggle placement
- Removed `N` overlay
- Updated shell/navigation tests

## Acceptance criteria

- Sidebar is on the left.
- Main content starts to its right.
- All routes open correctly.
- No sidebar scrollbars on standard desktop sizes.
- Settings is icon-only and inside the sidebar.
- Theme toggle appears directly above Settings.
- The black `N` overlay is gone.
- Mobile navigation still works.
- Backend files remain unchanged.

## Suggested commit

```text
feat(frontend): rebuild application shell and left sidebar
```

---

# 6. Phase 2 — Theme Foundation and Persistent Light/Dark Mode

## Goal

Create a maintainable theme system before page-level restyling.

## Required work

### 6.1 Semantic tokens

Implement shared semantic tokens for:

- Background
- Foreground
- Card
- Card foreground
- Popover
- Muted
- Muted foreground
- Border
- Input
- Primary
- Primary foreground
- Secondary
- Secondary foreground
- Accent
- Destructive
- Success
- Warning
- Error
- Focus ring
- Active navigation
- Hover navigation

Prefer:

- CSS variables
- Tailwind semantic classes
- Existing shadcn/ui conventions

### 6.2 Light mode

Create a polished light theme based on the same visual system as the references.

It should include:

- Soft neutral page background
- Clean white or off-white surfaces
- Subtle borders
- Balanced text contrast
- Restrained shadows
- Clear active states

### 6.3 Dark mode

Match the dark reference closely:

- Deep neutral background
- Slightly lighter sidebar and card surfaces
- Low-contrast borders
- Muted secondary text
- Clear primary text
- Subtle active navigation state
- No harsh pure-black/pure-white contrast

### 6.4 Theme switching

Requirements:

- Toggle light/dark mode
- Persist preference across reloads
- Avoid incorrect-theme flash
- Respect system preference only if user has not chosen
- Accessible label
- Tooltip
- Keyboard support
- Theme-specific icon behavior

Suggested behavior:

- Show sun icon in dark mode
- Show moon icon in light mode

### 6.5 Global foundation

Apply theme tokens to:

- `body`
- Application shell
- Sidebar
- Page background
- Default typography
- Borders
- Focus rings
- Selection color
- Scrollbar styling if intentionally customized

## Deliverables

- Shared light/dark token system
- Persistent theme switching
- No incorrect-theme flash
- Updated theme tests
- Updated global styles

## Acceptance criteria

- Theme persists after refresh.
- No flash of the wrong theme.
- New users follow system theme.
- All routes receive correct base tokens.
- Theme toggle is accessible.
- Light and dark contrast are acceptable.
- Backend files remain unchanged.

## Suggested commit

```text
feat(frontend): add persistent light and dark themes
```

---

# 7. Phase 3 — Shared Component Migration

## Goal

Update reusable components before page-by-page styling.

## Required components

Audit and migrate, where present:

- Button
- IconButton
- Input
- Select
- Textarea
- Checkbox
- Radio
- Switch
- Card
- Panel
- Badge
- Status badge
- Tabs
- Tooltip
- Dropdown menu
- Context menu
- Dialog
- Drawer
- Sheet
- Toast
- Alert
- Skeleton
- Empty state
- Loading state
- Table primitives
- Pagination
- Page header
- Breadcrumbs
- Date/time controls

## Requirements

- Preserve public APIs unless change is necessary.
- Search all usages before changing shared props.
- Use semantic tokens.
- Support both themes.
- Preserve keyboard and screen-reader behavior.
- Use consistent icon sizing.
- Use consistent radius, border, and shadow values.
- Avoid duplicated page-level arbitrary styles.
- Avoid unrelated rewrites.

## Deliverables

- Restyled shared component system
- Updated component tests
- Updated accessibility tests
- Updated component documentation if present

## Acceptance criteria

- Shared components render correctly in both themes.
- No repository-wide breakage from API changes.
- Focus states remain visible.
- Dialogs and menus manage focus correctly.
- Status styles are consistent.
- Backend files remain unchanged.

## Completion record

- Added native-compatible shared Input, Select, Textarea, Checkbox, and Radio controls with consistent responsive sizing, invalid states, disabled states, focus rings, and semantic tokens.
- Added Base UI Dialog composition with modal semantics, focus trapping, Escape dismissal, scroll lock, outside-press handling, and focus restoration; migrated settings dialogs without changing their public behavior.
- Added Alert, Skeleton, EmptyState, LoadingState, ErrorState, StatusBadge, and PageHeader primitives; migrated repeated shared usage across Today, Calendar, Jobs, Automations, Settings, editorial review, source health, and job status.
- Restyled Button, Badge, Card, Table, Tooltip, Progress, notices, and status treatments to the reference radius, density, icon stroke, border, shadow, and motion system.
- Measured light status foreground/surface pairs at 5.67:1–7.21:1 and verified light/dark axe coverage with no serious or critical violations.
- Added `tests/ui-primitives.test.tsx` for native form semantics, dialog naming and focus restoration, status/feedback states, button API preservation, and accessible toast dismissal.
- Verification: 51 unit files / 391 tests passed; TypeScript passed; production build passed; all 62 Chromium E2E cases passed, including responsive, keyboard, dialog, light/dark, and axe coverage.

## Suggested commit

```text
refactor(frontend): align shared components with reference system
```

---

# 8. Phase 4 — Primary Workflow Pages

## Goal

Migrate the main user-facing workflows.

## Pages

- Today
- Sources
- Drafts
- Calendar
- Library

## General requirements

- Preserve current page logic.
- Preserve routes.
- Preserve data-fetching and mutations.
- Do not move features between pages.
- Do not replace real data with mock reference content.
- Use shared components from Phase 3.

## Page-specific focus

### Today

- Clear information hierarchy
- Balanced dashboard density
- Reference-aligned cards
- Consistent empty/loading/error states

### Sources

- Compact table
- Visible important columns
- Clear status styling
- Refined details panel
- Responsive source management dialogs
- No unnecessary horizontal scrolling
- Consistent health-check states

### Drafts

- Refined cards and list states
- Clear review status
- Consistent action hierarchy
- Better metadata readability

### Calendar

- Appropriate visual density
- Clear event states
- Good light/dark readability
- Responsive behavior

### Library

- Refined filters
- Compact metadata presentation
- Clear item hierarchy
- Stable responsive layout

## Deliverables

- All five pages migrated
- Page-level tests updated
- Responsive tests updated
- No business logic changes

## Acceptance criteria

- Existing workflows still work.
- No page-level horizontal overflow.
- Tables remain readable.
- Mobile layouts are usable.
- Empty/loading/error states match the design system.
- Backend files remain unchanged.

## Suggested commit

```text
style(frontend): migrate primary newsroom pages
```

---

# 9. Phase 5 — Operational and Settings Pages

## Goal

Migrate technical and administrative areas.

## Pages

- Jobs
- Automations
- Diagnostics
- Retention
- Settings
- Review pages
- Detail pages
- Any remaining routes not completed in Phase 4

## Focus areas

### Jobs

- Compact tables
- Clear states
- Readable timestamps
- Clear action hierarchy

### Automations

- Consistent controls
- Clear enabled/disabled states
- Refined schedule metadata

### Diagnostics

- Technical density without clutter
- Readable severity states
- Responsive structured data
- Clear retry/error actions

### Retention

- Clear destructive actions
- Strong warnings
- Consistent form structure

### Settings

- Logical section grouping
- Consistent labels
- Refined inputs and switches
- Clear save/error states
- Good light/dark readability

## Deliverables

- All remaining routes migrated
- Tests updated
- Status and destructive styles standardized

## Acceptance criteria

- Every remaining route follows the same design system.
- Technical tables remain responsive.
- Destructive actions are clearly differentiated.
- Settings forms are accessible.
- Backend files remain unchanged.

## Suggested commit

```text
style(frontend): migrate operational and settings pages
```

---

# 10. Phase 6 — Responsive, Accessibility, and Visual Consistency

## Goal

Improve quality without adding new features.

## Required viewport checks

- Standard desktop
- Smaller laptop
- Tablet portrait
- Tablet landscape
- 375px mobile portrait
- Mobile landscape

## Required behavior checks

- Browser zoom
- Keyboard navigation
- Focus states
- Dialog focus management
- Tooltips
- Icon-only controls
- Contrast
- Reduced motion
- Touch targets
- Content overflow
- Sidebar behavior
- Table responsiveness
- Long labels
- Loading states
- Error states

## Visual consistency review

Compare all major routes against the reference package for:

- Color
- Spacing
- Typography
- Borders
- Radius
- Shadows
- Icon sizing
- Surface hierarchy
- Active states
- Hover states
- Dark mode
- Light mode

## Deliverables

- Responsive polish
- Accessibility fixes
- Visual consistency corrections
- Updated E2E and axe coverage

## Acceptance criteria

- No page-level horizontal overflow.
- No overlapping content.
- No clipped essential controls.
- No inaccessible icon-only buttons.
- Light and dark modes pass accessibility checks.
- Navigation works at all supported sizes.
- Backend files remain unchanged.

## Suggested commit

```text
test(frontend): complete responsive and accessibility polish
```

---

# 11. Phase 7 — Final Validation and Cleanup

## Goal

Validate the entire migration and fix regressions only.

Do not begin a new redesign in this phase.

## Required commands

Run the project’s actual equivalents of:

```bash
npm run test
npm run typecheck
npm run build
npm run test:e2e
```

Also run:

- Navigation tests
- Theme-toggle tests
- Theme-persistence tests
- Route smoke tests
- Light-mode accessibility checks
- Dark-mode accessibility checks

## Manual validation checklist

- [x] Sidebar is on the left.
- [x] Main content begins to the right.
- [x] No sidebar horizontal scrollbar.
- [x] No sidebar vertical scrollbar at standard desktop height.
- [x] Navigation labels and icons fit.
- [x] Theme toggle is directly above Settings.
- [x] Settings is icon-only and inside the sidebar.
- [x] Light theme applies to every route.
- [x] Dark theme applies to every route.
- [x] Theme preference persists.
- [x] No incorrect-theme flash.
- [x] Black draggable `N` overlay is removed.
- [x] All routes open correctly.
- [x] Existing workflows still work.
- [x] No backend file changed.
- [x] No reference mock data was introduced.
- [x] No unnecessary horizontal page overflow.
- [x] Tables, dialogs, forms, and detail panels still work.
- [x] UI is visually coherent and professional.

## Cleanup

- Remove confirmed dead frontend code.
- Remove obsolete styling no longer used.
- Remove duplicate tokens.
- Remove unused imports.
- Verify no shared component was deleted while still referenced.
- Review full Git diff.
- Confirm frontend-only scope.

## Final report

The final implementation report must include:

1. Reference files reviewed
2. Global design tokens added or changed
3. Application-shell changes
4. Sidebar changes
5. Theme-switching implementation
6. Shared components migrated
7. Pages migrated
8. Removal of the black `N` overlay
9. Responsive and accessibility changes
10. Tests and commands executed
11. Exact test results
12. Files changed
13. Genuine remaining limitations

Do not claim a test passed unless it was actually executed.

## Suggested commit

```text
chore(frontend): finalize reference migration validation
```

---

# 12. Session Handoff Protocol

At the end of every session, update this document.

Required handoff format:

```markdown
## Session handoff

### Completed
- ...

### Files changed
- ...

### Tests passed
- ...

### Tests failed
- ...

### Known issues
- ...

### Next session
- ...

### Recommended first commands
- git status
- git log --oneline -10
- ...
```

The next session must begin by reading:

```text
plan.md
git status
git log --oneline -10
```

Then it should inspect only the files relevant to the next phase unless a broader audit is necessary.

## Session handoff — Phase 0 through Phase 2

### Completed

- Audited all four reference files and current frontend architecture.
- Recorded authoritative routes, shared components, mobile behavior, token matrix, visual gaps, and baseline results.
- Rebuilt desktop shell as `260px left sidebar | minmax(0, 1fr) main content`.
- Replaced compact right rail presentation with reference-aligned labeled NewsCraft navigation groups.
- Kept only real routes and retained shared route data for desktop/mobile navigation.
- Added working theme placement control directly above icon-only Settings.
- Added persistent light/dark state with saved preference, system fallback, live system-change handling until explicit selection, and pre-hydration bootstrap.
- Added semantic error, focus, navigation hover, and navigation active roles plus reference-matched neutral surfaces for both themes.
- Added accessible moon/sun theme toggles to desktop sidebar and mobile navigation panel.
- Kept Settings inside sidebar with `aria-label="Settings"` and tooltip.
- Preserved arrow/Home/End keyboard movement, focus styling, active/hover/pressed states, mobile modal focus management, reduced-motion handling, and short-height fallback.
- Confirmed black draggable `N` is Next.js development indicator and confirmed supported `devIndicators: false` configuration.
- Updated shell/navigation unit and E2E coverage, including light/dark sidebar checks and 260px-layout Feed density.

### Files changed

- `plan.md`
- `frontend/components/newsroom/newsroom-shell.tsx`
- `frontend/components/newsroom/newsroom-sidebar.tsx`
- `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- `frontend/components/newsroom/newsroom-header.tsx`
- `frontend/components/providers/theme-provider.tsx`
- `frontend/components/theme/theme-toggle.tsx`
- `frontend/lib/theme.ts`
- `frontend/app/layout.tsx`
- `frontend/app/globals.css`
- `frontend/tests/newsroom-shell.test.tsx`
- `frontend/tests/navigation.test.tsx`
- `frontend/tests/mobile-nav.test.tsx`
- `frontend/tests/theme.test.tsx`
- `frontend/e2e/accessibility.spec.ts`
- `frontend/e2e/feed-desktop.spec.ts`
- `frontend/e2e/theme.spec.ts`

### Tests passed

- `npm test -- --reporter=default` — 50 files, 386 tests passed in 40.23s.
- `npm run typecheck` — passed.
- `npm run build` — passed; 12 static pages generated.
- `npm run test:e2e` — 62 Chromium tests passed in 3.1m.
- Final axe coverage passed in desktop/mobile and light/dark modes with no serious or critical violations.
- System-theme first paint, explicit preference persistence, sidebar interaction, and visual screenshot checks passed.

### Tests failed

- No outstanding failures.
- Phase 2’s first E2E run exposed a hydration race in test-only theme setup and an eager hover-transition assertion. Both were corrected; targeted checks and the complete rerun passed.

### Known issues

- Existing unit suite still emits React `act(...)` warnings in unrelated operation, article, and variant-editor tests.
- No commit was created because the repository began with extensive overlapping uncommitted frontend work.

### Next session

- Execute Phase 3 only: migrate shared components to the completed semantic theme foundation.

### Recommended first commands

- `git status`
- `git log --oneline -10`
- `sed -n '1,260p' plan.md`
- `sed -n '/# 7\\. Phase 3/,/# 8\\. Phase 4/p' plan.md`
- `rg --files frontend/components/ui`

---

## Session handoff — Phase 6

### Completed

- Completed responsive and accessibility audit against Phase 6 requirements and the native reference screenshot.
- Added safe-area-aware bottom spacing and a height-bounded, internally scrollable mobile navigation panel.
- Standardized remaining generic status/error colors on semantic light/dark tokens.
- Added six-viewport shell coverage plus focus, tooltip, touch-target, reduced-motion, 200% text-size, overflow, and tablet light/dark axe checks.
- Confirmed no backend code or API behavior changed.

### Files changed

- `plan.md`
- `frontend/app/globals.css`
- `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- `frontend/components/newsroom/newsroom-header.tsx`
- `frontend/components/newsroom/newsroom-shell.tsx`
- `frontend/components/newsroom/newsroom-sidebar.tsx`
- `frontend/components/editorial/content-pack-workspace.tsx`
- `frontend/components/editorial/evidence-panel.tsx`
- `frontend/components/editorial/variant-editor.tsx`
- `frontend/features/articles/collection-management.tsx`
- `frontend/features/articles/save-to-collection-dialog.tsx`
- `frontend/features/control/global-controls.tsx`
- `frontend/features/packages/components/copy-export-actions.tsx`
- `frontend/features/packages/components/manual-publishing-checklist.tsx`
- `frontend/features/packages/components/media-plan.tsx`
- `frontend/features/packages/components/platform-editor.tsx`
- `frontend/features/packages/components/telegram-preview.tsx`
- `frontend/e2e/responsive-accessibility.spec.ts`

### Tests passed

- `npm test -- --reporter=dot` — 51 files, 391 tests passed.
- `npm run typecheck` — passed.
- `npm run build` — passed with Next.js 16.2.11; 12 static pages generated and all routes collected.
- `npx playwright test e2e/responsive-accessibility.spec.ts e2e/sources.spec.ts` — 10 tests passed.
- `npx playwright test` — 71 Chromium tests passed in 2.7 minutes.
- Tablet portrait/landscape light/dark axe coverage found no serious or critical violations.

### Tests failed

- No outstanding failures.
- Sandboxed production build and Playwright server startup could not bind local ports. Authorized reruns passed.

### Known issues

- Existing unit suite still emits React `act(...)` warnings in operation, article, and variant-editor tests.
- Headless Playwright does not apply Chromium browser-chrome zoom shortcuts; Phase 6 automated coverage uses responsive reflow plus 200% root text sizing. Final manual Phase 7 browser-zoom inspection remains recommended.
- No commit was created because the repository began with extensive overlapping uncommitted frontend work.

### Next session

- Execute Phase 7 only: final validation, cleanup, complete manual checklist, and final report.

### Recommended first commands

- `git status`
- `git log --oneline -10`
- `sed -n '1,360p' plan.md`
- `sed -n '/# 11\\. Phase 7/,/# 12\\. Session Handoff/p' plan.md`
- `git diff --check`

---

## Session handoff — Phase 7

### Completed

- Completed the Phase 7 regression-only cleanup and final validation pass.
- Reviewed the reference package, current visual captures, semantic token system, full Git diff, frontend-only scope, deleted-route references, raw status colors, debug instrumentation, and reference mock-data leakage.
- Completed every Phase 7 manual checklist item using direct visual review plus unit, build, route, theme, responsive, workflow, and accessibility evidence.
- Restored the generated-only `next-env.d.ts` path change produced by the validation build so the final diff contains no build artifact.
- Confirmed no new redesign, backend change, contract change, or reference mock workflow was introduced.

### Files changed

- `plan.md`

No product code changed during Phase 7. The complete migration worktree contains 90 modified tracked files, 8 deleted tracked files, and 20 untracked paths, including `plan.md` and the provided `refrencess/` package.

### Tests passed

- `npm test -- --reporter=default` — final rerun passed: 51 files, 391 tests in 53.24s.
- `npm run typecheck` — passed with strict unused-local and unused-parameter checks enabled.
- `npm run build` — passed outside the sandbox with Next.js 16.2.11; compiled in 7.6s, TypeScript completed in 16.6s, 12 static pages generated, and all routes collected.
- `npm run test:e2e` — 71 Chromium tests passed in 3.4 minutes.
- Navigation, route smoke, removed-route redirect, theme toggle, system-theme first paint, persisted preference, light/dark accessibility, responsive shell, touch target, focus, reduced-motion, 200% text-size, dialog, form, table, and end-to-end workflow checks passed inside those suites.
- `git diff --check` — passed.
- Frontend-only scope audit — no changed files under `backend/` or `contracts/`.

### Tests failed

- First full unit run: 1 Jobs test timed out waiting for its initial mocked row; 50 files and 390 tests passed. The test passed in isolation, under six concurrent isolated runs, and in the final complete rerun. This is a load-sensitive test timing flake, not an outstanding product regression.
- First sandboxed production build: Turbopack could not bind its internal port (`Operation not permitted`). The authorized rerun passed.
- An extra root-level `npx tsc` diagnostic attempted to resolve an unrelated registry package and failed with `EAI_AGAIN`; it was not a project test. The actual local `npm run typecheck` passed.

### Known issues

- Existing unit tests still emit React `act(...)` warnings in operation, article, and variant-editor tests.
- Browser-chrome zoom shortcuts are not applied by headless Chromium. Automated coverage verifies responsive reflow and 200% root text sizing; an interactive browser-zoom spot check remains the only genuine manual limitation.
- The worktree still contains the complete multi-phase migration as uncommitted changes. No commit was created because the task did not request one and the repository began with overlapping uncommitted work.

### Next session

- Migration is complete. Review and commit the full frontend migration when ready; no implementation phase remains.

### Recommended first commands

- `git status`
- `git diff --check`
- `git diff --stat`
- `git diff -- frontend`
- `cd frontend && npm test -- --reporter=default`

---

# 13. Definition of Done

The migration is complete only when:

- Every reference file has been reviewed.
- Sidebar is correctly placed on the left.
- Theme toggle and Settings are correctly positioned.
- The black `N` overlay is removed.
- Light and dark modes are complete and persistent.
- Shared components match the reference system.
- Every remaining frontend route is migrated.
- Responsive layouts are usable.
- Accessibility checks pass.
- Unit tests pass.
- TypeScript passes.
- Production build passes.
- E2E tests pass.
- Backend files remain unchanged.
- The final frontend is visually polished, cohesive, and closely aligned with the reference package.
