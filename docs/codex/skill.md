# NewsCraft Codex Skill

Status: Phase 5 read-only connection guide
Transport: local MCP over STDIO, backed by canonical REST

## Purpose

NewsCraft turns collected source material into operator-reviewed, source-grounded publishing workflows. This guide lets a Codex instance pair with NewsCraft, maintain an authenticated heartbeat, discover the initial read-only tools, and diagnose safe readiness metadata.

The MCP adapter is only a discovery client. It forwards every heartbeat and tool call to the Codex Gateway REST API. REST services remain authoritative for authentication, scopes, rate limits, audit events, redaction, and immediate revocation.

## Prerequisites

- NewsCraft database migrations include `0015_codex_gateway`.
- Backend dependencies from `backend/pyproject.toml` are installed in a local virtual environment.
- `CODEX_GATEWAY_HASH_KEY` is configured as a URL-safe base64 encoding of exactly 32 random bytes.
- `CODEX_GATEWAY_PUBLIC_URL` is the URL Codex can reach.
- Remote gateway URLs use HTTPS. Plain HTTP is accepted only for `localhost`, `127.0.0.1`, or `::1`.
- NewsCraft runs in loopback `local_owner` mode, or profile authentication is configured when available.
- The operator has selected the least set of read scopes needed by this connection.

Never put a pairing code, paired credential, provider API key, Telegram bot token, proxy credential, or encryption key in this file, Git, `.codex/config.toml`, shell history, logs, or issue comments.

## Pair

### 1. Create a one-time pairing session

Create the session from Settings → Codex. In loopback `local_owner` mode, direct REST automation may use the same-origin local endpoint without a second administrator token. Omitting `scopes` grants all currently defined read scopes. Prefer an explicit minimal list:

```bash
export NEWSCRAFT_URL="http://localhost:8000"

curl --fail-with-body \
  -X POST "${NEWSCRAFT_URL}/codex-gateway/pairing-sessions" \
  -H "Origin: http://localhost:3000" \
  -H "Content-Type: application/json" \
  --data '{
    "device_name": "Codex workstation",
    "scopes": [
      "settings:read",
      "providers:read",
      "destinations:read",
      "automations:read",
      "jobs:read"
    ]
  }'
```

The response returns the pairing code once and includes a local exchange command. The session expires after five minutes by default.

### 2. Exchange once

Run the returned local command, or submit the code directly:

```bash
export NEWSCRAFT_PAIRING_CODE="<one-time-pairing-code>"

curl --fail-with-body \
  -X POST "${NEWSCRAFT_URL}/codex-gateway/pair" \
  -H "Content-Type: application/json" \
  --data "{\"pairing_code\":\"${NEWSCRAFT_PAIRING_CODE}\"}"
```

The paired credential is returned once. Store it in an OS credential manager when available. For a local session, expose it only through the process environment:

```bash
export NEWSCRAFT_CODEX_CREDENTIAL="<paired-credential>"
export NEWSCRAFT_BASE_URL="${NEWSCRAFT_URL}"
unset NEWSCRAFT_PAIRING_CODE
```

## Configure Codex MCP

Codex supports local STDIO MCP servers in `~/.codex/config.toml` or trusted project `.codex/config.toml` files. Keep the credential out of TOML and forward its environment variable:

```toml
[mcp_servers.newscraft]
command = "/absolute/path/to/NewsCraft/backend/.venv/bin/python"
args = ["-m", "app.codex_gateway.mcp_server"]
cwd = "/absolute/path/to/NewsCraft/backend"
env = { NEWSCRAFT_BASE_URL = "https://newscraft.example" }
env_vars = ["NEWSCRAFT_CODEX_CREDENTIAL"]
required = true
startup_timeout_sec = 15
tool_timeout_sec = 60
enabled_tools = [
  "newscraft_get_status",
  "newscraft_get_content_settings_summary",
  "newscraft_list_llm_providers",
  "newscraft_get_llm_provider_status",
  "newscraft_list_telegram_destinations",
  "newscraft_get_telegram_destination_status",
  "newscraft_list_automations",
  "newscraft_get_job_status",
]
```

