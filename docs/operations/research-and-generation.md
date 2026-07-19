# Research and generation operations

Release 3 is review-first. Manual intake, research, canonical generation, Telegram-pack
generation, edits, and exact revision approval are durable jobs or database changes. The
deterministic test gate does not call a live model, DuckDuckGo, article host, Codex process,
or Telegram endpoint.

## Local environment

Keep local values in an uncommitted `.env`; do not put credentials in this repository.

```dotenv
OPENROUTER_API_KEY=
CODEX_ENABLED=true
CODEX_EXECUTABLE=codex
CODEX_HOME=/home/operator/.codex
```

Fake mode needs no credentials and is the safe default for local acceptance testing. Codex
uses local Codex authentication from the configured executable's existing auth directory;
NewsCraft does not store a Codex token. OpenRouter uses `OPENROUTER_API_KEY` and, for
research only, the controlled DuckDuckGo loop before fetched pages are materialized through
the safe article fetcher.

For a host-run API/worker, install and authenticate the Codex CLI as the same operating-system
user, confirm `codex --version`, set `CODEX_HOME` to that user's authenticated Codex directory,
and set `CODEX_ENABLED=true`. `CODEX_EXECUTABLE` is the command name or absolute executable
path available to both processes. NewsCraft creates a temporary execution `HOME` and workspace;
it forwards only the auth-bearing `CODEX_HOME` and the executor's explicit environment allowlist.

The stock backend image does not install Codex or copy host authentication. Build an explicit
operator image containing the CLI, then use a local, uncommitted Compose override such as:

```yaml
services:
  api:
    environment:
      CODEX_ENABLED: "true"
      CODEX_EXECUTABLE: codex
      CODEX_HOME: /codex-auth
    volumes:
      - ${CODEX_HOME}:/codex-auth:ro
  worker-source-generation:
    environment:
      CODEX_ENABLED: "true"
      CODEX_EXECUTABLE: codex
      CODEX_HOME: /codex-auth
    volumes:
      - ${CODEX_HOME}:/codex-auth:ro
```

Keep the override and authentication directory out of version control. Leave
`CODEX_ENABLED=false` when the executable/auth boundary is not configured. Restart only the
source/generation worker after changing it; the API owns neither the executable nor its
authentication state.

## Validated provider profiles

The database stores credential references, never credential values. Select an enabled
`AIProviderProfile` UUID for each research or generation request. Model selection, OpenRouter
pricing, standard and deep research budgets, and Codex generation limits live only in
validated `AIProviderProfile.settings`; there are no flat environment aliases for them.

- Fake profiles have empty settings, require no secret reference, and support deterministic
  research and generation.
- OpenRouter profiles reference `OPENROUTER_API_KEY`. Their settings validate `base_url`,
  timeout, optional attribution headers, pricing, and standard/deep budgets. Research uses an
  explicit DuckDuckGo backend and enforces query, result, page, character, time, token,
  model-call, and estimated-cost ceilings.
- Codex profiles have no secret reference. Their settings validate standard/deep budgets and
  a single-call generation limit. Execution uses a temporary home and workspace, a read-only
  sandbox, a strict JSON schema, an allowlisted environment, bounded output, and a hard
  deadline. Research may use constrained browser search; generation cannot browse.

Provider configuration shape is validated by the API. Availability in Settings is a
time-bounded observation produced by the source/generation worker and can be `available`,
`unavailable`, `unknown`, or `stale`. Only a fresh `available` observation permits execution;
profiles remain editable while a worker or credential is unavailable. Never test availability
by placing a credential value in a profile, request, log, event, or diagnostic payload.

## Operator flow

1. Open **Settings**, inspect the **Canonical story** and **Telegram pack** templates, and
   activate the exact immutable versions to use.
2. Open **Inbox**, choose **Add source material**, and submit manual text or an HTTPS URL.
   Wait for the durable intake job and inspect the grouped story and completeness result.
3. Choose **Research more** for the standard budget or **Deep research** for the larger
   budget. Select a configured research profile and wait for the durable run outcome. A
   complete story may be generated without another automatic research run.
4. Choose **Generate Telegram draft**, select the brand and generation profile, and select
   both the active Canonical story and Telegram pack prompt-version IDs.
5. Open **Drafts**, then **Review** the exact generated revision and its evidence map. Use
   **Save revision** to create an immutable pending-review child; regeneration also creates a
   child rather than overwriting copy.
6. Choose **Approve** only after the body, media, direction, validation results, evidence, and
   exact content hash are correct. Telegram publish handoff remains disabled for draft,
   pending, rejected, stale, and dry-run revisions; approval enables it only for the exact
   approved revision.

Failures remain inspectable on the research run, generation request, Drafts list, Review
screen, and job timeline. Provider or validation failure falls to review and never becomes an
automatic publish request.

## Offline acceptance gate

Run the fake-provider suites with `OPENROUTER_API_KEY` empty and without invoking Codex. The
full PostgreSQL integration cases require a disposable database whose name ends in `_test`:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
TEST_DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test \
  PYTHONPATH=. .venv/bin/python -m pytest tests/postgres tests/integration -q
.venv/bin/ruff check .
```

Then run the frontend unit, type, build, and Playwright gates documented in the repository
README. Do not supply real provider or Telegram credentials to acceptance tests.
