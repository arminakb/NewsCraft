# Release 3 Editorial Research and Generation Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn captured source material into grouped, immutable, citation-backed stories that can be manually enriched, researched through Codex or a bounded OpenRouter/DuckDuckGo loop, generated into versioned content packs, edited, and approved at an exact revision.

**Architecture:** Preserve source items and provisional Telegram stories as immutable evidence, derive deterministic completeness reports, and run every fetch, research, and generation action as a durable `WorkflowJob`. Research adapters perform bounded I/O and return database-free candidate DTOs; only the research job handler may atomically persist fetched `ResearchSource`/`StoryEvidenceSnapshot` rows, resolve stable `evidence_key` values to database UUIDs, and create the cited story revision. Canonical generation consumes only persisted evidence and configured `AIProviderProfile` IDs, then produces immutable `StoryRevision` and Release 2-compatible Telegram `PlatformVariantRevision` records.

**Tech Stack:** Python 3.14, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL 18, Alembic, `httpx`, `ddgs`, Codex CLI, OpenRouter Chat Completions, pytest, Next.js 16, React 19, TanStack Query 5, TypeScript, Vitest, Playwright.

## Global Constraints

- Releases 0, 1, and 2 are complete and their full gates pass before this plan begins.
- Product mode remains local and single operator; no accounts, teams, RBAC, billing, or public deployment are introduced.
- Original `ContentItem`, `SourceItem`, `RawPayload`, Telegram message, and media records are never overwritten by research or generation.
- Existing Release 2 `telegram_provisional` stories, evidence snapshots, revisions, dispatches, and drafts are never moved or deleted. Grouping copies snapshots into a new canonical story and marks only the mutable provisional `Story.superseded_by_id` link, regardless of how many source-edit snapshots/revisions the provisional story has accumulated.
- Research modes are exactly `off`, `manual`, and `auto_if_incomplete`; automatic research runs only after the deterministic completeness evaluator returns `complete=false`.
- OpenRouter is the normal HTTP backend; Codex CLI is an optional local operator backend; deterministic fake backends remain mandatory for tests.
- All research, generation, route-policy, and frontend mutation contracts select `AIProviderProfile` by UUID. Provider type/model/secret configuration is resolved server-side from that enabled profile; API callers never select a provider by a free-form `fake`/`openrouter`/`codex` literal.
- Codex executes in an isolated temporary directory with an explicit resolved model, no Git requirement/rules/shell/code-mode/computer-use/apps/external-browser/full-CDP capability, a non-inherited temporary `HOME`, `--ephemeral`, `--sandbox read-only`, `--ignore-user-config`, strict JSON Schema output, bounded model calls/tokens/time, and no publishing or database secrets. Research enables only the built-in `browser_use` capability; generation disables it.
- OpenRouter research may search only through the application-owned DuckDuckGo/fetch loop and may cite only URLs successfully fetched and snapshotted by NewsCraft.
- OpenRouter model calls, input/output tokens, elapsed time, queries, pages, fetched characters, and estimated USD cost are bounded before each action and recorded after every call.
- Research backends never persist ORM rows and never emit database UUIDs for discovered evidence. They return stable `evidence_key` candidate citations; only the handler resolves those keys after persistence.
- All generated facts, disagreements, and platform claims carry claim-level evidence references before approval.
- OpenRouter profile settings reuse the Release 2 `OpenRouterProviderSettings` pricing and `research_budgets.standard/deep` contract. Codex profiles use strict `CodexProviderSettings`; capability availability is validated before enqueue.
- Canonical-story and Telegram-pack generation each select an active immutable prompt version with purpose keys `canonical_story` and `telegram_pack`; every `GenerationRun.prompt_template_version_id` is non-null and stage-appropriate.
- Platform revision states are exactly `draft`, `pending_review`, `approved`, and `rejected`. Every human edit and regeneration creates a new immutable `pending_review` revision; approval binds to one revision ID/content hash.
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

Required Release 1/2 tables and ORM names are `Story`, `StoryEvidenceSnapshot`, `StoryRevision`, `StoryEvidenceLink`, `BrandProfile`, `PromptTemplate`, `PromptTemplateVersion`, `AIProviderProfile`, `ResearchRun`, `ResearchAttempt`, `ResearchSource`, `GenerationRun`, `GenerationAttempt`, `ContentPack`, `PlatformVariant`, `PlatformVariantRevision`, `WorkflowJob`, and `WorkflowEvent`. `Story.superseded_by_id` is the shared nullable self-reference used for provisional-story consolidation. Release 2 capture marks every not-yet-grouped Telegram story `status="telegram_provisional"`; source edits retain that status. `StoryEvidenceSnapshot` fields are exactly `content_text`, `content_sha256`, and nullable `source_url`; evidence keys are exactly `content-item:<content_item_id>:<content_sha256>`, `url:<normalized_source_url>:<content_sha256>`, or `operator-text:<content_sha256>` in that precedence order. Later tasks must not introduce `body`, `content_hash`, mandatory-source aliases, or alternate evidence-key prefixes on ORM rows. Required Release 2 Telegram revisions have nullable `content.source_item_id`, nullable `content.source_url`, and a non-empty `evidence_map` of UUID-backed `CitationRef`-compatible objects; Release 3 consumes that contract without a backfill or alternate edit payload. Release 2 publication code continues to consume approved `PlatformVariantRevision` IDs and is not rewritten here.

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
- `app/research/base.py`: database-free request/result/provider contracts and budget accounting.
- `app/research/safe_fetch.py`: public-network-only candidate materialization before any research adapter returns.
- `app/core/codex_exec.py`: one constrained structured-output Codex subprocess boundary.
- `app/research/codex_adapter.py`: research-backend wrapper that permits Codex web research.
- `app/research/duckduckgo.py`: bounded search client.
- `app/research/openrouter_loop.py`: application-controlled pure I/O/DTO search/fetch/model loop; no ORM/session dependency.
- `app/research/fake.py`: deterministic research backend.
- `app/research/service.py`: research run lifecycle and persistence.
- `app/research/handlers.py`: sole persistence boundary for research sources, copied evidence, resolved citations, and result revisions.
- `app/generation/default_prompts.py`: immutable default `canonical_story` and `telegram_pack` template/version seeds beside Release 2 `telegram_rewrite`.
- `app/generation/provider_settings.py`: Release 2 shared OpenRouter pricing/research-budget schemas plus the strict Release 3 Codex settings schema.
- `app/generation/canonical.py`: evidence-to-canonical-story generation contract.
- `app/generation/providers/codex.py`: normal structured generation/rewrite provider backed by Codex CLI.
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
- `app/review/[revisionId]/page.tsx`: Release 2 review entrypoint extended in place for evidence/editor/research behavior.
- `components/editorial/story-inbox.tsx`: grouping, selection, shortlist, reject, and bulk actions.
- `components/editorial/manual-intake-dialog.tsx`: URL/text intake form.
- `components/editorial/research-panel.tsx`: completeness, manual/deep research controls, attempts, and results.
- `components/editorial/evidence-panel.tsx`: immutable evidence and citation navigation.
- `components/editorial/variant-editor.tsx`: revision-aware editor and conflict handling.
- `components/editorial/revision-timeline.tsx`: immutable revisions, authorship, validation, and approval history.

---

### Task 1: Group related source items and capture immutable evidence

**Files:**
- Modify: `backend/app/stories/__init__.py`
- Create: `backend/app/stories/grouping.py`
- Create: `backend/app/stories/evidence.py`
- Create: `backend/app/stories/repository.py`
- Create: `backend/app/stories/schemas.py`
- Create: `backend/app/stories/handlers.py`
- Modify: `backend/app/jobs/handlers.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/jobs/types.py`
- Create: `backend/tests/stories/test_grouping.py`
- Create: `backend/tests/stories/test_evidence.py`
- Create: `backend/tests/stories/test_repository.py`
- Create: `backend/tests/stories/test_handlers.py`

**Interfaces:**
- Consumes: `ContentItem`, `SourceItem`, Release 1 `Story.superseded_by_id`, `StoryEvidenceSnapshot.content_text/content_sha256/source_url`, and every unsuperseded Release 2 story with `status="telegram_provisional"`, including source-edited stories with multiple snapshots/revisions.
- Produces: `GroupingInput`, `GroupingDecision`, `EvidenceInput`, `CapturedEvidence`, `EvidenceRecord`, `build_evidence_key()`, `capture_evidence()`, `StoryRepository.group_content_items()`, `group_pending_content`, and automatic post-ingestion grouping jobs.

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
    assert [snapshot.content_text for snapshot in snapshots] == ["Evidence A", "Evidence B"]
    assert len({snapshot.content_sha256 for snapshot in snapshots}) == 2


def test_content_item_evidence_uses_locked_content_item_key():
    content_item_id = uuid4()
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=content_item_id,
            title="Title",
            content_text="Body",
            source_url="https://example.com/source",
            authors=["Reporter"],
            published_at=datetime(2026, 7, 11, tzinfo=UTC),
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    changed = capture_evidence(replace(evidence.input, content_text="Changed body"))
    assert evidence.content_sha256 == sha256(b"Body").hexdigest()
    assert evidence.evidence_key == f"content-item:{content_item_id}:{evidence.content_sha256}"
    assert evidence.content_sha256 != changed.content_sha256
    assert evidence.evidence_key != changed.evidence_key


def test_operator_text_evidence_allows_truthful_null_source_url():
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=None,
            title="Operator interview",
            content_text="Direct notes supplied by the operator.",
            source_url=None,
            authors=["Operator"],
            published_at=None,
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    assert evidence.source_url is None
    assert evidence.evidence_key == f"operator-text:{evidence.content_sha256}"


def test_url_evidence_key_includes_normalized_url_and_content_hash():
    evidence = capture_evidence(
        EvidenceInput(
            content_item_id=None,
            title="Fetched report",
            content_text="First immutable version",
            source_url="https://example.com/report?utm_source=test",
            authors=[],
            published_at=None,
            captured_at=datetime(2026, 7, 11, 9, tzinfo=UTC),
        )
    )
    changed = capture_evidence(replace(evidence.input, content_text="Changed immutable version"))
    assert evidence.evidence_key == f"url:https://example.com/report:{evidence.content_sha256}"
    assert changed.evidence_key == f"url:https://example.com/report:{changed.content_sha256}"
    assert changed.evidence_key != evidence.evidence_key


async def test_grouping_copies_all_release_two_provisional_snapshots_and_only_supersedes_story_rows(
    db_session, telegram_provisional_factory
):
    first = await telegram_provisional_factory(
        title="Agent launch",
        snapshot_texts=["Evidence A", "Evidence A corrected"],
    )
    second = await telegram_provisional_factory(
        title="Agent launch details",
        snapshot_texts=["Evidence B"],
    )
    original_snapshots = [*first.snapshots, *second.snapshots]
    original_snapshot_ids = {row.id for row in original_snapshots}
    original_revision_ids = {row.id for row in [*first.revisions, *second.revisions]}
    original_dispatch_revision_ids = {first.dispatch.story_revision_id, second.dispatch.story_revision_id}

    canonical = await StoryRepository(db_session).group_content_items([first.content_item.id, second.content_item.id])
    replay = await StoryRepository(db_session).group_content_items([first.content_item.id, second.content_item.id])
    copied = await StoryRepository(db_session).list_evidence(canonical.id)

    assert canonical.id not in {first.story.id, second.story.id}
    assert replay.id == canonical.id
    assert {row.content_sha256 for row in copied} == {row.content_sha256 for row in original_snapshots}
    assert {row.evidence_key for row in copied} == {row.evidence_key for row in original_snapshots}
    assert {row.id for row in copied}.isdisjoint(original_snapshot_ids)
    assert first.story.superseded_by_id == canonical.id
    assert second.story.superseded_by_id == canonical.id
    assert {row.id for row in [*first.revisions, *second.revisions]} == original_revision_ids
    assert {first.dispatch.story_revision_id, second.dispatch.story_revision_id} == original_dispatch_revision_ids


async def test_grouping_deduplicates_equal_snapshot_payloads_by_evidence_key(
    db_session, telegram_provisional_factory
):
    shared = evidence_snapshot_values(content_text="Shared evidence")
    first = await telegram_provisional_factory(snapshot_values=[shared])
    second = await telegram_provisional_factory(snapshot_values=[shared])
    canonical = await StoryRepository(db_session).group_content_items([first.content_item.id, second.content_item.id])
    copied = await StoryRepository(db_session).list_evidence(canonical.id)
    assert [row.evidence_key for row in copied].count(shared.evidence_key) == 1
    assert first.story.superseded_by_id == canonical.id
    assert second.story.superseded_by_id == canonical.id


