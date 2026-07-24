# NewsCraft Content Settings, Integrations, and Codex Gateway Plan

## Purpose

Redesign `/settings/content` into a coherent management surface for:

1. Telegram destinations
2. Generic LLM provider connections
3. Codex connectivity and permissions
4. Editorial profiles
5. Prompt governance

This roadmap also resolves the correctness, security, lifecycle, and UX problems documented in `docs/frontend-audit/content-settings-audit.md`.

Implementation must be split into bounded Codex sessions. Each session stops for operator review. Do not commit or push unless explicitly requested.

---

# Product decisions

## Telegram destinations

Content Settings becomes the single source of truth for Telegram destination management.

Operators must be able to:

- Create, edit, enable, disable, recheck, and delete destinations
- Rotate the Telegram bot token
- See whether the bot and destination are healthy
- Reuse the destination later from Automation

Primary fields:

- Display name
- Channel/group identifier
- Telegram bot token

The bot must be an administrator of the target channel or group.

Destination creation duplicated inside Automation must be removed after the new manager is validated. Automation should select an existing destination or link to Content Settings.

`allow_auto_publish` must not remain a hidden destination-level permission. Automatic publishing policy belongs to the Automation route and requires its own explicit warning and confirmation.

## Telegram network routes and proxies

Telegram connectivity must support an optional reusable network route that can be assigned from the Telegram Destinations section.

Initial supported connection modes:

- Direct connection
- HTTP/HTTPS CONNECT proxy
- SOCKS5 proxy, with optional username/password

The publishing and health-check path uses the HTTPS Telegram Bot API. Therefore the supported proxy types are HTTP/HTTPS CONNECT and SOCKS5.

MTProto proxy support is out of scope and must not be implemented. NewsCraft only needs bot-to-channel/group connectivity through the Bot API, so adding a Telegram client, TDLib, or a separate MTProto transport would introduce unnecessary complexity.

Proxy configuration should be represented by reusable proxy profiles rather than duplicating credentials in each destination. The Telegram destination form may create or select a profile.

Proxy profile fields:

- Display name
- Proxy type: `http_connect` or `socks5`
- Host
- Port
- Optional username
- Optional password
- Enabled state
- Last health check
- Safe failure code

Security rules:

- Proxy usernames/passwords use the encrypted secret store
- Never return or log secret values
- Validate host, port, scheme, and DNS resolution
- Protect against SSRF and access to private/internal metadata networks
- Use explicit egress policy and connection timeouts
- Do not silently fall back to a direct connection when a proxy is selected
- A destination health check and every publish request must use the same assigned route

Health must be reported separately for:

- Proxy reachability
- Telegram API reachability through the proxy
- Bot authentication
- Target resolution
- Bot administrator permission

A proxy may be shared by multiple destinations. Deletion must be blocked while it is assigned, unless destinations are reassigned or switched to Direct.

## Generic LLM providers

Do not create a separate frontend section for OpenRouter or every provider brand.

Use one unified LLM connection model and one reusable form.

Primary fields:

- Connection name
- API key
- Base URL
- Model name

The default protocol is OpenAI-compatible HTTP. Add a provider-specific adapter only when the generic protocol is insufficient.

Advanced fields may include:

- Timeout
- Token limits
- Standard/deep research budgets
- Optional pricing metadata
- Attribution headers
- Capability diagnostics

Remove OpenRouter-specific frontend sections, labels, seed assumptions, and dead-end configuration flows after migration.

Fake providers remain test/development infrastructure and are hidden from normal production settings.

Codex is not a generic LLM provider. It receives a dedicated gateway and UI card.

## Secret storage

The UI may accept API keys and Telegram bot tokens, but raw secrets must never be stored as plaintext in PostgreSQL or returned from an API.

Use a server-side encrypted secret store:

- Encrypt before persistence
- Keep the master key outside PostgreSQL
- Store ciphertext, nonce/metadata, key version, and rotation timestamps
- Return only safe metadata such as `configured` and `last_rotated_at`
- Never repopulate secret inputs
- Redact secrets from logs, errors, jobs, traces, and audit records
- Fail closed when the encryption key is unavailable

The storage adapter should be replaceable by an external secret manager later without changing frontend contracts.

