from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.jobs.models import AutomationControl
from app.jobs.runtime import RuntimeHeartbeatService
from app.jobs.types import JobStatus
from app.operations.diagnostics import OperationsDiagnostics, _publish_receipt_attention

NOW = datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
PUBLISH_JOB_ID = UUID("11111111-1111-4111-8111-111111111111")
RESEARCH_JOB_ID = UUID("22222222-2222-4222-8222-222222222222")
SOURCE_ID = UUID("33333333-3333-4333-8333-333333333333")
DESTINATION_ID = UUID("44444444-4444-4444-8444-444444444444")
ROUTE_ID = UUID("55555555-5555-4555-8555-555555555555")
RESEARCH_RUN_ID = UUID("66666666-6666-4666-8666-666666666666")
GENERATION_RUN_ID = UUID("77777777-7777-4777-8777-777777777777")


def test_ambiguous_and_dispatching_receipts_project_publication_attention():
    ambiguous = _publish_receipt_attention(
        SimpleNamespace(
            publish_job_id=PUBLISH_JOB_ID,
            status="ambiguous",
            ambiguous_at=NOW,
            updated_at=NOW - timedelta(seconds=1),
        )
    )
    dispatching = _publish_receipt_attention(
        SimpleNamespace(
            publish_job_id=PUBLISH_JOB_ID,
            status="dispatching",
            ambiguous_at=None,
            updated_at=NOW - timedelta(minutes=6),
        )
    )

    assert ambiguous.severity == "error"
    assert ambiguous.occurred_at == NOW
    assert "ambiguous" in ambiguous.title
    assert dispatching.severity == "warning"
    assert dispatching.occurred_at == NOW - timedelta(minutes=6)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class Rows:
    def __init__(self, values):
        self.values = list(values)

    def __iter__(self):
        return iter(self.values)

    def all(self):
        return list(self.values)


