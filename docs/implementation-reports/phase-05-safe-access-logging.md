# Phase 5 Implementation Report — Safe Uvicorn Access Logging

Date: 2026-07-17  
Plan source: `docs/archive/solutions.md`, Phase 5  
Implementation base revision: `f2953eeed31c4e82756344b6edaac858fda526c2`  
Verified Uvicorn version: `0.51.0`

## Status

**PHASE 5 GENUINELY COMPLETE.**

Every Phase 5 acceptance criterion was directly verified on the final tree. The real installed Uvicorn formatter, a live socket-backed ASGI server, 10,000 generated records, credential/query canaries, the complete 1,670-test backend suite, and an isolated Compose deployment all passed.

No Phase 9 behavior or any other production-hardening phase was implemented.

## Scope

Changed for Phase 5 only:

- `backend/app/core/logging.py`
- `backend/app/core/redaction.py`
- `backend/tests/core/test_redaction.py`
- `backend/tests/core/test_logging_uvicorn.py` (new)
- `docs/implementation-reports/phase-05-safe-access-logging.md` (this report)

Existing untracked audit, plan, task, and validation artifacts were preserved. No schema, API, health/readiness, proxy, credential-topology, worker, scheduler, frontend, or deployment policy was changed.

## Pre-fix verification and reproduction

The checkout's `backend/.venv/bin` directory was empty, and system Python did not have Uvicorn installed. The unchanged backend image was therefore built before any source edit, and the reproduction ran inside that image.

```bash
docker compose build api
```

The unchanged image resolved Uvicorn `0.51.0`. A real `logging.LogRecord` with Uvicorn's five access arguments was passed through the old `_RedactingFilter`, then through the real `uvicorn.logging.AccessFormatter`:

```bash
docker run --rm newscraft-backend:local python -c "import importlib.metadata, logging; from uvicorn.logging import AccessFormatter; from app.core.logging import _RedactingFilter; print('uvicorn=' + importlib.metadata.version('uvicorn'), flush=True); args=('127.0.0.1:43100','GET','/health?token=phase5-repro','1.1',200); record=logging.LogRecord('uvicorn.access', logging.INFO, '<phase5-repro>', 1, '%s - \"%s %s HTTP/%s\" %d', args, None); print('args_before_len=' + str(len(record.args)), flush=True); _RedactingFilter().filter(record); print('args_after_len=' + str(len(record.args)), flush=True); formatter=AccessFormatter(fmt='%(client_addr)s - \"%(request_line)s\" %(status_code)s', use_colors=False); print(formatter.format(record))"
```

Direct result:

```text
uvicorn=0.51.0
args_before_len=5
args_after_len=0
ValueError: not enough values to unpack (expected 5, got 0)
```

This verified the documented failure against both the current repository code and the actually installed Uvicorn version before implementation.

The pre-existing generic redaction/security baseline remained green (`21 passed`), demonstrating the exact coverage gap: no existing test used Uvicorn's structured formatter.

The new Phase 5 tests were then added before production changes. Their first run failed during collection because `redact_request_target`, `RedactingFormatter`, and `RedactingAccessFormatter` did not yet exist. That was the expected pre-implementation red state.

## Implementation

### Clone-based generic formatting

`RedactingFormatter` now creates a new `LogRecord` from a shallow copy of the original record dictionary. Only that clone is sanitized and passed to the configured formatter.

The generic path preserves the prior security boundary for:

- positional and mapping interpolation;
- non-string messages and hostile objects without invoking unsafe `__str__` methods;
- bounded recursive extra-field redaction;
- exception trace text and cached `exc_text`;
- stack information;
- URLs, recognized credentials, Telegram Bot tokens, headers, cookies, secret references, sessions, and proxy userinfo.

Existing formatter behavior is retained through a sanitized delegate. Multiple handlers can format the same original record independently; neither handler sees mutations made for another handler.

Malformed message interpolation or delegate failure returns a constant fail-closed sentinel. It never falls back to rendering the raw message or arguments.

### Dedicated Uvicorn access formatter