## Codex integration

Create a dedicated authenticated Codex Gateway.

REST is the canonical contract. An MCP adapter may expose the same scoped capabilities to Codex for tool discovery.

Use:

- One-time pairing
- Scoped credentials
- Expiration and rotation
- Revocation
- Authenticated heartbeats
- Audit logging
- Rate limiting
- Human approval for high-risk actions

A green status dot means a valid connection sent a recent authenticated heartbeat. It must not mean only that a token exists.

## Startup ownership

Operator-managed database configuration is authoritative.

Startup seeding must:

- Create only missing defaults
- Never replace an operator-selected prompt version
- Never overwrite provider model, enabled state, settings, or credentials
- Never silently reactivate deprecated records
- Be idempotent and repair-only

System-managed defaults and operator-managed records must be distinguishable.

---

# Target Content Settings structure

## Editorial Profiles

Primary:

- Name
- Output language
- Tone
- Default profile

Advanced:

- Editorial rules
- Attribution rules
- Default hashtags
- Platform preferences

## LLM Providers

Unified connection list showing:

- Name
- Base URL
- Model
- Enabled state
- Generation readiness
- Research readiness
- Last health check
- Edit
- Test connection
- Rotate API key
- Enable/disable
- Delete when safe

## Codex Connection

Dedicated card showing:

- Status dot
- Connected agent/device
- Last heartbeat
- Granted scopes
- Pair
- Revoke
- Rotate credential
- Recent safe activity
- Link to `skill.md`

## Telegram Destinations

Unified list showing:

- Name
- Normalized target
- Enabled state
- Assigned network route: Direct or proxy profile
- Proxy route health
- Telegram health
- Verified bot identity
- Administrator status
- Last check
- Edit
- Rotate token
- Change/test proxy
- Recheck
- Enable/disable
- Delete when safe

The create/edit dialog includes a **Connection route** control. Operators may choose Direct, select an existing proxy profile, or create a proxy profile inline. Proxy management remains a reusable resource even though it is surfaced inside the Telegram Destinations area.

## Prompt Governance

One consistent manager for:

- Canonical Story
- Telegram Automation Rewrite
- Telegram Pack
- Instagram Pack
- X Pack
- Blog Pack

Primary view: purpose, active version, status, and impact.

Advanced view: raw templates, variables, immutable history, checksums, diff, and activation controls.

---

# Phase 0 — Architecture lock and migration design

## Objective

Finalize contracts before changing application behavior.

## Deliverables

Create:

- `docs/content-settings/target-architecture.md`
- `docs/content-settings/secret-storage-threat-model.md`
- `docs/content-settings/codex-gateway-contract.md`
- `docs/content-settings/migration-map.md`

Define:

- Generic LLM provider schema
- Encrypted secret schema and key management
- Telegram target normalization
- Telegram proxy-profile schema and destination assignment
- HTTP CONNECT and SOCKS5 transport behavior
- Explicit exclusion of MTProto and TDLib from this product scope
- Proxy SSRF and egress-control threat model
- Dependency-aware deletion rules
- Codex scopes and pairing
- MCP tool allowlist
- Prompt ownership and seed behavior
- Migration and rollback strategy

## Required design details

### Telegram target normalization

Accept supported input forms such as:

- `@channel`
- Numeric chat ID
- Supported Telegram URL

Normalize before uniqueness checks.

### Telegram network routes

Define a reusable `telegram_proxy_profiles` contract and a nullable `proxy_profile_id` assignment on each destination.

The first production implementation supports:

- Direct
- HTTP CONNECT
- SOCKS5

MTProto and TDLib are explicitly excluded. The only supported Telegram transport is the HTTPS Bot API, optionally routed through HTTP CONNECT or SOCKS5.

Define:

- DNS and IP validation
- Private-network/metadata-address blocking
- Allowed ports or egress policy
- Connection and read timeouts
- TLS verification behavior
- Credential encryption
- No-direct-fallback policy
- Health-check stages
- Assignment and deletion dependencies
- Migration behavior for destinations with no proxy

### Safe deletion

A provider or destination referenced by an Automation, queued job, generation run, or publication must not be silently hard-deleted.

Either:

- Block deletion and show dependencies
- Require reassignment
- Disable while retaining historical references