class FakeSession:
    def __init__(
        self,
        *,
        heartbeats=(),
        queue_counts=(),
        attention_jobs=(),
        sources=(),
        destinations=(),
        routes=(),
        dispatches=(),
        research_rows=(),
        generation_runs=(),
        publish_jobs=(),
        publish_receipts=(),
        publication_rows=(),
        control=None,
    ):
        self.heartbeats = list(heartbeats)
        self.queue_counts = list(queue_counts)
        self.attention_jobs = list(attention_jobs)
        self.sources = list(sources)
        self.destinations = list(destinations)
        self.routes = list(routes)
        self.dispatches = list(dispatches)
        self.research_rows = list(research_rows)
        self.generation_runs = list(generation_runs)
        self.publish_jobs = list(publish_jobs)
        self.publish_receipts = list(publish_receipts)
        self.publication_rows = list(publication_rows)
        self.control = control
        self.scalar_sql: list[str] = []
        self.execute_sql: list[str] = []
        self.get_calls: list[tuple[object, object]] = []

    async def scalars(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.scalar_sql.append(sql)
        if "FROM runtime_heartbeats" in sql:
            return Rows(self.heartbeats)
        if "FROM workflow_jobs" in sql:
            return Rows(self.attention_jobs)
        if "FROM sources" in sql:
            return Rows(self.sources)
        if "FROM destinations" in sql:
            return Rows(self.destinations)
        if "FROM automation_routes" in sql:
            return Rows(self.routes)
        if "FROM automation_dispatches" in sql:
            return Rows(self.dispatches)
        if "FROM generation_runs" in sql:
            return Rows(self.generation_runs)
        if "FROM publish_jobs" in sql:
            return Rows(self.publish_jobs)
        if "FROM publish_operation_receipts" in sql:
            return Rows(self.publish_receipts)
        raise AssertionError(f"Unexpected scalar query: {sql}")

    async def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.execute_sql.append(sql)
        if "FROM workflow_jobs" in sql and "GROUP BY" in sql:
            return Rows(self.queue_counts)
        if "FROM research_runs" in sql:
            return Rows(self.research_rows)
        if "FROM publications JOIN publish_jobs" in sql:
            return Rows(self.publication_rows)
        raise AssertionError(f"Unexpected execute query: {sql}")

    async def get(self, model, identity):
        self.get_calls.append((model, identity))
        assert model is AutomationControl
        assert identity == "global"
        return self.control

    def add(self, _value):
        raise AssertionError("Diagnostics must remain read-only")

    async def flush(self):
        raise AssertionError("Diagnostics must remain read-only")

    async def commit(self):
        raise AssertionError("Diagnostics must remain read-only")


@pytest.mark.asyncio
async def test_snapshot_uses_exact_heartbeat_thresholds_and_expected_persisted_union():
    heartbeats = [
        _heartbeat("at-healthy-boundary", NOW - timedelta(seconds=30)),
        _heartbeat("just-degraded", NOW - timedelta(seconds=30, microseconds=1)),
        _heartbeat(
            "at-degraded-boundary",
            NOW - timedelta(seconds=90),
            component_type="scheduler",
            capabilities=["scheduling"],
        ),
        _heartbeat("just-down", NOW - timedelta(seconds=90, microseconds=1)),
        _heartbeat("additional-local-instance", NOW - timedelta(seconds=4)),
    ]
    session = FakeSession(heartbeats=heartbeats)

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids=(
            " just-down, at-healthy-boundary, missing-component, at-degraded-boundary, just-down "
        ),
    ).snapshot()

    assert snapshot.generated_at == NOW
    assert list(snapshot.components) == sorted(
        {
            "additional-local-instance",
            "at-degraded-boundary",
            "at-healthy-boundary",
            "just-degraded",
            "just-down",
            "missing-component",
        }
    )
    assert snapshot.components["at-healthy-boundary"].status == "healthy"
    assert snapshot.components["just-degraded"].status == "degraded"
    assert snapshot.components["at-degraded-boundary"].status == "degraded"
    assert snapshot.components["just-down"].status == "down"
    assert snapshot.components["additional-local-instance"].status == "healthy"
    assert snapshot.components["missing-component"].status == "unknown"
    assert snapshot.components["missing-component"].observed_at is None
    assert snapshot.components["missing-component"].last_success_at is None
    assert snapshot.components["missing-component"].action_url == "/diagnostics"
    assert snapshot.components["just-degraded"].observed_at == heartbeats[1].observed_at
    assert snapshot.components["just-degraded"].last_success_at is None
    assert snapshot.components["just-degraded"].action_url == "/jobs"
    assert snapshot.components["at-degraded-boundary"].action_url == "/automations"
    serialized = snapshot.model_dump(mode="json")
    assert "runtime_metadata" not in str(serialized)
    assert "should-never-leave-storage" not in str(serialized)
    assert "LIMIT 10000" in session.scalar_sql[0]


@pytest.mark.asyncio
async def test_snapshot_timestamp_covers_heartbeat_committed_during_observation():
    """A heartbeat committed after the request starts must not postdate its snapshot."""
    heartbeat_committed_during_query = _heartbeat(
        "worker-source-generation",
        NOW + timedelta(microseconds=1),
    )
    session = FakeSession(heartbeats=[heartbeat_committed_during_query])

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids="worker-source-generation",
    ).snapshot()

    component = snapshot.components["worker-source-generation"]
    assert component.observed_at == heartbeat_committed_during_query.observed_at
    assert snapshot.generated_at >= component.observed_at


