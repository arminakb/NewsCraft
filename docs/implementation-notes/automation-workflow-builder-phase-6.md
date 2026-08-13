# Automation Workflow Builder Phase 6

**Status:** Phase 6 release exit gate passed on 2026-08-01. The repository-wide quality-baseline gate remains blocked by inherited Phase 1–5 complexity and file-size debt described below.

Phase 6 hardens workflow security, prompt/resource boundaries, runtime recovery, frontend performance, responsive accessibility, Telegram-route compatibility, migration verification, and deterministic release acceptance.

## Delivered hardening

- Workflow graphs, catalogs, versions, snapshots, runs, node results, errors, and audit/event projections retain safe IDs and bounded summaries only. Credential, authorization, prompt-body, provider-response, header, message, and stack-trace shaped keys are removed.
- Runtime start validates the exact compiled graph, active resources, prompt-version IDs, and checksums. Source evidence cannot select destinations, credentials, review policy, tools, permissions, or publication behavior.
- Dry runs remain persisted and restart-safe while producing zero publication records. Exact reviewed revisions still publish only through the publishing worker and existing idempotency/receipt/reconciliation boundary.
- TanStack queries propagate cancellation signals. Terminal runs stop polling. Test Studio and run detail are loaded dynamically; the editor does not fetch full run history on startup.
- The browser suite covers keyboard-only operation, focus restoration, reduced motion, 200% text, light/dark themes, RTL content, touch/mobile bounds, Axe serious/critical checks, and the 390/768/1024/1440 viewport matrix.
- Legacy Telegram operations have explicit compatibility URLs under `/automations/telegram`, while `/automations` owns versioned workflow definitions. Existing route creation, dry run, pause/resume, backfill, history, and reconciliation journeys remain exercised.
- Alembic metadata now represents the deployed migration-audit table and article indexes. One head exists and `alembic check` reports no new upgrade operations.
- Acceptance scripts allow an isolated PostgreSQL host port and now pin template copy, dry-run safety, redacted run projection, exact approval/publication, and restart/crash recovery.

## Supported and deferred boundary

Supported v1 nodes and recovery policy are documented in [automation-workflows.md](../operations/automation-workflows.md). The deferred and prohibited set is canonical in “Explicit deferrals and prohibited nodes” of [automation-workflow-builder-contract.md](automation-workflow-builder-contract.md#explicit-deferrals-and-prohibited-nodes).

## Release evidence

Browser plugin tooling was unavailable in this workspace, so browser validation used the repository-pinned Playwright suite.

| Gate | Exact result |
| --- | --- |
| Workflow schema/compiler/API | `24 passed` |
| Worker/scheduler/Telegram runtime | `149 passed` |
| Focused security/API/schema regressions | `31 passed` |
| PostgreSQL workflow/integration/recovery list | `42 passed in 22.87s` |
| Fresh isolated acceptance on port 55433 | `10 passed in 13.67s`; container/network removed afterward |
| Frontend unit suite | `64 files, 492 tests passed` |
| Frontend typecheck | passed |
| Production Next.js build | passed; 19 generated pages, including workflow and Telegram compatibility routes |
| Full Playwright suite | `89 passed in 6.0m` |
| Isolated 30-node performance case | `1 passed in 18.5s` |
| OpenAPI/Docker/CI contracts | `43 passed, 1 deprecation warning in 8.88s` |
| Full mypy/Ruff | `263 source files`, zero findings in enforced normal checks |
| Alembic | `0028_automation_execution (head)` and `No new upgrade operations detected` |
| Repository whitespace | `git diff --check` passed |

Performance measurements from the isolated browser run:

| Nodes | Selection median | Samples |
| ---: | ---: | --- |
| 5 | 68.5 ms | 85.9, 64.1, 68.5 ms |
| 15 | 93.2 ms | 93.2, 93.7, 88.8 ms |
| 30 | 95.4 ms | 87.3, 95.4, 95.6 ms |

All samples remain below the 150 ms interaction budget.

## Exact commands

```bash
cd backend
.venv/bin/python -m pytest tests/test_automation_workflow_schema.py tests/test_automation_compiler.py tests/api/test_automations.py tests/api/test_automation_runs.py -v
.venv/bin/python -m pytest tests/test_job_worker.py tests/test_scheduler.py tests/test_telegram_route_handlers.py tests/test_telegram_process_handler.py tests/test_telegram_publish_service.py -v
.venv/bin/mypy app
.venv/bin/ruff check . ../scripts
.venv/bin/alembic heads
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test .venv/bin/alembic current
DATABASE_URL=postgresql+asyncpg://newscraft:newscraft@127.0.0.1:55432/newscraft_test .venv/bin/alembic check
.venv/bin/python -m pytest tests/test_openapi_contract.py tests/test_docker_config.py tests/test_ci_workflows.py -q

cd ..
scripts/test_postgres.sh tests/postgres/test_automation_definitions.py tests/postgres/test_automation_execution.py tests/postgres/test_automation_run_projection.py tests/postgres/test_scheduler_worker_integration.py tests/postgres/test_telegram_process_handler.py tests/postgres/test_telegram_publish_service.py tests/integration/test_publish_crash_recovery.py
NEWSCRAFT_TEST_PROJECT=newscraft-phase6-acceptance NEWSCRAFT_TEST_DATABASE_PORT=55433 scripts/test_acceptance.sh
backend/.venv/bin/python scripts/quality_baseline.py --check
git diff --check

cd frontend
env -u NODE_ENV npm run test
npm run typecheck
npm run build
env -u NODE_ENV npm run test:e2e
```

## Separated pre-existing quality failure

`backend/.venv/bin/python scripts/quality_baseline.py --check` remains non-zero:

- Ruff complex-function findings: `62`, committed budget `53`;
- Ruff excessive-statement findings: `32`, committed budget `25`;
- four application modules remain at least 1,000 lines, across both scanned areas: `backend/app/operations/health.py` (1,089), `backend/app/api/articles.py` (1,034), `frontend/components/dashboard/source-collections-panel.tsx` (1,143), and `frontend/features/articles/articles-page.tsx` (1,111). The 1,000-line ceiling is blocking for frontend as well as backend: `scripts/quality_baseline.py` scans `app`, `components`, `features`, and `lib` (`FRONTEND_SOURCE_DIRS`, line 18; `size_metrics(frontend_files(root), (300, 500, 1000))`, line 180) and `quality_gate_failures` reports a failure for either area whose `1000` bucket is non-empty (line 297).

The exact `+9` complexity and `+7` statement delta belongs to the already-present Phase 1–5 workflow definition implementation. The oversized backend files also predated this Phase 6 execution. Phase 6 does not hide the regression by raising budgets or adding lint suppressions. Normal Ruff, unused TypeScript, and full mypy remain clean.

This debt does not invalidate the plan's explicit PostgreSQL/browser exit gate, both of which passed. It does prevent describing the entire repository quality gate as green and should be resolved by extracting orchestration helpers and splitting the oversized modules before a strict all-gates release.
