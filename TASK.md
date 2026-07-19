You are a senior software architect, production-readiness auditor, and debugging engineer.

Your task is to deeply investigate the **NewsCraft project, referred to as Project B**, identify the actual root cause of each known production-readiness issue listed below, and create a precise, implementation-ready remediation plan.

## Main Objective

For every issue:

1. Inspect the relevant source code, configuration, tests, database behavior, runtime flow, and documentation.
2. Reproduce or statically confirm the issue whenever possible.
3. Identify the real root cause based on evidence.
4. Distinguish the root cause from symptoms and secondary effects.
5. Design the safest and smallest correct solution.
6. Define the exact implementation steps.
7. Define the tests and validation commands required to prove the fix.
8. Document everything in a new file named:

```text
solutions.md
```

Do not apply fixes during this task unless a minimal temporary diagnostic change is absolutely necessary to confirm a root cause.

The primary deliverable is the complete `solutions.md` file.

---

# Important Working Rules

* Do not guess.
* Do not trust previous reports without verifying them against the current codebase.
* Do not propose a rewrite unless the existing architecture makes a local fix impossible.
* Prefer targeted fixes over broad refactoring.
* Do not add unrelated features.
* Do not merge concepts from another repository.
* Do not modify production source files while preparing the report.
* Do not hide uncertainty.
* Clearly label findings as:

  * Confirmed
  * Strongly supported
  * Suspected
  * Not reproducible
  * Blocked by environment
* Cite exact file paths, classes, functions, methods, line ranges, configuration keys, database models, and test files.
* When runtime reproduction is impossible, perform static call-path analysis and clearly state the limitation.
* Inspect the repository before accepting any issue description as accurate.
* Treat security, data integrity, duplicate publication, worker survival, and credential leakage as high-risk concerns.

---

# Required Investigation Process

Before writing the final solution phases:

## Step 1 — Understand the Architecture

Inspect and summarize:

* API runtime
* PostgreSQL session and transaction handling
* Job queue and worker lifecycle
* Scheduler behavior
* Telegram automation flow
* Publishing flow
* Source ingestion flow
* Generation/provider execution
* Credential injection and secret boundaries
* Logging and redaction
* Docker Compose topology
* Frontend architecture
* Test structure
* Backup, restore, retention, and export systems
* CI and dependency management

Create a short architecture map for yourself before analyzing the issues.

## Step 2 — Build an Evidence Map

For every issue, locate:

* Relevant implementation files
* Relevant configuration files
* Relevant database models
* Relevant tests
* Existing documentation
* Runtime logs or audit reports
* Related code paths
* Possible secondary failure paths

## Step 3 — Root-Cause Analysis

For each issue, answer:

* What exactly is failing?
* Where does it fail?
* Under what conditions does it fail?
* What is the first incorrect assumption or operation?
* What is the true root cause?
* What are only symptoms?
* What other components are affected?
* What data-integrity or security risks exist?
* What is the smallest safe fix?
* What alternative fixes were considered?
* Why is the recommended approach better?
* Could the proposed fix introduce regressions?

## Step 4 — Create the Implementation Plan

Convert every issue into a separate phase inside `solutions.md`.

Each phase must be independently actionable by another engineering agent.

---

# Issues to Investigate

## Phase 1 — Telegram Route Mutations Commit Successfully but Return HTTP 500

Investigate route operations such as:

* Activate
* Pause
* Resume
* Dry-run
* Backfill
* Any other mutation that updates Telegram automation state

Reported behavior:

* The database mutation may commit successfully.
* The API then returns HTTP 500.
* The likely failure involves SQLAlchemy ORM state after commit, object expiration, lazy loading, response serialization, async session handling, or `MissingGreenlet`.

Investigate:

* Transaction boundaries
* `commit`
* `flush`
* `refresh`
* ORM expiration
* Pydantic response serialization
* Lazy relationships
* Async SQLAlchemy usage
* Response objects returned after session changes
* Exception handling
* Whether a failed response causes clients to retry a mutation that already succeeded

The solution must prevent:

* HTTP 500 after a successful mutation
* Client confusion
* Accidental duplicate requests
* ORM access outside a valid async context

---

## Phase 2 — Worker Crashes After a Handler Commits

