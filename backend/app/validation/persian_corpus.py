from __future__ import annotations

import hashlib
from typing import Any
from uuid import NAMESPACE_URL, uuid5

_CATEGORIES = (
    *(["hard_news"] * 6),
    *(["tutorial_analysis"] * 6),
    *(["research_technical"] * 6),
    *(["product_announcement"] * 6),
    *(["promotion_borderline"] * 12),
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def build_reference_corpus() -> dict[str, Any]:
    stories: list[dict[str, Any]] = []
    for index, category in enumerate(_CATEGORIES, start=1):
        source_type = "rss" if index <= 18 else "telegram"
        length = ("short", "medium", "long")[(index - 1) % 3]
        flags = []
        if index <= 8:
            flags.append("conflicting_multi_source")
        if 9 <= index <= 14:
            flags.append("insufficient_evidence")
        if 15 <= index <= 24:
            flags.append("mixed_script")
        if 25 <= index <= 30:
            flags.append("language_hint_conflict")
        promotional = category == "promotion_borderline" and index % 2 == 0
        title = f"نمونه ارزیابی {index}: گزارش {category.replace('_', ' ')}"
        first_text = (
            f"در نمونه {index}، منبع اصلی اعلام کرد نسخه AI-{index} در ساعت ۱۴:۳۰ منتشر شد. "
            "این متن شامل فارسی، English name، عدد 2026 و نیم‌فاصله است."
        )
        if "insufficient_evidence" in flags:
            first_text = f"منبع {index} فقط از یک رویداد احتمالی خبر می‌دهد و جزئیات تأییدشده ارائه نمی‌کند."
        evidence = [
            {
                "id": str(uuid5(NAMESPACE_URL, f"newscraft-persian-corpus:{index}:evidence:1")),
                "evidence_key": f"corpus:{index}:1",
                "title": title,
                "source_url": f"https://evaluation.invalid/{source_type}/{index}/1",
                "text": first_text,
                "sha256": _sha256(first_text),
            }
        ]
        if "conflicting_multi_source" in flags or length == "long":
            second_text = (
                f"منبع دوم درباره نمونه {index} زمان انتشار را ۱۵:۰۰ گزارش کرده و تأکید می‌کند قیمت هنوز قطعی نیست."
            )
            evidence.append(
                {
                    "id": str(uuid5(NAMESPACE_URL, f"newscraft-persian-corpus:{index}:evidence:2")),
                    "evidence_key": f"corpus:{index}:2",
                    "title": f"گزارش تکمیلی نمونه {index}",
                    "source_url": f"https://evaluation.invalid/{source_type}/{index}/2",
                    "text": second_text,
                    "sha256": _sha256(second_text),
                }
            )
        stories.append(
            {
                "id": str(uuid5(NAMESPACE_URL, f"newscraft-persian-corpus:{index}")),
                "split": "calibration" if index <= 12 else "held_out",
                "source_type": source_type,
                "length": length,
                "category": category,
                "flags": flags,
                "title": title,
                "expected_language": "fa",
                "promotional": promotional,
                "title_constraints": {
                    "language": "fa",
                    "must_be_complete": True,
                    "must_not_be_link_only": True,
                    "must_not_be_generic": True,
                },
                "evidence": evidence,
                "expected_claims": [
                    {
                        "id": f"claim-{index}-1",
                        "text": first_text.split(".")[0],
                        "evidence_ids": [evidence[0]["id"]],
                    }
                ],
                "research_enabled": False,
            }
        )
    return {
        "schema_version": "persian-generation-corpus-v1",
        "description": "Locked synthetic Persian editorial qualification corpus; no production or personal data.",
        "stories": stories,
    }


__all__ = ["build_reference_corpus"]
