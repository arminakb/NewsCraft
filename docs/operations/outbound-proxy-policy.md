# Outbound proxy policy

NewsCraft uses direct outbound networking unless an operator explicitly configures a reviewed proxy. The base `docker-compose.yml` does not inject a proxy hostname and does not require an external proxy network.

## Normalization and precedence

Missing, empty, and whitespace-only `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, and lowercase legacy equivalents normalize to no value. Uppercase names are canonical. An equal non-empty uppercase/lowercase duplicate is accepted; unequal non-empty duplicates fail with `proxy_environment_conflict` before the owning capability starts network work.

For HTTP targets, `HTTP_PROXY` takes precedence over `ALL_PROXY`. For HTTPS targets, `HTTPS_PROXY` takes precedence over `ALL_PROXY`. A proxy that is explicitly configured but unreachable produces a transport failure and is never bypassed by a direct retry.

General HTTP clients support the schemes validated against the installed `httpx[socks]` stack:

- `http`
- `https`
- `socks5`
- `socks5h`

Proxy URLs must contain a valid hostname and port, must not contain a query or fragment, and may contain credentials. Credentials and proxy hostnames are retained only inside the transport configuration; diagnostics, exceptions, API responses, logs, jobs, events, and history must never expose the raw URL or userinfo.

## `NO_PROXY`

`NO_PROXY` and `no_proxy` use the same duplicate/conflict rules. Comma-separated entries support:

- exact IPv4 or IPv6 addresses;
- IPv4 or IPv6 CIDR networks;
- exact hostnames such as `postgres` or `internal.example`;
- leading-dot domain suffixes such as `.internal.example`, matching the root and subdomains;
- optional ports on host/IP rules;
- `*` for an explicit bypass of every target.

An exact hostname does not match its subdomains. Bypassed requests use the explicit direct pool; they do not re-enable environment proxy discovery.

## Client ownership

All production `httpx` construction goes through `app.core.outbound_proxy.build_outbound_http_client`. It sets `trust_env=False`, owns direct and proxy connection pools, applies per-target bypass rules, and closes every pool with its owning client. This covers RSS/Atom ingestion, public Telegram HTML, OpenRouter generation and research, Telegram Bot API, media download, discovery, and daily bundle operations.

DuckDuckGo search receives one explicit proxy derived from the same policy and rejects the library-specific `DDGS_PROXY` environment variable. Codex subprocesses receive only normalized canonical uppercase proxy variables; raw lowercase or conflicting values are not forwarded.

## Telethon/MTProto

MTProto is not HTTP and does not inherit the general HTTP proxy automatically. NewsCraft translates `http`, `socks5`, and `socks5h` endpoints to Telethon explicitly. `socks5h` enables proxy-side DNS; `socks5` uses local DNS semantics.

`ALL_PROXY` is the unambiguous MTProto choice. If it is absent, one scheme-specific proxy or equal HTTP/HTTPS endpoints may be used. Different `HTTP_PROXY` and `HTTPS_PROXY` values are ambiguous for MTProto and fail with `proxy_mtproto_ambiguous`. An `https` proxy URL is valid for general HTTP but unsupported by the installed Telethon proxy transport; MTProto fails with `proxy_mtproto_scheme_unsupported` instead of silently connecting directly.

## SSRF-safe direct exception

Manual intake and research article materialization use `SafeHttpClient`, identified as `direct_pinned_ssrf`. This path deliberately keeps `proxy=None` and `trust_env=False` because it resolves and validates public IPs, pins the connection address while preserving the original Host/SNI, and revalidates every redirect. Routing it through a general proxy would move DNS resolution outside those guarantees.

This exception continues to reject loopback/private/link-local targets, unsafe redirects, and tested DNS-rebinding cases even when the general proxy policy is configured. Deployments that require every byte of egress to traverse a proxy must treat manual intake/research pinned fetching as unavailable until an equivalent proxy-aware pinning transport is proven.

## Compose deployment

For local development with a host-reachable proxy, configure the proxy variables normally and use the base stack. Only the source/generation and publishing workers receive them. Containers reach a host-loopback proxy through `host.docker.internal`.

If the proxy hostname exists only on a separate external Docker network, add the explicit override:

```bash
XRAY_PROXY_NETWORK=contenthub_default \
docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d
```

The override attaches only the two outbound workers to `XRAY_PROXY_NETWORK`; the API and scheduler remain detached and receive no proxy values. It does not inject a proxy URL. Operators must still configure the intended URL explicitly.

Production reads authenticated proxy URLs from worker-specific files mounted at
`/run/secrets/HTTP_PROXY`, `/run/secrets/HTTPS_PROXY`, and `/run/secrets/ALL_PROXY`.
Source and publishing use different host files and Docker secret objects. Create restrictive
empty files for direct mode; never reuse a shared proxy secret file across workers.

## Safe diagnostics and failures

`/diagnostics`, `/operations/diagnostics`, and `/operations/health` expose only:

- mode: `direct` or `proxy`;
- proxy scheme, or `mixed` when configured HTTP/HTTPS routes use different reviewed schemes;
- bypass-rule count;
- last connectivity status: `not_checked`, `ok`, or `failed`;
- a sanitized configuration error code.

They never expose raw environment values, proxy URLs, hostnames, usernames, passwords, tokens, or credential references. A configuration error prevents the affected client/capability from performing network work. Connectivity errors use a constant safe proxy error and preserve the no-fallback rule.