Restart Codex after changing MCP configuration. Run `codex mcp list` or use `/mcp` in the Codex TUI to confirm discovery. Codex CLI, IDE extension, and desktop app share the same Codex MCP configuration.

The machine-readable allowlist is [capabilities.json](./capabilities.json).

## Heartbeat and green status

The MCP process sends an authenticated heartbeat before it finishes startup. It then uses the server-provided interval. The server, not the client, calculates connection status:

- Green: valid connection with a recent authenticated heartbeat.
- Yellow: last authenticated heartbeat is stale.
- Gray: no authenticated heartbeat, expired credential, disconnected process, or revoked connection.
- Red: safe authentication or capability error requiring operator action.

A stored credential alone never produces green status.

To verify green:

1. Start or restart Codex with `NEWSCRAFT_CODEX_CREDENTIAL` in its environment.
2. Confirm `newscraft` appears in `codex mcp list` or `/mcp`.
3. Ask Codex to call `newscraft_get_status`.
4. As an administrator, read `GET /codex-gateway/connections/{connection_id}`.
5. Confirm `status` is `green` and `last_heartbeat_at` is recent.

## Available tools and REST fallback

| MCP tool | Required scope | Canonical REST endpoint |
| --- | --- | --- |
| `newscraft_get_status` | Authenticated connection | `GET /codex-gateway/tools/status` |
| `newscraft_get_content_settings_summary` | `settings:read` | `GET /codex-gateway/tools/content-settings-summary` |
| `newscraft_list_llm_providers` | `providers:read` | `GET /codex-gateway/tools/llm-providers` |
| `newscraft_get_llm_provider_status` | `providers:read` | `GET /codex-gateway/tools/llm-providers/{provider_id}` |
| `newscraft_list_telegram_destinations` | `destinations:read` | `GET /codex-gateway/tools/telegram-destinations` |
| `newscraft_get_telegram_destination_status` | `destinations:read` | `GET /codex-gateway/tools/telegram-destinations/{destination_id}` |
| `newscraft_list_automations` | `automations:read` | `GET /codex-gateway/tools/automations` |
| `newscraft_get_job_status` | `jobs:read` | `GET /codex-gateway/tools/jobs/{job_id}` |

If MCP is unavailable, call the corresponding REST endpoint with:

```bash
curl --fail-with-body \
  "${NEWSCRAFT_BASE_URL}/codex-gateway/tools/llm-providers" \
  -H "Authorization: Bearer ${NEWSCRAFT_CODEX_CREDENTIAL}"
```

These endpoints return safe metadata only. They do not return request authorization, provider keys, Telegram tokens, proxy usernames/passwords, pairing codes, encryption metadata, ciphertext, or master keys.

## Scope meanings

- `settings:read`: read safe Content Settings readiness summaries.
- `settings:write`: manage settings; not used by initial MCP tools.
- `providers:read`: read safe LLM provider metadata and readiness.
- `providers:write`: mutate providers; not used by initial MCP tools.
- `destinations:read`: read safe Telegram destination and route health.
- `destinations:write`: mutate destinations/proxies; not used by initial MCP tools.
- `prompts:read`: read prompt governance state; no initial standalone MCP tool.
- `prompts:write`: mutate prompt versions; not used by initial MCP tools.
- `automations:read`: read safe Automation route state.
- `automations:write`: mutate Automation routes; not used by initial MCP tools.
- `jobs:read`: read safe workflow job lifecycle metadata.
- `jobs:write`: retry/cancel jobs; not used by initial MCP tools.

Write scopes require explicit operator confirmation during pairing or scope changes. No Phase 5 MCP tool performs a write.

## Approval and safety rules

