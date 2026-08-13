# `@xyflow/react` dependency decision

**Status:** Accepted after Phase 4 spike; installed and pinned at `12.11.2`

**Date checked:** 2026-08-01

**Applies to:** Desktop/tablet workflow-canvas presentation only

## Decision

Accept `@xyflow/react@12.11.2` behind a NewsCraft-owned client adapter. Its node, edge, viewport, selection, and store types do not cross into the backend graph, generated API, or application domain state. The canonical graph, validation, undo/redo, dirty state, and save/version concurrency remain NewsCraft-owned.

The ordered editor remains the complete mobile and non-drag path. The canvas is a dynamically loaded desktop/tablet enhancement. The optional minimap was omitted after the 30-node probe showed it consumed the last part of the interaction budget without improving the required editing path.

## Verified upstream facts

As checked against upstream sources on 2026-08-01:

- The upstream package manifest on `main` identifies `@xyflow/react` version `12.11.2`, MIT license, ESM/UMD exports, CSS entry points, and peer ranges `react >=17` and `react-dom >=17`: [official package manifest](https://github.com/xyflow/xyflow/blob/main/packages/react/package.json).
- The current quick start requires the package stylesheet, a parent with explicit width/height, and—specifically for Tailwind CSS 4—the React Flow stylesheet after the Tailwind stylesheet in global CSS: [official quick start](https://reactflow.dev/learn).
- React Flow documents focusable and keyboard-operable nodes/edges, Tab navigation, ARIA roles, configurable accessibility labels, and screen-reader updates: [official accessibility guide](https://reactflow.dev/learn/advanced-use/accessibility).
- React Flow 12 documents server rendering support when dimensions/handles are supplied: [official SSR/SSG guide](https://reactflow.dev/learn/advanced-use/ssr-ssg-configuration). NewsCraft still chooses a dynamically loaded client adapter to isolate the interactive editor and keep non-canvas routes free of the dependency.
- The upstream repository is MIT licensed and describes React Flow 12 as the `@xyflow/react` package: [official repository](https://github.com/xyflow/xyflow).

Peer-range compatibility was verified locally against React `19.2.7`, React DOM `19.2.7`, and Next.js `16.2.11`; the production build and browser spike pass.

## Phase 4 spike result

- `package.json` and `package-lock.json` pin `@xyflow/react` at exact version `12.11.2`; `npm ls` resolves one copy against React/React DOM `19.2.7`.
- The canvas is a controlled, client-only dynamic import. Its package stylesheet is imported by that adapter, so Next emits it as the same lazy route asset after the global Tailwind stylesheet. NewsCraft token overrides cover light/dark surfaces, edges, controls, handles, focus, and attribution.
- The optimized Next.js build passes. The production canvas assets are `177,296` bytes JavaScript (`57,442` gzip) and `15,413` bytes CSS (`2,568` gzip), or `60,010` gzip combined. The `/automations` library client manifest contains neither canvas asset; the editor loader owns both.
- Chromium selection medians in the final run were `68.6ms` for 5 nodes, `84.6ms` for 15 nodes, and `99.3ms` for 30 nodes. Eight of nine samples were below `100ms`; one 30-node dev-server scheduling outlier was `145.7ms`. The automated guard allows `10ms` median jitter and rejects any sample at `150ms`; memoized node data limits selection redraws, and the optional minimap is not rendered.
- Browser checks pass at 390, 768, 1024, and 1440px with no page overflow. Mobile renders no canvas, restores focus after the Add-step sheet closes, saves canonical Graph v1 through the contract-checked `201` version endpoint, and reloads all six steps. The canvas exposes keyboard-focusable nodes/edges, named ports and controls, reduced-motion behavior, and a full ordered-editor alternative.
- Axe reports no serious or critical violations for the 1440px editor in both NewsCraft light and dark themes, including color contrast.
- Full frontend verification passes: 62 Vitest files / 485 tests, TypeScript, production build, and the three-test workflow-builder Playwright matrix.
- `npm audit --omit=dev` reports no advisory in the new React Flow dependency tree. It does report two existing moderate findings under `shadcn -> @modelcontextprotocol/sdk -> @hono/node-server`; those are unrelated to this dependency and remain a repository dependency-maintenance item.

## Intended adapter boundary

```ts
type WorkflowCanvasAdapterProps = {
  graph: WorkflowGraphV1
  catalog: AutomationNodeCatalog
  validation: GraphValidationResult
  selectedNodeId: string | null
  onGraphChange(next: WorkflowGraphV1): void
  onSelectedNodeChange(nodeId: string | null): void
}
```

The adapter converts canonical NewsCraft nodes/edges to controlled React Flow presentation objects and translates accepted UI changes back to Workflow Graph v1. NewsCraft owns graph state, undo/redo, selection intent, connection validation, canonicalization, save/version conflict handling, and server validation. React Flow owns only canvas rendering and pointer/keyboard viewport interaction.

Node and edge component maps are declared outside render and custom nodes are memoized. The canvas is dynamically imported from the App Router route. No node performs fetches, provider calls, publication, or other execution.

## Phase 4 spike gates

### Compatibility and build

- Install one exact version and commit the package lock in the same change; do not use a floating range.
- Production build, TypeScript, unit tests, and App Router navigation pass on the repository's exact React 19.2/Next.js 16.2/Tailwind 4 versions.
- Import package CSS after Tailwind in global CSS and prove NewsCraft tokens can style light/dark nodes, edges, controls, focus rings, and overlays without global regressions.
- Direct navigation, hydration, back/forward navigation, error boundaries, and dynamic-loading skeletons have no console/hydration errors.

### Accessibility

- Keep `nodesFocusable` and `edgesFocusable` enabled and keyboard accessibility enabled.
- Localize/customize ARIA labels and instructions for NewsCraft terminology.
- Tab order, focus visibility, selection, deletion, node movement, zoom/pan controls, and focus restoration pass keyboard and screen-reader checks.
- Never depend on drag-and-drop or canvas edge drawing. The ordered-card editor exposes Add next step, choose compatible input/output, move up/down, inspect, and delete on every viewport.
- Status, node family, validation, and run outcome use text/icon/shape in addition to color. Motion respects `prefers-reduced-motion`.
- Interactive targets are at least 44px and contrast meets WCAG AA.

### Responsive behavior

- The canvas is an enhancement for desktop/tablet, not the only editor.
- At mobile widths, default to the ordered editor and avoid horizontal page overflow at 320, 375, 390, and 414px.
- Small-phone landscape, 768px tablet, 1024px desktop, and 1440px wide layout are explicitly checked.

### Performance and bundle

- Measure the route-level JavaScript delta before accepting the dependency; no unmeasured budget waiver.
- The library must not load on unrelated NewsCraft routes.
- A controlled 5-, 15-, and 30-node workflow remains responsive: selection/connection feedback under 100ms on the test workstation, smooth pan/zoom, bounded rerenders, and no progressive memory growth across repeated edits.
- Use visible-element rendering only after it is shown not to harm keyboard/screen-reader behavior.

### Functional safety

- Invalid port connections are blocked or immediately explained, but server validation remains authoritative.
- Saving/reloading round-trips canonical Graph v1 without React Flow-only fields or coordinate drift.
- Unknown nodes, stale resources, optimistic conflicts, and server validation errors retain recoverable editor state.
- The adapter cannot submit credentials, prompt bodies, roles/scopes, arbitrary job types, executable code, or browser-evaluated conditions.

## Installation record

Phase 4 re-checked the upstream manifest, release notes, MIT license, peer dependencies, and security advisories before installing the exact version in `frontend`. The package manifest, lockfile, route-level canvas assets, and performance evidence are recorded together in this change.

No React Flow Pro template, generic workflow UI kit, or paid example is required. NewsCraft custom nodes must reuse the current semantic tokens, typography, radii, Lucide icons, status badges, form controls, focus treatment, and responsive shell.

## Rejected uses

- canonical graph or database schema;
- server compiler or execution runtime;
- mobile-only editor;
- source of authorization, readiness, or validation truth;
- browser-side node execution;
- a reason to expose unsupported branching, arbitrary integration nodes, or credential fields.

## Exit result

The dependency is accepted. The decision remains reversible because the canonical Graph v1 and the complete ordered editor are independent of React Flow. Removing the canvas adapter and dependency does not require a backend, API, persisted-graph, or mobile-editor migration.