Reported behavior:

* A job handler may commit a transaction.
* The worker later accesses expired, detached, unloaded, or session-bound ORM attributes.
* The worker crashes before marking the job complete.
* Jobs may remain incomplete even though side effects already occurred.

Investigate:

* Worker execution lifecycle
* Job object lifetime
* Handler transaction behavior
* Attempt metadata
* Job identifiers
* Post-handler bookkeeping
* Success/failure transitions
* Session ownership
* Retry behavior
* Idempotency implications
* Whether handlers and workers both control commits
* Risks of duplicated side effects after retry

The solution should clearly define:

* Which layer owns the transaction
* Which values must be snapshotted before handler execution
* Which values must not be read from ORM objects after commit
* How job completion should remain reliable after handler side effects
* How retries avoid duplicate publication or duplicated artifacts

---

## Phase 3 — Missing Worker Restart Policies

Reported behavior:

* Worker containers have no restart policy.
* A worker crash becomes a persistent outage until manual intervention.

Investigate:

* Docker Compose services
* Worker types
* Scheduler service
* API behavior when workers are unavailable
* Health checks
* Restart loops
* Crash visibility
* Poison jobs
* Whether `restart: unless-stopped`, `on-failure`, or another policy is more appropriate

The solution must not treat restart policies as a substitute for fixing crashes.

Define:

* Recommended restart strategy per service
* Backoff expectations
* Health-check behavior
* Alerting or diagnostics
* Protection against infinite crash loops
* Validation steps that intentionally kill a worker and confirm recovery

---

## Phase 4 — Blank Proxy Variables Force a Nonexistent Proxy

Reported behavior:

* Empty proxy environment variables may still be interpreted as configured.
* RSS, Telegram, or provider traffic may be routed through an invalid proxy.
* Real ingestion succeeds only after clearing the forced proxy.

Investigate:

* `HTTP_PROXY`
* `HTTPS_PROXY`
* `ALL_PROXY`
* Lowercase variants
* Application-specific proxy settings
* Docker Compose defaults
* Settings parsing
* HTTP client construction
* Telegram client configuration
* Provider clients
* RSS clients
* `NO_PROXY`
* Behavior when values are missing, empty, whitespace-only, or invalid

Define:

* A single normalized proxy configuration policy
* Expected behavior with no proxy
* Expected behavior with a valid proxy
* Expected behavior with an invalid proxy
* Validation tests for each network client

---

## Phase 5 — Access-Log Redaction Breaks Uvicorn Structured Logging

Reported behavior:

* Secret-redaction logic modifies logging arguments.
* Uvicorn’s access-log formatter expects a specific argument structure.
* The formatter breaks and logging itself raises an exception.

Investigate:

* Logging filters
* Formatters
* Handlers
* `LogRecord.msg`
* `LogRecord.args`
* Structured access-log arguments
* Request headers
* Query strings
* URLs
* Exception logs
* JSON logging if present
* Whether redaction mutates data in place
* Whether secrets can leak before or after formatting

The solution must:

* Preserve Uvicorn formatter contracts
* Redact sensitive values
* Never cause logging to raise an exception
* Cover API keys, Telegram tokens, authorization headers, cookies, credential references, proxy credentials, and sensitive query parameters

Include tests for both:

* Correct log formatting
* Absence of secret leakage

---

## Phase 6 — API Container Receives Worker-Scoped Credentials

Reported behavior:

* Credentials documented as source-worker, generation-worker, or publishing-worker scoped are also available to the API container.
* This violates capability separation and increases blast radius.

Investigate:

* Docker Compose environment sections
* `.env` usage
* Settings classes
* Secret loading
* Credential-reference mechanisms
* API schemas
* Job payloads
* Logs
* History or audit records
* Exports
* Backups
* Diagnostics endpoints
* Frontend projections
* Worker-specific environment variables

Define a strict credential topology:

* Which service receives which secret
* Which service receives only a credential reference
* Which values must never be returned by the API
* Which values must never be serialized into jobs
* Which values must never appear in logs, backups, exports, or diagnostics
* How local development remains usable without weakening production boundaries

---

## Phase 7 — Missing CI Workflow

Reported behavior:

* The project has no complete CI workflow.

Investigate the existing commands and create a proposed CI design covering:

* Backend unit tests
* Backend integration tests
* Database migration checks
* Alembic single-head validation
* Python compilation
* Linting
* Formatting checks
* Type checking
* Frontend unit tests
* Frontend type checking
* Frontend production build
* Docker Compose validation
* Security or secret scanning
* Dependency consistency
* Contract tests
* Optional browser E2E tests
* Artifact and test-report retention

Define:

* Required jobs
* Job dependencies
* Caching strategy
* PostgreSQL service setup
* Environment variables
* Which tests block merges
* Which tests may run nightly
* Recommended branch protection rules

Do not create the CI workflow yet. Document the exact implementation plan.

---

## Phase 8 — Missing Backend Dependency Locking and Unpinned Frontend Dependencies

Reported behavior:

* The backend lacks a clear lock or constraints strategy.
* Some frontend dependencies may use `latest` or insufficiently pinned versions.
* Fresh installations may produce different environments.

Investigate:

* Python dependency files
* Development dependencies
* Production dependencies
* Optional dependencies
* Transitive dependencies
* Node package files
* Lockfiles
* Docker build behavior
* Current installation instructions
* Reproducibility across clean environments

Recommend a dependency strategy appropriate for the project.

Define:

* Source dependency files
* Lock or constraints files
* Update workflow
* Security-update process
* Reproducible build validation
* Rules for direct and transitive dependencies
* Frontend pinning rules
* How Docker builds consume the locked dependencies

---

## Phase 9 — Missing Real Readiness and Operational Health Checks

Reported behavior:

* The API may be alive while workers, PostgreSQL, the scheduler, or queues are unhealthy.

Investigate existing:

* Health endpoints
* Diagnostics
* Worker heartbeats
* Scheduler state
* Job leases
* Queue statistics
* Retry counts
* Stuck jobs
* Oldest pending jobs
* Failed jobs
* Worker capabilities
* Database connectivity checks

Design distinct checks for:

* Liveness
* Readiness
* Dependency health
* Worker availability
* Scheduler health
* Queue lag
* Stuck or abandoned jobs
* Publishing capability
* Source-ingestion capability
* Generation capability

Define:

* Exact metrics
* Thresholds
* Failure states
* API response shape
* Container health checks
* Operational alerts
* Tests

---

## Phase 10 — Frontend and Backend Contract Drift in Browser E2E Tests

Reported behavior:

* Browser or mocked E2E tests show contract drift.
* Some frontend assumptions no longer match backend behavior.

Investigate:

* API client types
* OpenAPI schemas
* Handwritten frontend models
* Mocks
* Fixtures
* Playwright tests
* Response envelopes
* Pagination
* Error formats
* Status values
* Optional versus required fields
* Date-time formats
* Enum drift

Define:

* The source of truth for contracts
* Whether types should be generated
* How mocks should be validated
* How contract drift should fail CI
* The exact tests required to prove alignment

---

## Phase 11 — Story Inbox Large-List Performance Timeout

Reported behavior:

* One large-list bulk-selection test exceeded the default 10-second timeout.
* It passed with a longer timeout, but the behavior indicates a potential performance problem.

Investigate:

* List rendering
* State updates
* Bulk selection
* Re-renders
* Memoization
* Pagination
* Virtualization
* Network requests
* Filtering
* Sorting
* Test implementation
* Whether the timeout is caused by production code or test overhead

Do not solve the issue merely by increasing the timeout unless profiling proves the operation is acceptably fast.

Define measurable performance targets and a profiling plan.

---

## Phase 12 — Diagnostics Accessibility and Contrast Issue

Reported behavior:

* The Diagnostics UI has at least one contrast or accessibility defect.

Investigate:

* Exact affected component
* Color tokens
* Theme behavior
* Dark and light mode if applicable
* Focus states
* Semantic markup
* Accessible names
* Keyboard navigation
* Screen-reader behavior
* Automated accessibility tests

Define:

* Corrective changes
* WCAG target
* Automated regression tests
* Manual verification steps

---

## Phase 13 — Real Persian Generation Quality Is Unproven

Reported behavior:

* Multiple real OpenRouter attempts produced no usable content.
* The pipeline may technically run without producing acceptable Persian editorial output.

Investigate:

* Provider responses
* Schema failures
* Empty outputs
* Parsing failures
* Prompt design
* Context construction
* Evidence quality
* Language selection
* Persian script handling
* Title generation
* Promotional-content classification
* Model compatibility
* Timeout and retry behavior
* Provider fallback
* Cost and latency
* Whether failure is caused by provider quality, prompts, schemas, parsers, or upstream evidence

Design a controlled evaluation plan for at least 30 representative Persian stories.

Evaluation criteria should include:

* Factual accuracy
* Evidence grounding
* Relevance
* Clarity
* Natural Persian writing
* Title quality
* Platform fit
* Hallucination rate
* Unsupported claims
* Correct promotional classification
* Correct language and script
* Schema-completion reliability
* Cost
* Latency

Define acceptance thresholds, including:

* Minimum average editorial score
* Minimum schema-completion rate
* Maximum unsupported-claim rate
* Maximum retry rate
* Maximum acceptable cost and latency where appropriate

---

## Phase 14 — Controlled Live Telegram Publishing Is Unproven

Reported behavior:

* Safe live Telegram publishing has not been fully demonstrated.

Investigate the complete publication lifecycle:

* Approval
* Exact revision/hash verification
* Dispatch creation
* Worker execution
* Telegram request
* Telegram response
* Publication record
* Retry
* Reconciliation
* Crash recovery
* Duplicate prevention
* Manual operator intervention
* Revoked or modified approval
* Edited content after approval
* Network timeouts
* Ambiguous provider responses

Design tests for:

* Dry-run
* Authorized test channel
* Successful publication
* Crash before sending
* Crash during sending
* Crash after sending but before recording success
* Timeout with unknown delivery status
* Retry
* Duplicate suppression
* Reconciliation
* Approval/hash mismatch
* Credential failure
* Telegram API error
* Rate limiting
* Worker restart

The plan must prioritize zero duplicate publication.

---

## Phase 15 — Backup and Restore Have Not Been Proven End to End

Investigate:

* Database backup
* Media backup
* Export backup
* Checksums
* Encryption
* Credential exclusion
* Restore scripts
* Restore documentation
* Version compatibility
* Migration handling
* Retention
* Corrupted backup behavior
* Partial backup behavior

Design a disposable restore drill proving:

* Database records restore correctly
* Media files restore correctly
* Export files restore correctly
* Checksums match
* Referential integrity remains valid
* No credentials are unintentionally included
* The restored system can pass a smoke test

---

# Required `solutions.md` Structure

Create `solutions.md` using the following structure.

```markdown
# NewsCraft Production Hardening Solutions

## Executive Summary

- Overall technical assessment
- Most critical root causes
- Recommended repair order
- Dependencies between phases
- Risks that could change the recommendation
- Issues blocked by the current environment

## Architecture and Runtime Map

- API
- Database and transaction boundaries
- Job engine
- Workers
- Scheduler
- Ingestion
- Generation
- Publishing
- Credentials
- Logging
- Frontend
- Backup and restore
- Deployment topology

## Phase 1 — [Issue Name]

### 1. Problem Statement

Explain the observed behavior clearly.

### 2. Status

Use one:

- Confirmed
- Strongly supported
- Suspected
- Not reproducible
- Blocked by environment

### 3. Evidence

Include:

- File paths
- Functions/classes
- Line ranges
- Tests
- Configuration
- Logs
- Reproduction commands
- Relevant runtime observations

### 4. Root Cause

Explain the true technical root cause.

Separate:

- Primary root cause
- Contributing factors
- Symptoms
- Secondary risks

### 5. Impact

Describe the impact on:

- Reliability
- Data integrity
- Security
- Operations
- User experience
- Duplicate processing or publication
- Recovery

### 6. Recommended Solution

Describe the selected solution precisely.

### 7. Rejected or Alternative Solutions

For each alternative:

- Description
- Benefits
- Risks
- Why it is not recommended

### 8. Step-by-Step Implementation Plan

Use numbered steps.

Each step must include:

- Exact file or component
- Intended modification
- Reason
- Expected result
- Dependencies
- Potential regression risks

### 9. Required Tests

Include:

- Unit tests
- Integration tests
- Regression tests
- Failure-path tests
- Security tests
- Concurrency tests where relevant
- E2E tests where relevant

### 10. Validation Commands

Provide exact commands that should be executed.

### 11. Acceptance Criteria

Use objective, measurable conditions.

### 12. Rollback Plan

Explain how to revert safely if the fix causes regressions.

### 13. Estimated Complexity

Use:

- Low
- Medium
- High

Also provide an engineering-time estimate.

### 14. Dependencies on Other Phases

List blocking and dependent phases.

### 15. Definition of Done

Provide a final checklist.

## Phase 2 — [Issue Name]

Repeat the same structure for every issue.

## Final Execution Order

Provide the recommended implementation order.

Group phases into:

- P0 — Immediate runtime and security blockers
- P1 — Production-readiness requirements
- P2 — Product-quality validation
- P3 — Non-blocking improvements

## Cross-Phase Regression Plan

Define a test matrix covering:

- Fresh database
- Existing database
- Worker restart
- API restart
- Scheduler restart
- Network failure
- Provider failure
- Telegram failure
- Retry
- Duplicate prevention
- Backup and restore
- Secret leakage
- Proxy enabled
- Proxy disabled
- Large frontend data sets

## Final Production-Readiness Gate

Define the exact conditions required before the system can be considered ready for controlled production use.
```