@pytest.mark.asyncio
async def test_snapshot_reads_control_queue_and_newest_attention_without_writes_or_secrets():
    newer = _job(
        RESEARCH_JOB_ID,
        job_type="research_story",
        status=JobStatus.NEEDS_REVIEW,
        updated_at=NOW - timedelta(seconds=5),
        error_message="provider token=hunter2 needs operator review",
    )
    older = _job(
        PUBLISH_JOB_ID,
        job_type="telegram.publish",
        status=JobStatus.FAILED,
        updated_at=NOW - timedelta(seconds=20),
        error_message="destination failed Authorization: Bearer unsafe-token",
    )
    session = FakeSession(
        queue_counts=[
            (JobStatus.QUEUED, 7),
            (JobStatus.RUNNING, 2),
            (JobStatus.FAILED, 1),
            (JobStatus.NEEDS_REVIEW, 1),
        ],
        attention_jobs=[newer, older],
        control=SimpleNamespace(global_pause=True, dry_run=True),
    )

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids="",
    ).snapshot()

    assert snapshot.global_paused is True
    assert snapshot.dry_run is True
    assert snapshot.queue_counts == {
        "queued": 7,
        "running": 2,
        "succeeded": 0,
        "failed": 1,
        "needs_review": 1,
        "cancelled": 0,
    }
    assert [item.id for item in snapshot.attention] == [str(RESEARCH_JOB_ID), str(PUBLISH_JOB_ID)]
    assert snapshot.attention[0].kind == "research"
    assert snapshot.attention[0].severity == "warning"
    assert snapshot.attention[0].occurred_at == newer.updated_at
    assert snapshot.attention[0].action_url == "/jobs"
    assert snapshot.attention[1].kind == "publication"
    assert snapshot.attention[1].severity == "error"
    assert "hunter2" not in snapshot.attention[0].title
    assert "unsafe-token" not in snapshot.attention[1].title
    assert "[REDACTED]" in snapshot.attention[0].title
    assert "[REDACTED]" in snapshot.attention[1].title
    assert session.get_calls == [(AutomationControl, "global")]
    assert "GROUP BY workflow_jobs.status" in session.execute_sql[0]
    attention_sql = next(sql for sql in session.scalar_sql if "FROM workflow_jobs" in sql)
    assert "workflow_jobs.status IN ('failed', 'needs_review')" in attention_sql
    assert "ORDER BY workflow_jobs.updated_at DESC, workflow_jobs.id DESC" in attention_sql
    assert "LIMIT 100" in attention_sql