Historical provenance must remain valid.

### Provider compatibility

Define the minimum OpenAI-compatible contract required by generation, research, and health checks.

Generation readiness and research readiness must be separate truthful capabilities.

## Gate

No application code changes. Stop for architecture approval.

---

# Phase 1 — Authentication, authorization, and encrypted secrets

## Objective

Fix the highest-risk foundation before accepting credentials in the UI.

## Work

Protect sensitive settings mutations with application-level authorization.

Distinguish:

- Human administrator session
- Codex service connection
- Internal workers/services

Initial scopes:

- `settings:read`
- `settings:write`
- `providers:read`
- `providers:write`
- `destinations:read`
- `destinations:write`
- `prompts:read`
- `prompts:write`
- `automations:read`
- `automations:write`
- `jobs:read`
- `jobs:write`

Implement encrypted secret persistence and write-only API schemas.

Add audit events for:

- Create/edit
- Secret rotation
- Enable/disable
- Delete/revoke
- Pairing and scope changes
- Failed authorization
- Failed decryption

## Validation

- Encryption and decryption
- Master-key rotation
- Missing-key fail-closed behavior
- Response/log/job redaction
- Authorization on every mutation
- Audit-log redaction

## Gate

Security foundation only. No major page redesign.

---

# Phase 2 — Generic LLM provider backend

## Objective

Replace provider-brand-specific configuration with one generic connection contract.

## Proposed record

- `id`
- `name`
- `protocol`
- `base_url`
- `default_model`
- `enabled`
- `secret_id`
- `settings`
- `health_status`
- `generation_capability`
- `research_capability`
- `failure_code`
- `last_checked_at`
- timestamps

Primary protocol:

- `openai_compatible`

Development-only:

- `fake`

Codex must not be stored here.

## API

- `GET /llm-providers`
- `POST /llm-providers`
- `GET /llm-providers/{id}`
- `PATCH /llm-providers/{id}`
- `DELETE /llm-providers/{id}`
- `POST /llm-providers/{id}/rotate-secret`
- `POST /llm-providers/{id}/test`
- `POST /llm-providers/{id}/enable`
- `POST /llm-providers/{id}/disable`
- `GET /llm-providers/{id}/dependencies`

API key is accepted only during create and rotate/replace.

## Research readiness

Primary creation remains simple: name, API key, Base URL, and Model Name.

Provide safe defaults. Put optional research configuration under Advanced:

- Timeout
- Input/output token limits
- Standard/deep research budgets
- Optional pricing metadata
- Attribution headers

Fix the current defect where a provider created from the UI can generate but cannot research.

## Migration

- Convert existing OpenRouter rows into generic OpenAI-compatible providers
- Preserve IDs and provenance where practical
- Migrate credential references only through an explicit secure import
- Stop startup from rewriting provider values
- Keep temporary compatibility adapters
- Remove OpenRouter-specific UI/API naming after caller migration

## Validation

- CRUD and rotation
- Enable/disable recovery
- Test connection
- Generation and research capability
- Dependency-protected deletion
- Restart persistence
- Worker resolution
- Existing generation/research regressions

## Gate

Backend and migration only.

---

# Phase 3 — Telegram destination and proxy lifecycle backend

## Objective

Provide complete destination management with optional HTTP CONNECT or SOCKS5 routing through the Telegram HTTPS Bot API.

## Store

- Display name
- Canonical target
- Target type
- Encrypted bot-token secret
- Enabled state
- Health state
- Verified bot ID/username
- Verified chat ID/title/type
- Administrator status
- Last checked time
- Safe failure code
- Assigned nullable proxy profile
- timestamps

Proxy profiles store safe metadata plus encrypted optional credentials:

- Name
- Type
- Host
- Port
- Enabled state
- Encrypted username/password when configured
- Reachability status
- Last checked time
- Safe failure code

Do not store auto-publish permission at destination level.

## API