---

# Phase Priority Guidance

Use this default priority unless repository evidence supports a different order.

## P0 — Immediate Runtime and Security Blockers

1. Telegram mutations return HTTP 500 after commit
2. Worker crashes after handler commit
3. Missing worker restart policies
4. Incorrect proxy defaults
5. Logging/redaction failure
6. Credential scope violations

## P1 — Production-Readiness Requirements

7. CI workflow
8. Dependency locking
9. Readiness and operational health checks
10. Frontend/backend contract drift
11. Story Inbox performance
12. Diagnostics accessibility
13. Backup and restore validation

## P2 — Product-Quality Validation

13. Persian generation quality
14. Controlled Telegram publishing

---

# Required Quality Standards

The final `solutions.md` must be:

* Evidence-based
* Detailed
* Implementation-ready
* Ordered by risk and dependency
* Clear enough for another engineer to execute without repeating the investigation
* Explicit about uncertainty
* Explicit about tests
* Explicit about rollback
* Explicit about acceptance criteria
* Free of generic recommendations such as “improve error handling” without explaining exactly where and how

Bad example:

```text
Fix SQLAlchemy session handling.
```

Good example:

```text
In the Telegram route activation service, stop returning the ORM route instance directly after `session.commit()`. Either call `await session.refresh(route)` while the session is active and eagerly load every field needed by the response schema, or construct the response DTO from known scalar values before commit. Add a regression test proving that the database mutation succeeds and the endpoint returns HTTP 200 without triggering lazy loading or `MissingGreenlet`.
```

---

# Validation Expectations

Where the environment permits, execute relevant commands such as:

* Git status and repository integrity checks
* Python compilation
* Backend tests
* Focused regression tests
* Frontend tests
* Frontend type checking
* Frontend production build
* Docker Compose validation
* Migration validation
* Static call-path inspection
* Secret searches
* Dependency inspection

Do not download dependencies or modify the environment unless explicitly authorized.

If execution is blocked:

1. State exactly what is missing.
2. Continue with static analysis.
3. Mark the finding appropriately.
4. Provide the exact future command required to validate it.

---

# Final Deliverables

At the end of the task:

1. Create or overwrite:

```text
solutions.md
```

2. Ensure every identified issue has its own phase.

3. Ensure every phase contains:

* Evidence
* Root cause
* Exact solution
* Step-by-step implementation
* Tests
* Validation commands
* Acceptance criteria
* Rollback plan
* Definition of done

4. Do not modify production source code.

5. Provide a brief final response containing:

* The path to `solutions.md`
* Number of confirmed issues
* Number of suspected or blocked issues
* Recommended first implementation phase
* Any critical uncertainty that remains

Begin by inspecting the repository architecture and building an evidence map. Do not start writing generic solutions before investigating the actual implementation.
