# Release 3 Editorial Research and Generation Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn captured source material into grouped, immutable, citation-backed stories that can be manually enriched, researched through Codex or a bounded OpenRouter/DuckDuckGo loop, generated into versioned content packs, edited, and approved at an exact revision.

**Architecture:** Preserve source items as immutable evidence, derive deterministic completeness reports, and run every fetch, research, and generation action as a durable `WorkflowJob`. Research backends return one application-owned `ResearchBrief`; canonical generation consumes only persisted evidence and produces immutable `StoryRevision` and `PlatformVariantRevision` records whose citations resolve before approval.

**Tech Stack:** Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, `httpx`, `ddgs`, Codex CLI, OpenRouter Chat Completions, pytest, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright.

## Global Constraints

- Releases 0, 1, and 2 are complete and their full gates pass before this plan begins.
- Product mode remains local and single operator; no accounts, teams, RBAC, billing, or public deployment are introduced.
- Original `ContentItem`, `SourceItem`, `RawPayload`, Telegram message, and media records are never overwritten by research or generation.
- Research modes are exactly `off`, `manual`, and `auto_if_incomplete`; automatic research runs only after the deterministic completeness evaluator returns `complete=false`.
- OpenRouter is the normal HTTP backend; Codex CLI is an optional local operator backend; deterministic fake backends remain mandatory for tests.
- Codex executes in an isolated temporary directory with `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`, strict JSON Schema output, bounded time, and no publishing or database secrets.
- OpenRouter research may search only through the application-owned DuckDuckGo/fetch loop and may cite only URLs successfully fetched and snapshotted by NewsCraft.
- All generated facts, disagreements, and platform claims carry claim-level evidence references before approval.
- Every edit and regeneration creates a new immutable revision. Approval binds to one revision ID and content hash; a later edit is unapproved.
- API requests never perform URL fetches, Codex execution, DuckDuckGo searches, or model calls inline; they persist input, enqueue a job transactionally, and return its identifier.
- Time is stored in UTC; the UI renders it in the configured operator timezone, default `Asia/Tehran`.
- No AI process receives Telegram tokens, MTProto sessions, `DATABASE_URL`, or arbitrary shell access.
- Every task ends in a focused commit. Never stage `.superpowers/`, local media, credentials, `refactor.txt`, or the superseded 2026-07-07 audit plan.

## Dependencies and Execution Boundary

Required Release 1 contracts:

```python
from app.generation.providers.base import GenerationProvider, GenerationProviderRequest, GenerationProviderResult
from app.generation.providers.registry import ProviderRegistry
from app.jobs.models import WorkflowEvent, WorkflowJob
from app.jobs.registry import JobContext, JobHandler, JobHandlerRegistry, build_default_registry
from app.jobs.repository import EnqueueJobResult, JobRepository
from app.jobs.schemas import JobAcceptedOut
from app.jobs.types import JobErrorClass, JobOrigin, JobStatus
```

Required Release 1/2 tables and ORM names are `Story`, `StoryEvidenceSnapshot`, `StoryRevision`, `StoryEvidenceLink`, `BrandProfile`, `PromptTemplateVersion`, `ResearchRun`, `ResearchAttempt`, `ResearchSource`, `GenerationRun`, `GenerationAttempt`, `ContentPack`, `PlatformVariant`, `PlatformVariantRevision`, `WorkflowJob`, and `WorkflowEvent`. Required Release 2 publication code continues to consume approved `PlatformVariantRevision` IDs and is not rewritten here.

At the start, run:

```bash
git status --short
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
cd ../frontend
npm run test
npm run typecheck
cd ..
```

Expected: a clean release boundary, all backend and frontend tests pass, Ruff reports `All checks passed!`, and TypeScript exits 0. Stop if any expected Release 1/2 import or table is absent; repair the earlier release rather than creating a second competing abstraction.

This release explicitly excludes Instagram, X, and blog-specific package rendering and export; Release 4 owns those. It also excludes remote Telegram message edits, live Instagram/X/CMS connectors, AI-generated media, and unbounded research/backfill.

## File and Responsibility Map

### Backend

- `app/stories/grouping.py`: deterministic related-item scoring and story assignment.
- `app/stories/evidence.py`: immutable snapshot creation and content hashing.
- `app/stories/repository.py`: story, snapshot, revision, and evidence-link persistence.
- `app/stories/manual_intake.py`: normalized URL/text intake jobs.
- `app/stories/schemas.py`: story detail, evidence, canonical revision, and manual intake API contracts.
- `app/research/schemas.py`: completeness, queries, fetched sources, claims, citations, and research brief contracts.
- `app/research/completeness.py`: deterministic evidence sufficiency evaluation.
- `app/research/citations.py`: citation resolution and integrity validation.
- `app/research/codex_adapter.py`: constrained Codex subprocess adapter.
- `app/research/duckduckgo.py`: bounded search client.
- `app/research/safe_fetch.py`: public-network-only fetch and article extraction adapter.
- `app/research/openrouter_loop.py`: application-controlled search/fetch/model loop.
- `app/research/fake.py`: deterministic research backend.
- `app/research/service.py`: research run lifecycle and persistence.
- `app/research/handlers.py`: durable `research_story` handler registered with `JobHandlerRegistry`.
- `app/generation/canonical.py`: evidence-to-canonical-story generation contract.
- `app/generation/editorial_service.py`: content pack creation, regeneration, edit, and approval invariants.
- `app/generation/handlers.py`: durable canonical/pack generation handlers.
- `app/api/stories.py`: story/manual/research endpoints.
- `app/api/content_packs.py`: pack, revision, edit, generation, and approval endpoints.

### Frontend

- `lib/editorial-types.ts`: story, evidence, research, pack, revision, and editor types.
- `lib/editorial-api.ts`: typed editorial API calls.
- `lib/query-keys.ts`: story, research, pack, and revision cache keys.
- `app/inbox/page.tsx`: grouped story inbox and manual intake entrypoint.
- `app/drafts/page.tsx`: content pack list and generation states.
- `app/drafts/[packId]/page.tsx`: pack revision history.
- `app/review/[variantId]/page.tsx`: evidence/editor/preview approval workspace.
- `components/editorial/story-inbox.tsx`: grouping, selection, shortlist, reject, and bulk actions.
- `components/editorial/manual-intake-dialog.tsx`: URL/text intake form.
- `components/editorial/research-panel.tsx`: completeness, manual/deep research controls, attempts, and results.
- `components/editorial/evidence-panel.tsx`: immutable evidence and citation navigation.
- `components/editorial/variant-editor.tsx`: revision-aware editor and conflict handling.
- `components/editorial/revision-timeline.tsx`: immutable revisions, authorship, validation, and approval history.

---

### Task 1: Group related source items and capture immutable evidence

**Files:**
- Create: `backend/app/stories/__init__.py`
- Create: `backend/app/stories/grouping.py`
- Create: `backend/app/stories/evidence.py`
- Create: `backend/app/stories/repository.py`
- Create: `backend/app/stories/schemas.py`
- Create: `backend/tests/stories/test_grouping.py`
- Create: `backend/tests/stories/test_evidence.py`
- Create: `backend/tests/stories/test_repository.py`

**Interfaces:**
- Consumes: `ContentItem`, `SourceItem`, `RawPayload`, and Release 1 `Story`/`StoryEvidenceSnapshot` tables.
- Produces: `GroupingInput`, `GroupingDecision`, `EvidenceInput`, `capture_evidence()`, and `StoryRepository.group_content_items()`.