async def test_grouping_rejects_same_evidence_key_with_different_payload_before_superseding(
    db_session, telegram_provisional_factory
):
    original = evidence_snapshot_values(content_text="Original evidence")
    collision = replace(original, content_text="Different payload with reused key")
    first = await telegram_provisional_factory(snapshot_values=[original])
    second = await telegram_provisional_factory(snapshot_values=[collision])
    with pytest.raises(EvidenceKeyCollision, match="same evidence_key has different snapshot payload"):
        await StoryRepository(db_session).group_content_items([first.content_item.id, second.content_item.id])
    assert first.story.superseded_by_id is None
    assert second.story.superseded_by_id is None


async def test_group_pending_handler_is_replay_safe(run_job, unassigned_content_items):
    first = await run_job("story.group_pending", {"limit": 100}, idempotency_key="story-group:test-batch")
    second = await run_job("story.group_pending", {"limit": 100}, idempotency_key="story-group:test-batch")
    assert first.result == second.result
    assert await evidence_snapshot_count() == len(unassigned_content_items)


async def test_successful_ingestion_enqueues_one_grouping_followup(ingest_handler_fixture):
    await ingest_handler_fixture.run_successfully()
    followups = ingest_handler_fixture.jobs.by_type("story.group_pending")
    assert len(followups) == 1
    assert followups[0].idempotency_key == f"story-group:{ingest_handler_fixture.workflow_job_id}"
```

- [ ] **Step 5: Implement immutable evidence capture and repository persistence**

Define the exact application value objects and hash the exact UTF-8 `content_text` with SHA-256. Evidence keys reuse the locked Release 1 precedence and formats without aliases:

```python
@dataclass(frozen=True, slots=True)
class EvidenceInput:
    content_item_id: UUID | None
    title: str | None
    content_text: str
    source_url: str | None
    authors: list[str]
    published_at: datetime | None
    captured_at: datetime


@dataclass(frozen=True, slots=True)
class CapturedEvidence:
    input: EvidenceInput
    evidence_key: str
    content_sha256: str

    @property
    def source_url(self) -> str | None:
        return self.input.source_url


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_key: str
    evidence_snapshot_id: UUID
    content_item_id: UUID | None
    title: str | None
    content_text: str
    content_sha256: str
    source_url: str | None
    authors: tuple[str, ...]
    published_at: datetime | None
    captured_at: datetime


def build_evidence_key(*, content_item_id: UUID | None, source_url: str | None, content_sha256: str) -> str:
    if content_item_id is not None:
        return f"content-item:{content_item_id}:{content_sha256}"
    if source_url is not None:
        return f"url:{normalize_url(source_url)}:{content_sha256}"
    return f"operator-text:{content_sha256}"


def capture_evidence(value: EvidenceInput) -> CapturedEvidence:
    content_sha256 = hashlib.sha256(value.content_text.encode("utf-8")).hexdigest()
    evidence_key = build_evidence_key(
        content_item_id=value.content_item_id,
        source_url=value.source_url,
        content_sha256=content_sha256,
    )
    return CapturedEvidence(input=value, evidence_key=evidence_key, content_sha256=content_sha256)
```

`StoryRepository.list_evidence()` maps Release 1 ORM fields without aliases: callers receive `EvidenceRecord.content_text`, `content_sha256`, and nullable `source_url`. `StoryRepository.group_content_items(content_item_ids: Sequence[UUID]) -> Story` locks every matching content item, evidence snapshot, story, and `superseded_by_id`. A provisional Telegram story is identified only as `Story.status == "telegram_provisional" and Story.superseded_by_id is None`; snapshot count, revision count, and `created_by` do not determine eligibility. If the related set contains an active non-provisional canonical story, reuse the oldest one. If it contains only unassigned items and/or provisional Telegram stories, create a new canonical story with `status="inbox"`.

Before inserting, collect every source snapshot by `evidence_key`. For duplicate keys, compare the exact immutable payload tuple `(content_item_id, source_url, title, content_text, authors, published_at, content_sha256, snapshot_metadata, captured_at)` after canonical JSON normalization. Equal payloads produce one canonical copy; unequal payloads raise `EvidenceKeyCollision` and roll back without setting any supersession link. Copy each unique snapshot into the canonical story with a new snapshot UUID and the same immutable payload; never update/delete/move an original snapshot or revision. Flush every canonical copy first, then set `superseded_by_id` on each provisional story. Existing `AutomationDispatch.story_revision_id` values remain unchanged.

Register `story.group_pending`. Its handler selects a bounded page containing both content items with no evidence snapshot and all content items assigned to unsuperseded `telegram_provisional` stories, including every source-edit snapshot. It groups deterministically and returns counts/cursor without external I/O. After successful ingestion network work, `handle_ingest_collect` enqueues exactly one follow-up with key `story-group:{ingest_workflow_job.id}` before returning; a crash/replay reuses that key and cannot duplicate a canonical story/copied snapshot or re-supersede a provisional story. Historical and already-assigned Telegram items use the same explicit job endpoint added in Task 7.

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_grouping.py tests/stories/test_evidence.py tests/stories/test_repository.py tests/stories/test_handlers.py tests/test_job_handler_registry.py -q
.venv/bin/ruff check app/stories tests/stories
git diff --check
cd ..
git add backend/app/stories backend/app/jobs/handlers.py backend/app/jobs/registry.py backend/app/jobs/types.py backend/tests/stories backend/tests/test_job_handler_registry.py
git commit -m "feat: group stories with immutable evidence"
```

Expected: all focused tests pass, Ruff passes, and the commit contains only story grouping/evidence and job-registration files.

---

### Task 2: Evaluate completeness and enforce claim-level citation integrity

**Files:**
- Modify: `backend/app/research/__init__.py`
- Create: `backend/app/research/schemas.py`
- Create: `backend/app/research/completeness.py`
- Create: `backend/app/research/citations.py`
- Create: `backend/tests/research/test_completeness.py`
- Create: `backend/tests/research/test_citations.py`

**Interfaces:**
- Consumes: Task 1 `EvidenceRecord` values mapped from immutable snapshots and `build_evidence_key()`.
- Produces: `CompletenessReport`, `ResearchBudget`, database-free `DiscoveredSourcePayload`/`CandidateResearchBrief`, persisted `ResearchBrief`, `CitationRef`, `resolve_candidate_brief()`, `evaluate_completeness()`, and `validate_citations()`.

- [ ] **Step 1: Write failing completeness tests**

```python
def test_completeness_reports_every_deterministic_gap():
    report = evaluate_completeness(
        [evidence(source="Example Blog", content_text="short", primary=False)],
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
            evidence(source="Official release", content_text="a" * 500, primary=True),
            evidence(source="Independent report", content_text="b" * 500, primary=False),
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


class ResearchBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_model_calls: int = Field(default=6, ge=1, le=12)
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_cost_usd: Decimal = Field(default=Decimal("2.00"), ge=Decimal("0"), le=Decimal("50"))
    max_queries: int = Field(default=4, ge=1, le=8)
    max_results_per_query: int = Field(default=5, ge=1, le=10)
    max_pages: int = Field(default=8, ge=1, le=16)
    max_elapsed_seconds: int = Field(default=120, ge=10, le=600)
    max_total_chars: int = Field(default=120_000, ge=10_000, le=500_000)


class DiscoveredSourcePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str = Field(pattern=r"^url:https?://.+:[0-9a-f]{64}$", max_length=2_300)
    url: HttpUrl
    title: str | None = Field(default=None, max_length=500)
    publisher: str | None = Field(default=None, max_length=300)
    published_at: datetime | None = None
    retrieved_at: datetime
    content_text: str = Field(min_length=1, max_length=500_000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction_status: Literal["ok", "fallback"]

    @model_validator(mode="after")
    def evidence_key_matches_materialized_content(self) -> "DiscoveredSourcePayload":
        expected = build_evidence_key(
            content_item_id=None,
            source_url=str(self.url),
            content_sha256=self.content_sha256,
        )
        if self.evidence_key != expected:
            raise ValueError("evidence_key does not match normalized URL and content hash")
        return self


class CandidateCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str = Field(min_length=1, max_length=2_300)
    locator: str = Field(min_length=1, max_length=240)
    excerpt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CandidateClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1)
    citations: list[CandidateCitation] = Field(min_length=1)


class CandidateResearchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    verified_facts: list[CandidateClaim]
    disagreements: list[CandidateClaim]
    missing_information: list[str]
    suggested_angles: list[str]
    discovered_evidence_keys: list[str]


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str
    evidence_snapshot_id: UUID
    source_url: HttpUrl | None
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

`DiscoveredSourcePayload` is the only fetched-source DTO accepted from a backend. It deliberately has no ORM ID. Every key uses the locked Release 1 forms and precedence: `content-item:<content_item_id>:<content_sha256>` when a content item exists, otherwise `url:<normalized_source_url>:<content_sha256>` when a truthful URL exists, otherwise `operator-text:<content_sha256>`. Existing input evidence is exposed as Task 1 `EvidenceRecord`; every safely fetched discovery uses the `url:` form. A candidate brief may cite only a key present in the request evidence or its returned source list. Because the URL key includes `content_sha256`, fetching changed content at the same normalized URL yields a distinct immutable evidence key and snapshot.

- [ ] **Step 3: Run tests to verify missing implementations fail**

Run:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_completeness.py tests/research/test_citations.py -q
```

Expected: tests fail because completeness and citation functions do not yet exist.

- [ ] **Step 4: Implement completeness and citation validation**

Add tests proving a candidate payload containing `evidence_snapshot_id` is rejected as an extra field, a null-source operator snapshot resolves without inventing a URL, an unknown `evidence_key` fails, a changed fetched body fails its excerpt checksum, and a fully materialized candidate maps to the persisted UUID supplied by the handler.

`resolve_candidate_brief()` and `validate_citations()` return persisted citations or raise typed errors:

```python
class CitationIntegrityError(ValueError):
    pass


def resolve_candidate_brief(
    candidate: CandidateResearchBrief,
    evidence_by_key: Mapping[str, EvidenceRecord],
    discovered_source_ids: Mapping[str, UUID],
) -> ResearchBrief:
    return ResearchBrief(
        summary=candidate.summary,
        verified_facts=[resolve_candidate_claim(value, evidence_by_key) for value in candidate.verified_facts],
        disagreements=[resolve_candidate_claim(value, evidence_by_key) for value in candidate.disagreements],
        missing_information=candidate.missing_information,
        suggested_angles=candidate.suggested_angles,
        discovered_source_ids=[discovered_source_ids[key] for key in candidate.discovered_evidence_keys],
    )


def validate_citations(claims: Sequence[Claim], snapshots: Mapping[UUID, EvidenceRecord]) -> list[Claim]:
    for claim in claims:
        if not claim.citations:
            raise CitationIntegrityError("claim has no citations")
        for citation in claim.citations:
            snapshot = snapshots.get(citation.evidence_snapshot_id)
            if snapshot is None:
                raise CitationIntegrityError(f"unknown evidence snapshot: {citation.evidence_snapshot_id}")
            if citation.evidence_key != snapshot.evidence_key:
                raise CitationIntegrityError("citation evidence key does not match snapshot")
            citation_url = normalize_url(str(citation.source_url)) if citation.source_url else None
            snapshot_url = normalize_url(snapshot.source_url) if snapshot.source_url else None
            if citation_url != snapshot_url:
                raise CitationIntegrityError("citation URL does not match evidence snapshot")
            excerpt = resolve_locator(snapshot.content_text, citation.locator)
            if hashlib.sha256(excerpt.encode()).hexdigest() != citation.excerpt_sha256:
                raise CitationIntegrityError("citation excerpt hash does not match evidence")
    return list(claims)
```

`resolve_candidate_claim()` looks up every candidate `evidence_key`, resolves `chars:<start>-<end>` against `EvidenceRecord.content_text`, verifies `excerpt_sha256`, and emits a `CitationRef` using the record's exact `evidence_snapshot_id`, `evidence_key`, nullable `source_url`, plus the candidate locator and excerpt checksum. Use locators of the exact form `chars:<start>-<end>`, with `0 <= start < end <= len(content_text)`. Do not accept free-form quotations or provider-supplied database UUIDs as evidence.

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
- Modify: `backend/app/stories/handlers.py`
- Create: `backend/app/api/stories.py`
- Modify: `backend/app/stories/schemas.py`
- Modify: `backend/app/jobs/types.py`
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

    monkeypatch.setattr("app.stories.manual_intake.extract_article", forbidden_fetch)
    response = await client.post(
        "/stories/manual",
        json={"kind": "url", "url": "https://example.com/report", "title": "Optional title"},
    )
    assert response.status_code == 202
    assert set(response.json()) == {"job_id", "status", "deduplicated"}
    assert response.json()["status"] == "queued"
    assert response.json()["deduplicated"] is False
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
    snapshot = (await StoryRepository(db_session).list_evidence(story.id))[0]
    assert snapshot.content_text.startswith("Confirmed source")
    assert snapshot.source_url is None
    assert snapshot.evidence_key == build_evidence_key(
        content_item_id=snapshot.content_item_id,
        source_url=None,
        content_sha256=snapshot.content_sha256,
    )