- `GET /telegram/destinations`
- `POST /telegram/destinations`
- `GET /telegram/destinations/{id}`
- `PATCH /telegram/destinations/{id}`
- `DELETE /telegram/destinations/{id}`
- `POST /telegram/destinations/{id}/rotate-token`
- `POST /telegram/destinations/{id}/recheck`
- `POST /telegram/destinations/{id}/enable`
- `POST /telegram/destinations/{id}/disable`
- `GET /telegram/destinations/{id}/dependencies`
- `GET /telegram/destination-checks/{job_id}`
- `GET /telegram/proxies`
- `POST /telegram/proxies`
- `GET /telegram/proxies/{id}`
- `PATCH /telegram/proxies/{id}`
- `DELETE /telegram/proxies/{id}`
- `POST /telegram/proxies/{id}/rotate-credentials`
- `POST /telegram/proxies/{id}/recheck`
- `POST /telegram/proxies/{id}/enable`
- `POST /telegram/proxies/{id}/disable`
- `GET /telegram/proxies/{id}/dependencies`

## Verification

On destination create, target edit, token rotation, proxy reassignment, or recheck:

1. Validate without logging token or proxy credentials
2. Resolve and validate the selected proxy endpoint
3. Check proxy reachability
4. Reach the Telegram Bot API through the exact selected route
5. Call Telegram `getMe`
6. Resolve target using `getChat`
7. Verify admin rights using `getChatMember`
8. Persist separate proxy, Telegram, bot, target, and admin health states
9. Return an async check job
10. Let the frontend poll until completion

The publish worker must use the same route selected for the destination. Never silently bypass the proxy after a proxy failure.

Use safe failure codes rather than raw Telegram or proxy responses.

## Delete behavior

- Delete immediately when unused
- Otherwise block and list dependent Automation routes/jobs
- Offer disable or reassignment
- Never cascade-delete publications or history

## Automation integration

After validation:

- Remove destination creation from Automation builder
- Automation selects existing enabled/healthy destinations
- Add a link to Content Settings
- Keep auto-publish policy and confirmation at route level

## Validation

- Normalization and duplicate prevention
- Handle/URL/numeric IDs
- Bot and admin verification
- Token rotation
- Async polling
- Recheck and enable/disable
- Dependency-safe deletion
- HTTP CONNECT routing
- SOCKS5 routing with and without authentication
- DNS/IP validation and SSRF protection
- No direct fallback
- Proxy health versus Telegram health separation
- Shared proxy dependency-safe deletion
- Redacted proxy failures and credentials

## Gate

Backend lifecycle complete before frontend redesign.

---

# Phase 4 — Codex Gateway REST and pairing

## Objective

Create a secure entry gate for Codex.

## Pairing flow

1. Admin selects **Pair Codex**
2. Server creates a short-lived one-time pairing session
3. UI displays a pairing code or local command
4. Codex exchanges the code for a scoped credential
5. Server stores only a secure hash/representation
6. Codex begins authenticated heartbeats
7. UI reflects server-calculated connection state

## API

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

## Status

- Green: recent authenticated heartbeat
- Yellow: stale heartbeat
- Gray: disconnected, expired, or revoked
- Red: authentication/capability error

Expose safe metadata only:

- Agent/device name
- Connection ID
- Created time
- Last heartbeat
- Expiration
- Scopes
- Safe activity summary
- Revocation state

Use polling, SSE, or another bounded server-truth mechanism.

## Permissions

Default to read-only.

Write scopes require explicit operator selection.

Destructive actions require a narrowly scoped permission plus human approval or a separate high-risk scope.

Codex must never receive:

- Raw provider keys
- Telegram bot tokens
- Encryption material
- Unrestricted database access

## Initial capabilities

Read-only first:

- System status
- Safe Content Settings summary
- Provider metadata/status
- Destination metadata/status
- Feed/Collection/Automation state where authorized
- Job status

## Validation

- Expiration and replay prevention
- Credential hashing
- Revocation and rotation
- Scope enforcement
- Heartbeat transitions
- Rate limiting
- Audit events
- Secret redaction
- Destructive-action rejection

## Gate

REST gateway and pairing validated before MCP.

---

# Phase 5 — MCP adapter and Codex skill

## Objective

Make NewsCraft easy for Codex to discover without duplicating business logic.

## MCP adapter

Expose the same services and authorization rules through MCP.

Requirements:

- REST/service layer remains canonical
- No duplicate authorization
- Same scopes and audit events
- Explicit bounded tool schemas
- No secret-returning tools
- Read-only first
- Clear scope/approval errors