- [ ] **Step 1: Write failing grouping tests**

Create tests with these exact cases:

```python
from datetime import UTC, datetime, timedelta

from app.stories.grouping import GroupingInput, decide_group


def item(item_id: str, title: str, url: str, hours: int = 0) -> GroupingInput:
    return GroupingInput(
        content_item_id=item_id,
        title=title,
        canonical_url=url,
        published_at=datetime(2026, 7, 11, 8, tzinfo=UTC) + timedelta(hours=hours),
    )


def test_same_canonical_url_groups_even_when_titles_differ():
    result = decide_group(
        item("a", "OpenAI ships a new agent", "https://example.com/news?id=7"),
        item("b", "New coding agent arrives", "https://example.com/news?id=7&utm_source=rss"),
    )
    assert result.grouped is True
    assert result.reason == "canonical_url"
    assert result.score == 1.0


def test_related_titles_group_inside_72_hour_window():
    result = decide_group(
        item("a", "OpenAI releases new coding agent for developers", "https://a.example/story"),
        item("b", "OpenAI releases a coding agent for software developers", "https://b.example/story", hours=8),
    )
    assert result.grouped is True
    assert result.reason == "title_similarity"
    assert result.score >= 0.72


def test_old_or_weakly_related_items_do_not_merge():
    result = decide_group(
        item("a", "OpenAI releases new coding agent", "https://a.example/story"),
        item("b", "Global chip sales rise", "https://b.example/story", hours=96),
    )
    assert result.grouped is False
    assert result.reason == "insufficient_similarity"
```

- [ ] **Step 2: Run the grouping tests and verify failure**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_grouping.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.stories.grouping'`.

- [ ] **Step 3: Implement deterministic grouping**

Create these public contracts and rules:

```python
@dataclass(frozen=True, slots=True)
class GroupingInput:
    content_item_id: str
    title: str
    canonical_url: str | None
    published_at: datetime


@dataclass(frozen=True, slots=True)
class GroupingDecision:
    grouped: bool
    score: float
    reason: Literal["canonical_url", "title_similarity", "insufficient_similarity"]


def decide_group(left: GroupingInput, right: GroupingInput) -> GroupingDecision:
    left_url = normalize_url(left.canonical_url) if left.canonical_url else None
    right_url = normalize_url(right.canonical_url) if right.canonical_url else None
    if left_url and left_url == right_url:
        return GroupingDecision(True, 1.0, "canonical_url")
    hours = abs((left.published_at - right.published_at).total_seconds()) / 3600
    score = token_jaccard(normalize_title(left.title), normalize_title(right.title))
    if hours <= 72 and score >= 0.72:
        return GroupingDecision(True, score, "title_similarity")
    return GroupingDecision(False, score, "insufficient_similarity")
```

`normalize_title()` must Unicode-normalize with NFKC, case-fold, remove punctuation, and discard tokens shorter than two characters. `token_jaccard()` returns `0.0` when both token sets are empty.

- [ ] **Step 4: Write failing evidence immutability and repository tests**

Use the PostgreSQL test session fixture established in Release 1 and assert:

```python
async def test_group_content_items_reuses_story_and_captures_one_snapshot_per_hash(db_session, content_factory):
    first = await content_factory(title="Agent launch", canonical_url="https://a.example/agent", content_text="Evidence A")
    second = await content_factory(title="Agent launch details", canonical_url="https://b.example/agent", content_text="Evidence B")
    repository = StoryRepository(db_session)

    story = await repository.group_content_items([first.id, second.id])
    replay = await repository.group_content_items([first.id, second.id])

    assert replay.id == story.id
    snapshots = await repository.list_evidence(story.id)
    assert [snapshot.body for snapshot in snapshots] == ["Evidence A", "Evidence B"]
    assert len({snapshot.content_hash for snapshot in snapshots}) == 2


def test_capture_evidence_hashes_all_generation_relevant_fields():
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id="item-1",
            title="Title",
            body="Body",
            source_url="https://example.com/source",
            author="Reporter",
            published_at=datetime(2026, 7, 11, tzinfo=UTC),
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    changed = capture_evidence(replace(evidence.input, body="Changed body"))
    assert evidence.content_hash != changed.content_hash
```

- [ ] **Step 5: Implement immutable evidence capture and repository persistence**

Use canonical JSON with sorted keys and UTF-8 SHA-256:

```python
def capture_evidence(value: EvidenceInput) -> CapturedEvidence:
    payload = {
        "author": value.author,
        "body": value.body,
        "captured_at": value.captured_at.isoformat(),
        "content_item_id": value.content_item_id,
        "published_at": value.published_at.isoformat() if value.published_at else None,
        "source_url": value.source_url,
        "title": value.title,
    }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return CapturedEvidence(input=value, content_hash=hashlib.sha256(encoded).hexdigest())
```

`StoryRepository.group_content_items(content_item_ids: Sequence[UUID]) -> Story` must lock matching story assignments, reuse an existing story when one candidate groups, create one story otherwise, and insert a snapshot under a unique `(story_id, content_item_id, content_hash)` constraint. Never update a prior snapshot.

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_grouping.py tests/stories/test_evidence.py tests/stories/test_repository.py -q
.venv/bin/ruff check app/stories tests/stories
git diff --check
cd ..
git add backend/app/stories backend/tests/stories
git commit -m "feat: group stories with immutable evidence"
```

Expected: all focused tests pass, Ruff passes, and the commit contains only story grouping/evidence files.

---

### Task 2: Evaluate completeness and enforce claim-level citation integrity

**Files:**
- Create: `backend/app/research/__init__.py`
- Create: `backend/app/research/schemas.py`
- Create: `backend/app/research/completeness.py`
- Create: `backend/app/research/citations.py`
- Create: `backend/tests/research/test_completeness.py`
- Create: `backend/tests/research/test_citations.py`

**Interfaces:**
- Consumes: immutable `StoryEvidenceSnapshot` rows from Task 1.
- Produces: `CompletenessReport`, `ResearchBrief`, `Claim`, `CitationRef`, `evaluate_completeness()`, and `validate_citations()`.

- [ ] **Step 1: Write failing completeness tests**

```python
def test_completeness_reports_every_deterministic_gap():
    report = evaluate_completeness(
        [evidence(source="Example Blog", body="short", primary=False)],
        contradictions=["Launch date differs"],
    )
    assert report.complete is False
    assert report.score == 10
    assert report.reasons == [
        "fewer_than_two_independent_sources",
        "insufficient_body_text",
        "missing_primary_evidence",
        "unresolved_contradictions",
    ]


def test_completeness_accepts_two_sources_primary_evidence_and_resolved_conflicts():
    report = evaluate_completeness(
        [
            evidence(source="Official release", body="a" * 500, primary=True),
            evidence(source="Independent report", body="b" * 500, primary=False),
        ],
        contradictions=[],
    )
    assert report.complete is True
    assert report.score == 100
    assert report.reasons == []
```

The score starts at 100 and subtracts 30, 25, 20, and 15 respectively for the four reason codes; it is clamped to `0..100`. Independent sources are counted by normalized registrable host or source identity. Total non-whitespace body text must be at least 800 characters.

- [ ] **Step 2: Define the strict shared schemas**

Implement these exact contracts:

```python
CompletenessReason = Literal[
    "fewer_than_two_independent_sources",
    "insufficient_body_text",
    "missing_primary_evidence",
    "unresolved_contradictions",
]


class CompletenessReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    complete: bool
    score: int = Field(ge=0, le=100)
    reasons: list[CompletenessReason]
    independent_source_count: int = Field(ge=0)
    body_character_count: int = Field(ge=0)
    has_primary_evidence: bool


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_snapshot_id: UUID
    source_url: HttpUrl
    locator: str = Field(min_length=1, max_length=240)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    citations: list[CitationRef] = Field(min_length=1)


class ResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    verified_facts: list[Claim]
    disagreements: list[Claim]
    missing_information: list[str]
    suggested_angles: list[str]
    discovered_source_ids: list[UUID]
```

- [ ] **Step 3: Run tests to verify missing implementations fail**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_completeness.py tests/research/test_citations.py -q
```

Expected: tests fail because completeness and citation functions do not yet exist.

- [ ] **Step 4: Implement completeness and citation validation**

`validate_citations()` must return normalized citations or raise typed errors:

```python
class CitationIntegrityError(ValueError):
    pass


def validate_citations(claims: Sequence[Claim], snapshots: Mapping[UUID, EvidenceRecord]) -> list[Claim]:
    for claim in claims:
        if not claim.citations:
            raise CitationIntegrityError("claim has no citations")
        for citation in claim.citations:
            snapshot = snapshots.get(citation.evidence_snapshot_id)
            if snapshot is None:
                raise CitationIntegrityError(f"unknown evidence snapshot: {citation.evidence_snapshot_id}")
            if normalize_url(str(citation.source_url)) != normalize_url(snapshot.source_url):
                raise CitationIntegrityError("citation URL does not match evidence snapshot")
            excerpt = resolve_locator(snapshot.body, citation.locator)
            if hashlib.sha256(excerpt.encode()).hexdigest() != citation.excerpt_sha256:
                raise CitationIntegrityError("citation excerpt hash does not match evidence")
    return list(claims)
```

Use locators of the exact form `chars:<start>-<end>`, with `0 <= start < end <= len(body)`. Do not accept free-form quotations as evidence.

- [ ] **Step 5: Run focused tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_completeness.py tests/research/test_citations.py -q
.venv/bin/ruff check app/research tests/research
git diff --check
cd ..
git add backend/app/research backend/tests/research
git commit -m "feat: score evidence completeness and citations"
```

Expected: focused tests and Ruff pass.

---

### Task 3: Accept manual URLs and text through durable intake jobs

**Files:**
- Create: `backend/app/stories/manual_intake.py`
- Create: `backend/app/stories/handlers.py`
- Create: `backend/app/api/stories.py`
- Modify: `backend/app/stories/schemas.py`
- Modify: `backend/app/jobs/models.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/stories/test_manual_intake.py`
- Create: `backend/tests/api/test_story_routes.py`

**Interfaces:**
- Consumes: Release 1 `JobRepository.enqueue_job()`, `JobContext`, current `extract_article()`, and Task 1 `StoryRepository`.
- Produces: `ManualUrlInput`, `ManualTextInput`, `ManualIntakeRequest`, `create_manual_intake()`, job kind `manual_intake`, and `POST /stories/manual`.

- [ ] **Step 1: Write failing API and handler tests**

```python
async def test_manual_url_endpoint_enqueues_without_fetching(client, monkeypatch):
    fetch_called = False

    async def forbidden_fetch(*args, **kwargs):
        nonlocal fetch_called
        fetch_called = True
        raise AssertionError("API route performed network I/O")

    monkeypatch.setattr("app.discovery.article_extractor.ArticleExtractor.extract", forbidden_fetch)
    response = await client.post(
        "/stories/manual",
        json={"kind": "url", "url": "https://example.com/report", "title": "Optional title"},
    )
    assert response.status_code == 202
    assert response.json()["job_kind"] == "manual_intake"
    assert fetch_called is False


async def test_manual_text_job_creates_story_and_evidence(db_session, run_job):
    result = await JobRepository(db_session).enqueue_job(
        job_type="manual_intake",
        payload={
            "kind": "text",
            "title": "Operator note",
            "text": "Confirmed source material supplied by the operator.",
            "source_label": "Operator interview",
            "source_url": None,
        },
        idempotency_key="manual:text:case-1",
        origin="manual",
    )
    await run_job(result.job.id)
    story = await StoryRepository(db_session).get_for_job(result.job.id)
    assert story.title == "Operator note"
    assert (await StoryRepository(db_session).list_evidence(story.id))[0].body.startswith("Confirmed source")
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_manual_intake.py tests/api/test_story_routes.py -q
```

Expected: tests fail because the request schema, route, and handler are absent.

- [ ] **Step 3: Add exact discriminated request contracts and API behavior**

```python
class ManualUrlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["url"]
    url: HttpUrl
    title: str | None = Field(default=None, max_length=300)


class ManualTextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["text"]
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=20, max_length=200_000)
    source_label: str = Field(min_length=1, max_length=160)
    source_url: HttpUrl | None = None