async def test_manual_url_job_records_input_and_extraction_truth_without_inventing_http_payload(
    db_session, run_job, monkeypatch
):
    extracted = ExtractedArticle(
        url="https://example.com/report",
        final_url="https://example.com/report",
        title="Report",
        summary="Summary",
        content_text="Verified extracted report body long enough to retain.",
        content_html=None,
        author="Reporter",
        published_at=None,
        image_url=None,
        extraction_status="ok",
        extraction_warnings=[],
    )
    monkeypatch.setattr("app.stories.manual_intake.extract_article", AsyncMock(return_value=extracted))
    job = await enqueue_manual_url(db_session, "https://example.com/report")
    await run_job(job.id)
    raw = await raw_payload_for_job(job.id)
    snapshot = await evidence_for_job(job.id)
    assert raw.payload_kind == "manual_url_input"
    assert raw.request_url == "https://example.com/report"
    assert raw.http_status is None
    assert raw.raw_text is None
    assert snapshot.content_text == extracted.content_text
    assert snapshot.source_url == "https://example.com/report"
    assert snapshot.evidence_key == build_evidence_key(
        content_item_id=snapshot.content_item_id,
        source_url=snapshot.source_url,
        content_sha256=snapshot.content_sha256,
    )
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
    context.session.add(
        WorkflowEvent(
            workflow_job_id=job.id,
            event_type="manual_intake.completed",
            actor="worker",
            event_data={"story_id": str(story.id)},
        )
    )
    return {"story_id": str(story.id)}
```

For URL intake, `manual_discovery_item()` builds a `DiscoveryItem` with the submitted URL/title and no invented publisher fields. Persist `RawPayload(payload_kind="manual_url_input", request_url=submitted_url, final_url=extracted.final_url, http_status=None, raw_text=None)` because the existing `extract_article()` contract does not expose raw response status/body; store extraction status/warnings in metadata instead of inventing transport truth. Normalize the returned extraction into `ContentItem`/`SourceItem`, then snapshot its exact `content_text`, `content_sha256`, and final nullable URL. A fetch/extraction failure raises the Release 1 typed job error with `JobErrorClass.NEEDS_REVIEW`; no empty story is created.

For text intake, persist `RawPayload(payload_kind="manual_text_input", request_url="manual://operator", final_url=None, http_status=None, raw_text=request.text)`, a manual `ContentItem`/`SourceItem`, and an evidence snapshot whose `source_url` remains `None` unless the operator supplied one. Store `source_label` as operator provenance, never as a fetched publisher. Register with `registry.register("manual_intake", handle_manual_intake)` inside `build_default_registry()`.

- [ ] **Step 5: Run focused and regression tests, then commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/stories/test_manual_intake.py tests/api/test_story_routes.py tests/test_article_extractor.py -q
.venv/bin/ruff check app/stories app/api/stories.py tests/stories tests/api/test_story_routes.py
git diff --check
cd ..
git add backend/app/stories backend/app/api/stories.py backend/app/jobs/types.py backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/stories backend/tests/api/test_story_routes.py
git commit -m "feat: add durable manual story intake"
```

Expected: focused and article extraction regression tests pass.

---

### Task 4: Define the two-phase research contract, safe materializer, and deterministic fake

**Files:**
- Create: `backend/app/research/base.py`
- Create: `backend/app/research/fake.py`
- Create: `backend/app/research/prompts.py`
- Create: `backend/app/research/safe_fetch.py`
- Create: `backend/tests/research/test_provider_contract.py`
- Create: `backend/tests/research/test_safe_fetch.py`
- Create: `backend/tests/fixtures/research_brief.json`

**Interfaces:**
- Consumes: Task 1 `EvidenceRecord` and `build_evidence_key()`; Task 2 `ResearchBudget`, `DiscoveredSourcePayload`, and `CandidateResearchBrief`; enabled Release 1 `AIProviderProfile` rows resolved by the service.
- Produces: database-free `ResearchRequest`, `ResearchBackendOutput`, `ResearchResult`, `ResearchBackend`, `SafeArticleFetcher`, `FakeResearchBackend`, and `build_research_prompt()`.

- [ ] **Step 1: Write a parameterized provider contract test**

```python
@pytest.mark.parametrize("backend_factory", [FakeResearchBackend])
async def test_research_backend_returns_validated_brief_with_resolved_model(backend_factory, evidence_records):
    request = ResearchRequest(
        run_id=uuid4(),
        story_id=uuid4(),
        provider_profile_id=uuid4(),
        requested_model="fixture-v1",
        mode="manual",
        query_hint="Verify the announced release date",
        evidence=evidence_records,
        budget=ResearchBudget(max_model_calls=1, max_input_tokens=2_000, max_output_tokens=1_000),
    )
    backend = backend_factory.from_fixture("tests/fixtures/research_brief.json")
    result = await backend.research(request)
    assert result.provider_profile_id == request.provider_profile_id
    assert result.provider_type == "fake"
    assert result.requested_model == "fixture-v1"
    assert result.resolved_model == "fixture-v1"
    assert result.output.brief.verified_facts[0].citations
    assert all(
        source.evidence_key == f"url:{normalize_url(str(source.url))}:{source.content_sha256}"
        for source in result.output.sources
    )
    assert result.usage.model_calls == 1
    assert result.elapsed_ms >= 0
    assert not hasattr(backend, "session")
```

Create `backend/tests/research/test_safe_fetch.py` with the public-network rejection matrix (`127.0.0.1`, `localhost`, link-local metadata, RFC1918, IPv6 loopback, `file:`), redirect re-resolution, five-redirect limit, 5 MiB byte cap, extraction failure, and this successful materialization assertion:

```python
async def test_safe_fetch_returns_complete_database_free_source(public_resolver, article_transport):
    source = await SafeArticleFetcher(resolver=public_resolver, transport=article_transport).fetch(
        "https://news.example/report"
    )
    assert source.url == "https://news.example/report"
    assert source.retrieved_at.tzinfo is not None
    assert source.content_text == "Fetched article body"
    assert source.content_sha256 == sha256(source.content_text.encode()).hexdigest()
    assert source.evidence_key == f"url:{normalize_url(str(source.url))}:{source.content_sha256}"
    assert "evidence_snapshot_id" not in source.model_dump()


async def test_same_url_with_changed_content_creates_a_new_evidence_key(public_resolver, article_transport):
    article_transport.queue_article("Version one article body", "Version two article body")
    fetcher = SafeArticleFetcher(resolver=public_resolver, transport=article_transport)
    first = await fetcher.fetch("https://news.example/report")
    second = await fetcher.fetch("https://news.example/report")
    assert first.url == second.url
    assert first.content_sha256 != second.content_sha256
    assert first.evidence_key == f"url:{normalize_url(str(first.url))}:{first.content_sha256}"
    assert second.evidence_key == f"url:{normalize_url(str(second.url))}:{second.content_sha256}"
    assert first.evidence_key != second.evidence_key
```

- [ ] **Step 2: Run the test and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_provider_contract.py tests/research/test_safe_fetch.py -q
```

Expected: import failure for `app.research.base`.

- [ ] **Step 3: Implement the exact protocol and fake**

```python
class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID
    story_id: UUID
    provider_profile_id: UUID
    requested_model: str
    mode: Literal["manual", "auto_if_incomplete"]
    depth: Literal["standard", "deep"] = "standard"
    query_hint: str | None = Field(default=None, max_length=500)
    evidence: list[EvidenceRecord] = Field(min_length=1)
    budget: ResearchBudget


class ResearchBackendOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sources: list[DiscoveredSourcePayload]
    brief: CandidateResearchBrief


class ResearchUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    estimated_cost_usd: Decimal = Field(ge=Decimal("0"))
    queries: int = Field(ge=0)
    pages: int = Field(ge=0)
    fetched_characters: int = Field(ge=0)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_profile_id: UUID
    provider_type: Literal["fake", "codex", "openrouter"]
    requested_model: str
    resolved_model: str
    output: ResearchBackendOutput
    usage: ResearchUsage
    elapsed_ms: int = Field(ge=0)
    sanitized_events: list[dict[str, object]]


class ResearchBackend(Protocol):
    name: str

    async def research(self, request: ResearchRequest) -> ResearchResult:
        raise NotImplementedError
```

`ResearchBackend` implementations accept only value objects and injected I/O adapters; importing SQLAlchemy or accepting an `AsyncSession`/repository is a contract-test failure. The fake reads a checked-in `ResearchBackendOutput` fixture whose discovered-source keys use `url:<normalized_source_url>:<content_sha256>`, validates it, reports one bounded fake model call, and never performs network, subprocess, or database I/O.

`SafeArticleFetcher` re-resolves every redirect hop, permits only public `http`/`https` addresses, allows at most five redirects, caps response bytes at 5 MiB, extracts normalized article text, and returns `DiscoveredSourcePayload`. It stores the accepted final URL as `source_url`, first computes `content_sha256` from the returned `content_text`, then computes `evidence_key` exactly as `url:<normalized_source_url>:<content_sha256>`; it never trusts provider-supplied body/hash/key values and never persists anything. The URL plus body hash—not URL alone—is the immutable discovery identity.

- [ ] **Step 4: Run the contract test and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_provider_contract.py tests/research/test_safe_fetch.py -q
.venv/bin/ruff check app/research tests/research
git diff --check
cd ..
git add backend/app/research backend/tests/research backend/tests/fixtures/research_brief.json
git commit -m "feat: define research backend contract"
```

Expected: provider and public-network materialization contracts pass without database or internet access.

---

### Task 5: Add constrained Codex CLI research and generation adapters

**Files:**
- Create: `backend/app/core/codex_exec.py`
- Create: `backend/app/research/codex_adapter.py`
- Create: `backend/app/generation/providers/codex.py`
- Modify: `backend/app/generation/providers/registry.py`
- Modify: `backend/app/generation/provider_settings.py`
- Modify: `backend/app/api/generation_schemas.py`
- Modify: `backend/app/api/generation_settings.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/research/test_codex_adapter.py`
- Modify: `backend/tests/research/test_provider_contract.py`
- Create: `backend/tests/generation/test_codex_provider.py`
- Modify: `backend/tests/test_generation_settings_api.py`

**Interfaces:**
- Consumes: Task 4 database-free research contracts, `SafeArticleFetcher`, Release 1 `AIProviderProfile`/`GenerationProviderRequest/Result`, and the locally installed `codex` executable.
- Produces: budgeted `CodexExecutor`, database-free `CodexResearchBackend`, profile-resolved `CodexGenerationProvider`, and `build_codex_environment()`.

- [ ] **Step 1: Write failing command, secret isolation, schema, and timeout tests**

