from pathlib import Path
from uuid import uuid4

import pytest

from app.validation.persian_generation import (
    EvaluationDataError,
    build_execution_plan,
    load_corpus,
    score_evaluation,
)

CORPUS_PATH = Path(__file__).parents[2] / "validation/persian-generation/corpus-v1.json"


def test_locked_persian_corpus_has_required_strata_and_independent_repeat_identity():
    corpus = load_corpus(CORPUS_PATH)
    plan = build_execution_plan(corpus, campaign_id=uuid4(), repeats=2)

    assert len(corpus["stories"]) == 36
    assert len(plan) == 72
    assert len({item["evaluation_run_id"] for item in plan}) == 72
    assert sum(item["expected_provider_calls"] for item in plan) == 360
    with pytest.raises(EvaluationDataError):
        build_execution_plan(corpus, campaign_id=uuid4(), repeats=1)


def _passing_run_and_reviews():
    corpus = load_corpus(CORPUS_PATH)
    variants = []
    reviews = []
    for story_index, story in enumerate(corpus["stories"]):
        for repeat in (1, 2):
            evaluation_id = f"evaluation-{story_index}-{repeat}"
            for platform in ("telegram", "instagram", "x", "blog"):
                revision_id = f"revision-{story_index}-{repeat}-{platform}"
                variants.append(
                    {
                        "evaluation_run_id": evaluation_id,
                        "story_id": story["id"],
                        "split": story["split"],
                        "variant_revision_id": revision_id,
                    }
                )
                score = 4 if story_index % 2 else 5
                for reviewer in ("blind-a", "blind-b"):
                    reviews.append(
                        {
                            "variant_revision_id": revision_id,
                            "reviewer_id": reviewer,
                            "scores": {
                                "factual_accuracy": score,
                                "evidence_grounding": score,
                                "relevance": score,
                                "clarity": score,
                                "natural_persian": score,
                                "title": score,
                                "platform_fit": score,
                            },
                            "language_adherent": True,
                            "full_english_output": False,
                            "encoding_ok": True,
                            "title_acceptable": True,
                            "promotional": story["promotional"],
                            "claim_labels": [
                                {"claim_id": "claim-1", "support": "supported", "citation_valid": True}
                            ],
                        }
                    )
    packs = [
        {
            "evaluation_run_id": f"evaluation-{story_index}-{repeat}",
            "retried": False,
            "cost_usd": 0.1,
            "latency_seconds": 10,
        }
        for story_index in range(36)
        for repeat in (1, 2)
    ]
    calls = [
        {
            "baseline_call": True,
            "first_attempt_status": "succeeded",
            "final_status": "succeeded",
        }
        for _ in range(360)
    ]
    run = {
        "schema_version": "persian-generation-run-v1",
        "status": "completed",
        "campaign_id": str(uuid4()),
        "corpus_sha256": "a" * 64,
        "provider_configuration_checksum": "b" * 64,
        "prompt_checksums": {"canonical_story": "c" * 64},
        "corpus_stories": [
            {"id": story["id"], "split": story["split"], "promotional": story["promotional"]}
            for story in corpus["stories"]
        ],
        "packs": packs,
        "variants": variants,
        "provider_calls": calls,
    }
    return run, {"schema_version": "persian-generation-reviews-v1", "reviews": reviews}


def test_quality_scorer_enforces_all_thresholds_and_signs_immutable_inputs():
    run, reviews = _passing_run_and_reviews()
    report = score_evaluation(run, reviews, signing_key=b"test-signing-key")

    assert report["passed"] is True
    assert all(report["criteria"].values())
    assert report["metrics"]["weighted_inter_rater_agreement"] == 1
    assert report["signature"]["algorithm"] == "HMAC-SHA256"
    assert len(report["report_sha256"]) == len(report["signature"]["value"]) == 64


def test_quality_scorer_rejects_missing_second_blinded_review():
    run, reviews = _passing_run_and_reviews()
    reviews["reviews"].pop()

    with pytest.raises(EvaluationDataError, match="exactly two"):
        score_evaluation(run, reviews, signing_key=b"test-signing-key")
