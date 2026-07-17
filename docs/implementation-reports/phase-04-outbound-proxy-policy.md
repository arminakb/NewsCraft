# Phase 4 implementation report: outbound proxy policy

Date: 2026-07-18
Scope: Phase 4 only
Strict final status: **VERIFIED — PHASE 4 COMPLETE**

## Defect reproduction and root cause

The documented defect was reproduced before production changes. Rendering the original Compose file with proxy variables unset or explicitly empty injected `http://xray-proxy:10808` into `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY`. The base topology also attached API, workers, and scheduler to an unconditional external `xray_proxy` network. Whitespace survived Compose interpolation and had no shared application normalization boundary.

The primary root cause was `${VAR:-http://xray-proxy:10808}`: Compose's `:-` substitutes the fallback for both an unset variable and an empty variable. Contributing causes were split interpretation across explicit `proxy=`, `trust_env=True`, settings, library-specific variables, subprocess forwarding, and Telethon's separate proxy contract.

Sanitized pre-fix and post-fix renders covered unset, empty, whitespace, and valid values. Post-fix evidence confirmed blank values in direct mode, application normalization of whitespace to direct mode, preservation of valid values, no base `xray_proxy` network, and explicit attachment only through `docker-compose.proxy.yml`. Temporary render files were removed after validation.

## Affected client inventory

Inspected and migrated paths:

- RSS/Atom ingestion;
- public Telegram HTML fetching;
- Telegram Bot API publishing;
- OpenRouter generation and research;
- DuckDuckGo research search;
- media download;
- discovery/content-pack provider resolution;
- daily bundle HTTP extraction;
- Codex subprocess proxy forwarding;
- Telethon/MTProto source access.

Production `httpx.AsyncClient` construction now exists only in the central factory and the pinned SSRF exception.

## Architecture decisions

`app.core.outbound_proxy` is the single policy boundary.

- Missing, empty, and whitespace-only variables normalize to `None`.
- Upper/lowercase duplicates are accepted only when one is empty or both normalized values are equal. Unequal values fail with `proxy_environment_conflict`.
- HTTP uses `HTTP_PROXY` before `ALL_PROXY`; HTTPS uses `HTTPS_PROXY` before `ALL_PROXY`.
- Reviewed schemes are `http`, `https`, `socks5`, and `socks5h`, validated against locked `httpx` plus `python-socks` initialization.
- Malformed URLs, unsupported schemes, invalid `NO_PROXY`, and ambiguous MTProto settings fail with constant sanitized codes.
- `NO_PROXY` supports exact IPv4/IPv6, CIDR, exact host, leading-dot suffix, optional port, and wildcard matching.
- `build_outbound_http_client` forces `trust_env=False`, owns separate direct/proxy pools, applies per-target bypass, closes every pool, and never retries directly after a configured proxy failure.
- DuckDuckGo receives the resolved proxy explicitly and rejects independent `DDGS_PROXY` interpretation.
- Codex receives only normalized canonical uppercase proxy variables.

Telethon does not inherit HTTP proxy variables. HTTP, SOCKS5, and SOCKS5H settings are translated explicitly. HTTPS is rejected for MTProto with `proxy_mtproto_scheme_unsupported`; different HTTP/HTTPS endpoints are rejected with `proxy_mtproto_ambiguous`. Unsupported configuration prevents source-worker dependency construction before work is claimed.

## Explicit exception

`SafeHttpClient.network_policy` is `direct_pinned_ssrf`. It retains `proxy=None` and `trust_env=False` because it validates public DNS/IP results, pins the connected address while preserving Host/SNI, bounds responses, and revalidates redirects. General proxy routing would move DNS resolution outside those guarantees.

Existing tests reconfirmed loopback/private/link-local rejection, unsafe redirect rejection, DNS rebinding protections, and pinned direct behavior while a general proxy is configured.

## Safe diagnostics

Legacy diagnostics, operations diagnostics/health, worker and scheduler heartbeats, and the frontend expose only `mode`, `scheme`, `bypass_rule_count`, `last_connectivity_status`, and `configuration_error_code`. They never project a raw URL, host, userinfo, username, password, token, credential reference, or environment value.

## Changed files

Deployment/runtime:

- `.env.example`, `README.md`, `docker-compose.yml`, `docker-compose.proxy.yml` (new)
- `backend/pyproject.toml`
- `backend/app/core/outbound_proxy.py` (new), `safe_http.py`, `codex_exec.py`
- `backend/app/ingestion/service.py`, `daily_bundle/__main__.py`, `media/downloader.py`
- `backend/app/generation/providers/profiles.py`, `research/duckduckgo.py`
- `backend/app/api/content_packs.py`, `operations.py`, `schemas.py`
- `backend/app/jobs/worker.py`, `jobs/scheduler.py`
- `backend/app/diagnostics/service.py`, `operations/diagnostics.py`, `operations/health.py`

Frontend:

- `frontend/features/operations/types.ts`, `api.ts`, `diagnostics-dashboard.tsx`
- `frontend/tests/diagnostics-dashboard.test.tsx`
- `frontend/e2e/full-platform-acceptance.spec.ts`

Documentation:

- `docs/operations/outbound-proxy-policy.md` (new)
- `docs/operations/readiness-and-health.md`
- `docs/ingestion-backend.md`
- this report

Tests:

- `backend/tests/core/test_outbound_proxy.py` (new)
- `backend/tests/test_docker_config.py`, `test_daily_bundle_cli.py`, `test_job_worker.py`
- `backend/tests/test_runtime_heartbeat.py`, `test_diagnostics.py`
- `backend/tests/api/test_operations_routes.py`
- `backend/tests/research/test_duckduckgo.py`, `test_codex_adapter.py`
- `backend/tests/stories/test_manual_intake_policy.py`

Pre-existing dirty files, including the Phase 1/2 reports and `backend/app/core/redaction.py`, were preserved and are not Phase 4 deliverables.

## Tests added

The policy suite covers unset, empty, whitespace, uppercase, lowercase, equal/conflicting duplicates, malformed/unsupported URLs, credentialed URLs, IPv4/IPv6, exact hosts, suffixes, CIDR, wildcard bypass, safe diagnostics, inheritance rejection, all reviewed scheme initialization, ownership/cleanup, Telethon translation/errors, and credential-safe representations/exceptions.

The socket integration test uses separate local origin and recording-proxy servers. It proved that a valid HTTP proxy receives a request, `NO_PROXY` reaches the origin without reaching the proxy, and a dead configured proxy raises a safe error without any origin request.

Client-specific tests cover worker ownership, public HTML, Bot API, providers, DuckDuckGo, Codex, media, daily bundle, RSS, Telethon startup, diagnostics/API projection, and the pinned SSRF exception. Proxy credential canaries cover diagnostics and durable heartbeat metadata.

## Commands and exact results

Initial regression proof before production implementation:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app newscraft-backend:local \
  python -m pytest -p no:cacheprovider -q tests/core/test_outbound_proxy.py
```

Result: collection failed with `ModuleNotFoundError: app.core.outbound_proxy`, establishing the red test.

Compose validation used `docker compose --env-file /dev/null config --format json` with all proxy variables removed, explicitly blank, whitespace-only, and valid. The valid proxy-network case added `-f docker-compose.proxy.yml`. `backend/tests/test_docker_config.py`: **22 passed in 1.33s**. The corrected full suite also ran these tests with Docker CLI/socket access.

Image validation:

```bash
docker compose --env-file /dev/null build api
```

Result: image built successfully with `python-socks 2.8.2`; all four reviewed proxy schemes initialized successfully.

Focused command:

```bash
docker run --rm -v "$PWD/backend:/app" -w /app newscraft-backend:local \
  python -m pytest -p no:cacheprovider -q \
  tests/core/test_outbound_proxy.py tests/test_media_downloader.py \
  tests/test_telegram_bot_client.py tests/test_telegram_source_adapters.py \
  tests/stories/test_manual_intake_policy.py tests/test_ingestion_service.py \
  tests/test_daily_bundle_cli.py tests/test_provider_profile_resolver.py \
  tests/test_openrouter_provider.py tests/research/test_duckduckgo.py \
  tests/research/test_codex_adapter.py tests/test_diagnostics.py \
  tests/api/test_operations_routes.py tests/api/test_health_routes.py \
  tests/core/test_redaction.py tests/core/test_logging_uvicorn.py \
  tests/test_job_worker.py
```

Result including two focused heartbeat checks: **327 passed, 1 deprecation warning in 10.62s**. Dedicated policy run: **28 passed in 1.32s**.

The first full-suite container lacked the repository Alembic executable and Docker CLI/socket, producing four harness failures plus one heartbeat expectation failure: **1736 passed, 5 failed**. The expectation was corrected and the suite rerun with the required tools mounted read-only:

```bash
docker run --rm --network host \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  -e ENRICHMENT_PROVIDER=none -e LLM_PROVIDER=none \
  -v "$PWD:/workspace" \
  -v /tmp/newscraft-phase4-alembic:/workspace/backend/.venv/bin/alembic:ro \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins/docker-compose:/usr/lib/docker/cli-plugins/docker-compose:ro \
  -w /workspace/backend newscraft-backend:local \
  python -m pytest -p no:cacheprovider -q