```python
def option_values(argv: list[str], option: str) -> list[str]:
    return [argv[index + 1] for index, value in enumerate(argv[:-1]) if value == option]


async def test_codex_uses_isolated_reproducible_command(fake_process, request):
    backend = CodexResearchBackend(
        executor=CodexExecutor(process_runner=fake_process, executable="codex"),
        fetcher=fake_safe_fetcher(),
    )
    await backend.research(request)
    assert fake_process.argv[:4] == ["codex", "exec", "--ephemeral", "--json"]
    assert "--output-schema" in fake_process.argv
    assert ["--sandbox", "read-only"] == fake_process.argv[fake_process.argv.index("--sandbox"):][:2]
    assert "--ignore-user-config" in fake_process.argv
    assert "--skip-git-repo-check" in fake_process.argv
    assert "--ignore-rules" in fake_process.argv
    assert option_values(fake_process.argv, "--model") == [request.requested_model]
    assert option_values(fake_process.argv, "-c") == ['shell_environment_policy.inherit="none"']
    assert option_values(fake_process.argv, "--enable") == ["browser_use"]
    assert set(option_values(fake_process.argv, "--disable")) == {
        "shell_tool",
        "code_mode_host",
        "computer_use",
        "apps",
        "browser_use_external",
        "browser_use_full_cdp_access",
    }
    assert fake_process.cwd != Path.cwd()


async def test_codex_generation_disables_every_agentic_or_browser_capability(fake_process, generation_budget):
    await CodexExecutor(process_runner=fake_process, executable="codex").run(
        "Generate locked output",
        response_schema=TELEGRAM_SCHEMA,
        budget=generation_budget,
        resolved_model="gpt-5.4",
        allow_web=False,
    )
    assert option_values(fake_process.argv, "--enable") == []
    assert set(option_values(fake_process.argv, "--disable")) == {
        "shell_tool",
        "code_mode_host",
        "computer_use",
        "apps",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
    }
    assert option_values(fake_process.argv, "--model") == ["gpt-5.4"]


def test_codex_environment_uses_temporary_home_and_exact_auth_allowlist(tmp_path):
    source = {
        "PATH": "/usr/bin",
        "HOME": "/home/operator",
        "CODEX_HOME": "/home/operator/.codex",
        "OPENAI_API_KEY": "codex-auth",
        "TELEGRAM_DESTINATION_NEWS_TOKEN": "secret",
        "DATABASE_URL": "postgresql://secret",
        "OPENROUTER_API_KEY": "secret",
    }
    env = build_codex_environment(source, work_dir=tmp_path)
    assert env == {
        "PATH": "/usr/bin",
        "HOME": str(tmp_path),
        "CODEX_HOME": "/home/operator/.codex",
        "OPENAI_API_KEY": "codex-auth",
    }


async def test_codex_timeout_terminates_process_and_returns_retryable_error(hanging_process, request):
    backend = CodexResearchBackend(
        executor=CodexExecutor(process_runner=hanging_process, executable="codex", timeout_seconds=1),
        fetcher=fake_safe_fetcher(),
    )
    with pytest.raises(ResearchBackendError, match="codex timed out") as error:
        await backend.research(request)
    assert error.value.classification == "retryable"
    assert hanging_process.terminated is True


async def test_codex_materializes_urls_and_returns_evidence_keys_not_database_ids(fake_codex_executor, safe_fetcher, request):
    fake_codex_executor.output = raw_codex_output(
        source_url="https://news.example/report",
        citation_source_url="https://news.example/report",
        quote="verified excerpt",
    )
    result = await CodexResearchBackend(executor=fake_codex_executor, fetcher=safe_fetcher).research(request)
    source = result.output.sources[0]
    citation = result.output.brief.verified_facts[0].citations[0]
    assert source.content_text == "safe fetched body with verified excerpt"
    assert source.content_sha256 == sha256(source.content_text.encode()).hexdigest()
    assert source.evidence_key == f"url:{normalize_url(str(source.url))}:{source.content_sha256}"
    assert citation.evidence_key == source.evidence_key
    assert citation.locator == "chars:23-39"
    assert "evidence_snapshot_id" not in result.model_dump_json()


async def test_codex_enforces_one_model_call_and_total_token_budget(fake_process, request):
    request = request.model_copy(
        update={"budget": request.budget.model_copy(update={"max_model_calls": 1, "max_input_tokens": 100, "max_output_tokens": 50})}
    )
    fake_process.events = [usage_event(input_tokens=90, output_tokens=20)]
    with pytest.raises(ResearchBudgetExceeded, match="token budget exceeded"):
        await CodexResearchBackend(
            executor=CodexExecutor(process_runner=fake_process, executable="codex"),
            fetcher=fake_safe_fetcher(),
        ).research(request)
    assert fake_process.spawn_count == 1


async def test_codex_generation_uses_the_requested_schema_and_provider_contract(fake_codex_executor, generation_request):
    profile = ai_provider_profile(
        provider_type="codex",
        default_model="gpt-5.4",
        enabled=True,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )
    generation_request = replace(
        generation_request,
        metadata={
            **generation_request.metadata,
            "provider_profile_id": str(profile.id),
        },
    )
    provider = CodexGenerationProvider(executor=fake_codex_executor, profile=profile)
    result = await provider.generate(generation_request)
    assert fake_codex_executor.response_schema == generation_request.response_schema
    assert result.provider == "codex"
    assert result.output == fake_codex_executor.structured_output
    assert result.usage["codex_cli_version"] == fake_codex_executor.version
    assert fake_codex_executor.allow_web is False
    assert fake_codex_executor.resolved_model == "gpt-5.4"
    assert fake_codex_executor.budget.max_model_calls == 1
    assert fake_codex_executor.budget.max_output_tokens == 12_000


async def test_codex_provider_profile_seed_is_idempotent_and_contains_no_secret(fake_session):
    first = await seed_codex_provider_profile(fake_session, enabled=True)
    second = await seed_codex_provider_profile(fake_session, enabled=True)
    assert first.id == second.id
    assert first.provider_type == "codex"
    assert first.secret_ref is None
    assert CodexProviderSettings.model_validate(first.settings).research_budgets.deep.max_model_calls == 1


def test_codex_provider_settings_are_strict_and_contain_research_and_generation_limits():
    settings = default_codex_provider_settings()
    assert settings.research_budgets.standard.max_pages == 8
    assert settings.research_budgets.deep.max_pages == 16
    assert settings.generation_limits.max_model_calls == 1
    omitted = effective_codex_provider_settings(CodexProviderSettings.model_validate({}))
    assert omitted.research_budgets == settings.research_budgets
    assert omitted.generation_limits == settings.generation_limits
    with pytest.raises(ValidationError):
        CodexProviderSettings.model_validate({**settings.model_dump(), "base_url": "https://example.com"})


async def test_provider_capabilities_validate_settings_secret_and_executable(
    fake_session, fake_secret_resolver, fake_executable_resolver
):
    openrouter = await provider_profile(
        fake_session,
        provider_type="openrouter",
        default_model="model-a",
        secret_ref="OPENROUTER_API_KEY",
        settings=valid_openrouter_settings_with_pricing_and_budgets(),
    )
    codex = await provider_profile(
        fake_session,
        provider_type="codex",
        default_model="gpt-5.4",
        secret_ref=None,
        settings=default_codex_provider_settings().model_dump(mode="json"),
    )
    fake_secret_resolver.mark_configured("OPENROUTER_API_KEY")
    fake_executable_resolver.set("codex", "/usr/bin/codex")
    options = await list_provider_options(fake_session, fake_secret_resolver, fake_executable_resolver)
    assert options.by_id(openrouter.id).capabilities == {"generation": True, "research": True}
    assert options.by_id(codex.id).capabilities == {"generation": True, "research": True}
    fake_executable_resolver.set("codex", None)
    unavailable = await list_provider_options(fake_session, fake_secret_resolver, fake_executable_resolver)
    assert unavailable.by_id(codex.id).capabilities == {"generation": False, "research": False}
```

Extend generation-settings API tests to assert Codex profiles require no secret reference, reject extra/malformed `CodexProviderSettings`, apply server defaults when its nested limits are omitted, expose executable availability without leaking paths/environment details, and can be enabled/disabled like the other safe provider profiles. Fake profiles retain absent settings and receive server-default research budgets at resolution time. Reuse Release 2 `OpenRouterProviderSettings`; an OpenRouter profile is research-capable only when its secret/model are available and both `pricing` and `research_budgets` validate. OpenRouter generation may remain available when the optional research fields are absent.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_codex_adapter.py tests/generation/test_codex_provider.py -q
```

Expected: import failures for the shared executor and both adapters.

- [ ] **Step 3: Implement the constrained process boundary**

Import/re-export these Release 2 classes from `backend/app/generation/provider_settings.py` without renaming or creating JSON aliases: `ProviderPricingSettings(input_usd_per_million, output_usd_per_million)`, `ResearchBudgetSettings(max_model_calls, max_input_tokens, max_output_tokens, max_cost_usd, max_queries, max_results_per_query, max_pages, max_elapsed_seconds, max_total_chars)`, `ResearchBudgetsSettings(standard, deep)`, and `OpenRouterProviderSettings(base_url, timeout_seconds, http_referer, app_title, pricing, research_budgets)`. Add the exact Codex-only settings contract in that shared module; `app/api/generation_schemas.py` only imports/re-exports it for HTTP validation:

```python
class CodexGenerationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_model_calls: Literal[1] = 1
    max_input_tokens: int = Field(default=60_000, ge=1_000, le=500_000)
    max_output_tokens: int = Field(default=12_000, ge=500, le=100_000)
    max_elapsed_seconds: int = Field(default=180, ge=10, le=600)


class CodexProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    research_budgets: ResearchBudgetsSettings | None = None
    generation_limits: CodexGenerationLimits = Field(default_factory=CodexGenerationLimits)


def default_research_budgets() -> ResearchBudgetsSettings:
    return ResearchBudgetsSettings(
        standard=ResearchBudgetSettings(
            max_model_calls=1,
            max_input_tokens=60_000,
            max_output_tokens=12_000,
            max_cost_usd=Decimal("0"),
            max_queries=4,
            max_results_per_query=5,
            max_pages=8,
            max_elapsed_seconds=180,
            max_total_chars=120_000,
        ),
        deep=ResearchBudgetSettings(
            max_model_calls=1,
            max_input_tokens=120_000,
            max_output_tokens=24_000,
            max_cost_usd=Decimal("0"),
            max_queries=8,
            max_results_per_query=10,
            max_pages=16,
            max_elapsed_seconds=300,
            max_total_chars=250_000,
        ),
    )


def default_codex_provider_settings() -> CodexProviderSettings:
    return CodexProviderSettings(
        research_budgets=default_research_budgets(),
        generation_limits=CodexGenerationLimits(),
    )


def effective_codex_provider_settings(value: CodexProviderSettings) -> CodexProviderSettings:
    defaults = default_codex_provider_settings()
    return value.model_copy(
        update={
            "research_budgets": value.research_budgets or defaults.research_budgets,
            "generation_limits": value.generation_limits,
        }
    )
```

`AIProviderProfile.settings` is validated by provider type on create, patch, seed, option listing, research enqueue, and generation enqueue. Codex rejects any `secret_ref`, missing default model, missing executable, or malformed settings; omitted nested settings resolve through `effective_codex_provider_settings()` without mutating the stored profile. Fake profiles keep `settings={}`/absent and use the same server-default standard/deep research budgets. OpenRouter uses `settings.pricing.input_usd_per_million`/`output_usd_per_million` and `settings.research_budgets.standard/deep`; it never reads flat pricing/budget aliases or applies silent OpenRouter research defaults. Safe API options expose profile UUID/name/type/model plus boolean `capabilities.generation/research` and sanitized unavailability codes, never settings secrets or executable paths.

`CodexExecutor.run(prompt, response_schema, budget, *, resolved_model, allow_web) -> CodexExecutionResult` must construct this exact command, with generated absolute paths. `resolved_model` is required and never read from user configuration. The locally verified CLI exposes `--enable`/`--disable`; every invocation removes shell/code-host/computer-use/apps/external-browser/full-CDP capability, research enables only the built-in browser, and generation disables that browser too:

```python
disabled_features = [
    "shell_tool",
    "code_mode_host",
    "computer_use",
    "apps",
    "browser_use_external",
    "browser_use_full_cdp_access",
]
feature_args = [item for feature in disabled_features for item in ("--disable", feature)]
feature_args += ["--enable", "browser_use"] if allow_web else ["--disable", "browser_use"]
argv = [
    executable,
    "exec",
    "--ephemeral",
    "--json",
    "--model",
    resolved_model,
    "--output-schema",
    str(schema_path),
    "--sandbox",
    "read-only",
    "--ignore-user-config",
    "--skip-git-repo-check",
    "--ignore-rules",
    "-c",
    'shell_environment_policy.inherit="none"',
    *feature_args,
    "-C",
    str(work_dir),
    "-o",
    str(result_path),
    "-",
]
```

The raw Codex schema contains no database identifiers:

```python
class CodexSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    title: str | None = None
    publisher: str | None = None
    published_at: datetime | None = None


class CodexCandidateCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_key: str | None = Field(default=None, min_length=1, max_length=2_300)
    source_url: HttpUrl | None = None
    quote: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def references_exactly_one_evidence_input(self) -> "CodexCandidateCitation":
        if (self.evidence_key is None) == (self.source_url is None):
            raise ValueError("citation must reference one existing evidence key or one discovered source URL")
        return self
