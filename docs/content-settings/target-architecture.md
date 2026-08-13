# Content Settings Architecture

Status: current architecture
Date: 2026-07-22

## Boundaries and ownership

Content Settings owns operator-managed configuration for Editorial Profiles, LLM Providers, Codex Connection, Telegram Destinations, reusable Telegram Proxy Profiles, and Prompt Governance. PostgreSQL is authoritative for operator-managed state. Runtime environment variables may supply bootstrap credentials, encryption keys, and deployment policy, but must not overwrite operator changes.

REST is the canonical interface. Workers and the later MCP adapter call the same application services and authorization policy; they do not duplicate business rules.

## Identity and authorization

Every protected request resolves one application principal at the centralized `ApplicationPrincipalResolver` boundary:

- `local_owner`: server-created principal for the loopback-only single-owner deployment; full initial Settings access.
- future profile principal: authenticated profile session with server-assigned scopes.
- `codex_service`: paired service credential; only explicitly granted scopes.
- `internal_service`: worker or scheduler identity; only service-specific scopes.

Initial scopes:

- `settings:read`, `settings:write`
- `providers:read`, `providers:write`
- `destinations:read`, `destinations:write`
- `prompts:read`, `prompts:write`
- `automations:read`, `automations:write`
- `jobs:read`, `jobs:write`

Authorization is deny-by-default. The current local owner receives the complete initial scope set from server policy. Future profile principals may receive narrower grants. Codex and internal services receive only configured or persisted grants. Client-provided role and scope headers are ignored; bootstrap bearer identity is derived by matching a configured server credential.

Browser Settings has no separate Operator Secret or session. In `local_owner` mode, every mutation requires an explicit allowed `Origin`; missing, malformed, and cross-origin values fail closed. Local-owner startup accepts only loopback CORS origins, and official Compose publishes API and frontend ports on `127.0.0.1`. Forwarded client headers never establish locality or authority. Bearer-authenticated service requests retain their server-assigned identity and remain outside the browser origin check.

`APPLICATION_AUTH_MODE=profile` is the future integration seam. It currently rejects browser requests until profile-session resolution is implemented at the same boundary; individual Settings routes must not add temporary authentication mechanisms. Migration `0026_remove_operator_sessions` removes the obsolete session table without rewriting migration history.

## Generic LLM provider contract

`llm_providers` replaces brand-specific configuration:

| Field | Contract |
|---|---|
| `id` | UUID primary key |
| `name` | unique operator label |
| `protocol` | `openai_compatible`; `fake` only in test/development |
| `base_url` | normalized HTTPS origin plus optional path |
| `default_model` | non-empty provider model identifier |
| `enabled` | operator-owned state |
| `secret_id` | nullable FK to encrypted secret; required outside `fake` |
| `settings` | validated timeout, token, budget, pricing, and attribution metadata |
| health fields | status, safe failure code, last checked time |
| capability fields | generation and research readiness reported separately |
| ownership | `system_managed` or `operator_managed` |

Minimum OpenAI-compatible generation contract: authenticated HTTPS, `POST /chat/completions`, system/user messages, requested model, bounded timeout, JSON response parsing, usage when supplied, and stable mapping of HTTP/provider failures to safe codes. Research additionally requires configured budgets, sufficient context/output limits, attribution headers when required, and the same request/response contract. Generation readiness never implies research readiness.

Codex is excluded from `llm_providers` and uses the Codex Gateway.

## Telegram destination and target contract

Accepted target input:

- public username: `@channel_name`
- numeric Bot API chat ID, including `-100...`
- `https://t.me/<username>` and `https://telegram.me/<username>` with no query, fragment, credentials, or extra path

Normalization happens before lookup and uniqueness checks:

- trim surrounding whitespace;
- lowercase usernames and store as `@<username>`;
- validate username syntax `[A-Za-z][A-Za-z0-9_]{4,31}`;
- parse numeric IDs as canonical base-10 signed integers with no leading `+` or redundant zeroes;
- reduce supported URLs to canonical username form;
- reject invite links, message links, arbitrary hosts, malformed percent encoding, and unsupported schemes.

`destinations` evolves to store display name, canonical target, target type, encrypted bot-token `secret_id`, enabled state, verified bot/target identity, administrator state, separated health stages, safe failure code, assigned nullable proxy profile, timestamps, and ownership. Uniqueness is `(platform, canonical_target)`.

## Telegram proxy profiles and transport

`telegram_proxy_profiles` is reusable:

| Field | Contract |
|---|---|
| `id`, `name` | UUID and unique operator label |
| `proxy_type` | `http_connect` or `socks5` |
| `host`, `port` | normalized endpoint, validated against egress policy |
| `username_secret_id`, `password_secret_id` | nullable encrypted secrets |
| `enabled` | operator-owned state |
| health fields | reachability, safe failure code, last checked time |

Destinations reference profiles using nullable `proxy_profile_id`; null means Direct. Every destination check and publish operation resolves one immutable route snapshot at execution. Selected proxy failure is terminal for that attempt: no direct fallback.

HTTP proxy mode uses an HTTP/1.1 CONNECT tunnel to Telegram HTTPS endpoints, then normal TLS verification inside the tunnel. SOCKS5 supports no-auth and username/password auth, performs remote DNS through the proxy when policy allows, and still applies pre-connection host/IP policy. Connection, TLS handshake, and read timeouts are separately bounded. Certificate verification is always enabled in production.

MTProto proxies, Telegram client sessions, TDLib, and new Telethon transport use are explicitly out of scope. Publishing uses Telegram HTTPS Bot API only.

## Health model

Destination checks persist separate stages:

1. proxy endpoint policy and reachability;
2. Telegram API reachability through selected route;
3. bot authentication with `getMe`;
4. target resolution with `getChat`;
5. administrator permission with `getChatMember`.

Only safe enums cross API boundaries. Raw proxy, DNS, TLS, or Telegram responses remain redacted diagnostics.

## Dependency-aware deletion

Hard deletion is allowed only when no historical or active dependency exists. Providers and destinations are blocked when referenced by Automation routes, queued/running jobs, generation or research runs, publish jobs, or publications. Proxy deletion is blocked while any destination references it.

APIs return dependency counts and safe identifiers. Operator choices are reassignment, disablement, or deletion after dependencies are removed. Historical runs/publications retain original foreign keys and provenance. No cascade deletes history.

## Prompt ownership and startup seeds

Prompt templates and versions are database-authoritative. Versions are immutable. Activation is an audited operator action. Startup seeding:

- creates a missing system default and initial version;
- repairs only structurally missing system-managed defaults;
- never changes active operator version, content, enabled state, provider model, credentials, or operator-managed record;
- never reactivates deprecated rows;
- is idempotent.

Each seeded record carries ownership and seed identity/version so repair logic can distinguish system defaults from operator state.

## Module seams

- `app.security`: principals, scope policy, encrypted secret store, audit events.
- `app.settings`: orchestration and dependency checks shared by REST/MCP.
- `app.generation.providers`: protocol adapters; no persistence or authorization policy.
- `app.publishing.telegram`: Bot API transport selected from destination route snapshot.
- `app.codex_gateway`: pairing, credentials, heartbeat, and scoped capability facade.

Transport and UI never read ciphertext, master keys, raw tokens, or proxy credentials.
