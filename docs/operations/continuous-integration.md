# Continuous integration and release gate

`CI` is the credential-free pull-request gate. It uses the committed Python and npm locks and separates failures into static, unit, PostgreSQL/process, migration, frontend, contract, deployment-image, security, and mocked-browser boundaries. `release-gate` depends on every blocking job and is the single status to require in branch protection.

The workflow never reads OpenRouter or Telegram secrets. GitHub's read-only token is used only by the secret scanner. PostgreSQL databases are disposable and end in `_test`; live publishing and provider calls are prohibited in pull-request CI.

## Required repository settings

On the protected `main` branch, require:

- the `Release gate` status;
- one approving review and resolved conversations;
- the branch to be current before merge;
- force pushes and branch deletion disabled.

Repository administration is external state and cannot be enforced by workflow YAML. Verify these settings after the workflow has run once and GitHub has registered its status name.

## Failure ownership

- A new deterministic job is never hidden with `continue-on-error`.
- If a non-security job is demonstrably flaky, keep it visible and temporarily remove it from `release-gate` only with an issue, owner, and expiry no later than seven days.
- Secret scanning, migration safety, frozen installs, and production-image builds are never relaxed.
- Artifacts are retained for 30 days and must contain reports, traces, inventories, or sanitized topology only—never environment dumps, database contents, provider responses, or credentials.

## Nightly production drills

`Nightly production drills` runs a credential-free Compose stack with the fake generation provider and Telegram dry-run mode, captures HTTP smoke evidence, exercises worker restart recovery, runs backup/restore safety tests, and exercises the current Feed unit and browser workflow. Later phases may strengthen these jobs with their phase-owned live or scale fixtures; pull requests remain deterministic and side-effect free.

Run workflow syntax checks locally with `actionlint .github/workflows/*.yml` when actionlint is available. The repository tests also validate required job names, trigger shape, frozen installs, database naming, artifact retention, and the absence of live-secret expressions.