```

The executor writes that schema to `schema_path`, sends only the research prompt on stdin, returns validated JSON plus safe process metadata, and captures `codex --version`, exit code, elapsed milliseconds, redacted JSONL events, and token usage. It permits exactly one `codex exec` model call per research attempt. It terminates the process when cumulative reported input/output tokens cross `ResearchBudget.max_input_tokens`/`max_output_tokens`; if the installed CLI reports usage only at completion, it rejects the result as `needs_review` when over budget and records the overage. It rejects a result with missing token usage rather than treating unknown usage as zero.

`CodexResearchBackend` supplies the raw candidate schema and `build_research_prompt(request)` and invokes the executor with `resolved_model=request.requested_model, allow_web=True`. Raw discovered sources intentionally contain no evidence key because Codex cannot know the application extractor's content hash. Codex may browse through its explicitly enabled built-in browser capability, but every returned URL still passes through injected `SafeArticleFetcher`; the adapter ignores any provider-authored body/hash/key, assigns the exact `url:<normalized_source_url>:<content_sha256>` key returned by that fetcher, and rewrites a citation's `source_url` to that materialized key. A raw `evidence_key` citation is accepted only when it exactly names an existing `request.evidence` record. The adapter resolves each quoted excerpt against the corresponding persisted-input or safely fetched `content_text` and returns only `DiscoveredSourcePayload` plus `CandidateResearchBrief`. An unfetchable or unreturned source URL, quote not found exactly once, unknown existing evidence key, or over-budget call is `needs_review`. It never imports SQLAlchemy or persists a source/snapshot.

`CodexGenerationProvider` serializes locked provider messages as untrusted input, supplies `request.response_schema`, invokes the executor with `resolved_model=resolved_profile.model, allow_web=False`, and returns the exact Release 1 provider result. Generation can therefore rewrite only its locked input and cannot silently perform an untracked research pass. Generation orchestration loads the enabled `AIProviderProfile` named by `provider_profile_id`, verifies `provider_type="codex"`, takes the model/budget from that profile, and passes the profile ID in request metadata; the public API never sends `provider="codex"`.

`build_codex_environment(source, *, work_dir)` copies only `PATH`, `CODEX_HOME`, `OPENAI_API_KEY`, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `SSL_CERT_FILE`, `LANG`, and `LC_ALL` when present, ignores inherited `HOME`, and then sets `HOME=str(work_dir)`. `CODEX_HOME` is retained only so the CLI can authenticate; `--ignore-user-config` prevents its configuration from widening capabilities. Kill and await the process on timeout. Cap combined stdout/stderr capture at 1 MiB. Register `CodexGenerationProvider` internally beside fake/OpenRouter; orchestration resolves it only from the selected profile. Add global `codex_enabled` and `codex_executable` settings, then idempotently seed one no-secret `Codex CLI` profile with `default_codex_provider_settings().model_dump(mode="json")`. Availability resolves the executable at runtime but never returns its path.

- [ ] **Step 4: Run focused tests, an opt-in local contract check, and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_codex_adapter.py tests/research/test_provider_contract.py tests/generation/test_codex_provider.py tests/test_generation_provider_contract.py tests/test_generation_settings_api.py -q
.venv/bin/ruff check app/core/codex_exec.py app/research/codex_adapter.py app/generation/providers/codex.py app/api/generation_schemas.py app/api/generation_settings.py tests/research/test_codex_adapter.py tests/generation/test_codex_provider.py
if command -v codex >/dev/null; then codex --version; fi
git diff --check
cd ..
git add backend/app/core/codex_exec.py backend/app/research/codex_adapter.py backend/app/generation/provider_settings.py backend/app/generation/providers/codex.py backend/app/generation/providers/registry.py backend/app/api/generation_schemas.py backend/app/api/generation_settings.py backend/app/core/config.py backend/app/main.py backend/tests/research/test_codex_adapter.py backend/tests/research/test_provider_contract.py backend/tests/generation/test_codex_provider.py backend/tests/test_generation_settings_api.py
git commit -m "feat: add constrained Codex research and generation"
```

Expected: deterministic tests pass. The version command may report a local Codex version but performs no research and uses no credentials.

---

### Task 6: Add bounded DuckDuckGo search and the OpenRouter research loop

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/research/duckduckgo.py`
- Create: `backend/app/research/openrouter_loop.py`
- Create: `backend/tests/research/test_duckduckgo.py`
- Create: `backend/tests/research/test_openrouter_loop.py`
- Modify: `backend/tests/research/test_provider_contract.py`

**Interfaces:**
- Consumes: Task 2 `ResearchBudget`; Task 4 research DTOs/`SafeArticleFetcher`; a configured Release 1 `AIProviderProfile`; and Release 2 `OpenRouterProviderSettings`, `ProviderPricingSettings`, and `ResearchBudgetsSettings` resolved to the Release 2 OpenRouter HTTP transport.
- Produces: `SearchResult`, `DuckDuckGoSearchClient`, database-free `OpenRouterResearchBackend`, and a controlled `search -> fetch -> finish` DTO loop.

- [ ] **Step 1: Add the DuckDuckGo dependency and write failing budget tests**

Add one runtime dependency:

```toml
"ddgs>=9.0,<10",
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
        profile=openrouter_profile(),
    )
    result = await backend.research(
        request(budget=ResearchBudget(max_queries=1, max_results_per_query=5, max_pages=1, max_elapsed_seconds=120, max_total_chars=120_000))
    )
    assert fake_search.queries == ["agent release"]
    assert fake_fetch.urls == ["https://one.example/report"]
    assert result.sanitized_events[-1]["budget_exhausted"] is True


async def test_final_answer_cannot_cite_search_result_that_was_not_fetched(scripted_model, fake_search, fake_fetch):
    backend = backend_with(scripted_model.finish(brief_citing("https://unfetched.example/story")), fake_search, fake_fetch)
    with pytest.raises(ResearchBackendError, match="citation URL was not fetched") as error:
        await backend.research(request())
    assert error.value.classification == "needs_review"


async def test_loop_enforces_model_call_token_and_cost_budgets(scripted_model, fake_search, fake_fetch):
    backend = backend_with(
        scripted_model.actions(search("agent release"), finish(valid_candidate_brief())),
        fake_search,
        fake_fetch,
        profile=openrouter_profile(
            settings=valid_openrouter_settings_with_pricing_and_budgets(
                input_usd_per_million="1.00",
                output_usd_per_million="2.00",
            )
        ),
    )
    budget = ResearchBudget(
        max_model_calls=1,
        max_input_tokens=1_000,
        max_output_tokens=500,
        max_cost_usd=Decimal("0.001"),
    )
    with pytest.raises(ResearchBudgetExceeded, match="cost budget exhausted"):
        await backend.research(request(budget=budget))
    assert scripted_model.call_count == 1


def test_duckduckgo_client_forces_the_real_duckduckgo_backend(monkeypatch):
    calls: list[dict[str, object]] = []

    class FakeDDGS:
        def text(self, query: str, **kwargs):
            calls.append({"query": query, **kwargs})
            return [{"title": "Result", "href": "https://example.com/report", "body": "Snippet"}]

    monkeypatch.setattr("app.research.duckduckgo.DDGS", FakeDDGS)
    results = asyncio.run(DuckDuckGoSearchClient().search("agent release", limit=5))
    assert calls == [{"query": "agent release", "backend": "duckduckgo", "max_results": 5}]
    assert results[0].url == "https://example.com/report"
```

- [ ] **Step 2: Run tests and verify failure**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research/test_duckduckgo.py tests/research/test_openrouter_loop.py -q
```

Expected: import failures for the new search/fetch/loop modules.

- [ ] **Step 3: Implement exact budgets, actions, and pure DTO boundary**

```python
class SearchAction(BaseModel):
    action: Literal["search"]
    query: str = Field(min_length=2, max_length=200)


class FetchAction(BaseModel):
    action: Literal["fetch"]
    url: HttpUrl


class FinishAction(BaseModel):
    action: Literal["finish"]
    brief: CandidateResearchBrief
```

`DuckDuckGoSearchClient.search()` calls `DDGS().text(query, backend="duckduckgo", max_results=limit)` through `asyncio.to_thread`, normalizes results to title/URL/snippet, removes duplicate normalized URLs, and never marks a search hit fetched. Do not use `backend="auto"`, Bing, Brave, Mojeek, or an omitted backend.

`OpenRouterResearchBackend` is constructed only after the service loads an enabled `AIProviderProfile`, verifies `provider_type="openrouter"`, validates its settings with the Release 2 `OpenRouterProviderSettings`, resolves its secret reference/model, selects `settings.research_budgets[request.depth]`, and reads rates only from `settings.pricing.input_usd_per_million` and `settings.pricing.output_usd_per_million`. Missing pricing or research budgets makes that profile unavailable for research before enqueue; flat aliases are forbidden. It sends request evidence plus successful search/fetch observations to the model and returns `ResearchBackendOutput`; it has no session/repository and never persists `ResearchSource`, `StoryEvidenceSnapshot`, or `StoryRevision`.

Before every action/model call, atomically check remaining `max_model_calls`, input/output tokens, estimated USD cost, queries, pages, elapsed time, and fetched characters. Pass the remaining output-token allowance to OpenRouter. After every response, require usage counts, accumulate exact input/output tokens, compute cost from profile rates, and stop with `ResearchBudgetExceeded` before another call when any limit is exhausted. Unknown usage or rates are `needs_review`, never zero cost. Permit at most 12 total actions inside the stricter model-call/query/page budgets.

Every selected URL passes through Task 4 `SafeArticleFetcher`; only its returned `DiscoveredSourcePayload` is shown back to the model. The finish action returns `CandidateResearchBrief` citing stable evidence keys. Validate locators/hashes against input evidence plus safely fetched DTOs. A forbidden/unfetched URL becomes a sanitized observation and can never appear in final citations.

- [ ] **Step 4: Run tests and commit**

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
- Modify: `backend/app/api/telegram_schemas.py`
- Modify: `backend/app/api/telegram_automations.py`
- Modify: `backend/app/automations/telegram/handlers.py`
- Modify: `backend/app/jobs/types.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/app/api/routes.py`
- Create: `backend/tests/research/test_service.py`
- Create: `backend/tests/research/test_handlers.py`
- Modify: `backend/tests/api/test_story_routes.py`
- Create: `backend/tests/research/test_telegram_route_research.py`

**Interfaces:**
- Consumes: Tasks 2, 4, 5, and 6; enabled Release 1 `AIProviderProfile` rows; Release 1 jobs/events/attempts.
- Produces: sole atomic research persistence boundary, story list/editorial-state/grouping APIs, `ResearchService.request()`, job kind `research_story`, profile-ID Telegram research policies/continuation, `POST /stories/{story_id}/research-runs`, `GET /stories/{story_id}/research-runs`, and `GET /research-runs/{run_id}`.

- [ ] **Step 1: Write failing policy and lifecycle tests**

```python
async def test_off_mode_never_enqueues_research(db_session, complete_story):
    result = await ResearchService(db_session).request(
        story_id=complete_story.id,
        mode="off",
        depth="standard",
        provider_profile_id=None,
        query_hint=None,
    )
    assert result.disposition == "skipped"
    assert result.job_id is None


async def test_auto_mode_enqueues_only_when_incomplete(db_session, incomplete_story, complete_story):
    service = ResearchService(db_session)
    profile = await enabled_provider_profile(db_session, provider_type="fake")
    incomplete = await service.request(
        story_id=incomplete_story.id,
        mode="auto_if_incomplete",
        depth="standard",
        provider_profile_id=profile.id,
        query_hint=None,
    )
    complete = await service.request(
        story_id=complete_story.id,
        mode="auto_if_incomplete",
        depth="standard",
        provider_profile_id=profile.id,
        query_hint=None,
    )
    assert incomplete.disposition == "enqueued"
    assert complete.disposition == "complete_without_research"


async def test_research_depth_uses_selected_profiles_nested_budget_without_flat_aliases(db_session, incomplete_story):
    profile = await enabled_openrouter_profile(
        db_session,
        settings=valid_openrouter_settings_with_pricing_and_budgets(),
    )
    result = await ResearchService(db_session).request(
        story_id=incomplete_story.id,
        mode="manual",
        depth="deep",
        provider_profile_id=profile.id,
        query_hint=None,
    )
    payload = await workflow_job_payload(db_session, result.job_id)
    expected = OpenRouterProviderSettings.model_validate(profile.settings).research_budgets.deep
    assert payload["budget"] == expected.model_dump(mode="json")
    assert "max_model_calls" not in profile.settings
    assert "input_cost_per_million" not in profile.settings


async def test_research_handler_records_attempt_sources_revision_and_event(run_job, queued_research):
    await run_job(queued_research.job_id)
    detail = await ResearchService(queued_research.session).get_run(queued_research.run_id)
    assert detail.status == "succeeded"
    assert len(detail.attempts) == 1
    assert detail.result_revision_id is not None
    assert detail.events[-1].event_type == "research.succeeded"


async def test_handler_alone_persists_sources_snapshots_and_resolves_keys_atomically(
    db_session, run_job, queued_research
):
    source_url = "https://news.example/report"
    content_text = "Fetched evidence with exact cited phrase."
    content_sha256 = sha256(content_text.encode()).hexdigest()
    queued_research.backend.output = output_with_source_and_candidate_citation(
        evidence_key=f"url:{normalize_url(source_url)}:{content_sha256}",
        url=source_url,
        content_text=content_text,
        locator="chars:28-40",
    )
    await run_job(queued_research.job_id)
    source = await research_source_for_run(db_session, queued_research.run_id)
    snapshot = await snapshot_for_evidence_key(db_session, queued_research.story_id, source.citation_key)
    revision = await result_revision(db_session, queued_research.run_id)
    assert source.content_sha256 == snapshot.content_sha256
    assert snapshot.content_text == content_text
    assert revision.citations[0]["evidence_snapshot_id"] == str(snapshot.id)
    assert revision.citations[0]["evidence_key"] == source.citation_key


async def test_unknown_candidate_key_rolls_back_all_research_materialization(db_session, run_job, queued_research):
    queued_research.backend.output = output_citing_unknown_key()
    await run_job(queued_research.job_id)
    assert await research_source_count(db_session, queued_research.run_id) == 0
    assert await research_snapshot_count(db_session, queued_research.run_id) == 0
    assert await result_revision(db_session, queued_research.run_id) is None
    assert (await ResearchService(db_session).get_run(queued_research.run_id)).status == "needs_review"
```