Initial tools:

- `newscraft_get_status`
- `newscraft_get_content_settings_summary`
- `newscraft_list_llm_providers`
- `newscraft_get_llm_provider_status`
- `newscraft_list_telegram_destinations`
- `newscraft_get_telegram_destination_status`
- `newscraft_list_automations`
- `newscraft_get_job_status`

Select the transport supported by the installed Codex environment. REST remains the fallback.

## Skill

Create:

`docs/codex/skill.md`

It must explain:

- NewsCraft purpose
- Prerequisites
- Pairing steps
- REST/MCP configuration
- Heartbeat behavior
- Available tools/endpoints
- Scope meanings
- Approval rules
- Secret restrictions
- Idempotency
- Error/retry behavior
- Safe examples
- Revoke/disconnect
- Troubleshooting
- How to verify the green status

Optionally add a machine-readable capability manifest.

## Validation

- A real Codex instance can pair using only the skill
- Tool discovery works
- Read-only calls succeed
- Unauthorized tools are rejected
- Revocation is immediate
- Green status requires heartbeat

## Gate

Operator validates the connection before write tools.

---

# Phase 6 — Content Settings frontend redesign

## Objective

Replace the mixed settings page with a coherent management interface.

Recommended order:

1. Editorial Profiles
2. LLM Providers
3. Codex Connection
4. Telegram Destinations
5. Prompt Governance

Default views show readiness summaries. Raw infrastructure goes under Advanced.

## LLM provider UI

One reusable list and create/edit dialog.

Primary form:

- Connection name
- API key
- Base URL
- Model name

Actions:

- Test
- Edit
- Rotate key
- Enable/disable
- Delete
- View dependencies

Advanced:

- Timeout
- Research budgets
- Token limits
- Pricing
- Attribution headers
- Diagnostics

Secret fields are write-only, never repopulated, and cleared after mutation.

Remove OpenRouter-specific UI.

## Telegram destination UI

One list and create/edit dialog.

Primary form:

- Destination name
- Channel/group identifier
- Bot token
- Connection route: Direct or proxy profile

The proxy picker supports selecting an existing proxy and creating one inline. Proxy create/edit fields are type, host, port, and optional username/password. Supported types are HTTP CONNECT and SOCKS5 only.

Actions:

- Edit
- Rotate token
- Recheck
- Enable/disable
- Delete
- View dependencies
- Change/test proxy
- Manage proxy profiles

Show verified bot/target identity, admin state, selected route, proxy reachability, Telegram reachability, last check, and safe error reason.

Poll async checks automatically.

## Codex card

Show:

- Status dot
- Connected/disconnected
- Agent/device
- Last seen
- Scopes
- Pair
- Revoke
- Rotate
- Activity
- Open `skill.md`

## Shared UX behavior

All forms must support:

- Field-level validation
- Structured server errors
- Cancel without validation
- Dirty-state tracking
- Unsaved-change warning
- Reset/revert
- Pending lock
- Consistent success/error feedback
- Retry
- Keyboard accessibility
- Focus restoration

## Gate

Desktop review first. Mobile remains deferred.

---

# Phase 7 — Prompt governance correctness and consolidation

## Objective

Fix prompt persistence and unify prompt management.

## Backend

- Startup creates missing defaults only
- Operator activation survives restart
- Activation is transactional
- Enforce prompt size limits
- Validate variables consistently
- Store activation identity, reason, and timestamp
- Require prompt-write authorization
- Preserve immutable generation provenance

## Automation route prompt policy

Introduce:

- `follow_active`
- `pinned`

Rules:

- Existing routes remain pinned during migration
- New-route default is explicitly chosen
- UI clearly shows mode
- Switching mode requires confirmation
- Jobs persist exact resolved version/checksum

## Frontend

One component for every prompt purpose.

Show:

- Friendly purpose name
- Pipeline explanation
- Active version
- Required variables
- Version history
- Diff
- Validation
- Impact warning
- Activation result

Raw templates remain under Advanced.

## Validation

- Restart persistence
- Every purpose can initialize/manage versions
- Structured errors
- Diff and confirmation
- Pinned/follow-active behavior
- Existing revisions remain immutable
- Complete cache invalidation

