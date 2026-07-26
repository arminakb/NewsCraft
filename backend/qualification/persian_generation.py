"""Protected Persian generation qualification CLI."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select

from app.db.session import async_session
from app.generation.default_prompts import seed_default_editorial_prompts, seed_default_telegram_configuration
from app.generation.editorial_service import EditorialService, GeneratePackRequest
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    GenerationAttempt,
    GenerationRun,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.jobs.models import WorkflowJob
from app.stories.models import Story, StoryEvidenceSnapshot

PLATFORMS = ["telegram", "instagram", "x", "blog"]
DIMENSIONS = [
    "factual_accuracy",
    "evidence_grounding",
    "relevance",
    "clarity",
    "natural_persian",
    "title",
    "platform_fit",
]
TERMINAL_JOB_STATUSES = {"succeeded", "failed", "needs_review", "cancelled"}


class EvaluationDataError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _verified_self_hash(value: dict[str, Any], field: str) -> str:
    supplied = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    expected = _sha256(unsigned)
    if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
        raise EvaluationDataError(f"{field} does not match the immutable payload")
    return supplied


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if corpus.get("schema_version") != "persian-generation-corpus-v1":
        raise EvaluationDataError("unsupported corpus schema")
    stories = corpus.get("stories")
    if not isinstance(stories, list) or len(stories) != 36:
        raise EvaluationDataError("corpus must contain exactly 36 stories")
    if len({item.get("id") for item in stories}) != 36:
        raise EvaluationDataError("corpus story IDs must be unique")
    expected = {
        "source_type": {"rss": 18, "telegram": 18},
        "length": {"short": 12, "medium": 12, "long": 12},
        "split": {"calibration": 12, "held_out": 24},
        "category": {
            "hard_news": 6,
            "tutorial_analysis": 6,
            "research_technical": 6,
            "product_announcement": 6,
            "promotion_borderline": 12,
        },
    }
    for field, counts in expected.items():
        if Counter(item.get(field) for item in stories) != Counter(counts):
            raise EvaluationDataError(f"corpus {field} strata are invalid")
    minimum_flags = {
        "conflicting_multi_source": 8,
        "insufficient_evidence": 6,
        "mixed_script": 10,
        "language_hint_conflict": 6,
    }
    for flag, minimum in minimum_flags.items():
        if sum(flag in item.get("flags", []) for item in stories) < minimum:
            raise EvaluationDataError(f"corpus requires at least {minimum} {flag} stories")
    for story in stories:
        if story.get("research_enabled") is not False or story.get("expected_language") != "fa":
            raise EvaluationDataError("baseline corpus must be Persian with research disabled")
        for evidence in story.get("evidence", []):
            if hashlib.sha256(evidence["text"].encode()).hexdigest() != evidence.get("sha256"):
                raise EvaluationDataError("corpus evidence hash mismatch")
    return corpus


def build_execution_plan(corpus: dict[str, Any], *, campaign_id: UUID, repeats: int) -> list[dict[str, Any]]:
    if repeats != 2:
        raise EvaluationDataError("qualification requires exactly two independent repeats")
    return [
        {
            "evaluation_run_id": str(uuid5(campaign_id, f"{story['id']}:{repeat}")),
            "story_id": story["id"],
            "repeat": repeat,
            "expected_provider_calls": 5,
        }
        for story in corpus["stories"]
        for repeat in range(1, repeats + 1)
    ]


def _weighted_kappa(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    count = len(left)
    observed = sum(((a - b) / 4) ** 2 for a, b in zip(left, right, strict=True)) / count
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum(left_counts[a] * right_counts[b] * ((a - b) / 4) ** 2 for a in range(1, 6) for b in range(1, 6)) / (
        count * count
    )
    return 1.0 if expected == 0 and observed == 0 else (0.0 if expected == 0 else 1 - observed / expected)


def score_evaluation(
    run: dict[str, Any],
    reviews: dict[str, Any],
    *,
    signing_key: bytes,
) -> dict[str, Any]:
    if run.get("schema_version") != "persian-generation-run-v1" or run.get("status") != "completed":
        raise EvaluationDataError("run is incomplete or unsupported")
    if reviews.get("schema_version") != "persian-generation-reviews-v1":
        raise EvaluationDataError("reviews are unsupported")
    run_sha256 = _verified_self_hash(run, "run_sha256")
    if len(signing_key) < 32:
        raise EvaluationDataError("report signing key must contain at least 32 bytes")
    packs = run.get("packs", [])
    calls = run.get("provider_calls", [])
    variants = run.get("variants", [])
    if len(packs) != 72 or len(variants) != 288 or len(calls) < 360:
        raise EvaluationDataError("run does not contain the required 72 packs, 288 variants, and 360 calls")
    baseline_calls = [item for item in calls if item.get("baseline_call") is True]
    if len(baseline_calls) != 360:
        raise EvaluationDataError("run must identify exactly 360 baseline calls")

    review_rows = reviews.get("reviews", [])
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in review_rows:
        if row.get("reviewer_id") and row.get("variant_revision_id"):
            by_variant[row["variant_revision_id"]].append(row)
    variant_ids = {item["variant_revision_id"] for item in variants}
    if set(by_variant) != variant_ids or any(len(rows) != 2 for rows in by_variant.values()):
        raise EvaluationDataError("every variant requires exactly two blinded reviews")
    if any(rows[0]["reviewer_id"] == rows[1]["reviewer_id"] for rows in by_variant.values()):
        raise EvaluationDataError("variant reviewers must be distinct")

    adjudicated = set(reviews.get("adjudicated_variant_ids", []))
    dimension_values: dict[str, list[float]] = defaultdict(list)
    left_scores: list[int] = []
    right_scores: list[int] = []
    language_checks: list[bool] = []
    encoding_checks: list[bool] = []
    title_checks: list[bool] = []
    full_english_checks: list[bool] = []
    claim_labels: list[str] = []
    citation_checks: list[bool] = []
    promo_pairs: list[tuple[bool, bool]] = []
    story_labels = {item["id"]: bool(item["promotional"]) for item in run["corpus_stories"]}
    for variant in variants:
        rows = sorted(by_variant[variant["variant_revision_id"]], key=lambda item: item["reviewer_id"])
        needs_adjudication = False
        for dimension in DIMENSIONS:
            scores = [row.get("scores", {}).get(dimension) for row in rows]
            if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5 for value in scores):
                raise EvaluationDataError("review scores must be integers from 1 to 5")
            needs_adjudication |= abs(scores[0] - scores[1]) > 1
            dimension_values[dimension].extend(scores)
            left_scores.append(scores[0])
            right_scores.append(scores[1])
        if needs_adjudication and variant["variant_revision_id"] not in adjudicated:
            raise EvaluationDataError("all greater-than-one-point disagreements must be adjudicated")
        language_checks.extend(bool(row.get("language_adherent")) for row in rows)
        encoding_checks.extend(bool(row.get("encoding_ok")) for row in rows)
        title_checks.extend(bool(row.get("title_acceptable")) for row in rows)
        full_english_checks.extend(bool(row.get("full_english_output")) for row in rows)
        expected_promo = story_labels[variant["story_id"]]
        promo_pairs.extend((expected_promo, bool(row.get("promotional"))) for row in rows)
        for row in rows:
            for claim in row.get("claim_labels", []):
                label = claim.get("support")
                if label not in {"supported", "minor_unsupported", "material_unsupported"}:
                    raise EvaluationDataError("claim support labels are invalid")
                claim_labels.append(label)
                citation_checks.append(bool(claim.get("citation_valid")))
    if not claim_labels:
        raise EvaluationDataError("reviews must label factual claims")

    first_completion = mean(item["first_attempt_status"] == "succeeded" for item in baseline_calls)
    final_completion = mean(item["final_status"] == "succeeded" for item in baseline_calls)
    retry_pack_rate = mean(bool(item.get("retried")) for item in packs)
    material_count = claim_labels.count("material_unsupported")
    minor_rate = claim_labels.count("minor_unsupported") / len(claim_labels)
    tp = sum(expected and actual for expected, actual in promo_pairs)
    fp = sum(not expected and actual for expected, actual in promo_pairs)
    fn = sum(expected and not actual for expected, actual in promo_pairs)
    promo_precision = tp / (tp + fp) if tp + fp else 0.0
    promo_recall = tp / (tp + fn) if tp + fn else 0.0
    costs = sorted(float(item["cost_usd"]) for item in packs)
    latencies = sorted(float(item["latency_seconds"]) for item in packs)
    p95_index = max(0, int(0.95 * len(packs) + 0.999999) - 1)
    dimension_means = {key: mean(values) for key, values in dimension_values.items()}
    metrics = {
        "first_attempt_structured_completion": first_completion,
        "final_structured_completion": final_completion,
        "retrying_pack_rate": retry_pack_rate,
        "material_unsupported_claims": material_count,
        "minor_unsupported_claim_rate": minor_rate,
        "citation_coverage": mean(citation_checks),
        "editorial_score_mean": mean(value for values in dimension_values.values() for value in values),
        "dimension_means": dimension_means,
        "persian_adherence": mean(language_checks),
        "encoding_integrity": mean(encoding_checks),
        "title_acceptance": mean(title_checks),
        "full_english_outputs": sum(full_english_checks),
        "promo_precision": promo_precision,
        "promo_recall": promo_recall,
        "mean_pack_cost_usd": mean(costs),
        "p95_pack_cost_usd": costs[p95_index],
        "max_pack_cost_usd": max(costs),
        "p95_pack_latency_seconds": latencies[p95_index],
        "max_pack_latency_seconds": max(latencies),
        "weighted_inter_rater_agreement": _weighted_kappa(left_scores, right_scores),
    }
    held_out = [
        rows
        for variant_id, rows in by_variant.items()
        if next(item for item in variants if item["variant_revision_id"] == variant_id)["split"] == "held_out"
    ]
    held_out_floor = min(
        row["scores"][dimension]
        for rows in held_out
        for row in rows
        for dimension in ("factual_accuracy", "evidence_grounding")
    )
    criteria = {
        "first_attempt_structured_completion": first_completion >= 0.98,
        "final_structured_completion": final_completion == 1,
        "retrying_pack_rate": retry_pack_rate <= 0.05,
        "zero_material_unsupported_claims": material_count == 0,
        "minor_unsupported_claim_rate": minor_rate <= 0.02,
        "citation_coverage": metrics["citation_coverage"] == 1,
        "editorial_score_mean": metrics["editorial_score_mean"] >= 4.2,
        "dimension_means": all(value >= 4 for value in dimension_means.values()),
        "held_out_accuracy_grounding_floor": held_out_floor >= 3,
        "persian_adherence": metrics["persian_adherence"] >= 0.95,
        "no_full_english_output": metrics["full_english_outputs"] == 0,
        "encoding_integrity": metrics["encoding_integrity"] == 1,
        "title_mean": dimension_means["title"] >= 4,
        "title_acceptance": metrics["title_acceptance"] == 1,
        "promo_precision": promo_precision >= 0.9,
        "promo_recall": promo_recall >= 0.9,
        "mean_pack_cost": metrics["mean_pack_cost_usd"] <= 0.75,
        "p95_pack_cost": metrics["p95_pack_cost_usd"] <= 1.5,
        "max_pack_cost": metrics["max_pack_cost_usd"] <= 2,
        "p95_pack_latency": metrics["p95_pack_latency_seconds"] <= 120,
        "max_pack_latency": metrics["max_pack_latency_seconds"] <= 180,
        "weighted_inter_rater_agreement": metrics["weighted_inter_rater_agreement"] >= 0.7,
    }
    report: dict[str, Any] = {
        "schema_version": "persian-generation-quality-report-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "campaign_id": run["campaign_id"],
        "corpus_sha256": run["corpus_sha256"],
        "run_sha256": run_sha256,
        "reviews_sha256": _sha256(reviews),
        "provider_configuration_checksum": run["provider_configuration_checksum"],
        "prompt_checksums": run["prompt_checksums"],
        "metrics": metrics,
        "criteria": criteria,
        "passed": all(criteria.values()),
    }
    report["report_sha256"] = _sha256(report)
    report["signature"] = {
        "algorithm": "HMAC-SHA256",
        "value": hmac.new(signing_key, report["report_sha256"].encode(), hashlib.sha256).hexdigest(),
    }
    return report


async def _seed_and_enqueue(args: argparse.Namespace, corpus: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("NEWSCRAFT_PERSIAN_EVALUATION_DATABASE") != "isolated":
        raise EvaluationDataError("run requires NEWSCRAFT_PERSIAN_EVALUATION_DATABASE=isolated")
    campaign_id = uuid4()
    plan = build_execution_plan(corpus, campaign_id=campaign_id, repeats=args.repeats)
    started = datetime.now(UTC)
    async with async_session() as session:
        await seed_default_editorial_prompts(session)
        await seed_default_telegram_configuration(session)
        profile = await session.get(AIProviderProfile, UUID(args.provider_profile_id))
        brand = await session.scalar(
            select(BrandProfile).where(BrandProfile.output_language == "fa", BrandProfile.is_default.is_(True))
        )
        if profile is None or not profile.enabled:
            raise EvaluationDataError("qualified provider profile is unavailable")
        if brand is None:
            raise EvaluationDataError("an isolated default Persian brand profile is required")
        for fixture in corpus["stories"]:
            story_id = UUID(fixture["id"])
            story = await session.get(Story, story_id)
            if story is None:
                session.add(Story(id=story_id, title=fixture["title"], status="inbox", primary_language="fa"))
                for evidence in fixture["evidence"]:
                    session.add(
                        StoryEvidenceSnapshot(
                            id=UUID(evidence["id"]),
                            story_id=story_id,
                            evidence_key=evidence["evidence_key"],
                            source_url=evidence["source_url"],
                            title=evidence["title"],
                            content_text=evidence["text"],
                            authors=[],
                            content_sha256=evidence["sha256"],
                            snapshot_metadata={"evaluation_corpus": "v1"},
                        )
                    )
            else:
                existing = list(
                    await session.scalars(
                        select(StoryEvidenceSnapshot).where(StoryEvidenceSnapshot.story_id == story_id)
                    )
                )
                if story.title != fixture["title"] or {row.content_sha256 for row in existing} != {
                    item["sha256"] for item in fixture["evidence"]
                }:
                    raise EvaluationDataError("existing evaluation fixture does not match locked corpus")
        await session.flush()
        service = EditorialService(session)
        job_ids: list[str] = []
        for entry in plan:
            accepted = await service.request_content_pack(
                UUID(entry["story_id"]),
                GeneratePackRequest(
                    brand_profile_id=brand.id,
                    platforms=PLATFORMS,
                    generation_provider_profile_id=profile.id,
                    research_mode="off",
                ),
                evaluation_run_id=UUID(entry["evaluation_run_id"]),
            )
            job_ids.append(str(accepted.job_id))
        await session.commit()
        prompts = list(
            await session.execute(
                select(PromptTemplate.purpose_key, PromptTemplateVersion.checksum_sha256)
                .join(PromptTemplateVersion, PromptTemplateVersion.prompt_template_id == PromptTemplate.id)
                .where(PromptTemplateVersion.is_active.is_(True))
            )
        )
        initial_job = await session.get(WorkflowJob, UUID(job_ids[0]))
        provider_checksum = initial_job.payload["generation_provider_configuration_checksum"]

    deadline = asyncio.get_running_loop().time() + args.timeout_seconds
    evaluation_ids = {item["evaluation_run_id"] for item in plan}
    jobs: list[WorkflowJob] = []
    while asyncio.get_running_loop().time() < deadline:
        async with async_session() as session:
            candidates = list(
                await session.scalars(
                    select(WorkflowJob).where(
                        WorkflowJob.created_at >= started,
                        WorkflowJob.job_type.in_(["content_pack.generate", "content_pack.generate_telegram"]),
                    )
                )
            )
            jobs = [item for item in candidates if item.payload.get("evaluation_run_id") in evaluation_ids]
            grouped = Counter(item.payload.get("evaluation_run_id") for item in jobs)
            if all(grouped[item] == 2 for item in evaluation_ids) and all(
                item.status in TERMINAL_JOB_STATUSES for item in jobs
            ):
                break
        await asyncio.sleep(2)
    else:
        raise EvaluationDataError("evaluation timed out before all jobs reached a terminal state")

    async with async_session() as session:
        jobs = list(await session.scalars(select(WorkflowJob).where(WorkflowJob.id.in_([item.id for item in jobs]))))
        job_by_id = {str(item.id): item for item in jobs}
        job_eval = {str(item.id): item.payload["evaluation_run_id"] for item in jobs}
        runs = list(await session.scalars(select(GenerationRun).where(GenerationRun.created_at >= started)))
        runs = [
            item
            for item in runs
            if ((item.request_payload or {}).get("execution") or {}).get("workflow_job_id") in job_by_id
        ]
        attempts = list(
            await session.scalars(
                select(GenerationAttempt).where(GenerationAttempt.generation_run_id.in_([item.id for item in runs]))
            )
        )
        attempts_by_run: dict[UUID, list[GenerationAttempt]] = defaultdict(list)
        for attempt in attempts:
            attempts_by_run[attempt.generation_run_id].append(attempt)
        provider_calls = []
        costs_by_eval: dict[str, float] = defaultdict(float)
        retries_by_eval: dict[str, bool] = defaultdict(bool)
        for run in runs:
            workflow_id = run.request_payload["execution"]["workflow_job_id"]
            eval_id = job_eval[workflow_id]
            ordered = sorted(attempts_by_run[run.id], key=lambda item: item.attempt_number)
            costs_by_eval[eval_id] += sum(float(item.usage.get("cost_usd", 0)) for item in ordered)
            retries_by_eval[eval_id] |= len(ordered) > 1
            provider_calls.append(
                {
                    "generation_run_id": str(run.id),
                    "evaluation_run_id": eval_id,
                    "baseline_call": True,
                    "first_attempt_status": ordered[0].status if ordered else "missing",
                    "final_status": ordered[-1].status if ordered else "missing",
                    "attempts": len(ordered),
                    "retry_reasons": [item.error_code for item in ordered[:-1]],
                    "input_tokens": sum(int(item.usage.get("input_tokens", 0)) for item in ordered),
                    "output_tokens": sum(int(item.usage.get("output_tokens", 0)) for item in ordered),
                    "cost_usd": sum(float(item.usage.get("cost_usd", 0)) for item in ordered),
                    "provider": ordered[-1].provider if ordered else None,
                    "resolved_model": ordered[-1].resolved_model if ordered else None,
                    "latency_seconds": sum(
                        (item.finished_at - item.started_at).total_seconds() if item.finished_at else 0
                        for item in ordered
                    ),
                }
            )
        plan_by_eval = {item["evaluation_run_id"]: item for item in plan}
        packs = []
        variants = []
        corpus_by_id = {item["id"]: item for item in corpus["stories"]}
        for eval_id, entry in plan_by_eval.items():
            related = [item for item in jobs if item.payload.get("evaluation_run_id") == eval_id]
            platform_job = next((item for item in related if item.job_type == "content_pack.generate_telegram"), None)
            started_at = min(item.created_at for item in related)
            finished_at = max((item.finished_at or item.updated_at) for item in related)
            packs.append(
                {
                    **entry,
                    "status": "succeeded" if all(item.status == "succeeded" for item in related) else "failed",
                    "retried": retries_by_eval[eval_id],
                    "cost_usd": costs_by_eval[eval_id],
                    "latency_seconds": (finished_at - started_at).total_seconds(),
                }
            )
            for row in (platform_job.result or {}).get("revisions", []) if platform_job else []:
                variants.append(
                    {
                        "evaluation_run_id": eval_id,
                        "story_id": entry["story_id"],
                        "split": corpus_by_id[entry["story_id"]]["split"],
                        "variant_revision_id": row["revision_id"],
                        "variant_id": row["variant_id"],
                    }
                )
    if sum(item["cost_usd"] for item in packs) > args.max_campaign_cost_usd:
        raise EvaluationDataError("completed campaign exceeded its preapproved cost ceiling")
    output = {
        "schema_version": "persian-generation-run-v1",
        "status": "completed",
        "campaign_id": str(campaign_id),
        "created_at": datetime.now(UTC).isoformat(),
        "corpus_sha256": _sha256(corpus),
        "provider_profile_id": args.provider_profile_id,
        "provider_configuration_checksum": provider_checksum,
        "prompt_checksums": dict(prompts),
        "corpus_stories": [
            {"id": item["id"], "split": item["split"], "promotional": item["promotional"]} for item in corpus["stories"]
        ],
        "packs": packs,
        "variants": variants,
        "provider_calls": provider_calls,
    }
    output["run_sha256"] = _sha256(output)
    return output


def _run_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the protected Persian generation qualification campaign")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--provider-profile-id", required=True)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-campaign-cost-usd", type=float, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=14_400)
    parser.add_argument("--confirm-funded-run", action="store_true")
    return parser


def _score_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Score a blinded Persian generation campaign")
    parser.add_argument("score", nargs="?")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--signing-key-file", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "score":
        args = _score_parser().parse_args(arguments)
        run = json.loads(args.run.read_text(encoding="utf-8"))
        reviews = json.loads(args.reviews.read_text(encoding="utf-8"))
        report = score_evaluation(run, reviews, signing_key=args.signing_key_file.read_bytes())
        _write_private_json(args.output, report)
        if not report["passed"]:
            raise SystemExit(2)
        return
    args = _run_parser().parse_args(arguments)
    if not args.confirm_funded_run or args.max_campaign_cost_usd <= 0:
        raise SystemExit("a positive preapproved budget and --confirm-funded-run are required")
    corpus = load_corpus(args.corpus)
    output = asyncio.run(_seed_and_enqueue(args, corpus))
    _write_private_json(args.output, output)


if __name__ == "__main__":
    main()