`RedactingAccessFormatter` subclasses the real `uvicorn.logging.AccessFormatter` and validates the access contract before delegation:

1. `record.args` must be a tuple;
2. the tuple must contain exactly client, method, request target, HTTP version, and status;
3. the first four values must be strings;
4. status must be an actual integer, not a string or boolean;
5. strings and the request target are sanitized on a cloned record;
6. the status integer is preserved unchanged;
7. Uvicorn performs its normal request-line, status-phrase, and color-aware formatting.

Invalid access structure returns the fail-closed sentinel instead of raising or exposing the original values.

### Sensitive request-target redaction

`redact_request_target()` handles relative ASGI request targets without discarding useful route data. It preserves path, fragments, non-sensitive query diagnostics, and safe numeric metrics while redacting sensitive query families including:

- token and authorization variants;
- bare or segmented `key` names;
- API/private keys;
- secret/password names;
- cookie/session variants;
- credential/reference variants.

The same query-value rule is also used for absolute HTTP(S) URLs. Existing safe numeric metrics such as `max_output_tokens=10` remain visible.

### Fail-closed behavior

Both formatters contain all formatting-time `BaseException` failures and emit only:

```text
[LOG_FORMAT_FAILED] logger=<sanitized-bounded-name> level=<sanitized-bounded-level>
```

The sentinel does not include message text, arguments, extras, exception text, stack text, paths, or formatter exception text.

### Explicit, idempotent configuration

`configure_logging()` no longer installs a mutating redaction filter. It:

- removes any legacy NewsCraft mutating filter left by a reload;
- wraps configured application/Uvicorn error handlers with `RedactingFormatter`;
- wraps Uvicorn access handlers with `RedactingAccessFormatter`;
- preserves existing formatter instances as sanitized delegates;
- installs formatter protection for handlers added to future loggers;
- promotes compatible existing non-root loggers so late handlers are protected;
- remains idempotent when called repeatedly.

## Tests added or changed

`backend/tests/core/test_logging_uvicorn.py` directly covers:

- real Uvicorn `AccessFormatter` inheritance and five-tuple behavior;
- original-record immutability;
- exact client/method/path/protocol/status preservation;
- sensitive relative query redaction;
- empty, short, long, list, non-integer, and boolean access structures failing closed;
- positional and mapping interpolation;
- exceptions, cached exception text, stack text, and extras;
- non-string/hostile values;
- malformed format strings and exploding delegate formatters;
- API key, Telegram Bot token, authorization, cookie, secret reference/value, proxy userinfo, Telegram session, and query canaries;
- two handlers receiving independent clones and one line each;
- idempotent explicit Uvicorn/application formatter configuration;
- 10,000 generated valid and malformed records with no exception or canary leak;
- a real Uvicorn server serving ASGI 200, 404, and 500 responses over a bound localhost socket, with three requests producing exactly three safe access lines and a redacted error traceback.

`backend/tests/core/test_redaction.py` adds the dedicated relative request-target contract, including safe path/query retention, bare-key redaction, session/credential redaction, and safe numeric metric retention.

## Exact validation commands and results

### Focused Phase 5 command

The source-plan command was executed inside the built backend image with a temporary `.venv/bin/python` shim because the checkout's `.venv/bin` is empty:

```bash
docker run --rm --tmpfs /repo/backend/.venv/bin \
  -v /home/armin/Documents/NewsCraft:/repo -w /repo/backend \
  newscraft-backend:local sh -c \
  "ln -s /usr/local/bin/python /repo/backend/.venv/bin/python && \
   PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q \
   tests/core/test_redaction.py tests/core/test_logging_uvicorn.py"
```

Result: **34 passed in 2.08s**.

### Secret-boundary regressions

```bash
docker run --rm -v /home/armin/Documents/NewsCraft/backend:/workspace \
  -w /workspace -e PYTHONPATH=. newscraft-backend:local \
  python -m pytest -p no:cacheprovider -q \
  tests/core/test_redaction.py tests/core/test_logging_uvicorn.py \
  tests/core/test_secret_boundary.py tests/test_secret_redaction.py \
  tests/test_job_event_redaction.py
```

