# Automation Workflow Builder Phase 5

**Status:** Implemented on 2026-08-01

Phase 5 adds a lazy Test Studio, persisted run inspection, bounded Runs filters and pagination, immutable version history, exact revision and Operations Job links, and workflow-aware Operations history taxonomy.

## Supported Test Studio contract

- `POST /automations/{automation_id}/runs` starts an exact persisted `version_number` with a required idempotency key.
- Test Studio exposes only `Validate only` and a full `dry_run=true` execution. Partial runs, isolated node retry, and output comparison remain hidden because no safe durable server contract exists for them.
- A manual entry accepts either `story_id` or `story_revision_id`, never both. `story_id` resolves the latest immutable Story revision server-side. A Telegram entry accepts only an optional positive `source_message_id` and rejects Story overrides.
- Browser refresh resumes inspection from the deep-linked `runId`. Polling is cancelled in the background and stops when the persisted run becomes terminal.
- Run projections redact credential, authorization, prompt-body, provider-response, header, message, and stack-trace keys before returning data. The client applies a second display allowlist.

## Draft integration seam

The repository has exact revision review at `/review/{revision_id}`, but it has no separate generalized Drafts creation entry point that can cleanly host “Create with workflow” without redesigning the editorial surface.

The next Draft/Feed consumer must reuse the existing run-start contract:

1. choose an `automation_id` and exact persisted `version_number`;
2. send one safe `story_id` or `story_revision_id` plus `dry_run=false` only when the workflow lifecycle and server policy permit it;
3. retain the returned `AutomationRun.id` and follow its persisted node-run projection;
4. open the resulting `platform_variant_revision_id` through `/review/{revision_id}`;
5. use the related `workflow_job_id` for Operations detail.

It must not submit graph JSON, raw prompt text, credentials, provider responses, roles/scopes, or a client-selected job type. A separate Draft-specific execution API is intentionally not added.

## Operational ownership

Runs provide product-level workflow/version/node/artifact truth. Operations Center remains the owner of job attempts and raw operational detail. History can now filter workflow, version, run, and node-run subjects and links run events back to `/automations/runs` or exact revisions.

## Verification

- API and PostgreSQL tests cover bounded filters, stable cursor pagination, safe input validation, projection redaction, restart-safe dry runs, and the no-publication boundary.
- Frontend tests cover input modes, resume, persisted node results, safe errors, deep links, filters, version diff, and restore-as-new-draft.
- The Playwright journey covers mobile/reduced-motion operation, validate, dry run, refresh resume, activate/pause, Runs inspection, exact revision link, actual Operations Job navigation, light/dark rendering, focus, overflow, and Axe serious/critical checks.
