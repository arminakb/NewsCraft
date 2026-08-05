# Codex Gateway Contract

Status: current gateway contract
Date: 2026-07-22

## Principles

REST is canonical. MCP is a discovery adapter over the same services, principal, scope checks, rate limits, approval rules, and audit sink. Codex never receives provider keys, Telegram bot tokens, proxy credentials, master keys, ciphertext, or unrestricted database access.

## Pairing lifecycle

1. Authenticated human administrator creates a pairing session with requested scopes and device label.
2. Server creates a single-use, high-entropy code, stores only its keyed hash, and returns code once.
3. Pairing session expires after five minutes and is rate-limited by administrator, IP, and session.
4. Codex exchanges code once over HTTPS for a scoped credential.
5. Server stores only credential hash, prefix/fingerprint, scopes, expiry, and status.
6. Replay, expired, revoked, or already-used code returns a constant safe error.
7. Credential rotation issues a replacement and atomically revokes predecessor.

Default grants are read-only. Write scopes require explicit operator selection. Destructive operations require both matching narrow scope and per-action human approval; possession of `*:write` alone is insufficient.

## Credential and heartbeat contract

Bearer credentials are random, non-guessable, short-lived, revocable, hash-only at rest, and compared in constant time. Requests carry stable connection ID and correlation ID. Rate limits apply per connection and endpoint class.

Authenticated heartbeat updates server time only after credential, connection, expiry, revocation, and scope checks. Status:

- green: valid heartbeat within configured fresh window;
- yellow: valid but stale heartbeat;
- gray: never connected, expired, disconnected, or revoked;
- red: safe authentication or capability error requiring operator action.

A stored credential without recent authenticated heartbeat is never green.

## REST surface

- `POST /codex-gateway/pairing-sessions`
- `GET /codex-gateway/pairing-sessions/{id}`
- `DELETE /codex-gateway/pairing-sessions/{id}`
- `POST /codex-gateway/pair`
- `POST /codex-gateway/heartbeat`
- `GET /codex-gateway/connections`
- `GET /codex-gateway/connections/{id}`
- `PATCH /codex-gateway/connections/{id}/scopes`
- `POST /codex-gateway/connections/{id}/rotate`
- `DELETE /codex-gateway/connections/{id}`
- `GET /codex-gateway/capabilities`
- `GET /codex-gateway/activity`

Mutation requests support idempotency keys where replay could create credentials or duplicate work. Responses expose only safe connection metadata, scopes, expiry, heartbeat time, revocation state, and redacted activity.

### Operator-read authorization boundary

Only two local-operator reads are intentionally unauthenticated:

- `GET /codex-gateway/connections` returns `CodexConnectionSummaryOut`: connection ID, sanitized device name, scopes, status, connection state, sanitized failure code, expiry, and last heartbeat.
- `GET /codex-gateway/activity` returns `GatewayActivitySummaryOut`: event ID, allowlisted action, outcome, and creation time. Audit metadata, actor details, reason text, request IDs, headers, logs, and provider payloads are excluded.

All other gateway boundaries keep their existing authorization:

| Route | State effect | Authorization |
|---|---|---|
| `POST /pairing-sessions` | creates pairing session | application principal with `settings:write` |
| `GET /pairing-sessions/{id}` | reads one-time pairing state | application principal with `settings:read` |
| `DELETE /pairing-sessions/{id}` | cancels pairing session | application principal with `settings:write` |
| `POST /pair` | consumes pairing code and creates connection | one-time pairing-code verification inside gateway service |
| `POST /heartbeat` | updates authenticated heartbeat | paired gateway bearer credential inside gateway service |
| `GET /connections` | safe summary read | public local-operator read |
| `GET /connections/{id}` | detailed connection read | application principal with `settings:read` |
| `PATCH /connections/{id}/scopes` | changes scopes | application principal with `settings:write` |
| `POST /connections/{id}/rotate` | rotates credential | application principal with `settings:write` plus idempotency key |
| `DELETE /connections/{id}` | revokes connection | application principal with `settings:write` |
| `GET /capabilities` | reads effective capabilities | application principal with `settings:read` or paired gateway bearer credential |
| `GET /activity` | safe activity summary read | public local-operator read |
| `GET /codex-gateway/tools/*` | reads scoped resources and records tool audit | paired gateway bearer credential plus route-specific read scope |

Official Compose publishes API and frontend ports on `127.0.0.1`, although Uvicorn binds `0.0.0.0` inside its container and alternate deployments can publish the API more broadly. The two public summaries therefore remain safe allowlists under LAN exposure; loopback binding is defense in depth, not their secrecy boundary.

## MCP allowlist

Initial read-only tools:

- `newscraft_get_status` requires authenticated connection.
- `newscraft_get_content_settings_summary` requires `settings:read`.
- `newscraft_list_llm_providers` and `newscraft_get_llm_provider_status` require `providers:read`.
- `newscraft_list_telegram_destinations` and `newscraft_get_telegram_destination_status` require `destinations:read`.
- `newscraft_list_automations` requires `automations:read`.
- `newscraft_get_job_status` requires `jobs:read`.

No wildcard tool forwarding, arbitrary HTTP, SQL, shell, secret lookup, prompt mutation, publication, deletion, or credential-management tool is allowed initially. Later write tools require explicit schema allowlisting, matching write scope, idempotency, audit event, and human approval classification.

## Error contract

Errors return stable codes: `authentication_required`, `credential_invalid`, `credential_expired`, `credential_revoked`, `scope_denied`, `approval_required`, `rate_limited`, and `capability_unavailable`. They never distinguish hash lookup internals or expose authorization headers, credentials, secret identifiers, raw upstream responses, or stack traces.

## Audit contract

Pairing creation/cancellation/exchange, heartbeat rejection, credential rotation/revocation, scope changes, rate-limit decisions, tool calls, approval decisions, and failed authorization are audited with redacted metadata. Read activity may be sampled only when policy permits; every write and high-risk attempt is retained.