@pytest.mark.asyncio
async def test_snapshot_merges_durable_attention_newest_first_without_duplicates_or_live_checks():
    source = SimpleNamespace(
        id=SOURCE_ID,
        name="Wire token=source-secret",
        active=True,
        health_status="broken",
        failure_count=3,
        last_error_message="Authorization: Bearer source-token",
        last_error_type="fetch_failed",
        last_failure_at=NOW - timedelta(seconds=2),
        updated_at=NOW - timedelta(minutes=1),
    )
    destination = SimpleNamespace(
        id=DESTINATION_ID,
        name="Newsroom",
        enabled=True,
        health_status="unknown",
        last_health_check_at=NOW - timedelta(seconds=3),
        updated_at=NOW - timedelta(minutes=1),
    )
    paused_route = SimpleNamespace(
        id=ROUTE_ID,
        name="Morning wire",
        enabled=True,
        paused_at=NOW - timedelta(seconds=4),
    )
    newer_problem_dispatch = SimpleNamespace(
        id=UUID("88888888-8888-4888-8888-888888888888"),
        route_id=ROUTE_ID,
        status="failed",
        error_code="telegram_failed",
        error_message="password=dispatch-secret",
        updated_at=NOW - timedelta(seconds=1),
    )
    research_run = SimpleNamespace(
        id=RESEARCH_RUN_ID,
        status="needs_review",
        created_at=NOW - timedelta(minutes=1),
        started_at=NOW - timedelta(seconds=12),
        finished_at=NOW - timedelta(seconds=4),
    )
    research_attempt = SimpleNamespace(
        status="needs_review",
        error_message="provider api_key=research-secret",
        error_code="citation_gap",
        error_class="needs_review",
        started_at=NOW - timedelta(seconds=12),
        finished_at=NOW - timedelta(seconds=5),
    )
    generation_run = SimpleNamespace(
        id=GENERATION_RUN_ID,
        status="failed",
        error_message="Bearer generation-secret",
        error_code="invalid_output",
        error_class="permanent",
        created_at=NOW - timedelta(seconds=15),
        started_at=NOW - timedelta(seconds=10),
        finished_at=NOW - timedelta(seconds=6),
    )
    publish_job = SimpleNamespace(
        id=PUBLISH_JOB_ID,
        workflow_job_id=None,
        status="reconciliation_required",
        updated_at=NOW - timedelta(seconds=7),
    )
    stale_publication = SimpleNamespace(
        id=UUID("99999999-9999-4999-8999-999999999999"),
        publish_job_id=PUBLISH_JOB_ID,
        reconciliation_status="required",
        published_at=NOW - timedelta(seconds=8),
    )
    represented_workflow_job = _job(
        RESEARCH_JOB_ID,
        job_type="telegram.publish",
        status=JobStatus.FAILED,
        updated_at=NOW - timedelta(seconds=9),
        error_message="publish failed",
    )
    newer_linked_publish_job = SimpleNamespace(
        id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        workflow_job_id=RESEARCH_JOB_ID,
        status="attention",
        updated_at=NOW - timedelta(milliseconds=500),
    )
    session = FakeSession(
        attention_jobs=[represented_workflow_job],
        sources=[source],
        destinations=[destination],
        routes=[paused_route],
        dispatches=[newer_problem_dispatch],
        research_rows=[(research_run, research_attempt)],
        generation_runs=[generation_run],
        publish_jobs=[newer_linked_publish_job, publish_job],
        publication_rows=[(stale_publication, None)],
    )

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids="",
    ).snapshot()

    assert [(item.kind, item.occurred_at) for item in snapshot.attention] == [
        ("publication", newer_linked_publish_job.updated_at),
        ("route", newer_problem_dispatch.updated_at),
        ("source", source.last_failure_at),
        ("destination", destination.last_health_check_at),
        ("research", research_run.finished_at),
        ("generation", generation_run.finished_at),
        ("publication", publish_job.updated_at),
        ("publication", represented_workflow_job.updated_at),
    ]
    assert [item.id for item in snapshot.attention].count(f"route:{ROUTE_ID}") == 1
    assert [item.id for item in snapshot.attention].count(f"publication:{PUBLISH_JOB_ID}") == 1
    assert "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" in str(snapshot.model_dump())
    assert snapshot.attention[0].action_url == "/jobs"
    assert snapshot.attention[1].action_url == f"/automations/{ROUTE_ID}"
    assert snapshot.attention[2].action_url == "/sources"
    assert snapshot.attention[3].action_url == "/automations"
    assert snapshot.attention[4].action_url == "/inbox"
    assert snapshot.attention[5].action_url == "/drafts"
    assert snapshot.attention[6].action_url == "/jobs"
    serialized = str(snapshot.model_dump())
    for secret in ("source-secret", "source-token", "dispatch-secret", "research-secret", "generation-secret"):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") >= 4

    scalar_sql = "\n".join(session.scalar_sql)
    execute_sql = "\n".join(session.execute_sql)
    assert "sources.active IS true" in scalar_sql
    assert "sources.health_status != 'healthy'" in scalar_sql
    assert "destinations.enabled IS true" in scalar_sql
    assert "destinations.health_status != 'healthy'" in scalar_sql
    assert "automation_routes.paused_at IS NOT NULL" in scalar_sql
    assert "automation_dispatches.status IN ('failed', 'needs_review')" in scalar_sql
    assert "SELECT automation_dispatches.id" in scalar_sql
    assert "automation_dispatches.route_id = automation_dispatches_1.route_id" in scalar_sql
    assert "generation_runs.status IN ('failed', 'needs_review')" in scalar_sql
    assert "publish_jobs.status IN ('attention', 'reconciliation_required')" in scalar_sql
    assert "research_runs.status IN ('failed', 'needs_review')" in execute_sql
    assert "SELECT max(research_attempts.attempt_number)" in execute_sql
    assert "publications.reconciliation_status != 'confirmed'" in execute_sql
    assert "ORDER BY" in scalar_sql
    assert "ORDER BY" in execute_sql