Result: **44 passed in 3.47s**. This contains the 34 focused tests plus 10 additional secret/event boundary regressions.

### Complete backend suite

The complete suite needs the repository-level scripts, a real `_test` PostgreSQL database, the hard-coded `.venv/bin/alembic` path used by one migration test, and the host Docker CLI/plugin used by one Compose test. The authoritative final command supplied all four:

```bash
docker run --rm --network host \
  --tmpfs /repo/backend/.venv/bin \
  -v /home/armin/Documents/NewsCraft:/repo \
  -v /usr/bin/docker:/usr/bin/docker:ro \
  -v /usr/lib/docker/cli-plugins/docker-compose:/usr/lib/docker/cli-plugins/docker-compose:ro \
  -w /repo/backend \
  -e PYTHONPATH=. \
  -e DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  -e TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  newscraft-backend:local sh -c \
  "ln -s /usr/local/bin/alembic /repo/backend/.venv/bin/alembic && \
   python -m pytest -p no:cacheprovider -q"
```

Result: **1,670 passed, 1 warning in 240.23s**.

The sole warning is the pre-existing `StarletteDeprecationWarning` stating that `httpx` with `starlette.testclient` is deprecated in favor of `httpx2`. It did not fail the suite.

Two earlier full-suite attempts had incomplete container tool mounts. The first stopped at two operations-test collection errors; the second produced `1,668 passed` plus the migration/Docker tool-path failures. Both were superseded by the single green 1,670-test command above and are not counted as acceptance evidence.

### Static and source integrity

```bash
docker run --rm -v /home/armin/Documents/NewsCraft:/repo \
  -w /repo/backend newscraft-backend:local ruff check .
```

Result: **passed**.

```bash
docker run --rm -v /home/armin/Documents/NewsCraft:/repo \
  -w /repo/backend newscraft-backend:local \
  python -m compileall -q app ../scripts
```

Result: **passed**.

```bash
docker run --rm -v /home/armin/Documents/NewsCraft/backend:/workspace \
  -w /workspace newscraft-backend:local \
  ruff format --check app/core/logging.py app/core/redaction.py \
  tests/core/test_redaction.py tests/core/test_logging_uvicorn.py \
  tests/core/test_secret_boundary.py
```

Result: **passed — all five selected files already formatted**.

```bash
git diff --check
```

Result: **passed**.

The repository-wide `ruff format --check .` was also run. It reported 99 pre-existing files outside the Phase 5 change set that would be reformatted, so the global format criterion is **not marked passed**. Those unrelated files were not rewritten because that would exceed Phase 5 scope.

### Post-fix real formatter verification

```bash
docker run --rm newscraft-backend:local python -c "import importlib.metadata, logging; from uvicorn.logging import AccessFormatter; from app.core.logging import RedactingAccessFormatter; print('uvicorn=' + importlib.metadata.version('uvicorn')); args=('127.0.0.1:43100','GET','/health?token=phase5-postfix','1.1',200); record=logging.LogRecord('uvicorn.access', logging.INFO, '<phase5-postfix>', 1, '%s - \"%s %s HTTP/%s\" %d', args, None); formatter=RedactingAccessFormatter(fmt='%(client_addr)s - \"%(request_line)s\" %(status_code)s', use_colors=False); print(formatter.format(record)); print('original_args_after_len=' + str(len(record.args))); print('real_access_formatter=' + str(isinstance(formatter, AccessFormatter)))"
```

Result:

```text
uvicorn=0.51.0
127.0.0.1:43100 - "GET /health?token=%5BREDACTED%5D HTTP/1.1" 200 OK
original_args_after_len=5
real_access_formatter=True
```

### Deployed Compose validation

The exact default-project command was attempted first:

```bash
docker compose up -d --build postgres api
```

It built the final image, but the API correctly refused to start because the retained default PostgreSQL volume was stamped with unavailable historical revision `0016_persian_llm_generation`, while this checkout ends at `0009_operational_retention`. The retained volume was not destroyed, stamped, downgraded, or otherwise modified.

