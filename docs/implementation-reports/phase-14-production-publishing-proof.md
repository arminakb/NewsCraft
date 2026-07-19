# Phase 14 — Controlled live Telegram publishing proof

## Outcome

The repository-side live qualification boundary is implemented. NewsCraft now
has a protected, manual-only staging workflow and a signed harness for exact
channel/revision/hash/marker preflight, dry-run proof, one-send success with
replay suppression, deliberate post-send ambiguity, and later two-observer
remote/local verification.

No Telegram message was sent from this workstation. The final external proof
remains pending because no approved private staging channel/token, written send
authorization, two-person observation window, or permission to create an
ambiguous remote outcome was supplied. Production publishing must remain
disabled until the workflow artifacts pass the runbook.

## Implemented controls

- `live-telegram-staging.yml` is `workflow_dispatch` only, uses the protected
  `live-telegram-staging` environment, serializes all runs, grants read-only
  repository permission, and accepts the exact scenario, destination, revision,
  hash, unique marker, authorized target/chat identity, ticket, and evidence.
- The workflow mounts a dedicated `TELEGRAM_STAGING_TOKEN` and report-signing
  key as mode-0600 files. Neither is accepted as an input or artifact; a final
  count-only scan fails if either value appears in the report.
- Credential expressions are scoped only to the preparation step, unset before
  the harness runs, and removed by an `always()` cleanup step; they are not
  inherited through job-wide environment state.
- The harness requires `NEWSCRAFT_LIVE_TELEGRAM_STAGING=authorized`, two distinct
  observers, a written authorization ticket, a current migration head, and no
  fresh publishing-worker heartbeat. This prevents a background worker racing
  the controlled direct invocation.
- Destination preflight requires the exact UUID/target, enabled+healthy state,
  `allow_auto_publish=false`, and the dedicated token reference. A real `getChat`
  must match the authorized numeric channel ID, title, and `channel` type.
- Revision preflight requires the exact current content hash, approved
  non-dry-run Telegram schema, route provenance (including edited descendants),
  and exactly one safe `NC-STAGING-*` marker.
- Dry-run requires global dry-run and proves zero client sends and zero local
  publication. Live success requires dry-run/pause off, verifies expected
  operation/message counts, then replays the publisher and requires no increase
  in send count plus one exact local publication.
- The ambiguity scenario injects only at the existing
  `telegram.after_send_before_receipt` boundary after Telegram returned success.
  It requires one ambiguous receipt, no publication, one total client call, and
  a replay result of `telegram_publish_reconciliation_required`.
- The separate verify scenario never sends. It requires two-observer
  confirmation of exactly one remote marker and exact positive unique remote
  IDs, then matches them to one confirmed local publication/hash.
- Verification also requires the observed ID sequence to equal the durable
  publication IDs and validates the expected public-channel permalink. Private
  numeric channel IDs correctly require no derived permalink.
- Signed reports retain authorization/observation references, safe chat
  identity, operation hashes/status, remote IDs, local publication/permalink,
  scenario outcome, canonical report SHA-256, and HMAC-SHA256 signature.
- Operations diagnostics now explicitly surface dispatching and ambiguous
  receipts in addition to destination health, failed/rate-limited workflow jobs,
  reconciliation-required publish jobs, unconfirmed publications, and worker
  health.
- The runbook defines least-privilege channel/token setup, two-person GitHub
  environment configuration, text/photo/document/media-group/buttons/scheduled
  cases, separate ambiguity authorization, reconciliation, monitoring, evidence
  retention, cleanup, token revocation, and rollback order.

The harness never deletes a Telegram message or automatically reconciles an
ambiguous outcome. Both remain separate, explicitly authorized operator actions.

## Verification

Lightweight code-focused verification was used because the workstation is known
to be hardware-unstable:

```text
ruff check (staging harness, diagnostics, and focused tests): passed
pytest test_telegram_renderer.py test_telegram_bot_client.py
       test_telegram_publish_service.py test_telegram_reconciliation_api.py
       test_telegram_staging_validation.py operations/test_diagnostics.py:
       125 passed in 1.61s (one existing Starlette/httpx deprecation warning)
pytest integration/test_publish_crash_recovery.py: 7 skipped in 0.03s because
       no explicitly configured `*_test` PostgreSQL database was present
workflow YAML parse: passed
```

The completion audit's cross-phase backend policy suite passed **164 tests in
2.53 seconds**, including mismatched remote/local IDs, duplicate or non-positive
IDs, permalink identity, and workflow secret-scope policy.

The PostgreSQL crash-recovery suite, container restart matrix, real channel
success, media variants, scheduled send, manual remote verification, and live
ambiguity/reconciliation drill were not run locally. They require the protected
staging environment; the host constraint also makes local container stress
inappropriate.

## External acceptance still required

1. Configure the dedicated private channel, low-privilege token, staging
   database, environment secrets, two required reviewers, owner/rotation/hours,
   and cleanup policy exactly as the runbook states.
2. Run the credential-free PostgreSQL crash/fault matrix in a healthy CI runner.
3. Produce signed dry-run evidence with zero sends.
4. Produce success+verify evidence for text, photo, document, media group,
   HTML/buttons, and scheduled scenarios; confirm one marker per scenario and no
   replay duplicates.
5. Under separate written authorization, produce ambiguity evidence, reconcile
   exact observed IDs, then produce the no-send verification report.
6. Scan logs/screenshots/artifacts for the token canary, retain signed evidence,
   and exercise dry-run/pause/disable/revoke rollback.

## Rollback

Enable global dry-run and pause, disable route and destination, stop the
publishing worker, preserve durable receipts/publication/evidence, and revoke or
rotate the staging token. Never retry or delete an ambiguous message before
reconciliation; deletion requires its own authorization after evidence capture.