In `backend/tests/api/test_story_routes.py`, also assert `GET /stories` filters/paginates active grouped stories, `POST /stories/group-pending` returns HTTP 202 without grouping inside the request, `PATCH /stories/{id}/editorial-state` transitions one active story, and `POST /stories/bulk-editorial-state` updates a bounded set atomically. Assert a superseded story returns 409, invalid state returns 422, and every successful transition appends a sanitized workflow event.

Create `backend/tests/research/test_telegram_route_research.py` proving: `off` stores no research profile; `manual` stores an enabled `research_provider_profile_id` but never researches automatically and leaves a review action; `auto_if_incomplete` requires an enabled profile ID and skips research for a complete story; an incomplete story enqueues one research job containing that UUID and performs no generation/publish call; successful research enqueues one deterministic `telegram.route.process` continuation; and failed/needs-review research leaves the dispatch in review without auto-publishing.

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
    provider_profile_id: UUID
    query_hint: str | None = Field(default=None, max_length=500)


class ResearchDisposition(BaseModel):
    disposition: Literal["skipped", "complete_without_research", "enqueued"]
    run_id: UUID | None
    job_id: UUID | None
    completeness: CompletenessReport
```

`ResearchService.request()` accepts keyword-only `story_id`, `mode`, `depth`, `provider_profile_id`, and `query_hint`. `off` requires `provider_profile_id=None`. Manual/auto modes load the exact enabled `AIProviderProfile`, reject unavailable profiles, resolve provider type/model/secret server-side, and validate the provider-specific settings schema. OpenRouter selects `OpenRouterProviderSettings.research_budgets.standard/deep` and requires `pricing`; Codex selects the configured or server-default `CodexProviderSettings.research_budgets.standard/deep` and requires the executable; fake uses the same server-default standard/deep budgets while keeping profile settings absent. Convert the selected `ResearchBudgetSettings` to the Task 2 runtime `ResearchBudget`; request bodies cannot override profile ceilings and flat setting aliases are rejected. It snapshots completeness, inserts `ResearchRun(provider_profile_id=profile.id)`, stores the complete budget in the attempt/job payload, and enqueues `research_story:{story_id}:{evidence_set_hash}:{profile.id}:{resolved_model}:{mode}:{depth}` transactionally. Manual always enqueues; auto only when incomplete.

The research handler is the only ORM persistence boundary. It commits the running attempt, builds `EvidenceRecord` inputs, resolves the backend from the persisted profile, and calls it outside a transaction. Then one new transaction locks the run/story and performs all of these effects or none: recompute each returned body hash and exact `url:<normalized_source_url>:<content_sha256>` key; insert `ResearchSource` with `citation_key=source.evidence_key` and `content_sha256=source.content_sha256`; insert `StoryEvidenceSnapshot` with the source's exact `content_text`, `content_sha256`, nullable URL, and `snapshot_metadata={"research_source_id": str(research_source.id), "evidence_key": source.evidence_key, "retrieved_at": source.retrieved_at.isoformat()}`; merge existing/new `EvidenceRecord` values by key; resolve `CandidateResearchBrief` to UUID-backed `ResearchBrief`; insert the result `StoryRevision` and every `StoryEvidenceLink`; finish run/attempt; append `research.succeeded`; enqueue an optional continuation. No backend receives a session and no adapter persists. Validation, duplicate-key, hash, citation, or budget failure rolls back the materialization transaction and records only the classified failed/needs-review attempt in a separate transaction.

Allow Telegram routes to persist `research_mode` as `off`, `manual`, or `auto_if_incomplete` and `content_filters.research_provider_profile_id` as a UUID string; remove/never introduce `research_backend`. Add `PATCH /telegram/automations/{route_id}/research-policy` with `{research_mode, research_provider_profile_id}`. `off` requires null; manual/auto require an enabled research-capable profile. For an incomplete auto route, `process_route_dispatch` enqueues research with the profile UUID and a sanitized continuation descriptor, then finishes without generating or publishing. On success, the handler enqueues exactly one continuation key `telegram-route-process-after-research:{dispatch_id}:{result_revision_id}`. On failure it records review-required and never creates the continuation. Continuation carries the completed research-run ID so it cannot recurse and still re-enters all Release 2 validation/pause/destination/media auto-publish gates.

- [ ] **Step 4: Add API endpoints that return before research begins**

Add `GET /stories` with search/editorial-state/completeness filters, stable cursor pagination, evidence counts, latest-evidence timestamps, and `include_superseded=false` by default. Add `POST /stories/group-pending` with `{limit: 1..500}`; it enqueues `story.group_pending` using a canonical candidate-set hash and returns `JobAcceptedOut`. The endpoint includes historical unassigned items and Release 2 assigned provisional Telegram singletons.

Add exact short mutation contracts:

```python
class StoryEditorialStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["inbox", "shortlisted", "rejected"]


class StoryBulkEditorialStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    story_ids: list[UUID] = Field(min_length=1, max_length=200)
    state: Literal["inbox", "shortlisted", "rejected"]
```

`PATCH /stories/{story_id}/editorial-state` and `POST /stories/bulk-editorial-state` lock active nonsuperseded stories, set `Story.status`, append `story.editorial_state_changed` with old/new state, and return updated summaries. Bulk is all-or-nothing; missing/superseded IDs return 409 with no changes. Task 8 automatically changes an active story to `drafted` only after its first `ContentPack` is transactionally created.

```python
@router.post("/{story_id}/research-runs", response_model=ResearchDisposition, status_code=202)
async def create_research_run(story_id: UUID, payload: ResearchRunCreate, session: AsyncSession = SessionDependency):
    result = await ResearchService(session).request(
        story_id=story_id,
        mode=payload.mode,
        depth=payload.depth,
        provider_profile_id=payload.provider_profile_id,
        query_hint=payload.query_hint,
    )
    await session.commit()
    return result
```

The GET endpoints return completeness input hashes, provider profile ID/display name/type, requested/resolved model, budgets/consumption, attempts, sanitized errors, fetched source metadata, result revision ID, and job status. They never return secret references/values, raw authorization headers, or Codex environment values.

- [ ] **Step 5: Run focused tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/research tests/api/test_story_routes.py tests/test_job_handler_registry.py tests/test_job_worker.py tests/postgres/test_job_repository.py -q
.venv/bin/ruff check app/research app/api/stories.py app/api/telegram_schemas.py app/api/telegram_automations.py app/automations/telegram/handlers.py tests/research tests/api/test_story_routes.py
git diff --check
cd ..
git add backend/app/research backend/app/api/stories.py backend/app/api/telegram_schemas.py backend/app/api/telegram_automations.py backend/app/automations/telegram/handlers.py backend/app/jobs/types.py backend/app/jobs/registry.py backend/app/api/routes.py backend/tests/research backend/tests/api/test_story_routes.py
git commit -m "feat: orchestrate durable story research"
```

Expected: research, API, and job regression tests pass.

---

### Task 8: Generate canonical story revisions and immutable content-pack revisions

**Files:**
- Modify: `backend/app/generation/default_prompts.py`
- Create: `backend/app/generation/canonical.py`
- Create: `backend/app/generation/editorial_service.py`
- Create: `backend/app/generation/handlers.py`
- Create: `backend/app/api/content_packs.py`
- Modify: `backend/app/api/generation_settings.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_default_prompts.py`
- Modify: `backend/tests/test_generation_settings_api.py`
- Create: `backend/tests/generation/test_canonical.py`
- Create: `backend/tests/generation/test_editorial_service.py`
- Create: `backend/tests/api/test_content_pack_routes.py`

**Interfaces:**
- Consumes: validated persisted evidence/research from Tasks 1–7, enabled Release 1 `AIProviderProfile` rows, Release 1 job/content-pack models, and Release 2 shared `TelegramVariantContent`/`TelegramEvidenceCitation`/renderer contracts with nullable `source_item_id`/`source_url` and non-empty UUID-backed `evidence_map`.
- Produces: `CanonicalStoryOutput`, profile-ID/prompt-ID `GeneratePackRequest` and `RegenerateVariantRequest`, typed `EditVariantRequest`, `ApprovalRequest`, canonical/pack jobs, revision-conflict behavior, and content-pack APIs.

- [ ] **Step 1: Write failing canonical grounding and revision tests**

```python
async def test_canonical_generation_rejects_unknown_citation(fake_generation_provider, story_with_evidence):
    fake_generation_provider.result = canonical_output(citation_id=uuid4())
    with pytest.raises(CitationIntegrityError):
        await generate_canonical_revision(story_with_evidence, fake_generation_provider)


async def test_editorial_prompt_seed_is_idempotent_and_keeps_two_active_purposes(fake_session):
    first = await seed_default_editorial_prompts(fake_session)
    second = await seed_default_editorial_prompts(fake_session)
    assert first.canonical_story.id == second.canonical_story.id
    assert first.telegram_pack.id == second.telegram_pack.id
    assert first.canonical_story.prompt_template.purpose_key == "canonical_story"
    assert first.telegram_pack.prompt_template.purpose_key == "telegram_pack"
    assert first.canonical_story.is_active is True
    assert first.telegram_pack.is_active is True


async def test_pack_request_rejects_inactive_or_wrong_purpose_prompt_versions(
    editorial_service, story, generation_profile, prompt_versions
):
    request = generate_pack_request(
        canonical_prompt_template_version_id=prompt_versions.telegram_pack.id,
        platform_prompt_template_version_id=prompt_versions.inactive_canonical_story.id,
    )
    with pytest.raises(InvalidGenerationRequest, match="active canonical_story prompt version"):
        await editorial_service.request_content_pack(story.id, request, generation_profile)


async def test_each_generation_run_uses_the_stage_specific_non_null_prompt_version(
    editorial_service, run_jobs, story, generation_profile, prompt_versions
):
    accepted = await editorial_service.request_content_pack(
        story.id,
        generate_pack_request(
            canonical_prompt_template_version_id=prompt_versions.canonical_story.id,
            platform_prompt_template_version_id=prompt_versions.telegram_pack.id,
        ),
        generation_profile,
    )
    await run_jobs.until_idle(accepted.job_id)
    canonical_run, telegram_run = await generation_runs_for_job(accepted.job_id)
    assert canonical_run.prompt_template_version_id == prompt_versions.canonical_story.id
    assert telegram_run.prompt_template_version_id == prompt_versions.telegram_pack.id
    assert all(run.prompt_template_version_id is not None for run in (canonical_run, telegram_run))


async def test_edit_creates_new_pending_review_revision_and_preserves_approved_parent(db_session, approved_variant):
    service = EditorialService(db_session)
    edited = await service.edit_variant(
        approved_variant.variant_id,
        base_revision_id=approved_variant.revision_id,
        base_content_hash=approved_variant.content_hash,
        content=approved_variant.rewrite_output.model_copy(update={"body": "Human-edited Telegram copy"}),
        media_asset_ids=approved_variant.content.media_asset_ids,
        edit_note="Tighten opening",
    )
    assert edited.id != approved_variant.revision_id
    assert edited.parent_revision_id == approved_variant.revision_id
    assert edited.content["body"] == "Human-edited Telegram copy"
    assert edited.evidence_map == approved_variant.evidence_map
    assert edited.approval_state == "pending_review"
    assert approved_variant.approval_state == "approved"


async def test_release_two_revision_edit_revalidates_and_copies_nonempty_evidence_map(
    db_session, release_two_variant
):
    assert release_two_variant.evidence_map
    edited = await EditorialService(db_session).edit_variant(
        release_two_variant.variant_id,
        base_revision_id=release_two_variant.revision_id,
        base_content_hash=release_two_variant.content_hash,
        content=release_two_variant.rewrite_output.model_copy(update={"body": "Reviewed copy"}),
        media_asset_ids=release_two_variant.content.media_asset_ids,
        edit_note="Review source rewrite",
    )
    assert edited.evidence_map == release_two_variant.evidence_map
    assert all(CitationRef.model_validate(item) for item in edited.evidence_map)
    assert edited.approval_state == "pending_review"


def test_telegram_variant_content_retains_release_two_publish_contract():
    content = TelegramVariantContent.model_validate(
        {
            "body": "بازنویسی",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": str(uuid4()),
            "source_url": "https://t.me/source/10",
            "media_policy": "preserve",
            "media_asset_ids": [str(uuid4())],
            "direction": "rtl",
            "dry_run": False,
        }
    )
    assert set(content.model_dump(mode="json")) == {
        "body", "parse_mode", "buttons", "source_item_id", "source_url",
        "media_policy", "media_asset_ids", "direction", "dry_run",
    }


def test_telegram_variant_content_allows_truthful_null_source_identity():
    content = TelegramVariantContent.model_validate(
        {
            "body": "Operator-provided source",
            "parse_mode": "HTML",
            "buttons": [],
            "source_item_id": None,
            "source_url": None,
            "media_policy": "omit",
            "media_asset_ids": [],
            "direction": "ltr",
            "dry_run": False,
        }
    )
    assert content.source_item_id is None
    assert content.source_url is None


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


from app.generation.telegram_schema import TelegramEvidenceCitation, TelegramVariantContent


class GeneratePackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brand_profile_id: UUID
    platform: Literal["telegram"]
    generation_provider_profile_id: UUID
    canonical_prompt_template_version_id: UUID
    platform_prompt_template_version_id: UUID
    research_mode: Literal["off", "manual", "auto_if_incomplete"] = "off"
    research_provider_profile_id: UUID | None = None


class EditVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision_id: UUID
    base_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: TelegramRewriteOutput
    media_asset_ids: list[UUID]
    edit_note: str = Field(min_length=1, max_length=500)


class RegenerateVariantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_provider_profile_id: UUID
    platform_prompt_template_version_id: UUID
    instruction: str | None = Field(default=None, max_length=1_000)


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

Extend Release 2 `backend/app/generation/default_prompts.py` with immutable prompt specs for exact purpose keys `canonical_story` and `telegram_pack`. `canonical_story` instructs the provider to use only supplied persisted evidence, preserve uncertainty/disagreement, emit claim-level citations, and return `CanonicalStoryOutput`; `telegram_pack` instructs it to transform the locked canonical revision into `TelegramRewriteOutput` without adding facts. `seed_default_editorial_prompts()` uses the existing checksum/version helper: identical content returns the active row, changed content creates version `N+1`, deactivates the prior version, and never updates an existing version's templates/schema/checksum. Seed both during the existing bootstrap transaction.

Generation orchestration must follow this exact state flow:

```python
async def request_content_pack(service: EditorialService, story_id: UUID, request: GeneratePackRequest) -> JobAcceptedOut:
    prompts = await service.require_active_prompt_versions(
        canonical_id=request.canonical_prompt_template_version_id,
        canonical_purpose="canonical_story",
        platform_id=request.platform_prompt_template_version_id,
        platform_purpose="telegram_pack",
    )
    completeness = await service.completeness(story_id)
    if request.research_mode == "auto_if_incomplete" and not completeness.complete:
        if request.research_provider_profile_id is None:
            raise InvalidGenerationRequest("auto research requires research_provider_profile_id")
        return await service.enqueue_research_then_generation(story_id, request, prompts)
    return await service.enqueue_canonical_then_pack_generation(story_id, request, prompts)
