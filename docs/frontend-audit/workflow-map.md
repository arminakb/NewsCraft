# Frontend workflow map

## What the operator sees first

The root route is Today. It currently presents, in order:

1. Global automation controls.
2. Telegram publication outcomes.
3. Queue summary cards.
4. Needs-attention jobs.
5. Running jobs.
6. Recent successes.

When paused, the strongest visible action is **Resume automations**. The screen does not tell a first-time operator that new editorial work begins in Inbox or offer an Add story action.

## Actual primary editorial workflow

Repository runbooks and frontend mutations support this sequence:

```text
Collect / add material
  → group into stories
  → inspect evidence and completeness
  → shortlist or reject
  → research if needed
  → generate a content pack
  → inspect platform preview and evidence
  → edit into an immutable child revision
  → approve the exact revision and content hash
  → copy/export or create a publication handoff
  → publish Telegram through its guarded boundary, or publish other platforms manually
  → record/inspect the result in Calendar and Library
```

### Route-by-route

1. **Collect** — `/inbox`
   - Add text or URL through Add story.
   - Group ungrouped captured content with Group pending content.
   - Durable jobs are visible in `/jobs`.
2. **Inspect and select** — `/inbox`
   - Expand a story, inspect evidence and completeness.
   - Shortlist or reject one or many stories.
3. **Research** — `/inbox`
   - Choose standard/deep research and an available provider.
   - Bind a successful research run to generation.
4. **Generate** — `/inbox`
   - Choose brand, generation provider, and prompt versions for the compatibility Telegram flow.
   - Multi-platform generation is supported by the API and rendered by the content-pack workspace.
5. **Review/edit** — `/drafts/[packId]`
   - Switch platform variant.
   - Compare approximation preview with exact payload, evidence, validation, media, and revision history.
   - Save creates a new immutable pending-review revision.
6. **Approve/reject** — `/drafts/[packId]` and `/review/[revisionId]`
   - Approval is bound to exact revision ID and content hash.
   - Any later edit requires a new review.
7. **Publish/export** — `/review/[revisionId]`
   - Telegram uses a guarded durable publishing boundary.
   - Instagram, X, and blog use manual publication plans and checklists.
   - Package export requires the intended current revision set to be approved.
8. **Track/lookup** — `/calendar`, `/library`, `/jobs`
   - Calendar projects Telegram schedules and manual plans.
   - Library provides read-only persisted records.
   - Jobs provides durable execution and recovery truth.

## Ingestion and source operations workflow

```text
Configure/seed sources
  → run ingest
  → inspect ingestion job/run
  → inspect raw content and media
  → approve captured content when appropriate
  → group pending content into editorial stories
```

- `/sources`: source health, seed, manual ingestion, source detail.
- `/runs`: ingestion-run status.
- `/content`: raw captured-item filters, detail, and approval.
- `/media`: extracted and downloaded media candidates.
- `/diagnostics`: source and runtime failures.

This workflow is necessary for setup, troubleshooting, and recovery, but it is not the daily editorial workflow once collection is operating.

## Telegram automation workflow

```text
Create source and destination configuration
  → check destination health
  → create route with conservative defaults
  → activate new-only boundary
  → dry run / review generated revision
  → pause, resume, or bounded backfill when needed
  → reconcile ambiguous publication outcomes
```

Routes: `/automations`, `/automations/new`, `/automations/[routeId]`, `/automations/[routeId]/history`, `/review/[revisionId]`, and `/diagnostics`.

This workflow exposes recovery-critical capabilities. It can move under an Advanced/Automation section, but it must not be removed.

## Configuration workflow

- `/settings/content`: brands, immutable prompt versions, provider profiles/capability observations, destinations, and credential references.
- `/settings/retention`: bounded cleanup policy, preview, and confirmed retention job.

Configuration is occasional and technically dense. It should not compete visually with Today, Inbox, and Drafts.

## Duplicated or overlapping concepts

| Concept | Current surfaces | Interpretation |
| --- | --- | --- |
| Work needing attention | Today, Job Queue, Diagnostics, sidebar summary | Different projections of the same operational truth; keep links but establish one primary triage entry. |
| Captured material | Content, Inbox, Library Originals | Raw ingestion record, grouped editorial workflow, and read-only archive respectively; terminology does not explain the distinction. |
| Draft/revision review | Drafts, Review & Publish, content-pack workspace, exact review | Same lifecycle split across list, workspace, filtered list link, and exact handoff. |
| Publication outcomes | Today, Review, Calendar, Library Publications, Diagnostics reconciliation | Useful at different lifecycle stages, but hierarchy is unclear. |
| Source failures | Today jobs, Sources, Diagnostics | Recovery links are valid; duplicate status presentation should be contextual. |
| Prompt/provider/destination configuration | Content Settings and parts of Automation builder | Necessary dependencies, currently exposed close to normal workflow language. |

## Only-UI access points that must be preserved

- Global pause and dry-run controls.
- Manual story intake and grouping.
- Story shortlist/reject, research, and generation.
- Exact revision edit, approve, reject, regenerate, media assignment, and dirty-navigation protection.
- Copy/export and manual publication checklist.
- Telegram route activation, pause/resume, dry run, bounded backfill, publish, and reconciliation.
- Job retry/cancel and detailed payload/result/event inspection.
- Source seeding and manual ingestion.
- Raw content approval.
- Prompt/provider/brand/destination configuration.
- Retention preview and confirmed execution.

None should be deleted during navigation simplification.

