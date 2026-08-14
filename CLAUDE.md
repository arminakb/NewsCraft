# NewsCraft — Claude instructions

Read `AGENTS.md` for agent skills (issue tracker, triage labels, domain
docs) and `README.md` for the full development and operations reference.

## Orchestration

This repository is worked on by a Claude Fable session acting as sole
orchestrator. The complete operating procedure lives in
`.claude/skills/orchestrate/SKILL.md` — invoke it with `/orchestrate` for
any multi-ticket or delegated work and follow it exactly. Non-negotiable
guardrails auto-load from `.claude/rules/orchestration-guardrails.md` and
apply to ALL work in this repo, orchestrated or not. Run state lives in
`.orchestrator/` (state.md/ledger.md tracked; runs/ gitignored).

Model routing (default; record any owner directive verbatim in
`.orchestrator/state.md`): implementation and fixes → Opus at high effort,
raised to max for high-risk/cross-cutting/concurrency scopes; cold review →
codex `gpt-5.6-sol` at max effort via
`.orchestrator/scripts/codex-review.sh`; all other delegated work → Opus
high. If an Opus round is inadequate on inspection, redo it via the sol
fixer at max (`codex-fix.sh`). Subagent definitions:
`.claude/agents/opus-{implementer,investigator,test-runner,fixer}.md`.
Never set CLAUDE_CODE_SUBAGENT_MODEL. External CLI models (Codex)
participate only as cold reviewers or fixers, never as orchestrators.

Merge policy: never merge a PR without the owner's explicit approval; a
standing directive recorded in `.orchestrator/state.md` is a record of
approval, never authorization by itself.

## Toolchain (pinned)

- Python 3.14.6 with uv 0.11.29. Backend dev env: `cd backend && uv sync
  --locked`. Production uses `uv sync --locked --no-dev --no-editable`.
- Node.js 26.4.0 / npm 11.17.0. Always `npm ci`, never `npm install`;
  dependency updates change `package.json` and `package-lock.json`
  together.

## Gates

Full registered gate (all must pass before any merge):

- Backend tests: `cd backend && uv run python -m pytest tests -v`
- PostgreSQL queue contract suite: `scripts/test_postgres.sh` (owns a
  disposable migrated test database; `NEWSCRAFT_KEEP_TEST_DATABASE=1` only
  for local diagnosis)
- Acceptance journeys: `scripts/test_acceptance.sh`
- Quality baseline (blocking): `backend/.venv/bin/python
  scripts/quality_baseline.py --check` — enforces Ruff, zero full-app mypy
  and TypeScript unused-code findings, complexity budgets, and the
  <1,000-line module ceiling
- Frontend: `cd frontend && npm run test && npm run typecheck && npm run build`
- Frontend e2e when frontend behavior changed: `cd frontend && npm run
  test:e2e` (set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium`
  to use the system browser)

Typecheck/lint exist as Ruff + mypy (backend) and `tsc --noEmit`
(frontend), enforced through `quality_baseline.py` — do not invent
additional linters or formatters.

## Environment notes

- Compose services bind to 127.0.0.1 and use `restart: "no"` in base/dev/
  test/acceptance configs; `docker-compose.acceptance.yml` is never a
  deployment configuration.
- Never point tests at a real database; the test scripts own disposable
  ones.
- `scripts/backup_restore.py restore` is destructive (requires
  `--confirm-replace`) — never run it as part of routine work.