@pytest.mark.asyncio
async def test_snapshot_suppresses_older_linked_records_but_keeps_newer_durable_state():
    linked_jobs = [
        _job(
            UUID("10000000-0000-4000-8000-000000000001"),
            job_type="ingest.collect",
            status=JobStatus.FAILED,
            updated_at=NOW - timedelta(seconds=1),
            error_message="collection failed",
            payload={"source_ids": [str(SOURCE_ID)]},
        ),
        _job(
            UUID("10000000-0000-4000-8000-000000000002"),
            job_type="telegram.destination.check",
            status=JobStatus.FAILED,
            updated_at=NOW - timedelta(seconds=2),
            error_message="destination check failed",
            payload={"destination_id": str(DESTINATION_ID)},
        ),
        _job(
            UUID("10000000-0000-4000-8000-000000000003"),
            job_type="telegram.route.process",
            status=JobStatus.NEEDS_REVIEW,
            updated_at=NOW - timedelta(seconds=3),
            error_message="route needs review",
            payload={"route_id": str(ROUTE_ID)},
        ),
        _job(
            UUID("10000000-0000-4000-8000-000000000004"),
            job_type="research_story",
            status=JobStatus.FAILED,
            updated_at=NOW - timedelta(seconds=4),
            error_message="research failed",
            payload={"run_id": str(RESEARCH_RUN_ID)},
        ),
        _job(
            UUID("10000000-0000-4000-8000-000000000005"),
            job_type="build_export",
            status=JobStatus.FAILED,
            updated_at=NOW - timedelta(seconds=5),
            error_message="generation failed",
        ),
    ]
    session = FakeSession(
        attention_jobs=linked_jobs,
        sources=[
            SimpleNamespace(
                id=SOURCE_ID,
                name="Wire",
                health_status="broken",
                last_error_message="new source failure",
                last_error_type="fetch_failed",
                last_failure_at=NOW,
                updated_at=NOW,
            )
        ],
        destinations=[
            SimpleNamespace(
                id=DESTINATION_ID,
                name="Newsroom",
                health_status="unhealthy",
                last_health_check_at=NOW - timedelta(minutes=1),
                updated_at=NOW - timedelta(minutes=1),
            )
        ],
        routes=[
            SimpleNamespace(
                id=ROUTE_ID,
                name="Morning wire",
                paused_at=NOW - timedelta(minutes=1),
            )
        ],
        research_rows=[
            (
                SimpleNamespace(
                    id=RESEARCH_RUN_ID,
                    status="failed",
                    created_at=NOW - timedelta(minutes=2),
                    started_at=NOW - timedelta(minutes=2),
                    finished_at=NOW - timedelta(minutes=1),
                ),
                None,
            )
        ],
        generation_runs=[
            SimpleNamespace(
                id=GENERATION_RUN_ID,
                status="failed",
                error_message="older generation failure",
                error_code="generation_failed",
                error_class="permanent",
                created_at=NOW - timedelta(minutes=2),
                started_at=NOW - timedelta(minutes=2),
                finished_at=NOW - timedelta(minutes=1),
                request_payload={"execution": {"workflow_job_id": str(linked_jobs[-1].id)}},
            )
        ],
    )

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids="",
    ).snapshot()

    assert [item.id for item in snapshot.attention] == [
        f"source:{SOURCE_ID}",
        *(str(job.id) for job in linked_jobs),
    ]
    assert not any(
        item.id.startswith(("destination:", "route:", "research:", "generation:")) for item in snapshot.attention
    )


@pytest.mark.asyncio
async def test_snapshot_calls_existing_runtime_heartbeat_service_contract(monkeypatch):
    session = FakeSession()
    calls = []

    async def fake_list_recent(self, *, limit=100):
        calls.append((self.session, limit))
        return [_heartbeat("persisted-only", NOW)]

    monkeypatch.setattr(RuntimeHeartbeatService, "list_recent", fake_list_recent)

    snapshot = await OperationsDiagnostics(
        session,
        clock=FrozenClock(),
        expected_runtime_component_ids="",
    ).snapshot()

    assert calls == [(session, 10_000)]
    assert set(snapshot.components) == {"persisted-only"}


def _heartbeat(
    component_id: str,
    observed_at: datetime,
    *,
    component_type: str = "worker",
    capabilities: list[str] | None = None,
):
    return SimpleNamespace(
        component_id=component_id,
        component_type=component_type,
        capabilities=capabilities or ["source", "generation"],
        observed_at=observed_at,
        runtime_metadata={
            "nested": {"api_key": "should-never-leave-storage"},
            "job_types": ["ingest.collect"],
        },
    )


def _job(job_id, *, job_type, status, updated_at, error_message, payload=None, result=None):
    return SimpleNamespace(
        id=job_id,
        job_type=job_type,
        status=status,
        updated_at=updated_at,
        error_code=None,
        error_message=error_message,
        payload=payload or {},
        result=result or {},
    )
