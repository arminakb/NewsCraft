# NewsCraft Rescue Execution Index

> **Executor entrypoint:** Read the approved design and then execute the release plans below in order. Use `superpowers:subagent-driven-development` (same session) or `superpowers:executing-plans` (separate session), test-first, with requirement and quality review after every task.

## Objective

Turn NewsCraft from a one-shot ingestion dashboard into a local, single-operator content platform that collects durable source material, creates evidence-grounded platform drafts, supports review-first or explicitly enabled automatic Telegram publishing, and exports complete manual publishing packages for Instagram, X, and blogs.

## Approved Product Decisions

- Local, single-operator product; authentication and RBAC are not part of this rescue.
- PostgreSQL is the durable source of truth and job queue.
- Review is the safe default. Auto-publish is opt-in per automation/destination and remains subject to a global kill switch.
- Telegram is the first real publishing connector.
- Telegram-to-Telegram routes process only messages newer than route activation by default.
- Backfill is always explicit and bounded by count or date.
- Telegram source albums/media are downloaded and re-uploaded; each route chooses preserve, omit, or replace manually.
- OpenRouter is the production HTTP provider. Codex CLI is a local operator-only provider.
- Research is off by default and can be manual or automatic only when evidence is incomplete.
- Codex research may use its own browsing capability. OpenRouter research uses a controlled DuckDuckGo search/fetch loop with budgets, evidence capture, and citation validation.
- Instagram, X, and blog destinations produce validated drafts and export/copy packages; the operator publishes them manually in the initial product.
- No live external publishing or credentialed smoke test belongs in the deterministic default test suite.

## Starting Repository State

- Branch: `refactor-cleanup`.
- Approved design commit: `a6ed602` (`docs: define NewsCraft content platform rescue`).
- Release 0 plan commit: `bce6584` (`docs: plan truthful Release 0 baseline`).
- Release 2 first draft: `e97e28d`; Release 1 plan: `997749a`; Release 3 plan: `ad75133`; Release 4 plan: `8fc32d7`; Release 5 plan: `e7a0099`.
- Cross-plan corrections: `edee27c` aligns the Telegram worker/redaction contracts and `85cf1f5` aligns later verification/reconciliation contracts.
- The commit containing this index is the final audited handoff: it closes activation-race, capability-claim, provider-profile, evidence-materialization, revision-schema, scheduling, export-storage, heartbeat, and reconciliation contradictions across Releases 1-5.
- These are planning commits only. Application implementation has not started in this planning handoff.
- The worktree still contains the pre-existing validated cleanup diff: 46 files, 666 insertions, and 8,092 deletions.
- Preserve and do not stage these unrelated untracked artifacts unless a later explicit task says otherwise:
  - `refactor.txt`
  - `docs/superpowers/plans/2026-07-07-local-app-audit-remediation.md`
  - `.superpowers/`
- `backend/.dockerignore` and `frontend/lib/empty-data.ts` belong to the Release 0 cleanup checkpoint.

Before execution, verify the state instead of trusting this snapshot:

```bash
git branch --show-current
git log -5 --oneline
git status --short
git diff --shortstat
```

## Source of Truth

1. [Approved product and architecture design](../specs/2026-07-11-newscraft-content-platform-rescue-design.md)
2. [Release 0: truthful baseline](2026-07-11-release-0-truthful-baseline.md)
3. [Release 1: platform spine and newsroom shell](2026-07-11-release-1-platform-spine-newsroom-shell.md)
4. [Release 2: Telegram automation vertical](2026-07-11-release-2-telegram-automation-vertical.md)
5. [Release 3: editorial research and generation](2026-07-11-release-3-editorial-research-generation.md)
6. [Release 4: multi-platform manual packages](2026-07-11-release-4-multiplatform-manual-packages.md)
7. [Release 5: operational hardening](2026-07-11-release-5-operational-hardening.md)

The design governs product behavior and invariants. A release plan governs task order and exact implementation scope. If they genuinely conflict, stop and resolve the conflict before coding; do not silently choose one.

## Required Execution Order

```text
Release 0: truthful baseline
    ↓
Release 1: durable platform spine + Newsroom shell
    ↓
Release 2: end-to-end Telegram automation
    ↓
Release 3: editorial research + generation studio
    ↓
Release 4: Instagram/X/blog manual packages
    ↓
Release 5: operational hardening + acceptance
```

Do not parallelize implementation tasks that share migrations, ORM models, API schemas, query keys, or the application shell. Parallel read-only review and research are safe. Each release must end in working software and cannot depend on a later release to repair its core contract.

