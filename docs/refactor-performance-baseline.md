# Refactor performance baseline

Captured on 2026-07-26 for Phase 0 of `REFACTOR_PLAN.md`.

## Reproduce

From the repository root:

```bash
scripts/performance_baseline.sh
```

The command starts an isolated PostgreSQL 18.3 database, applies every
migration, replaces only the disposable `_test` database contents, seeds the
representative dataset, warms each surface once, measures it three times, emits
JSON, and removes the database.

The dataset contains:

| Record | Count |
| --- | ---: |
| Content items | 20,000 |
| Stories and evidence snapshots | 1,000 each |
| Workflow jobs | 10,000 |
| Content packs and current Telegram revisions | 250 each |
| Publications | 250 |
| Research runs | 250 |
| Sources | 20 |

Surface requests run concurrently in the same shape as the frontend. Timings
are in-process HTTP request, database, mapping, validation, and serialization
time. Query counts come from SQLAlchemy's cursor-execution boundary. Wall-clock
results are machine-sensitive; query counts and relative hotspots are the more
stable comparison.

## Recorded baseline

| Surface | Requests | Queries | p50 | p95 |
| --- | ---: | ---: | ---: | ---: |
| Today | 6 | 1,009 | 613.19 ms | 618.77 ms |
| Inbox | 1 | 2 | 14.19 ms | 14.55 ms |
| Feed | 2 | 12 | 628.84 ms | 709.03 ms |
| Raw Content | 1 | 1 | 29.19 ms | 29.51 ms |
| Drafts | 2 | 1,753 | 776.64 ms | 782.69 ms |
| Jobs | 2 | 5 | 13.52 ms | 14.28 ms |
| Library | 3 | 3 | 19.58 ms | 20.56 ms |

The exact requests and all three samples remain in the JSON emitted by the
command.

## Defects exposed

- Today executes 1,009 queries because the Telegram outcome list resolves
  dispatch, publication, evidence, and media data revision by revision.
- Drafts executes 1,753 queries because it combines that Telegram list with
  per-pack and per-revision request projection.
- Feed holds its query count to 12, but the facet route still loads every
  content-item identifier and derives coverage in application memory. Its
  709.03 ms p95 at 20,000 items confirms the known scan is a defect; this number
  is not an accepted permanent latency budget.
- Inbox, Raw Content, Jobs, and Library remain bounded on this dataset and are
  useful controls for later comparisons.

Later phases should rerun this command after each query refactor and compare
both query counts and timings. A faster wall-clock result does not compensate
for an unbounded query or full-table application-memory scan.