The same validation was then run under an isolated project with fresh named volumes:

```bash
docker compose -p newscraft-phase5 up -d --build postgres api
```

Result: PostgreSQL healthy; API healthy.

```bash
curl -fsS 'http://127.0.0.1:8000/health?token=log-canary'
```

Result: `{"status":"ok"}`.

```bash
docker compose -p newscraft-phase5 logs --no-color api | tee /tmp/newscraft-api.log
```

The relevant deployed line was:

```text
INFO: 172.21.0.1:45750 - "GET /health?token=%5BREDACTED%5D HTTP/1.1" 200 OK
```

```bash
! rg -n 'log-canary|Logging error|not enough values to unpack' /tmp/newscraft-api.log
```

Result: **passed with zero matches**.

```bash
rg -n 'GET .*health.* 200' /tmp/newscraft-api.log
```

Result: **passed**; safe 200 access lines were present.

```bash
rg -c 'GET /health\?token=%5BREDACTED%5D HTTP/1\.1.*200 OK' /tmp/newscraft-api.log
```

Result: **1**. The one explicit canary request produced one access record. Other `/health` lines came from the configured container health check and contained no query canary.

After validation, the isolated containers and network were removed without `-v`; all named volumes, including the incompatible retained default volume, were preserved. The disposable `postgres-test` container was stopped.

## Acceptance criteria

| Criterion | Result | Direct evidence |
| --- | --- | --- |
| 10,000 generated valid/malformed records produce zero formatter exceptions | **PASS** | Dedicated 10,000-iteration test in the 34-test focused gate |
| Uvicorn access output retains client, method, safe path, protocol, and status | **PASS** | Real Uvicorn formatter test, live ASGI 200/404/500 test, post-fix script, and deployed line |
| No registered secret canary appears in access, error, exception, or fallback output | **PASS** | Credential matrix, exception/stack/extra tests, fail-closed tests, live ASGI test, and deployed negative scan |
| One request produces one access record; logger/handler configuration is not duplicated | **PASS** | Three live ASGI requests produced exactly three lines; deployed canary count was exactly one; repeated configuration test remained idempotent |
| Full backend and deployed request-smoke logs contain no `Logging error` | **PASS** | 1,670-test full backend run plus isolated Compose log scan |

## Definition of done

- [x] No filter destroys `msg` or `args`; the legacy mutating filter was removed and original-record immutability is asserted.
- [x] Uvicorn access and generic clone-based formatters are installed explicitly and idempotently.
- [x] Real formatter, live ASGI, failure, stress, and credential/query canary tests pass.
- [x] Formatting failures cannot escape into application flow, and fallback output contains no raw record values.
- [x] Deployed access logs are structured, useful, one-per-request, and clean.

## Remaining risks and non-Phase-5 conditions

1. **Dependency drift remains Phase 8.** `pyproject.toml` specifies `uvicorn[standard]>=0.35` without a backend lock. Phase 5 is directly verified against resolved Uvicorn `0.51.0`; a future resolver change must rerun the real-formatter and ASGI tests.
2. **The retained default PostgreSQL volume is incompatible with this checkout.** This prevented default-project API startup but did not affect the isolated fresh-volume Phase 5 deployment. Resolving or restoring that historical schema is not a logging change and was intentionally not attempted.
3. **Repository-wide format normalization remains pre-existing debt.** Ruff lint passes, and all Phase 5 files pass format-check; 99 unrelated existing files do not.
4. **One non-failing framework deprecation warning remains.** It concerns Starlette TestClient/httpx compatibility and did not affect Uvicorn access logging.
5. Query redaction is deliberately based on recognized sensitive key families. Operators and application code must not place credentials under innocuous query names.

None of these conditions leaves a Phase 5 acceptance criterion unverified.

## Rollback

No migration is involved. Revert the two logging/redaction production files and their focused tests/report together. If rollback is required during an incident, disable Uvicorn access logging temporarily; do not restore either the mutating filter or unredacted access arguments. Keep the last known safe generic formatter active.