```

`require_active_prompt_versions()` loads and locks both rows, joins their `PromptTemplate`, rejects a missing/inactive row or wrong `purpose_key`, and stores both immutable IDs in the workflow payload/continuation. Regeneration similarly requires an active `platform_prompt_template_version_id` whose purpose is `telegram_pack`; its `GenerationRun` stores that non-null ID. The service loads `generation_provider_profile_id`, requires an enabled/available profile, resolves its provider type/default model/secret and generation limits internally, and stores that exact UUID on `GenerationRun.provider_profile_id`; no generation job payload/API carries a provider-type literal. Auto research resolves `research_provider_profile_id` through Task 7. Manual mode never auto-enqueues research; it uses the selected current story revision after an operator-run research result.

The canonical handler snapshots its evidence set and creates `GenerationRun(prompt_template_version_id=request.canonical_prompt_template_version_id, ...)`, records the attempt with that version's exact prompt/schema snapshot, validates every claim citation, and writes a new immutable `StoryRevision`. The pack handler creates a distinct `GenerationRun(prompt_template_version_id=request.platform_prompt_template_version_id, ...)`, renders Telegram from that exact revision and a canonical snapshot/hash of the selected brand profile plus immutable platform prompt, and records the second prompt snapshot. No `GenerationRun` may use a null prompt FK or the other stage's purpose. It writes `TelegramVariantContent.model_dump(mode="json")` exactly to `PlatformVariantRevision.content` and resolved claim citations exactly to the separate non-empty `evidence_map`; it never embeds citations/manual package fields inside the Release 2 Telegram content JSON. `source_item_id` and `source_url` remain independently nullable, and no handler dereferences or fabricates either when absent. Validate `TelegramRewriteOutput(body, parse_mode, buttons)` plus source/media/direction/dry-run rules before persistence, then run the existing Release 2 renderer contract test against the stored revision.

Use an input hash derived from story revision hash, canonical brand-profile hash, prompt checksum, generation profile UUID/resolved model, and platform. Initial completed generation is `pending_review`; in-progress scaffold rows may be `draft`; regeneration/human edit always creates a child `pending_review`; approval changes only the exact hash-matching row to `approved`; rejection changes only that row to `rejected`. Editing rejects stale base hashes with HTTP 409. For a human edit, accept only provider-editable `TelegramRewriteOutput` plus ordered media IDs, then rebuild `TelegramVariantContent` by copying `source_item_id`, `source_url`, `media_policy`, `direction`, and `dry_run` from the parent and validating the submitted media IDs; the client cannot change provenance, route policy, direction, or dry-run state. The server loads the parent's non-empty map, parses every item through shared `TelegramEvidenceCitation`, re-runs `validate_citations()` against persisted snapshots, copies the exact map into the child, and recomputes canonical SHA-256 over `{content, evidence_map}`; the client cannot submit or replace citations. Citation changes occur only through grounded generation/regeneration. This same request/assembly path consumes Release 2 revisions without backfill. Creating the first pack also changes the active nonsuperseded `Story.status` to `drafted` in the enqueue transaction. Release 2 auto mode remains the only path that may approve automatically, and it must re-run every validation/evidence/media/pause/destination gate.

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
POST   /platform-variants/{variant_id}/regenerate
POST   /platform-variant-revisions/{revision_id}/approve
POST   /platform-variant-revisions/{revision_id}/reject
```

All mutating long operations return HTTP 202 plus a job. Edit/approve/reject are short transactional mutations and return HTTP 201/200. Rejection records an event and does not delete a revision.

- [ ] **Step 6: Run focused tests and commit**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m pytest tests/generation tests/api/test_content_pack_routes.py tests/research tests/test_telegram_publish_service.py tests/test_telegram_process_handler.py -q
.venv/bin/ruff check app/generation app/api/content_packs.py tests/generation tests/api/test_content_pack_routes.py
git diff --check
cd ..
git add backend/app/generation backend/app/api/content_packs.py backend/app/api/generation_settings.py backend/app/api/routes.py backend/app/main.py backend/tests/generation backend/tests/api/test_content_pack_routes.py backend/tests/test_default_prompts.py backend/tests/test_generation_settings_api.py
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
- Produces: `StorySummary`, `StoryDetail`, `AIProviderOption`, `PromptVersionOption`, `ResearchRunDetail`, `groupPendingStories()`, `createManualStory()`, `setStoryEditorialState()`, `bulkSetStoryEditorialState()`, profile-ID `requestResearch()`, prompt-version-ID `requestContentPack()`, and an operator-usable Inbox.

- [ ] **Step 1: Write failing API mapping and UI state tests**

```tsx
it("submits manual URL intake and exposes the durable job", async () => {
  const fetchSpy = stubFetch({ job_id: "job-1", status: "queued", deduplicated: false }, 202)
  await expect(createManualStory({ kind: "url", url: "https://example.com/report", title: null })).resolves.toMatchObject({ jobId: "job-1" })
  expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/manual", expect.objectContaining({ method: "POST" }))
})

it("queues grouping for historical unassigned content instead of grouping in the browser request", async () => {
  const fetchSpy = stubFetch({ job_id: "job-group", status: "queued", deduplicated: false }, 202)
  await expect(groupPendingStories({ limit: 500 })).resolves.toMatchObject({ jobId: "job-group" })
  expect(fetchSpy).toHaveBeenCalledWith("/api/backend/stories/group-pending", expect.objectContaining({ method: "POST" }))
})

it("groups evidence under a story and offers research only from a truthful completeness state", async () => {
  renderWithClient(<StoryInbox initialStories={[incompleteStory]} />)
  expect(screen.getByText("2 evidence items")).toBeInTheDocument()
  expect(screen.getByText("Coverage incomplete")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Research more" }))
  expect(await screen.findByRole("dialog", { name: "Research story" })).toBeInTheDocument()
})

it("sends provider profile UUID and never a provider-type literal", async () => {
  const fetchSpy = stubFetch({ disposition: "enqueued", run_id: "run-1", job_id: "job-1", completeness }, 202)
  const providerProfileId = "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b0"
  await requestResearch("story-1", {
    mode: "manual",
    depth: "deep",
    providerProfileId,
    queryHint: "Verify the timeline",
  })
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/backend/stories/story-1/research-runs",
    expect.objectContaining({
      body: JSON.stringify({
        mode: "manual",
        depth: "deep",
        provider_profile_id: providerProfileId,
        query_hint: "Verify the timeline",
      }),
    })
  )
})

it("supports single and bulk shortlist/reject mutations", async () => {
  stubFetchOnce(storySummary({ editorial_state: "shortlisted" }))
  await setStoryEditorialState("story-1", "shortlisted")
  stubFetchOnce({ updated: ["story-1", "story-2"], state: "rejected" })
  await bulkSetStoryEditorialState(["story-1", "story-2"], "rejected")
  expect(fetch).toHaveBeenNthCalledWith(
    1,
    "/api/backend/stories/story-1/editorial-state",
    expect.objectContaining({ method: "PATCH" })
  )
  expect(fetch).toHaveBeenNthCalledWith(
    2,
    "/api/backend/stories/bulk-editorial-state",
    expect.objectContaining({ method: "POST" })
  )
})


it("submits both immutable prompt version IDs when generating a pack", async () => {
  const fetchSpy = stubFetch({ job_id: "job-pack", status: "queued", deduplicated: false }, 202)
  await requestContentPack("story-1", {
    brandProfileId: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b3",
    generationProviderProfileId: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b0",
    canonicalPromptTemplateVersionId: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b4",
    platformPromptTemplateVersionId: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b5",
  })
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/backend/stories/story-1/content-packs",
    expect.objectContaining({
      body: expect.stringContaining('"canonical_prompt_template_version_id":"018f47ac-8d2e-7f62-bfd4-6a0a7243d3b4"'),
    })
  )
  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/backend/stories/story-1/content-packs",
    expect.objectContaining({
      body: expect.stringContaining('"platform_prompt_template_version_id":"018f47ac-8d2e-7f62-bfd4-6a0a7243d3b5"'),
    })
  )
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
export type AIProviderOption = {
  id: string
  name: string
  providerType: "fake" | "openrouter" | "codex"
  defaultModel: string | null
  capabilities: { generation: boolean; research: boolean }
  unavailableReason: string | null
}

export type PromptVersionOption = {
  id: string
  purpose: "canonical_story" | "telegram_pack"
  version: number
  checksumSha256: string
  active: boolean
}

export type StorySummary = {
  id: string
  title: string
  evidenceCount: number
  latestEvidenceAt: string
  completeness: { complete: boolean; score: number; reasons: string[] }
  editorialState: "inbox" | "shortlisted" | "rejected" | "drafted"
}

export type EvidenceDetail = {
  id: string
  evidenceKey: string
  title: string | null
  contentText: string
  contentSha256: string
  sourceUrl: string | null
  publishedAt: string | null
  capturedAt: string
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

The Inbox must render real loading, error, empty, and data states; support search, completeness filter, shortlist, reject, bounded multi-select state changes, and story expansion; and show truthful source/timestamp/snapshot data. Single and bulk state mutations call Task 7 APIs, retain selection on failure, and invalidate list/detail queries on success. When historical/unconsolidated Telegram content exists, show `Group pending content`, enqueue the durable grouping job, and display its outcome. Add `Inbox` to both Release 1 navigation components only after this route works.

`ManualIntakeDialog` uses a URL/Text tab, validates text at 20 characters, closes only after exact `JobAcceptedOut`, and displays the returned job. Evidence cards render `Open original source` only when `sourceUrl !== null`; manual operator text with a null URL shows `Operator-provided text` and never renders an empty/fabricated link. `ResearchPanel` receives configured `AIProviderOption[]`, disables rows whose `capabilities.research` is false, submits the selected profile UUID, offers `Research more` (`mode=manual`, `depth=standard`) and `Deep research` (`mode=manual`, `depth=deep`), and polls the returned run/job. Pack generation disables profiles whose `capabilities.generation` is false and submits both active immutable prompt-version UUIDs. Provider type is display metadata, not a mutation value.

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
- Modify: `frontend/features/automations/route-builder.tsx`
- Modify: `frontend/features/automations/route-detail.tsx`
- Modify: `frontend/features/review/telegram-review-workspace.tsx`
- Modify: `frontend/features/settings/content-settings-page.tsx`
- Modify: `frontend/app/drafts/page.tsx`
- Create: `frontend/app/drafts/[packId]/page.tsx`
- Modify: `frontend/app/review/[revisionId]/page.tsx`
- Modify: `frontend/lib/editorial-api.ts`
- Create: `frontend/tests/variant-editor.test.tsx`
- Create: `frontend/tests/evidence-panel.test.tsx`
- Create: `frontend/tests/revision-timeline.test.tsx`
- Modify: `frontend/tests/telegram-route-builder.test.tsx`
- Modify: `frontend/tests/telegram-review-workspace.test.tsx`
- Modify: `frontend/tests/content-settings-page.test.tsx`
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

it("marks edited content pending review and handles a stale revision conflict", async () => {
  const save = vi.fn().mockRejectedValue(new ApiError("Conflict", 409, "revision changed"))
  render(<VariantEditor revision={approvedRevision} onSave={save} />)
  await userEvent.type(screen.getByLabelText("Telegram message"), " Added context")
  expect(screen.getByText("Changes will create a pending review revision")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Save new revision" }))
  expect(await screen.findByText("A newer revision exists. Reload before saving.")).toBeInTheDocument()
})

it("navigates from a claim citation to the exact evidence locator", async () => {
  render(<EvidencePanel evidence={evidence} activeCitation={citation} />)
  expect(screen.getByTestId("evidence-excerpt")).toHaveTextContent("announced on July 11")
  expect(screen.getByRole("link", { name: "Open original source" })).toHaveAttribute("href", evidence.sourceUrl)
})

it("does not render a source link for operator evidence with no URL", () => {
  render(<EvidencePanel evidence={{ ...evidence, sourceUrl: null }} activeCitation={citation} />)
  expect(screen.queryByRole("link", { name: "Open original source" })).not.toBeInTheDocument()
  expect(screen.getByText("Operator-provided text")).toBeInTheDocument()
})


it("shows immutable canonical and Telegram-pack prompt versions in settings", () => {
  render(
    <ContentSettingsPage
      promptVersions={[
        { id: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b4", purpose: "canonical_story", version: 1, active: true },
        { id: "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b5", purpose: "telegram_pack", version: 1, active: true },
      ]}
    />
  )
  expect(screen.getByRole("heading", { name: "Canonical story prompts" })).toBeInTheDocument()
  expect(screen.getByRole("heading", { name: "Telegram pack prompts" })).toBeInTheDocument()
  expect(screen.getAllByText("Active version 1")).toHaveLength(2)
})


it("submits the configured provider profile UUID for regeneration", async () => {
  const fakeProfileId = "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b0"
  const openRouterProfileId = "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b1"
  const codexProfileId = "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b2"
  const telegramPromptId = "018f47ac-8d2e-7f62-bfd4-6a0a7243d3b5"
  render(
    <VariantEditor
      revision={draftRevision}
      availableProviders={[
        { id: fakeProfileId, name: "Deterministic fake", providerType: "fake", defaultModel: "fake-v1", capabilities: { generation: true, research: true }, unavailableReason: null },
        { id: openRouterProfileId, name: "OpenRouter", providerType: "openrouter", defaultModel: "model-a", capabilities: { generation: true, research: true }, unavailableReason: null },
        { id: codexProfileId, name: "Codex CLI", providerType: "codex", defaultModel: "gpt-5.4", capabilities: { generation: true, research: true }, unavailableReason: null },
      ]}
      availablePromptVersions={[
        { id: telegramPromptId, purpose: "telegram_pack", version: 1, active: true },
      ]}
    />
  )
  await userEvent.selectOptions(screen.getByLabelText("AI provider"), codexProfileId)
  await userEvent.selectOptions(screen.getByLabelText("Telegram pack prompt"), telegramPromptId)
  await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))
  expect(regenerateVariant).toHaveBeenCalledWith(draftRevision.variantId, {
    providerProfileId: codexProfileId,
    platformPromptTemplateVersionId: telegramPromptId,
    instruction: null,
  })
})
```

