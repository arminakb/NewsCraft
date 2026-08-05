from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.automations.definitions.models import AutomationTemplate
from app.automations.definitions.schemas import WorkflowGraphV1, canonical_graph_data


@dataclass(frozen=True, slots=True)
class SystemTemplateSeed:
    key: str
    version: int
    name: str
    description: str
    complexity: str
    graph: WorkflowGraphV1
    requirements: tuple[str, ...]


def _graph(*, nodes: list[dict[str, object]], edges: list[dict[str, str]], output: str | None) -> WorkflowGraphV1:
    return WorkflowGraphV1.model_validate(
        {
            "schema_version": 1,
            "entry_node_id": nodes[0]["id"] if nodes else "",
            "nodes": nodes,
            "edges": edges,
            "output_node_ids": [output] if output else [],
            "metadata": {"layout": {node["id"]: {"x": 80 + index * 260, "y": 120} for index, node in enumerate(nodes)}},
        }
    )


_EMPTY_UUID = str(UUID(int=0))

SYSTEM_TEMPLATE_SEEDS = (
    SystemTemplateSeed(
        "blank-workflow",
        2,
        "Blank workflow",
        "Start with an empty canvas and add only the steps you need.",
        "starter",
        _graph(
            nodes=[],
            edges=[],
            output=None,
        ),
        (),
    ),
    SystemTemplateSeed(
        "research-first-draft",
        1,
        "Research-first Draft",
        "Research an exact Story revision before creating a reviewable content package.",
        "intermediate",
        _graph(
            nodes=[
                {"id": "trigger-1", "type": "manual", "config": {}},
                {"id": "research-1", "type": "research", "config": {}},
                {"id": "generate-1", "type": "generate_content_pack", "config": {}},
                {"id": "draft-1", "type": "save_drafts", "config": {}},
            ],
            edges=[
                {
                    "source_node_id": "trigger-1",
                    "source_port": "story",
                    "target_node_id": "research-1",
                    "target_port": "story",
                },
                {
                    "source_node_id": "research-1",
                    "source_port": "story",
                    "target_node_id": "generate-1",
                    "target_port": "story",
                },
                {
                    "source_node_id": "generate-1",
                    "source_port": "drafts",
                    "target_node_id": "draft-1",
                    "target_port": "drafts",
                },
            ],
            output="draft-1",
        ),
        ("manual", "research", "generation", "drafts"),
    ),
    SystemTemplateSeed(
        "breaking-news-telegram",
        1,
        "Breaking News to Telegram",
        "Capture new Telegram material, generate a Draft, require review, then publish safely.",
        "advanced",
        _graph(
            nodes=[
                {
                    "id": "trigger-1",
                    "type": "telegram_new_item",
                    "config": {"source_id": _EMPTY_UUID},
                },
                {"id": "generate-1", "type": "generate_telegram", "config": {}},
                {"id": "review-1", "type": "human_review", "config": {}},
                {
                    "id": "publish-1",
                    "type": "telegram_publish",
                    "config": {"destination_id": _EMPTY_UUID},
                },
            ],
            edges=[
                {
                    "source_node_id": "trigger-1",
                    "source_port": "story",
                    "target_node_id": "generate-1",
                    "target_port": "story",
                },
                {
                    "source_node_id": "generate-1",
                    "source_port": "draft",
                    "target_node_id": "review-1",
                    "target_port": "draft",
                },
                {
                    "source_node_id": "review-1",
                    "source_port": "approved",
                    "target_node_id": "publish-1",
                    "target_port": "draft",
                },
            ],
            output="publish-1",
        ),
        ("telegram_source", "generation", "human_review", "telegram_destination"),
    ),
)


async def seed_automation_templates(session: AsyncSession) -> list[AutomationTemplate]:
    existing = {
        (item.seed_key, item.seed_version)
        for item in await session.scalars(select(AutomationTemplate))
    }
    created: list[AutomationTemplate] = []
    for seed in SYSTEM_TEMPLATE_SEEDS:
        if (seed.key, seed.version) in existing:
            continue
        row = AutomationTemplate(
            seed_key=seed.key,
            seed_version=seed.version,
            ownership="system_managed",
            name=seed.name,
            description=seed.description,
            complexity=seed.complexity,
            graph_seed=canonical_graph_data(seed.graph),
            capability_requirements=list(seed.requirements),
        )
        session.add(row)
        created.append(row)
    if created:
        await session.flush()
    return created


__all__ = ["SYSTEM_TEMPLATE_SEEDS", "seed_automation_templates"]
