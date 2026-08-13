# Phase 12 — Diagnostics Accessibility and Contrast

## Status and scope

- **Strict status:** IMPLEMENTATION COMPLETE — HEALTHY-HARDWARE AXE AND MANUAL VERIFICATION PENDING
- **Starting revision:** `cc603b3` on `phase-12-diagnostics-accessibility`
- **Model:** GPT-5 Codex
- **Authoritative source:** `docs/archive/solutions.md`, Phase 12
- **Prerequisites:** Phase 10's repaired `/operations/diagnostics` and reconciliation mocks plus Phase 7's blocking browser job are present.

The documented defect was confirmed in source: the shared destructive badge used 12 px destructive text over 10%/20% translucent same-token backgrounds. Diagnostics used that badge for its highest-priority error attention and used light-theme-only ad hoc component status classes.

## Implementation

- `Badge` now supplies explicit semantic `error`, `warning`, `success`, and `neutral` variants with paired light/dark foreground, background, border, and focus-ring classes.
- The legacy `destructive` badge uses the same explicit error palette, removing the unsafe translucent pairing for all existing consumers.
- Forced-colors classes retain visible text/borders. Status remains visible text; all nearby status/action icons are decorative with `aria-hidden="true"`.
- Diagnostics maps every component status exhaustively to a semantic badge variant. Attention errors/warnings use semantic variants rather than destructive/outline ad hoc choices.
- The shared Phase 10 diagnostics fixture now includes an actual error-attention row, so the repaired Axe route exercises the original failing treatment.
- Accessibility coverage is defined for light and dark themes at 390×844 and 1440×1000. The existing skip-link, focus, touch-target, and unmatched-request assertions remain.
- Each viewport/theme combination explicitly exercises healthy, degraded,
  down, unknown, warning, and error palettes plus loading and API-error states.
- `badge-contrast.test.tsx` numerically protects normal-text >=4.5:1 and focus-indicator >=3:1 for all eight theme/status pairs and statically rejects the old translucent classes.
- Diagnostics component tests cover visible healthy/degraded/down/unknown/error labels, semantic classes, RTL prose, action naming, exact timestamps, and decorative icon semantics.
- `docs/operations/accessibility-verification.md` records the required keyboard, zoom/reflow, forced-color, reduced-motion, RTL, and screen-reader release checklist and evidence fields.

No API, database, or data behavior changed.

## Files

- `frontend/components/ui/badge.tsx`
- `frontend/features/operations/diagnostics-dashboard.tsx`
- `frontend/e2e/support/mock-backend.ts`
- `frontend/e2e/accessibility.spec.ts`
- `frontend/tests/badge-contrast.test.tsx`
- `frontend/tests/diagnostics-dashboard.test.tsx`
- `docs/operations/accessibility-verification.md`
- this report

## Evidence

Static WCAG luminance calculations produced:

| Pair | Text ratio | Focus ratio |
| --- | ---: | ---: |
| error light | 8.20:1 | 5.30:1 |
| error dark | 13.22:1 | 8.51:1 |
| warning light | 13.45:1 | 6.37:1 |
| warning dark | 13.45:1 | 10.39:1 |
| success light | 8.57:1 | 6.78:1 |
| success dark | 13.36:1 | 9.94:1 |
| neutral light | 16.30:1 | 9.45:1 |
| neutral dark | 18.41:1 | 13.59:1 |

Source scans confirmed the old `bg-destructive/10`, `dark:bg-destructive/20`, and `text-destructive` badge treatment is absent from Badge/Diagnostics. Decorative icons in the component retain `aria-hidden="true"`.

The completion audit passed the lightweight generated-contract/status test set,
TypeScript typecheck, and deterministic collection of all 60 Playwright cases.
Chromium/Axe execution and manual assistive-technology checks remain deferred
to the Phase 7 healthy CI runner.

## Acceptance and Definition of Done

- [x] Exact source-level failing treatment and affected node are identified.
- [x] Explicit semantic light/dark status pairs replace translucent destructive text.
- [x] Numeric palette tests encode >=4.5:1 text and >=3:1 focus thresholds.
- [x] Diagnostics retains text labels, named links, RTL boundary, timestamps, and decorative icons.
- [x] Light/dark and mobile/desktop Axe scenarios encode every status palette
  plus loading and API-error states in the blocking browser suite.
- [x] Manual zoom/forced-color/RTL/screen-reader checklist is documented.
- [ ] Runtime Vitest, Axe, keyboard, zoom, forced-color, and screen-reader evidence is pending healthy hardware by explicit user direction.

## Risks, cleanup, and rollback

- Tailwind class presence and numeric palette math do not replace computed browser evidence; release remains gated on healthy CI plus the manual checklist.
- The shared destructive badge changes visually wherever used, but preserves its semantic intent with a stronger contrast pair.
- No generated screenshots, Axe JSON, `.next`, core dump, or credential artifact is committed.
- Rollback should preserve an explicit verified error palette; do not restore the translucent same-token classes or suppress Axe.

The pre-existing untracked root `AGENTS.md` remains excluded and untouched. No Phase 11 behavior was implemented.