## Commit and Review Discipline

For every task in every release:

1. Record the starting SHA.
2. Write the smallest failing test for the requested behavior.
3. Run it and capture the expected failure.
4. Implement the minimum production change.
5. Run the focused test, then the relevant suite.
6. Inspect `git diff --check`, staged paths, and test output.
7. Commit only that task with the commit subject specified by its plan.
8. Run task-scoped requirement and code-quality review against the recorded SHA range.
9. Fix and re-review every Critical or Important finding before starting the next task.

Never mix generated companion output, credentials, local databases, downloaded media, or unrelated user files into a commit. Do not push unless the user explicitly requests it.

## Cross-Release Invariants

- Immutable evidence, prompt versions, platform revisions, approvals, attempts, and publication receipts.
- Telegram activation is a gap-free, bounded two-coordinate initialization; no post newer than the effective activation boundary is discarded merely to establish a cursor.
- Capability workers filter allowed job types inside the atomic queue-claim query; an incapable worker never claims and then rejects a job.
- Generation and research requests select persisted provider-profile UUIDs. Provider type, model, settings, availability, and secrets are resolved server-side from that exact profile.
- Research adapters return database-free candidate evidence; only the durable research handler persists snapshots and resolves stable evidence keys to UUID citations.
- Every long-running action returns a durable job and exposes progress/failure state.
- Idempotency keys protect collection, generation, automation dispatch, and publishing.
- Publishing always references one immutable approved revision and one destination.
- Editing an approved revision creates a new `pending_review` revision; the approved parent remains immutable.
- Auto mode never bypasses validation, evidence, duplicate prevention, pause controls, rate limits, or publication receipts.
- Network/provider/Telegram calls happen outside database transactions.
- Leases, bounded retries, heartbeats, and explicit recovery handle worker crashes.
- Time is stored in UTC and displayed in the operator's configured timezone.
- Secrets are redacted recursively from errors, logs, events, metadata, and URLs.
- The application never displays fabricated operational state, source provenance, schedule times, or success.
- Persian content retains explicit RTL boundaries while application chrome remains usable LTR.

## Release Exit Gates

Each release plan contains focused gates. Before declaring any release complete, also run the gates that exist at that point:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .

cd ../frontend
npm run test
npm run typecheck
npm run build

cd ..
docker compose config >/tmp/newscraft-compose.yml
git diff --check
```

Run Playwright at the desktop and mobile viewports once Release 0 establishes the deterministic local command. Run Alembic upgrade and downgrade checks after every migration-bearing release. Credentialed Telegram/OpenRouter/Codex smoke tests are opt-in, clearly labeled, and never required for the normal gate.

## Definition of Rescued

The project is complete only when the acceptance criteria in the approved design pass. In particular, a clean install must support this operator-visible flow:

1. Configure sources, providers, prompts, brand profile, Telegram destination, and an automation route.
2. Collect only new Telegram messages by default, preserving evidence and albums.
3. Optionally enrich incomplete material through a bounded research backend.
4. Generate immutable, platform-valid revisions.
5. Review and edit an exact revision, or explicitly enable auto mode.
6. Publish idempotently to Telegram with durable receipts and recovery.
7. Create complete Instagram, X, and blog packages for manual publishing.
8. Pause globally or per route, inspect failures/history, retry safely, and restore from backup without losing the audit trail.

## Planning Handoff Integrity

- 53 ordered implementation tasks across Releases 0-5.
- 52 required task commits; Release 0 Task 5 is a verification-only gate.
- Every behavior-changing task is test-first and names focused verification commands plus an exact commit subject.
- Markdown fences, placeholder scans, whitespace checks, stale path/state scans, migration order, provider-profile selection, and cross-release model/API contracts were checked before this handoff.
- No application implementation is part of the final planning commit; execution begins with Release 0.

## Suggested Delegation Prompt

```text
Work in /home/wingman/code/NewsCraft on branch refactor-cleanup.
Read docs/superpowers/plans/2026-07-11-newscraft-rescue-execution-index.md first, then the approved design and the current release plan. Execute releases strictly in order, beginning with Release 0. Use test-driven development and subagent-driven task review. Commit every independently testable task with the plan's exact commit subject. Preserve unrelated user files and the explicitly excluded untracked artifacts. Do not push or perform credentialed external publishing unless I explicitly authorize it. Continue through the current release without asking routine preference questions; stop only for a genuine blocker or a conflict between the design and plan.
```
