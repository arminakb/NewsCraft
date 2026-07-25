# Frontend/backend dependency matrix

All browser API calls normally pass through the same-origin Next.js proxy at `/api/backend/*`. This matrix groups closely related endpoints; it is not an OpenAPI replacement.

| Frontend surface | Reads | Mutations | Capability / protection notes |
| --- | --- | --- | --- |
| Global shell | `GET /automation-control`, `GET /jobs/summary` | None | Shows truthful global state and sidebar queue counts on every route. |
| Today `/` | `GET /automation-control`, `GET /jobs`, `GET /jobs/summary`, `GET /telegram/drafts`, `GET /telegram/reconciliation` | `PATCH /automation-control`, `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel` | Primary operational overview; reconciliation request is newer than some E2E fixtures. |
| Inbox `/inbox` | `GET /stories`, `GET /stories/{id}`, `GET /stories/{id}/evidence`, `GET /stories/{id}/research-runs`, `GET /research-runs/{id}`, `GET /ai-provider-profiles`, `GET /brand-profiles`, `GET /prompt-templates`, `GET /prompt-templates/{id}/versions` | `POST /stories/manual`, `POST /stories/group-pending`, `PATCH /stories/{id}/editorial-state`, `POST /stories/bulk-editorial-state`, `POST /stories/{id}/research-runs`, `POST /stories/{id}/content-packs` | Main editorial intake/research/generation surface. Jobs are durable and asynchronous. |
| Job Queue `/jobs` | `GET /jobs`, `GET /jobs/{id}`, `GET /jobs/summary` | `POST /jobs/{id}/retry`, `POST /jobs/{id}/cancel`, `POST /ingest/run` | Recovery-critical; payload/result/event detail may expose implementation concepts but is useful for diagnosis. |
| Drafts `/drafts` | `GET /content-pack-requests`, `GET /content-packs`, `GET /telegram/drafts` | None on list | Combines current content-pack requests with legacy Telegram drafts. |
| Content-pack workspace `/drafts/[packId]` | `GET /content-packs/{id}`, `GET /platform-variants/{id}/revisions`, `GET /platform-variant-revisions/{id}`, rendered HTML and publication-plan projections | `POST /platform-variants/{id}/revisions`, `POST /platform-variant-revisions/{id}/approve`, `POST /platform-variant-revisions/{id}/reject`, `POST /platform-variants/{id}/regenerate`, export and manual-plan mutations | Immutable child revisions, exact hash approval, and export revision-set binding must remain unchanged. |
| Exact review `/review/[revisionId]` | Exact revision, pack, evidence, Telegram dispatch/destination/control state, persisted manual plan | Exact approve/reject/edit; Telegram publish/schedule; manual publication plan/checklist/complete/cancel | Publishing boundary differs by platform. Telegram is automated only through guarded durable jobs; other platforms are manual-only. |
| Calendar `/calendar` | `GET /calendar?start&end&timezone` | None | Read-only projection of Telegram schedules and manual plans; response is strictly decoded. |
| Library `/library` | `GET /library/originals`, `GET /stories`, `GET /library/evidence`, `GET /library/research-runs`, `GET /library/research-runs/{id}`, `GET /content-packs`, `GET /exports`, `GET /publications` | None | Read-only lookup surface with strict URL/path decoding and cursor pagination. |
| Sources `/sources` | `GET /sources`, `GET /sources/{id}` | `POST /sources/seed`, `POST /ingest/run` | Setup and recovery access; manual ingest enqueues a durable job. |
| Content `/content` | `GET /content-items`, `GET /content-items/{id}` | `POST /content-items/{id}/approve` | Raw ingestion-level queue. Relationship between this approval and story editorial state should remain distinct. |
| Ingestion Runs `/runs` | `GET /ingest/runs` | None | Diagnostic projection of ingestion activity. |
| Media `/media` | `GET /media-assets` | None | Diagnostic media projection; current client shows only the first 12 mapped assets. |
| Diagnostics `/diagnostics` | `GET /diagnostics`, `GET /operations/diagnostics`, `GET /operations/history`, `GET /telegram/reconciliation` | `POST /telegram/publish-jobs/{id}/reconcile` | Combines source diagnostics with newer persisted runtime/queue/reconciliation truth. Recovery-critical. |
| Automation list/detail/history | `GET /telegram/automations`, `GET /telegram/automations/{id}`, `GET /telegram/automations/{id}/dispatches`, options/sources/destinations/profiles/templates/history | Create/update route; activate/pause/resume; destination check; dry run; bounded backfill | Route activation records a new-only boundary. Dry run is review-only. Pause/resume and backfill are operational controls. |
| Content Settings `/settings/content` | Brands, prompt templates/versions, AI provider profiles/capabilities, Telegram destinations | Create/update brand/provider/template; create/activate immutable prompt version; destination configuration/check | Stores credential references and environment variable names, never secret values. Availability is worker-observed and time-bounded. |
| Retention `/settings/retention` | `GET /operations/retention-policy` | `PUT /operations/retention-policy`, `POST /operations/retention-preview`, `POST /operations/retention-runs` | Destructive administrative capability protected by server preview token and exact confirmation. Must remain in Advanced. |

## Endpoint families from `features/automations/telegram-api.ts`

- Telegram sources: `GET/POST /telegram/sources`.
- Destinations: `GET/POST /telegram/destinations` plus destination check.
- Routes: list, detail, create, activate, pause, resume, dry run, bounded backfill, and dispatch history under `/telegram/automations`.
- Drafts/revisions: list, detail, save child, approve, reject, publish, schedule under `/telegram/drafts` and `/telegram/publish-jobs`.
- Brand profiles: list, create, update under `/brand-profiles`.
- Prompt templates and immutable versions: list, create, activate under `/prompt-templates` and `/prompt-template-versions`.
- AI provider profiles: list, create, update under `/ai-provider-profiles`.

## Endpoint families from `features/packages/api.ts`

- Exact package/revision reads and strict decoders.
- Platform-specific immutable edits.
- Exact approval/rejection against expected content hashes.
- Sanitized rendered HTML for blog previews.
- Copy/export jobs and polling.
- Manual publication plan creation, checklist updates, completion, and cancellation.

## Verification gaps

- `Unknown — requires verification`: whether every legacy Telegram draft mutation remains reachable through the newer multi-platform workspace for all historical rows.
- `Unknown — requires verification`: whether raw Content approval is a normal daily operator step or only an ingestion-quality/recovery action for this installation.
- `Unknown — requires verification`: whether Media needs a dedicated route after its read-only diagnostics can be linked contextually from a story/revision.
- `Unknown — requires verification`: whether the older `/diagnostics` response can eventually be fully replaced by `/operations/diagnostics`; both are currently consumed.

