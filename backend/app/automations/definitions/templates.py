from __future__ import annotations

from dataclasses import dataclass

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