Extend the Telegram builder/review tests to prove all three research modes are visible; `off` clears `researchProviderProfileId`; `auto_if_incomplete` requires an available profile UUID; `manual` shows `Research more` but does not run automatically; and a completed manual research run offers regeneration from the new story revision. Assert no request sends `research_backend` or a provider-type literal, and an auto-research failure displays `Review required` with no publish action.
Extend content-settings tests to show the enabled Codex CLI profile with no secret field, capability-specific availability, and an unavailable executable as a truthful disabled option. The same page exposes immutable version history and active state for `canonical_story` and `telegram_pack`; activation creates/selects versions through the existing immutable prompt API and never edits a version in place.

- [ ] **Step 2: Run tests and verify failure**

```bash
cd frontend
npx vitest run tests/variant-editor.test.tsx tests/evidence-panel.test.tsx tests/revision-timeline.test.tsx tests/telegram-route-builder.test.tsx tests/telegram-review-workspace.test.tsx tests/content-settings-page.test.tsx
```

Expected: import failures for editor components.

- [ ] **Step 3: Implement editor state and API calls**

Add exact client methods:

```tsx
export type EditVariantInput = {
  baseRevisionId: string
  baseContentHash: string
  content: { body: string; parseMode: "HTML"; buttons: TelegramButton[] }
  mediaAssetIds: string[]
  editNote: string
}

export function saveVariantRevision(variantId: string, input: EditVariantInput): Promise<VariantRevision>
export function approveVariantRevision(revisionId: string, input: { expectedContentHash: string; note: string | null }): Promise<VariantRevision>
export function rejectVariantRevision(revisionId: string, input: { reason: string }): Promise<VariantRevision>
export function regenerateVariant(variantId: string, input: { providerProfileId: string; platformPromptTemplateVersionId: string; instruction: string | null }): Promise<JobAccepted>
```

`VariantEditor` edits only `body`, `parseMode`, `buttons`, and media assignments. It displays nullable source provenance, media policy, direction, and dry-run state as read-only values; those fields and the separate non-empty evidence map are copied/revalidated server-side and never submitted as editable data. It never rewrites the stored shape to `{text, citations}`. It keeps loaded revision ID/hash separate from the form, never mutates query-cache revisions in place, warns on dirty navigation, saves a child `pending_review` revision, clears dirty state only after success, and disables approval while dirty or validation errors exist. Initial generation/regeneration list configured `AIProviderOption` rows and active purpose-filtered `PromptVersionOption` rows, display provider type/model/prompt version, but submit only profile/prompt UUIDs and persist those selections in returned jobs/runs.

Extend the Telegram route builder with `off`, `manual`, and `auto_if_incomplete` plus `researchProviderProfileId`; extend route detail/review with completeness, research job outcome, `Research more`, and regenerate-from-result actions. Evidence citations focus the exact `chars:start-end` excerpt and conditionally render the source link only for non-null `sourceUrl`. Revision timeline states are only `draft`, `pending_review`, `approved`, or `rejected` and show origin, parent, provider-profile/model or operator, timestamp, and validation.

- [ ] **Step 4: Add drafts, pack detail, and review routes**

The routes must implement these visible state contracts:

```tsx
type DraftRouteState =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "failed"; message: string; jobId: string | null }
  | { kind: "ready"; pack: ContentPackDetail }
```

Drafts list generation state and last failure; pack detail lists exact variants/revisions. Extend the existing Release 2 `/review/[revisionId]` page in place; the route loads that exact revision and derives its variant/pack rather than introducing a conflicting `/review/[variantId]` filesystem segment. Review uses a desktop split layout and stacks evidence above the editor below 900px. After approval, Telegram actions from Release 2 become enabled only for the approved revision. A unified cross-platform Library remains later work; Release 3 uses Inbox, Drafts, and Review and does not expose Instagram/X/blog controls before Release 4.

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
  await page.getByLabel("Canonical story prompt").selectOption("canonical-story-v1")
  await page.getByLabel("Telegram pack prompt").selectOption("telegram-pack-v1")
  await page.getByRole("button", { name: "Queue generation" }).click()
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
git add frontend/components/editorial frontend/features/automations/route-builder.tsx frontend/features/automations/route-detail.tsx frontend/features/review/telegram-review-workspace.tsx frontend/features/settings/content-settings-page.tsx frontend/app/drafts frontend/app/review frontend/lib/editorial-api.ts frontend/tests frontend/e2e/editorial-studio.spec.ts
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
        {
            "mode": "manual",
            "depth": "standard",
            "provider_profile_id": str(app_harness.fake_provider_profile.id),
            "query_hint": "Verify date",
        },
    )
    await app_harness.worker.run_until_idle()
    pack = await app_harness.post_json(
        f"/stories/{story.id}/content-packs",
        {
            "brand_profile_id": str(app_harness.brand.id),
            "platform": "telegram",
            "generation_provider_profile_id": str(app_harness.fake_provider_profile.id),
            "canonical_prompt_template_version_id": str(app_harness.canonical_story_prompt_version.id),
            "platform_prompt_template_version_id": str(app_harness.telegram_pack_prompt_version.id),
            "research_mode": "off",
            "research_provider_profile_id": None,
        },
    )
    await app_harness.worker.run_until_idle()
    revision = await app_harness.revision_for_job(pack["job_id"])
    edited = await app_harness.post_json(
        f"/platform-variants/{revision.variant_id}/revisions",
        {
            "base_revision_id": str(revision.id),
            "base_content_hash": revision.content_hash,
            "content": {
                "body": "Edited copy",
                "parse_mode": revision.content["parse_mode"],
                "buttons": revision.content["buttons"],
            },
            "media_asset_ids": revision.content["media_asset_ids"],
            "edit_note": "Operator edit",
        },
    )
    approved = await app_harness.post_json(
        f"/platform-variant-revisions/{edited['id']}/approve",
        {"expected_content_hash": edited["content_hash"], "note": "Ready"},
    )
    assert approved["approval_state"] == "approved"
    assert approved["id"] == edited["id"]
    assert edited["approval_state"] == "pending_review"
    assert edited["content"]["body"] == "Edited copy"
    assert research["job_id"] is not None
    canonical_run, telegram_run = await app_harness.generation_runs_for_job(pack["job_id"])
    assert canonical_run.prompt_template_version_id == app_harness.canonical_story_prompt_version.id
    assert telegram_run.prompt_template_version_id == app_harness.telegram_pack_prompt_version.id
```

- [ ] **Step 2: Document exact local configuration**

Document these settings and safety facts:

```dotenv
OPENROUTER_API_KEY=
CODEX_EXECUTABLE=codex
```

Explain that fake mode needs no credentials, Codex uses local Codex authentication, OpenRouter uses its key plus the controlled DDG loop, and none of these variables are committed. Model selection, pricing, standard/deep research budgets, and Codex generation limits live only in validated `AIProviderProfile.settings`, not flat environment aliases. Include exact UI flow: Settings → inspect/activate Canonical story and Telegram pack prompt versions → Inbox → Add source material → Research more/Deep research → Generate Telegram draft with both prompt versions → Review → Save revision → Approve.

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

- Unassigned items and every unsuperseded `telegram_provisional` story—including source edits—form one inspectable story; equal evidence keys deduplicate only after payload equality and collisions roll back before supersession.
- Manual URL/text entry returns a durable job and records truthful provenance.
- Completeness is deterministic and visible; `auto_if_incomplete` never runs for complete evidence.
- Telegram routes support off/manual/auto-if-incomplete research; failures fall to review and cannot leak into auto-publish.
- Codex and OpenRouter return database-free materialized source DTOs/candidate citations; only the handler persists and resolves UUID citations atomically.
- Research and generation select enabled `AIProviderProfile` UUIDs; shared OpenRouter pricing/standard/deep budgets and strict Codex settings validate server-side with capability-specific availability and fake/Codex server defaults.
- Codex receives the resolved profile model, a temporary HOME, auth-only CODEX_HOME, no Git/rules/shell/code-host/computer-use/apps/external-browser/full-CDP capability, and bounded model-call/input/output-token/time limits; DuckDuckGo/OpenRouter obeys explicit DuckDuckGo backend plus model-call/token/cost/query/page/time/character budgets.
- Research creates a new evidence-backed story revision and does not overwrite sources.
- Canonical generation and Telegram pack generation use active immutable `canonical_story`/`telegram_pack` prompt-version UUIDs respectively, store non-null stage-correct prompt FKs, and preserve evidence mappings.
- Telegram revisions retain Release 2 body/parse-mode/buttons/source/media/direction/dry-run content plus separate evidence maps; per-platform validation passes before review/publish.
- Human edits and regeneration create immutable `pending_review` children; approval binds to the exact ID/hash and states remain draft/pending_review/approved/rejected.
- Inbox, research, Drafts, and Review flows render loading, empty, failure, success, mobile stacking, Persian/RTL evidence, and durable job outcomes.
- The full deterministic gate passes without external credentials.