---

# Phase 8 — Editorial profiles and remaining audit defects

## Objective

Complete profile behavior and resolve remaining state issues.

## Work

- Expose output language
- Clarify tone
- Expose editorial and attribution rules
- Expose hashtags and platform preferences
- Implement real default-profile selection or remove `is_default`
- Explain queued-job versus existing-revision behavior
- Add dirty tracking, cancel, reset, and revert
- Fix stale option caches
- Use consistent structured feedback
- Rename misleading technical labels
- Keep diagnostics/raw config under Advanced

## Validation

- Backend consumes the default profile
- Future-work impact is documented
- Existing revisions remain unchanged
- All selectors refresh
- Unsaved-change protection works

---

# Phase 9 — Integration cleanup

## Objective

Remove duplication after replacement workflows pass.

Remove or migrate:

- OpenRouter-specific frontend
- Old provider endpoint callers
- Startup provider overwrites
- Automation destination creation
- Old prompt managers
- Destination-level auto-publish control
- Dead secret-reference-only UI
- Obsolete Content Settings tests and labels

Preserve history and provenance.

Regression-check:

- Research
- Generation
- Telegram Automation
- Scheduler
- Drafts/Review regeneration
- Telegram publishing
- Provider capability checks
- Destination checks
- Codex pairing/status
- Prompt activation after restart

---

# Phase 10 — Final acceptance and operations

## Operations

Create runbooks for:

- Backup/restore of encrypted metadata
- Master-key rotation
- Lost-key behavior
- Provider key rotation
- Telegram token rotation
- Codex pairing/revocation
- MCP troubleshooting
- Audit review
- Health/readiness
- Migration rollback

Add metrics for:

- Provider checks
- Destination checks
- Codex heartbeats
- Authorization failures
- Prompt activation
- Secret decryption failures
- Rate limiting

## Final acceptance matrix

### Telegram

- Create
- Normalize
- Verify
- Edit
- Rotate
- Recheck
- Enable/disable
- Delete safely
- Select in Automation
- Publish through existing safety gates
- Create/edit/delete reusable proxy profiles
- Route destination health checks through HTTP CONNECT or SOCKS5
- Route publishing through the same selected proxy
- Distinguish proxy failure from Telegram, bot, target, and admin failure
- Never silently fall back to Direct
- Protect against SSRF and internal-network access
- Do not introduce MTProto or TDLib into the bot publishing path

### LLM providers

- Create generic connection
- Test
- Generate
- Research
- Edit
- Rotate
- Enable/disable
- Delete safely
- Survive restart
- Preserve provenance

### Codex

- Pair
- Authenticate
- Discover tools
- Read permitted data
- Heartbeat
- Show green status
- Reject unauthorized writes
- Revoke
- Rotate
- Audit

### Prompts

- Create immutable version
- Validate
- Diff
- Activate
- Survive restart
- Resolve pinned/follow-active routes
- Preserve provenance

### Security

- No raw secrets in responses, logs, jobs, traces, or browser state
- Authorization on sensitive mutations
- Immediate revocation
- Missing encryption key fails closed
- Destructive actions require explicit permission/approval

### UX

- Clear hierarchy
- No duplicated configuration
- Consistent forms
- Dirty-state protection
- Keyboard accessibility
- Accurate readiness states
- Raw configuration under Advanced

---

# Recommended Codex sessions

1. Session 6B — Architecture and security contract
2. Session 6C — Authentication and encrypted secrets
3. Session 6D — Generic LLM provider backend
4. Session 6E — Telegram destination and HTTP/SOCKS5 proxy backend
5. Session 6F — Codex Gateway REST and pairing
6. Session 6G — MCP adapter and `skill.md`
7. Session 6H — Content Settings frontend redesign
8. Session 6I — Prompt governance
9. Session 6J — Editorial profiles and remaining audit fixes
10. Session 6K — Integration cleanup
11. Session 6L — Final acceptance and operations

Each session must:

- Stay within scope
- Preserve existing workflow guarantees
- Add focused tests
- Run relevant regression suites
- Stop for operator review
- Avoid commit/push unless explicitly requested

Do not combine security, schema migration, Codex gateway, MCP, and the complete frontend redesign in one session.
