# Documentation index

Created 2026-08-13. This file exists because four planning programmes had
accumulated under `docs/` with no entry point and with conflicting route
names. It says what each area is and whether it is live; it makes no new
decisions. `README.md` (development and operations), `AGENTS.md` (agent
skills), and `CLAUDE.md` (gates and toolchain) remain the repository's
top-level entry points.

## Canonical vocabulary

Older documents predate the newsroom shell and use route names that no
longer exist. When a doc disagrees with this list, the code wins
(`frontend/components/newsroom/newsroom-sidebar.tsx`,
`frontend/app/**/page.tsx`):

| Concept | Current route | Names used in archived docs |
| --- | --- | --- |
| Daily overview | `/` (Today) | Today |
| Ingestion sources | `/sources` | Sources |
| Article surface | `/feed` | `/content`, `/inbox` (frontend-audit), `/articles` (frontend-consolidation) |
| Automations | `/automations` | Automations, Telegram routes |
| Jobs, diagnostics, health | `/operations` | `/jobs`, `/diagnostics`, `/runs` |
| Settings | `/settings` | `/settings/content`, Advanced > System |

`/jobs`, `/diagnostics`, `/calendar`, and `/settings/content` still resolve
but only as redirect stubs into the routes above. `/drafts`, `/library`,
`/media`, `/inbox`, `/content`, and `/runs` have no page at all.

## Planning programmes

| Programme | Scope | Status | Entry doc |
| --- | --- | --- | --- |
| Guided Visual Workflow Builder | Six-phase build of the `/automations` builder | Active — phase status table in the plan; section 2 is a historical snapshot | [`plan.md`](../plan.md) |
| Workflow builder implementation notes | Per-phase evidence and the accepted implementation contract for the plan above | Active | [`implementation-notes/automation-workflow-builder-contract.md`](implementation-notes/automation-workflow-builder-contract.md) |
| Production hardening (phases 01–15) | 2026-07 hardening programme: transaction boundaries, CI, locking, readiness, contracts, restore | Closed — all 15 phases implemented and audited | [`implementation-reports/hardening-final-audit.md`](implementation-reports/hardening-final-audit.md); plan restored at [`archive/solutions.md`](archive/solutions.md) |
| Frontend audit (2026-07-21/22) | Route-by-route audit of the pre-newsroom shell and a proposed IA | Superseded — every file carries a supersession banner | [`frontend-audit/current-state.md`](frontend-audit/current-state.md) |
| Frontend consolidation | Articles/Collections data contract, field map, wireframe, metadata normalization | Partly superseded — the `/articles` surface shipped as `/feed`; the Collections decision is implemented | [`frontend-consolidation/data-contract.md`](frontend-consolidation/data-contract.md) |

## Reference areas (not programmes)

| Area | Contents |
| --- | --- |
| [`adr/`](adr/) | Accepted architecture decision records |
| [`agents/`](agents/) | Agent-facing domain notes, issue tracker, triage labels |
| [`operations/`](operations/) | Runbooks: CI, dependencies, backup/restore, proxy policy, readiness, release acceptance |
| [`content-settings/`](content-settings/) | Target architecture, migration map, and threat model for settings and credentials |
| [`archive/`](archive/) | Restored historical planning artifacts, kept only so citations resolve |
| [`research/`](research/), [`codex/`](codex/), [`superpowers/`](superpowers/) | Standalone notes and tooling specs |

Single-file references live at the top of `docs/`:
[`ingestion-backend.md`](ingestion-backend.md),
[`ingestion-source-catalog.md`](ingestion-source-catalog.md),
[`proxy-validation-notes.md`](proxy-validation-notes.md),
[`refactor-performance-baseline.md`](refactor-performance-baseline.md),
[`production-readiness-audit-2026-07-15.md`](production-readiness-audit-2026-07-15.md),
and [`armin-selective-audit.md`](armin-selective-audit.md).
