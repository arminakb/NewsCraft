# Secret Storage Threat Model

Status: current security contract
Date: 2026-07-22

## Assets

Protected values include LLM API keys, Telegram bot tokens, proxy usernames/passwords, Codex pairing credentials, and future external-service credentials. Encryption master keys are higher-value deployment secrets and never enter PostgreSQL.

## Trust boundaries

- Browser/API clients may submit a secret only on create or rotate/replace operations.
- API process may encrypt and persist secrets but must not expose them afterward.
- Scoped workers may decrypt only secrets needed for assigned work.
- PostgreSQL, backups, logs, traces, jobs, audit rows, and normal API responses are treated as unable to hold plaintext.
- Deployment secret mount or environment supplies versioned master keys.

## Storage contract

`encrypted_secrets` stores:

- UUID and purpose;
- owner type and owner UUID;
- AES-256-GCM ciphertext and 96-bit random nonce;
- key version;
- creation and rotation timestamps.

Authenticated additional data binds ciphertext to secret ID, purpose, owner, and key version. Moving ciphertext to another row or changing metadata makes decryption fail. Plaintext is never stored in model fields, returned schemas, jobs, logs, errors, or audit metadata.

Safe API metadata is limited to `configured`, `last_rotated_at`, and key-version health when an administrator needs rotation status. Secret inputs use write-only schema types and are never repopulated.

## Key management and rotation

- Active key and version come from deployment secret configuration outside PostgreSQL.
- Key material is exactly 32 random bytes encoded as URL-safe base64.
- Previous versioned keys may remain mounted during a bounded rotation window.
- New writes always use the active version.
- Rotation rewraps rows transactionally: decrypt with recorded version, encrypt with active version, update nonce/ciphertext/version/timestamp.
- Remove old key only after all rows report the active version and backup/rollback window expires.
- Unknown, missing, malformed, or duplicate key versions fail closed.

Database rollback after key rotation requires old key material. Operational backups must coordinate database snapshot and key-version retention; database backup alone is insufficient.

## Threats and controls

| Threat | Control |
|---|---|
| Database or backup disclosure | AES-256-GCM; key outside PostgreSQL |
| Ciphertext substitution | AAD binds row identity and ownership metadata |
| Nonce reuse | fresh 96-bit cryptographic random nonce per encryption |
| API response disclosure | output models expose metadata only; secret input type masks representation |
| Log/job/audit disclosure | recursive redaction plus allowlisted audit metadata |
| Missing/malformed master key | decryption and secret writes fail closed with safe code |
| Unauthorized decryption | principal/scope checks at service boundary; workers receive least privilege |
| Memory/process compromise | deployment isolation and short plaintext lifetime; Python cannot guarantee zeroization |
| Rotation partial failure | per-row transaction, retained prior keys, resumable version scan |
| Oracle/error leakage | one safe public failure code; detailed cause never includes key/ciphertext/plaintext |

## Telegram proxy and SSRF threats

Proxy endpoints are attacker-controlled network destinations even when submitted by an administrator. Before persistence and again before connection:

- accept hostname or IP only, never a URL with credentials/path/query;
- normalize IDNA and reject malformed/ambiguous host representations;
- allow only deployment-approved ports;
- resolve every A/AAAA result and reject loopback, private, link-local, multicast, unspecified, reserved, and metadata ranges;
- pin validated resolved addresses for connection or revalidate after connection to resist DNS rebinding;
- apply explicit outbound allow/deny policy, connection/read timeouts, and response-size bounds;
- never fall back to Direct;
- redact proxy credentials and upstream error bodies.

Cloud metadata destinations, including `169.254.169.254` and IPv6 link-local equivalents, are always blocked.

## Audit requirements

Record create/edit, secret rotation, enable/disable, delete/revoke, pairing/scope changes, failed authorization, failed decryption, and master-key rewrap. Audit events contain actor type/id, required scope, action, resource type/id, outcome, safe reason code, request correlation ID, and redacted metadata. Audit rows never contain request bodies, authorization headers, secret references that reveal deployment layout, ciphertext, nonce, or key bytes.

## Residual risks

An attacker controlling an authorized API or worker process can observe plaintext during legitimate use. Envelope encryption with an external KMS can later reduce key exposure without changing caller contracts because callers depend on the secret-store interface, not AES-GCM details.
