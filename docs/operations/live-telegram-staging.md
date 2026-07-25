# Controlled live Telegram staging qualification

Production publishing stays disabled until this procedure has signed evidence
for dry-run, success, replay, and one separately authorized ambiguity drill.
Never use a public channel or a general-purpose bot.

## One-time staging boundary

1. Create a private channel with two named human owners. Add a dedicated bot
   with only the permission needed to post; do not grant administration beyond
   that permission.
2. Store its token only as the publishing-owned file secret
   `TELEGRAM_STAGING_TOKEN`. Record token owner, rotation/revocation procedure,
   allowed test hours, evidence retention, and message cleanup policy in the
   authorization ticket.
3. Create a NewsCraft destination that references `TELEGRAM_STAGING_TOKEN`, has
   `allow_auto_publish=false`, is enabled, and passes its `getChat` health check.
4. Configure the GitHub environment `live-telegram-staging` with required
   reviewers (two-person approval), deployment-branch restrictions, and only:
   `TELEGRAM_STAGING_DATABASE_URL`, `TELEGRAM_STAGING_TOKEN`, and
   `TELEGRAM_STAGING_REPORT_SIGNING_KEY`.
5. Keep the staging database and channel separate from production. The workflow
   refuses a fresh publishing-worker heartbeat, so stop the staging publishing
   worker before approval. Source/generation workers are not needed.

## Revision preparation

Use an operator-authored or Phase 13-qualified Telegram revision. For every
scenario create a new revision containing one unique marker matching
`NC-STAGING-[A-Z0-9-]{8,80}`. Use non-sensitive, owned test media only. Exercise:

- text plus HTML/buttons;
- one photo;
- one document;
- a media group;
- a scheduled revision within Telegram limits.

Record the exact destination UUID, revision UUID, content SHA-256, channel target
reference, numeric `getChat` channel ID, title, expected operation count, and
expected returned message-ID count. Approve the exact hash only after review.

## Protected workflow input

Run `live-telegram-staging.yml` manually. Its first nine fields are explicit;
the tenth, `evidence_json`, has this shape:

```json
{
  "observer_one": "editor-a",
  "observer_two": "operator-b",
  "expected_operation_count": 1,
  "expected_remote_message_count": 1,
  "remote_message_ids": "",
  "observation_ticket": "",
  "confirm_exactly_one_remote_marker": false
}
```

The environment approval is the send authorization. A token is never an input,
argument, artifact, database value, or report field.

## Ordered qualification

1. Enable global dry-run. Run `scenario=dry-run` with a dedicated revision. The
   signed report must show zero remote sends and no `Publication`.
2. Disable global dry-run and global pause. Confirm the route is enabled, the
   destination is healthy, and the publishing worker remains stopped. Run a
   text-only `scenario=success`. The harness calls `getChat`, sends through the
   real publisher once, then replays the exact publish call. The report must show
   no increased send count on replay and one exact local publication.
3. Two observers inspect the private channel and confirm exactly one message has
   the marker and that its IDs/content/media/buttons match. Rerun with
   `scenario=verify`, the observed comma-separated positive IDs, an observation
   ticket, and `confirm_exactly_one_remote_marker=true`. This step never sends.
4. Repeat success then verify for each media/rendering case. Use a new marker and
   revision every time.
5. Under a separate written authorization, run `scenario=ambiguity`. The harness
   injects process death only after Telegram returned success, persists one
   ambiguous receipt, and proves immediate replay makes no second client call.
6. Observers inspect the channel. Reconcile through the existing NewsCraft UI/API
   with the exact positive IDs only after confirming the message. Repeat the
   no-send `scenario=verify`; it must match a confirmed local publication.

Do not use message-text search as automatic evidence. The unique marker supports
human observation; the reconciliation decision is fenced by operation key,
attempt generation, exact IDs, and existing 409 conflict behavior.

## Fault matrix before the live window

Run the credential-free renderer/client/service/reconciliation and PostgreSQL
crash suites from the Phase 14 report. They cover text/photo/document/media
group/buttons, credential/4xx/429/5xx/connect/timeout classifications, crash
before send, crash after send, crash after receipt, stale lease, replay,
concurrency, approval/hash/evidence drift, and reconciliation conflicts. Never
point deterministic tests at Telegram or supply a live token.

## Monitoring and rollback

Operations diagnostics surface unhealthy destinations, failed/rate-limited jobs,
`dispatching` or ambiguous receipts, reconciliation-required publish jobs,
unconfirmed publications, and publishing-worker health. Treat a dispatching
receipt older than five minutes or any ambiguity as a page; do not resend.

Rollback order:

1. Enable global dry-run and global pause.
2. Disable the route and destination, then stop the publishing worker.
3. Preserve workflow, attempt, receipt, publication, signed report, and remote
   observation evidence before changing deployment state.
4. Revoke/rotate the staging token.
5. Do not retry or delete an ambiguous message until reconciliation is complete.
6. Message deletion is a separate authorized Telegram action after evidence
   capture. Record its remote IDs and result; never automate cleanup from the
   qualification harness.