ManualIntakeRequest = Annotated[ManualUrlInput | ManualTextInput, Field(discriminator="kind")]
```

The route sets `job_payload = payload.model_dump(mode="json")`, computes `payload_hash = hashlib.sha256(json.dumps(job_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()`, and calls `JobRepository(session).enqueue_job(job_type="manual_intake", payload=job_payload, idempotency_key=f"manual_intake:{payload_hash}", origin="manual")`. It commits and returns `JobAcceptedOut(job_id=result.job.id, status=result.job.status, deduplicated=not result.created)` with HTTP 202.

- [ ] **Step 4: Implement URL/text handlers**

Use this dispatch contract:

```python
async def handle_manual_intake(job: WorkflowJob, context: JobContext) -> dict[str, object]:
    request = TypeAdapter(ManualIntakeRequest).validate_python(job.payload)
    if request.kind == "url":
        await context.session.commit()
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            extracted = await extract_article(client, manual_discovery_item(request))
        evidence = EvidenceInput.from_extracted_article(extracted, title_override=request.title)
    else:
        evidence = EvidenceInput.from_operator_text(request)
    story = await StoryRepository(context.session).create_from_manual_evidence(evidence, job.id)
    context.session.add(WorkflowEvent.for_job(job, "manual_intake.completed", subject_id=story.id))
    return {"story_id": str(story.id)}
```

For URL intake, `manual_discovery_item()` builds a `DiscoveryItem` with the submitted URL/title and no invented publisher fields. Persist the HTTP response as `RawPayload`, normalize into `ContentItem`/`SourceItem`, then snapshot it. A fetch/extraction failure raises the Release 1 typed job error with `JobErrorClass.NEEDS_REVIEW`; no empty story is created. Text intake records provenance type `operator_text` and never pretends it was fetched. Register with `registry.register("manual_intake", handle_manual_intake)` inside `build_default_registry()`.

- [ ] **Step 5: Run focused and regression tests, then commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_manual_intake.py tests/api/test_story_routes.py tests/test_article_extractor.py -q
.venv/bin/ruff check app/stories app/api/stories.py tests/stories tests/api/test_story_routes.py
git diff --check
cd ..
git add backend/app/stories backend/app/api/stories.py backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/stories backend/tests/api/test_story_routes.py
git commit -m "feat: add durable manual story intake"
```

Expected: focused and article extraction regression tests pass.

---

### Task 4: Define one research backend contract and deterministic fake

**Files:**
- Create: `backend/app/research/base.py`
- Create: `backend/app/research/fake.py`
- Create: `backend/app/research/prompts.py`
- Create: `backend/tests/research/test_provider_contract.py`
- Create: `backend/tests/fixtures/research_brief.json`

**Interfaces:**
- Consumes: Task 2 `ResearchBrief` and immutable evidence records.
- Produces: `ResearchRequest`, `ResearchResult`, `ResearchBackend`, `FakeResearchBackend`, and `build_research_prompt()`.

- [ ] **Step 1: Write a parameterized provider contract test**

```python
@pytest.mark.parametrize("backend_factory", [FakeResearchBackend])
async def test_research_backend_returns_validated_brief_with_resolved_model(backend_factory, evidence_records):
    request = ResearchRequest(
        run_id=uuid4(),
        story_id=uuid4(),
        mode="manual",
        query_hint="Verify the announced release date",
        evidence=evidence_records,
        max_elapsed_seconds=120,
    )
    result = await backend_factory.from_fixture("tests/fixtures/research_brief.json").research(request)
    assert result.backend == "fake"
    assert result.requested_model == "fixture-v1"
    assert result.resolved_model == "fixture-v1"
    assert result.brief.verified_facts[0].citations
    assert result.elapsed_ms >= 0
```

- [ ] **Step 2: Run the test and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_provider_contract.py -q
```

Expected: import failure for `app.research.base`.

- [ ] **Step 3: Implement the exact protocol and fake**

```python
class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    story_id: UUID
    mode: Literal["manual", "auto_if_incomplete"]
    depth: Literal["standard", "deep"] = "standard"
    query_hint: str | None = Field(default=None, max_length=500)
    evidence: list[EvidenceRecord] = Field(min_length=1)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["fake", "codex", "openrouter"]
    requested_model: str
    resolved_model: str
    brief: ResearchBrief
    usage: dict[str, int | float | str]
    elapsed_ms: int = Field(ge=0)
    sanitized_events: list[dict[str, object]]


class ResearchBackend(Protocol):
    name: str

    async def research(self, request: ResearchRequest) -> ResearchResult:
        raise NotImplementedError
```

The fake reads the checked-in fixture, validates it with `ResearchBrief.model_validate_json()`, and never performs network or subprocess I/O.

- [ ] **Step 4: Run the contract test and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_provider_contract.py -q
.venv/bin/ruff check app/research tests/research
git diff --check
cd ..
git add backend/app/research backend/tests/research backend/tests/fixtures/research_brief.json
git commit -m "feat: define research backend contract"
```

Expected: provider contract test passes.

---

### Task 5: Add the constrained Codex CLI research adapter

**Files:**
- Create: `backend/app/research/codex_adapter.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/research/test_codex_adapter.py`

**Interfaces:**
- Consumes: Task 4 `ResearchBackend`, `ResearchRequest`, `ResearchResult`, `build_research_prompt()`, and the locally installed `codex` executable.
- Produces: `CodexResearchBackend` and `build_codex_environment()`.

- [ ] **Step 1: Write failing command, secret isolation, schema, and timeout tests**

```python
async def test_codex_uses_isolated_reproducible_command(fake_process, request):
    backend = CodexResearchBackend(process_runner=fake_process, executable="codex")
    await backend.research(request)
    assert fake_process.argv[:4] == ["codex", "exec", "--ephemeral", "--json"]
    assert "--output-schema" in fake_process.argv
    assert ["--sandbox", "read-only"] == fake_process.argv[fake_process.argv.index("--sandbox"):][:2]
    assert "--ignore-user-config" in fake_process.argv
    assert fake_process.cwd != Path.cwd()


def test_codex_environment_excludes_application_and_publishing_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DESTINATION_NEWS_TOKEN", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "codex-auth")
    env = build_codex_environment(os.environ)
    assert env["OPENAI_API_KEY"] == "codex-auth"
    assert "TELEGRAM_DESTINATION_NEWS_TOKEN" not in env
    assert "DATABASE_URL" not in env
    assert "OPENROUTER_API_KEY" not in env


async def test_codex_timeout_terminates_process_and_returns_retryable_error(hanging_process, request):
    backend = CodexResearchBackend(process_runner=hanging_process, timeout_seconds=1)
    with pytest.raises(ResearchBackendError, match="codex timed out") as error:
        await backend.research(request)
    assert error.value.classification == "retryable"
    assert hanging_process.terminated is True
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_codex_adapter.py -q
```

Expected: import failure for `CodexResearchBackend`.

- [ ] **Step 3: Implement the constrained process boundary**

The adapter must construct this exact command, with generated absolute paths:

```python
argv = [
    executable,
    "exec",
    "--ephemeral",
    "--json",
    "--output-schema",
    str(schema_path),
    "--sandbox",
    "read-only",
    "--ignore-user-config",
    "-C",
    str(work_dir),
    "-o",
    str(result_path),
    "-",
]
```

Write `ResearchBrief.model_json_schema()` to `schema_path`, send only `build_research_prompt(request)` on stdin, parse `result_path` with `ResearchBrief.model_validate_json()`, and capture `codex --version`, exit code, elapsed milliseconds, and redacted JSONL event summaries. Environment keys are limited to `PATH`, `HOME`, `CODEX_HOME`, `OPENAI_API_KEY`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `LANG`, and `LC_ALL` when present. Kill and await the process on timeout. Cap combined stdout/stderr capture at 1 MiB.

- [ ] **Step 4: Run focused tests, an opt-in local contract check, and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_codex_adapter.py tests/research/test_provider_contract.py -q
.venv/bin/ruff check app/research/codex_adapter.py tests/research/test_codex_adapter.py
if command -v codex >/dev/null; then codex --version; fi
git diff --check
cd ..
git add backend/app/research/codex_adapter.py backend/app/core/config.py backend/tests/research/test_codex_adapter.py
git commit -m "feat: add constrained Codex research adapter"
```

Expected: deterministic tests pass. The version command may report a local Codex version but performs no research and uses no credentials.

---

### Task 6: Add bounded DuckDuckGo search and the OpenRouter research loop

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/research/duckduckgo.py`
- Create: `backend/app/research/safe_fetch.py`
- Create: `backend/app/research/openrouter_loop.py`
- Create: `backend/tests/research/test_duckduckgo.py`
- Create: `backend/tests/research/test_safe_fetch.py`
- Create: `backend/tests/research/test_openrouter_loop.py`

**Interfaces:**
- Consumes: Task 4 research contracts, the Release 2 OpenRouter HTTP transport, and current article extraction.
- Produces: `SearchBudget`, `SearchResult`, `DuckDuckGoSearchClient`, `SafeArticleFetcher`, `OpenRouterResearchBackend`, and a controlled `search -> fetch -> finish` action loop.

- [ ] **Step 1: Add the DuckDuckGo dependency and write failing budget tests**

Add one runtime dependency:

```toml
"ddgs>=9.0",
```

Write tests that use fakes only:

```python
async def test_loop_enforces_query_page_time_and_character_budgets(scripted_model, fake_search, fake_fetch):
    backend = OpenRouterResearchBackend(
        model=scripted_model.actions(
            search("agent release"),
            search("agent release date"),
            fetch("https://one.example/report"),
            fetch("https://two.example/report"),
            finish(valid_brief()),
        ),
        search_client=fake_search,
        fetcher=fake_fetch,
        budget=SearchBudget(max_queries=1, max_results_per_query=5, max_pages=1, max_elapsed_seconds=120, max_total_chars=120_000),
    )
    result = await backend.research(request())
    assert fake_search.queries == ["agent release"]
    assert fake_fetch.urls == ["https://one.example/report"]
    assert result.sanitized_events[-1]["budget_exhausted"] is True


async def test_final_answer_cannot_cite_search_result_that_was_not_fetched(scripted_model, fake_search, fake_fetch):
    backend = backend_with(scripted_model.finish(brief_citing("https://unfetched.example/story")), fake_search, fake_fetch)
    with pytest.raises(ResearchBackendError, match="citation URL was not fetched") as error:
        await backend.research(request())
    assert error.value.classification == "needs_review"
```

- [ ] **Step 2: Write public-network fetch safety tests**

```python
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://localhost/admin",
    "http://169.254.169.254/latest/meta-data",
    "http://10.0.0.5/private",
    "file:///etc/passwd",
])
async def test_safe_fetch_rejects_local_private_and_non_http_targets(url, resolver, transport):
    with pytest.raises(UnsafeFetchTarget):
        await SafeArticleFetcher(resolver=resolver, transport=transport).fetch(url)


async def test_safe_fetch_snapshots_successful_public_article(public_resolver, article_transport):
    page = await SafeArticleFetcher(resolver=public_resolver, transport=article_transport).fetch("https://news.example/report")
    assert page.final_url == "https://news.example/report"
    assert page.content_hash == sha256(page.body.encode()).hexdigest()
    assert page.retrieved_at.tzinfo is not None
```

- [ ] **Step 3: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_duckduckgo.py tests/research/test_safe_fetch.py tests/research/test_openrouter_loop.py -q
```

Expected: import failures for the new search/fetch/loop modules.

- [ ] **Step 4: Implement exact budgets, actions, and persistence boundary**

```python
class SearchBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_queries: int = Field(default=4, ge=1, le=8)
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    max_pages: int = Field(default=8, ge=1, le=16)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)
    max_total_chars: int = Field(default=120_000, ge=10_000, le=500_000)


class SearchAction(BaseModel):
    action: Literal["search"]
    query: str = Field(min_length=2, max_length=200)


class FetchAction(BaseModel):
    action: Literal["fetch"]
    url: HttpUrl


class FinishAction(BaseModel):
    action: Literal["finish"]
    brief: ResearchBrief
```

`DuckDuckGoSearchClient.search()` calls `DDGS().text(query, max_results=limit)` through `asyncio.to_thread`, normalizes results to title/URL/snippet, removes duplicate normalized URLs, and never marks a result fetched. `SafeArticleFetcher` re-resolves every redirect hop, permits only public `http`/`https` addresses, allows at most five redirects, caps response bytes at 5 MiB, and returns a snapshot only after article extraction succeeds.

The OpenRouter loop sends persisted evidence plus successful search/fetch observations to the model, permits at most 12 actions, applies `SearchBudget` before each action, persists each successful fetch as `ResearchSource` plus `StoryEvidenceSnapshot`, and validates all final citations against those snapshots. A model-requested forbidden URL becomes a sanitized observation, not a fetch.

- [ ] **Step 5: Run tests and commit**

```bash
cd backend
.venv/bin/pip install -e '.[dev]'
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_duckduckgo.py tests/research/test_safe_fetch.py tests/research/test_openrouter_loop.py tests/research/test_provider_contract.py -q
.venv/bin/ruff check app/research tests/research
git diff --check
cd ..
git add backend/pyproject.toml backend/app/research backend/tests/research
git commit -m "feat: add bounded OpenRouter research loop"
```

Expected: all deterministic search/fetch/provider tests pass without internet access.

---

### Task 7: Orchestrate manual and automatic research as durable jobs

**Files:**
- Create: `backend/app/research/service.py`
- Create: `backend/app/research/handlers.py`
- Modify: `backend/app/api/stories.py`
- Modify: `backend/app/jobs/models.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/research/test_service.py`
- Create: `backend/tests/research/test_handlers.py`
- Modify: `backend/tests/api/test_story_routes.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5, and 6; Release 1 jobs/events/attempts.
- Produces: `ResearchService.request()`, job kind `research_story`, `POST /stories/{story_id}/research-runs`, `GET /stories/{story_id}/research-runs`, and `GET /research-runs/{run_id}`.

- [ ] **Step 1: Write failing policy and lifecycle tests**

```python
async def test_off_mode_never_enqueues_research(db_session, complete_story):
    result = await ResearchService(db_session).request(
        story_id=complete_story.id,
        mode="off",
        depth="standard",
        backend="fake",
        query_hint=None,
    )
    assert result.disposition == "skipped"
    assert result.job_id is None


async def test_auto_mode_enqueues_only_when_incomplete(db_session, incomplete_story, complete_story):
    service = ResearchService(db_session)
    incomplete = await service.request(incomplete_story.id, "auto_if_incomplete", "standard", "fake", None)
    complete = await service.request(complete_story.id, "auto_if_incomplete", "standard", "fake", None)
    assert incomplete.disposition == "enqueued"
    assert complete.disposition == "complete_without_research"


async def test_research_handler_records_attempt_sources_revision_and_event(run_job, queued_research):
    await run_job(queued_research.job_id)
    detail = await ResearchService(queued_research.session).get_run(queued_research.run_id)
    assert detail.status == "succeeded"
    assert len(detail.attempts) == 1
    assert detail.result_revision_id is not None
    assert detail.events[-1].event_type == "research.succeeded"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_service.py tests/research/test_handlers.py tests/api/test_story_routes.py -q
```

Expected: failure because the service and endpoints are absent.

- [ ] **Step 3: Implement request policy and handler lifecycle**

Use exact request/response contracts:

```python
class ResearchRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["manual", "auto_if_incomplete"]
    depth: Literal["standard", "deep"] = "standard"
    backend: Literal["fake", "codex", "openrouter"]
    query_hint: str | None = Field(default=None, max_length=500)


class ResearchDisposition(BaseModel):
    disposition: Literal["skipped", "complete_without_research", "enqueued"]
    run_id: UUID | None
    job_id: UUID | None
    completeness: CompletenessReport
```

`ResearchService.request()` snapshots completeness, inserts `ResearchRun`, and enqueues `research_story:{story_id}:{evidence_set_hash}:{backend}:{mode}:{depth}` in the same transaction. Manual mode always enqueues at its requested standard/deep depth. Auto mode enqueues only when incomplete. The handler creates an attempt before invoking a backend, performs external work outside a database transaction, persists returned sources/brief/revision atomically, validates citations, and classifies backend errors as `retryable`, `needs_review`, or `permanent` using Release 1 job rules.

- [ ] **Step 4: Add API endpoints that return before research begins**

```python
@router.post("/{story_id}/research-runs", response_model=ResearchDisposition, status_code=202)
async def create_research_run(story_id: UUID, payload: ResearchRunCreate, session: AsyncSession = SessionDependency):
    result = await ResearchService(session).request(story_id, payload.mode, payload.depth, payload.backend, payload.query_hint)
    await session.commit()
    return result
```

The GET endpoints return completeness input hashes, backend/model identity, attempts, sanitized errors, fetched source metadata, result revision ID, and job status. They never return provider keys, raw authorization headers, or Codex environment values.

- [ ] **Step 5: Run focused tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research tests/api/test_story_routes.py tests/jobs -q
.venv/bin/ruff check app/research app/api/stories.py tests/research tests/api/test_story_routes.py
git diff --check
cd ..
git add backend/app/research backend/app/api/stories.py backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/research backend/tests/api/test_story_routes.py
git commit -m "feat: orchestrate durable story research"
```

Expected: research, API, and job regression tests pass.

---

### Task 8: Generate canonical story revisions and immutable content-pack revisions

**Files:**
- Create: `backend/app/generation/canonical.py`
- Create: `backend/app/generation/editorial_service.py`
- Modify: `backend/app/generation/handlers.py`
- Create: `backend/app/api/content_packs.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/generation/test_canonical.py`
- Create: `backend/tests/generation/test_editorial_service.py`
- Create: `backend/tests/api/test_content_pack_routes.py`

**Interfaces:**
- Consumes: validated evidence/research from Tasks 1–7, Release 1 provider/job/content-pack models, and Release 2 Telegram renderer.
- Produces: `CanonicalStoryOutput`, `GeneratePackRequest`, `EditVariantRequest`, `ApprovalRequest`, canonical and pack generation jobs, revision-conflict behavior, and content-pack APIs.

- [ ] **Step 1: Write failing canonical grounding and revision tests**

```python
async def test_canonical_generation_rejects_unknown_citation(fake_generation_provider, story_with_evidence):
    fake_generation_provider.result = canonical_output(citation_id=uuid4())
    with pytest.raises(CitationIntegrityError):
        await generate_canonical_revision(story_with_evidence, fake_generation_provider)


async def test_edit_creates_new_unapproved_revision_and_preserves_approved_parent(db_session, approved_variant):
    service = EditorialService(db_session)
    edited = await service.edit_variant(
        approved_variant.variant_id,
        base_revision_id=approved_variant.revision_id,
        base_content_hash=approved_variant.content_hash,
        payload={"text": "Human-edited Telegram copy", "citations": approved_variant.citations},
        edit_note="Tighten opening",
    )
    assert edited.id != approved_variant.revision_id
    assert edited.parent_revision_id == approved_variant.revision_id
    assert edited.approval_state == "unapproved"
    assert approved_variant.approval_state == "approved"


async def test_approval_rejects_stale_hash(db_session, variant_revision):
    with pytest.raises(RevisionConflict, match="content hash changed"):
        await EditorialService(db_session).approve_revision(
            variant_revision.id,
            expected_content_hash="0" * 64,
            note=None,
        )
```

- [ ] **Step 2: Define canonical output and editor request schemas**

```python
class CanonicalStoryOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str = Field(min_length=1, max_length=300)
    narrative: str = Field(min_length=50)
    facts: list[Claim] = Field(min_length=1)
    disagreements: list[Claim]
    angles: list[str]
    missing_information: list[str]


class GeneratePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_profile_id: UUID
    platform: Literal["telegram"]
    provider: Literal["fake", "openrouter", "codex"]
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    research_backend: Literal["fake", "openrouter", "codex"] | None = None


class EditVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload: dict[str, object]
    edit_note: str = Field(min_length=1, max_length=500)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str | None = Field(default=None, max_length=500)
```

- [ ] **Step 3: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation/test_canonical.py tests/generation/test_editorial_service.py tests/api/test_content_pack_routes.py -q
```

Expected: failures for missing canonical and editorial services.

- [ ] **Step 4: Implement two-stage generation and immutable edits**

Generation orchestration must follow this exact state flow:

```python
async def request_content_pack(service: EditorialService, story_id: UUID, request: GeneratePackRequest) -> JobAcceptedOut:
    completeness = await service.completeness(story_id)
    if request.research_mode == "auto_if_incomplete" and not completeness.complete:
        return await service.enqueue_research_then_generation(story_id, request)
    return await service.enqueue_canonical_then_pack_generation(story_id, request)
```

The canonical handler snapshots its evidence set, records `GenerationRun`/`GenerationAttempt`, validates every claim citation, and writes a new immutable `StoryRevision`. The pack handler renders Telegram from that exact revision and brand/prompt versions, validates with the Release 2 Telegram renderer, then writes a new `PlatformVariantRevision`. Use an input hash derived from story revision hash, brand profile version, prompt version checksum, provider/model policy, and platform. Regeneration always creates a child revision even when output text matches. Editing recomputes canonical JSON SHA-256 and rejects stale base hashes with HTTP 409. Approval stores revision ID, content hash, operator timestamp, and optional note.

- [ ] **Step 5: Add resource routes**

Implement these exact endpoints:

```text
GET    /stories/{story_id}
GET    /stories/{story_id}/evidence
GET    /stories/{story_id}/revisions
POST   /stories/{story_id}/content-packs
GET    /content-packs
GET    /content-packs/{pack_id}
GET    /platform-variants/{variant_id}/revisions
POST   /platform-variants/{variant_id}/revisions
POST   /platform-variant-revisions/{revision_id}/approve
POST   /platform-variant-revisions/{revision_id}/reject
```

All mutating long operations return HTTP 202 plus a job. Edit/approve/reject are short transactional mutations and return HTTP 201/200. Rejection records an event and does not delete a revision.

- [ ] **Step 6: Run focused tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation tests/api/test_content_pack_routes.py tests/research tests/publishing -q
.venv/bin/ruff check app/generation app/api/content_packs.py tests/generation tests/api/test_content_pack_routes.py
git diff --check
cd ..
git add backend/app/generation backend/app/api/content_packs.py backend/app/api/routes.py backend/tests/generation backend/tests/api/test_content_pack_routes.py
git commit -m "feat: add canonical generation and revision approval"
```

Expected: generation, editorial API, research, and Telegram publishing regressions pass.

---

### Task 9: Build typed editorial API clients and the grouped Inbox

**Files:**
- Create: `frontend/lib/editorial-types.ts`
- Create: `frontend/lib/editorial-api.ts`
- Modify: `frontend/lib/query-keys.ts`
- Create: `frontend/components/editorial/story-inbox.tsx`
- Create: `frontend/components/editorial/manual-intake-dialog.tsx`
- Create: `frontend/components/editorial/research-panel.tsx`
- Create: `frontend/app/inbox/page.tsx`
- Modify: `frontend/components/newsroom/newsroom-sidebar.tsx`
- Modify: `frontend/components/newsroom/mobile-newsroom-nav.tsx`
- Create: `frontend/tests/editorial-api.test.ts`
- Create: `frontend/tests/story-inbox.test.tsx`
- Create: `frontend/tests/manual-intake-dialog.test.tsx`
- Create: `frontend/tests/research-panel.test.tsx`
- Modify: `frontend/tests/navigation.test.tsx`

**Interfaces:**
- Consumes: story, manual intake, completeness, and research endpoints from Tasks 3, 7, and 8.
- Produces: `StorySummary`, `StoryDetail`, `ResearchRunDetail`, `createManualStory()`, `requestResearch()`, and an operator-usable Inbox.

- [ ] **Step 1: Write failing API mapping and UI state tests**

```tsx
it("submits manual URL intake and exposes the durable job", async () => {
  const fetchSpy = stubFetch({ job_id: "job-1", job_kind: "manual_intake", status: "queued" }, 202)
  await expect(createManualStory({ kind: "url", url: "https://example.com/report", title: null })).resolves.toMatchObject({ jobId: "job-1" })
  expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/manual", expect.objectContaining({ method: "POST" }))
})

it("groups evidence under a story and offers research only from a truthful completeness state", async () => {
  renderWithClient(<StoryInbox initialStories={[incompleteStory]} />)
  expect(screen.getByText("2 evidence items")).toBeInTheDocument()
  expect(screen.getByText("Coverage incomplete")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Research more" }))
  expect(await screen.findByRole("dialog", { name: "Research story" })).toBeInTheDocument()
})

it("shows pending, failure, and completed research outcomes", async () => {
  const { rerender } = render(<ResearchPanel story={story} run={pendingRun} />)
  expect(screen.getByText("Research queued")).toBeInTheDocument()
  rerender(<ResearchPanel story={story} run={failedRun} />)
  expect(screen.getByRole("button", { name: "Retry research" })).toBeInTheDocument()
  rerender(<ResearchPanel story={story} run={completedRun} />)
  expect(screen.getByRole("link", { name: "Open fetched source" })).toHaveAttribute("href", "https://example.com/source")
})

```

Extend `frontend/tests/navigation.test.tsx` to render both existing navigation components and assert each exposes an `Inbox` link to `/inbox` once the route exists.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/editorial-api.test.ts tests/story-inbox.test.tsx tests/manual-intake-dialog.test.tsx tests/research-panel.test.tsx
```

Expected: import failures for editorial client and components.

- [ ] **Step 3: Add exact frontend contracts and query keys**

```tsx
export type ResearchMode = "off" | "manual" | "auto_if_incomplete"
export type ResearchBackend = "fake" | "codex" | "openrouter"

export type StorySummary = {
  id: string
  title: string
  evidenceCount: number
  latestEvidenceAt: string
  completeness: { complete: boolean; score: number; reasons: string[] }
  editorialState: "inbox" | "shortlisted" | "rejected" | "drafted"
}

export const editorialQueryKeys = {
  stories: (filters: StoryFilters) => ["stories", filters] as const,
  story: (id: string) => ["stories", id] as const,
  evidence: (storyId: string) => ["stories", storyId, "evidence"] as const,
  researchRuns: (storyId: string) => ["stories", storyId, "research-runs"] as const,
  contentPacks: ["content-packs"] as const,
  contentPack: (id: string) => ["content-packs", id] as const,
  variantRevisions: (variantId: string) => ["platform-variants", variantId, "revisions"] as const,
}
```

- [ ] **Step 4: Implement the grouped Inbox and manual/research actions**

The Inbox must render real loading, error, empty, and data states; support search, completeness filter, shortlist, reject, multi-select, and story expansion; and show source names, URLs, timestamps, and snapshot counts without invented values. Add `Inbox` to both Release 1 navigation components only after this route works. `ManualIntakeDialog` uses a URL/Text tab, validates text at 20 characters, closes only after HTTP 202, and displays the returned job in a durable outcome banner. `ResearchPanel` offers backend selection, optional query hint, `Research more` (`mode=manual`, `depth=standard`) and `Deep research` (`mode=manual`, `depth=deep`), and polls the returned job/run until terminal.

Use mutation invalidation exactly as follows:

```tsx
onSuccess: async (result) => {
  setOutcome({ kind: "job", jobId: result.jobId, message: "Research queued" })
  await queryClient.invalidateQueries({ queryKey: editorialQueryKeys.researchRuns(storyId) })
  await queryClient.invalidateQueries({ queryKey: editorialQueryKeys.story(storyId) })
}
```

- [ ] **Step 5: Run tests, type checking, and commit**

```bash
cd frontend
npm run test -- tests/editorial-api.test.ts tests/story-inbox.test.tsx tests/manual-intake-dialog.test.tsx tests/research-panel.test.tsx
npm run typecheck
git diff --check
cd ..
git add frontend/lib/editorial-types.ts frontend/lib/editorial-api.ts frontend/lib/query-keys.ts frontend/components/editorial frontend/app/inbox/page.tsx frontend/components/newsroom/newsroom-sidebar.tsx frontend/components/newsroom/mobile-newsroom-nav.tsx frontend/tests/editorial-api.test.ts frontend/tests/story-inbox.test.tsx frontend/tests/manual-intake-dialog.test.tsx frontend/tests/research-panel.test.tsx frontend/tests/navigation.test.tsx
git commit -m "feat: add grouped editorial inbox and research controls"
```

Expected: focused tests and TypeScript pass.

---

### Task 10: Build the evidence-backed revision editor and exact approval flow

**Files:**
- Create: `frontend/components/editorial/evidence-panel.tsx`
- Create: `frontend/components/editorial/variant-editor.tsx`
- Create: `frontend/components/editorial/revision-timeline.tsx`
- Modify: `frontend/app/drafts/page.tsx`
- Create: `frontend/app/drafts/[packId]/page.tsx`
- Create: `frontend/app/review/[variantId]/page.tsx`
- Modify: `frontend/lib/editorial-api.ts`
- Create: `frontend/tests/variant-editor.test.tsx`
- Create: `frontend/tests/evidence-panel.test.tsx`
- Create: `frontend/tests/revision-timeline.test.tsx`
- Create: `frontend/e2e/editorial-studio.spec.ts`

**Interfaces:**
- Consumes: content-pack/revision/evidence routes from Task 8 and Release 2 Telegram preview/publish behavior.
- Produces: full drafts list, pack detail, evidence-side editor, immutable revision history, regenerate, save, approve, reject, and schedule/publish handoff.

- [ ] **Step 1: Write failing editor invariant tests**

```tsx
it("approves the exact loaded revision and hash", async () => {
  const approve = vi.fn().mockResolvedValue({ approvalState: "approved" })
  render(<VariantEditor revision={revision({ id: "rev-2", contentHash: "a".repeat(64) })} onApprove={approve} />)
  await userEvent.click(screen.getByRole("button", { name: "Approve revision" }))
  expect(approve).toHaveBeenCalledWith({ revisionId: "rev-2", expectedContentHash: "a".repeat(64), note: null })
})

it("marks edited content unapproved and handles a stale revision conflict", async () => {
  const save = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  render(<VariantEditor revision={approvedRevision} onSave={save} />)
  await userEvent.type(screen.getByLabelText("Telegram message"), " Added context")
  expect(screen.getByText("Changes require new approval")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(await screen.findByText("A newer revision exists. Reload before saving.")).toBeInTheDocument()
})

it("navigates from a claim citation to the exact evidence locator", async () => {
  render(<EvidencePanel evidence={evidence} activeCitation={citation} />)
  expect(screen.getByTestId("evidence-excerpt")).toHaveTextContent("announced on July 11")
  expect(screen.getByRole("link", { name: "Open original source" })).toHaveAttribute("href", evidence.sourceUrl)
})
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/variant-editor.test.tsx tests/evidence-panel.test.tsx tests/revision-timeline.test.tsx
```

Expected: import failures for editor components.

- [ ] **Step 3: Implement editor state and API calls**

Add exact client methods:

```tsx
export function saveVariantRevision(variantId: string, input: EditVariantInput): Promise<VariantRevision>
export function approveVariantRevision(revisionId: string, input: { expectedContentHash: string; note: string | null }): Promise<VariantRevision>
export function rejectVariantRevision(revisionId: string, input: { reason: string }): Promise<VariantRevision>
export function regenerateVariant(variantId: string, input: { provider: AiProvider; instruction: string | null }): Promise<JobAccepted>
```

`VariantEditor` keeps the loaded revision ID/hash separate from the draft form, never mutates query-cache revisions in place, warns on dirty navigation, saves a child revision, clears dirty state only after success, and disables approval while dirty or validation errors exist. Evidence citations appear beside the relevant claim and focus the exact `chars:start-end` excerpt. Revision timeline entries show origin (`generated` or `human_edit`), parent, provider/model or operator, timestamp, validation, and approval state.

- [ ] **Step 4: Add drafts, pack detail, and review routes**

The routes must implement these visible state contracts:

```tsx
type DraftRouteState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "failed"; message: string; jobId: string | null }
  | { kind: "ready"; pack: ContentPackDetail }
```

Drafts list generation state and last failure; pack detail lists exact variants/revisions; review uses a desktop split layout and stacks evidence above the editor below 900px. After approval, Telegram actions from Release 2 become enabled only for the approved revision. Do not expose Instagram/X/blog controls before Release 4.

- [ ] **Step 5: Add the browser flow**

Mock backend responses deterministically and cover:

```ts
test("manual text to research to generated revision to approval", async ({ page }) => {
  await page.goto("/inbox")
  await page.getByRole("button", { name: "Add source material" }).click()
  await page.getByRole("tab", { name: "Text" }).click()
  await page.getByLabel("Title").fill("Agent release")
  await page.getByLabel("Source text").fill("Confirmed source material long enough for manual intake and evidence capture.")
  await page.getByLabel("Source label").fill("Operator notes")
  await page.getByRole("button", { name: "Create story" }).click()
  await expect(page.getByText("Intake queued")).toBeVisible()
  await page.getByRole("button", { name: "Research more" }).click()
  await page.getByRole("button", { name: "Start research" }).click()
  await expect(page.getByText("Research complete")).toBeVisible()
  await page.getByRole("button", { name: "Generate Telegram draft" }).click()
  await page.getByRole("link", { name: "Review draft" }).click()
  await page.getByRole("button", { name: "Approve revision" }).click()
  await expect(page.getByText("Revision approved")).toBeVisible()
})
```

- [ ] **Step 6: Run frontend gates and commit**

```bash
cd frontend
npm run test
npm run typecheck
npm run build
npx playwright test e2e/editorial-studio.spec.ts --project=chromium
git diff --check
cd ..
git add frontend/components/editorial frontend/app/drafts frontend/app/review frontend/lib/editorial-api.ts frontend/tests frontend/e2e/editorial-studio.spec.ts
git commit -m "feat: add evidence-backed editorial studio"
```

Expected: frontend unit, type, build, and editorial browser tests pass.

---

### Task 11: Prove Release 3 end to end and record operator configuration

**Files:**
- Create: `backend/tests/integration/test_editorial_research_generation_flow.py`
- Create: `docs/operations/research-and-generation.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: every Release 3 task.
- Produces: deterministic manual-intake/research/generation/approval acceptance coverage and operator setup instructions for fake, OpenRouter, and Codex backends.

- [ ] **Step 1: Write the full backend integration test**

```python
async def test_manual_story_research_generation_edit_and_exact_approval(app_harness):
    intake = await app_harness.post_json(
        "/stories/manual",
        {"kind": "text", "title": "Release", "text": "x" * 900, "source_label": "Operator", "source_url": None},
    )
    await app_harness.worker.run_until_idle()
    story = await app_harness.story_for_job(intake["job_id"])
    research = await app_harness.post_json(
        f"/stories/{story.id}/research-runs",
        {"mode": "manual", "backend": "fake", "query_hint": "Verify date"},
    )
    await app_harness.worker.run_until_idle()
    pack = await app_harness.post_json(
        f"/stories/{story.id}/content-packs",
        {"brand_profile_id": str(app_harness.brand.id), "platform": "telegram", "provider": "fake", "research_mode": "off", "research_backend": None},
    )
    await app_harness.worker.run_until_idle()
    revision = await app_harness.revision_for_job(pack["job_id"])
    edited = await app_harness.post_json(
        f"/platform-variants/{revision.variant_id}/revisions",
        {"base_revision_id": str(revision.id), "base_content_hash": revision.content_hash, "payload": revision.payload | {"text": "Edited copy"}, "edit_note": "Operator edit"},
    )
    approved = await app_harness.post_json(
        f"/platform-variant-revisions/{edited['id']}/approve",
        {"expected_content_hash": edited["content_hash"], "note": "Ready"},
    )
    assert approved["approval_state"] == "approved"
    assert approved["id"] == edited["id"]
    assert research["job_id"] is not None
```

- [ ] **Step 2: Document exact local configuration**

Document these settings and safety facts:

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_RESEARCH_MODEL=
CODEX_EXECUTABLE=codex
CODEX_RESEARCH_TIMEOUT_SECONDS=180
RESEARCH_MAX_QUERIES=4
RESEARCH_MAX_RESULTS_PER_QUERY=5
RESEARCH_MAX_PAGES=8
RESEARCH_MAX_ELAPSED_SECONDS=120
RESEARCH_MAX_TOTAL_CHARS=120000
```

Explain that fake mode needs no credentials, Codex uses local Codex authentication, OpenRouter uses its key plus the controlled DDG loop, and none of these variables are committed. Include exact UI flow: Inbox → Add source material → Research more/Deep research → Generate Telegram draft → Review → Save revision → Approve.

- [ ] **Step 3: Run the complete Release 3 gate**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests -q
.venv/bin/ruff check .
alembic upgrade head
cd ../frontend
npm run test
npm run typecheck
npm run build
npx playwright test --project=chromium
cd ..
docker compose config >/tmp/newscraft-release3-compose.yml
git diff --check
```

Expected: all backend/frontend tests pass, Ruff/type/build/Playwright pass, Alembic is at head, Compose renders, and diff check is clean.

- [ ] **Step 4: Commit acceptance coverage and docs**

```bash
git add backend/tests/integration/test_editorial_research_generation_flow.py docs/operations/research-and-generation.md README.md
git commit -m "test: prove editorial research and generation flow"
git status --short
```

Expected: commit succeeds and no Release 3 file remains modified. Unrelated explicitly excluded artifacts may remain untracked.

## Release 3 Exit Criteria

- Related source items form one inspectable story with immutable evidence snapshots.
- Manual URL/text entry returns a durable job and records truthful provenance.
- Completeness is deterministic and visible; `auto_if_incomplete` never runs for complete evidence.
- Codex and OpenRouter research satisfy the same strict contract and retain provider/model/attempt metadata.
- DuckDuckGo/OpenRouter search obeys query/page/time/character budgets and cannot cite an unfetched URL.
- Research creates a new evidence-backed story revision and does not overwrite sources.
- Canonical generation and Telegram pack generation preserve evidence mappings.
- Human edits and regeneration create immutable child revisions; approval binds to the exact ID/hash.
- Inbox, research, Drafts, and Review flows render loading, empty, failure, success, mobile stacking, Persian/RTL evidence, and durable job outcomes.
- The full deterministic gate passes without external credentials.