- Initial tools are marked read-only, non-destructive, and idempotent.
- The adapter has no wildcard forwarding, arbitrary URL, SQL, shell, secret lookup, prompt mutation, publication, deletion, or credential-management tool.
- A future write tool must have an explicit schema, matching write scope, idempotency where replay matters, an audit event, and the required human approval classification.
- A destructive action always requires a narrow permission and human approval. A broad `*:write` scope is insufficient.
- Do not ask an operator to paste a secret into chat. Ask them to configure it through the approved write-only UI or process environment.

## Idempotency

All initial MCP tools map to read-only `GET` endpoints and are safe to retry. Heartbeats are idempotent server-time updates. Pairing exchange is single-use. Credential rotation requires an `Idempotency-Key` through the administrator REST endpoint.

## Errors and retries

| Code | Meaning | Recovery |
| --- | --- | --- |
| `authentication_required` | No bearer credential reached the gateway. | Start Codex from a shell that exports `NEWSCRAFT_CODEX_CREDENTIAL`; restart Codex. |
| `credential_invalid` | Credential shape/hash is invalid. | Check environment forwarding; pair again if the one-time value was lost. |
| `credential_expired` | Credential passed its server expiry. | Pair again or ask an administrator to rotate it. |
| `credential_revoked` | Administrator revoked the connection. | Stop retrying; request a new pairing session. |
| `scope_denied` | Tool requires a scope not granted to this connection. | Ask an administrator to add only the required read scope, then retry. |
| `approval_required` | A future action needs human approval. | Stop and obtain approval through the operator workflow. |
| `rate_limited` | Connection exceeded a bounded endpoint rate. | Wait for `retry_after_seconds`, then retry once. |
| `capability_unavailable` | Resource is absent or the canonical service cannot answer safely. | Verify the ID, call status, then retry after the dependency recovers. |

Errors expose stable codes and optional retry timing. They never expose credentials, authorization headers, lookup internals, raw upstream responses, or stack traces.

## Safe usage examples

- “Call `newscraft_get_status` and summarize only unavailable checks.”
- “List LLM providers and identify which enabled connections are not generation-ready.”
- “Get Telegram destination status for `<uuid>` and distinguish proxy, Telegram API, bot, target, and administrator failures.”
- “List automations and report disabled or paused routes.”
- “Get job status for `<uuid>` and explain its safe error code.”

Do not request “all configuration,” raw payload dumps, tokens, credentials, database access, or publication actions.

## Revoke or disconnect

To disconnect temporarily, stop Codex or disable/remove the local MCP configuration. The connection becomes yellow, then gray when heartbeats stop.

To revoke immediately, use Settings → Codex. A loopback local-owner deployment may also call:

```bash
curl --fail-with-body \
  -X DELETE \
  "${NEWSCRAFT_URL}/codex-gateway/connections/<connection-id>" \
  -H "Origin: http://localhost:3000"
```

Revocation takes effect on the next heartbeat or tool call. The MCP process does not silently fall back to another credential.

## Troubleshooting

- MCP server missing: run `codex mcp list`, inspect the absolute Python path and `cwd`, then restart Codex.
- Startup reports `authentication_required`: export `NEWSCRAFT_CODEX_CREDENTIAL` in the environment that launches Codex and keep `env_vars` configured.
- Startup reports `credential_invalid`, `credential_expired`, or `credential_revoked`: stop retries and pair/rotate as appropriate.
- Remote URL rejected: use HTTPS. HTTP is intentionally limited to loopback.
- `scope_denied`: compare the tool table with `GET /codex-gateway/capabilities`; grant only the missing read scope.
- `rate_limited`: honor `retry_after_seconds`; do not loop aggressively.
- Gray connection while MCP appears configured: confirm the process stayed running and inspect recent safe activity through `GET /codex-gateway/activity`.
- Red connection: inspect `failure_code`, resolve the named authentication/scope issue, then verify a successful heartbeat.

## References

- [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [NewsCraft Codex Gateway contract](../content-settings/codex-gateway-contract.md)