```

Corrected result: **1741 passed, 1 deprecation warning in 382.17s (6m22s)**.

Static checks:

```bash
ruff check .
ruff format --check app/core/outbound_proxy.py tests/core/test_outbound_proxy.py
python -m compileall -q app ../scripts
git diff --check
```

Results: lint passed; new policy/test files were already formatted; compilation passed; diff check passed.

Repository-wide `ruff format --check .` reported **95 files would be reformatted, 257 already formatted**. This pre-existing formatting baseline affects unrelated phases and was not mass-reformatted. It is not a lint or functional failure in the new policy files.

Frontend checks:

```bash
npm test -- tests/diagnostics-dashboard.test.tsx
npm run typecheck
npm run build
npm test
```

Results: diagnostics **3 passed**; type-check passed; production build passed and generated all 17 static pages. The full run had **369 passed and one unrelated story-inbox timeout**; immediate isolated rerun passed **13/13**.

## Deployed validation evidence

Fresh projects were started without the proxy-network override:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    -u http_proxy -u https_proxy -u all_proxy -u no_proxy \
  docker compose --env-file /dev/null -p newscraft-phase4-unset \
  up -d --wait postgres api worker-source-generation worker-publishing scheduler

HTTP_PROXY= HTTPS_PROXY= ALL_PROXY= NO_PROXY= \
http_proxy= https_proxy= all_proxy= no_proxy= \
  docker compose --env-file /dev/null -p newscraft-phase4-empty \
  up -d --wait postgres api worker-source-generation worker-publishing scheduler
```

Both projects reported API, database, workers, and scheduler healthy. Diagnostics returned direct mode, null scheme, zero bypass rules, and no error. Docker inspection showed only each project's default network.

Unset-mode real ingestion:

- job `beafcb03-22f8-4ab8-8109-5bbb8f780950`;
- OpenAI News, Hacker News, Google AI Blog, GitHub Blog;
- **succeeded: checked 4, fetched 4, failed 0, parsed 1,099, media candidates 64**.

An earlier historical-source run reached OpenAI and Hacker News but IRNA and Zoomit were currently unavailable. The subsequent 4/4 run distinguishes source availability from proxy behavior.

Explicit-empty-mode real ingestion:

- job `c13a7c07-e114-49b2-b174-2d721d1901c3`;
- Hacker News;
- **succeeded: checked 1, fetched 1, failed 0, parsed 30**.

No live provider or publication credential was supplied. Fake-provider and client contract suites validated approved credential-free behavior. Runtime logs retained Phase 5 redaction (`HTTP Request: GET [URL]`) and safe constant job statuses.

The local TCP recording-proxy integration verified proxied routing, bypass, and dead-proxy no-fallback. No external proxy was required.

Cleanup:

```bash
docker compose -p newscraft-phase4-unset down -v --remove-orphans
docker compose -p newscraft-phase4-empty down -v --remove-orphans
docker compose --profile test stop postgres-test
docker compose --profile test rm -f postgres-test
```

All isolated Phase 4 containers, volumes, networks, and temporary resources were removed.

## Security and canary results

Credential canaries were exercised in URLs, malformed configuration, transport failures, MTProto startup, diagnostics/API responses, and durable worker heartbeat metadata. Assertions confirmed zero leakage from representations, exceptions, APIs, durable projections, existing job/event/history redaction boundaries, and deployed logs. Proxy secrets are passed only to the explicit transport or Telethon adapter; constant safe codes are persisted/displayed.

## Acceptance checklist

- [x] Unset, empty, and whitespace settings produce direct mode.
- [x] Base Compose has no external proxy requirement or injected fallback.
- [x] General clients use one normalized policy with `trust_env=False`.
- [x] Valid HTTP proxy routing and all reviewed scheme initialization are tested.
- [x] MTProto translation and safe unsupported/ambiguous failures are tested.
- [x] Invalid/conflicting configuration fails before owning network work.
- [x] Dead proxy never causes direct egress; bypass never reaches the proxy.
- [x] Pinned SSRF protections remain green.
- [x] Credential canaries are absent from output and durable projections.
- [x] Real direct ingestion succeeded 4/4 with proxies unset.
- [x] Real direct ingestion succeeded with variables explicitly empty.
- [x] Phase 1, 2, 5, and 9 regressions are green in the full backend suite.
- [x] Isolated resources were cleaned up.

## Remaining risks and unverified items

- **NOT VERIFIED:** live use of an operator-owned authenticated HTTPS/SOCKS5/SOCKS5H proxy. Installed-stack initialization and deterministic routing/translation are tested; the safe local HTTP recording proxy was verified with real sockets.
- **NOT VERIFIED:** live OpenRouter/provider connectivity with a real credential. No credential was provided.
- **NOT VERIFIED:** live Telegram publication. It was prohibited and no token was used.
- Repository-wide Ruff formatting remains a pre-existing baseline failure; Phase 4 lint and new-file formatting checks are green.

These external integrations are not required to establish the directly verified base-default, normalization, no-fallback, SSRF, diagnostic, and real direct-ingestion acceptance criteria. Operators should canary their actual proxy before production enablement.

## Scope confirmation

No Phase 3, Phase 6, or other incomplete phase was implemented. Phase 1, Phase 2, Phase 5, and Phase 9 behavior was preserved and regression-tested. No commit was created.
