from __future__ import annotations

import builtins
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.automations.definitions.schemas import (
    ARTIFACT_CAPABILITIES,
    ARTIFACT_KINDS,
    ArtifactInputContract,
    ArtifactOutputContract,
    AutomationNodeCatalogOut,
    NodeCatalogItemOut,
    PortCatalogOut,
)

PlatformName = Literal["telegram", "instagram", "x", "blog"]
ValidatorName = Literal["evidence", "required_fields", "platform_shape", "attribution", "media", "duplicate_guard"]
Sha256Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


def _default_platforms() -> list[PlatformName]:
    return ["telegram"]


def _default_validators() -> list[ValidatorName]:
    return ["evidence", "required_fields", "platform_shape"]


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ManualConfig(_ConfigModel):
    story_revision_id: UUID | None = None


class CollectionArticleAddedConfig(_ConfigModel):
    collection_id: UUID | None = None


class NewSourceItemConfig(_ConfigModel):
    source_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ScheduleConfig(_ConfigModel):
    schedule_kind: Literal["daily", "interval"] = "daily"
    timezone: str = Field(default="Asia/Tehran", min_length=1, max_length=255)
    local_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    interval_minutes: int | None = Field(default=None, ge=5, le=10_080)
    catch_up_limit: int = Field(default=1, ge=0, le=10)

    @model_validator(mode="after")
    def validate_schedule_fields(self):
        if self.schedule_kind == "daily" and self.local_time is None:
            raise ValueError("daily schedule requires local_time")
        if self.schedule_kind == "interval" and self.interval_minutes is None:
            raise ValueError("interval schedule requires interval_minutes")
        return self


class SelectContentConfig(_ConfigModel):
    source_ids: list[UUID] = Field(default_factory=list, max_length=50)
    languages: list[str] = Field(default_factory=list, max_length=20)
    topics: list[str] = Field(default_factory=list, max_length=50)
    content_types: list[str] = Field(default_factory=list, max_length=20)
    minimum_score: int | None = Field(default=None, ge=0, le=100)
    require_media: bool | None = None
    sort: Literal["newest", "oldest", "score"] = "newest"
    max_count: int = Field(default=20, ge=1, le=200)


class FilterContentConfig(_ConfigModel):
    include_terms: list[str] = Field(default_factory=list, max_length=100)
    exclude_terms: list[str] = Field(default_factory=list, max_length=100)
    min_text_characters: int = Field(default=1, ge=1, le=100_000)
    require_media: bool = False


class ResearchConfig(_ConfigModel):
    provider_profile_id: UUID | None = Field(
        default=None,
        title="LLM Provider",
        description="LLM provider profile from Settings used to run research.",
    )
    prompt_template_version_id: UUID | None = Field(
        default=None,
        title="System Prompt",
        description="Reusable system prompt from Settings → Prompts used as the research instruction.",
    )
    prompt_checksum_sha256: Sha256Checksum | None = Field(
        default=None,
        title="Prompt Checksum",
        description="Immutable checksum of the selected prompt version.",
    )
    mode: Literal["manual", "auto_if_incomplete"] = "auto_if_incomplete"
    query_budget: int = Field(
        default=3, ge=1, le=10, title="Query Budget",
        description="How many search queries the research agent may perform.",
    )
    page_budget: int = Field(
        default=10, ge=1, le=50, title="Page Budget",
        description="How many pages the agent may inspect.",
    )
    time_budget_seconds: int = Field(
        default=120, ge=10, le=600, title="Time Budget",
        description="Maximum allowed research execution time in seconds.",
    )


class GenerateContentPackConfig(_ConfigModel):
    editorial_profile_id: UUID | None = None
    provider_profile_id: UUID | None = Field(
        default=None,
        title="LLM Provider",
        description="LLM provider profile from Settings used to generate content.",
    )
    prompt_version_ids: list[UUID] = Field(default_factory=list, max_length=10)
    prompt_checksums: dict[UUID, Sha256Checksum] = Field(default_factory=dict, max_length=10)
    platforms: list[PlatformName] = Field(default_factory=_default_platforms, min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_prompt_snapshots(self):
        if set(self.prompt_checksums) != set(self.prompt_version_ids):
            raise ValueError("prompt checksums must match the exact prompt-version IDs")
        return self


class ValidateConfig(_ConfigModel):
    validator_ids: list[ValidatorName] = Field(default_factory=_default_validators, min_length=1, max_length=6)


class HumanReviewConfig(_ConfigModel):
    instructions: str | None = Field(default=None, max_length=500)


class EmptyConfig(_ConfigModel):
    pass


class ManualPackageConfig(_ConfigModel):
    platforms: list[Literal["instagram", "x", "blog"]] = Field(min_length=1, max_length=3)


class TelegramPublishConfig(_ConfigModel):
    destination_id: UUID | None = None
    quiet_hours: dict[str, str] | None = None
    retry_policy: dict[str, int] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PortDefinition:
    # Kept only for readable legacy graphs and old clients. Compatibility uses contracts below.
    artifact_types: tuple[str, ...]
    required: bool = True
    max_connections: int | None = 1
    input_contract: ArtifactInputContract | None = None
    output_contract: ArtifactOutputContract | None = None


@dataclass(frozen=True, slots=True)
class NodeDefinition:
    type: str
    family: str
    display_name: str
    description: str
    config_model: builtins.type[_ConfigModel]
    inputs: dict[str, PortDefinition]
    outputs: dict[str, PortDefinition]
    entry: bool = False
    terminal: bool = False
    runtime_status: Literal["existing", "extension", "unavailable"] = "existing"
    runtime_owner: Literal["api", "scheduler", "source", "generation", "publishing", "compiler"] = "compiler"
    runtime_job_types: tuple[str, ...] = ()
    ui_hints: dict[str, object] | None = None
    input_contract: ArtifactInputContract | None = None
    output_contract: ArtifactOutputContract | None = None
    preserves_input_artifact: bool = False

    def catalog_item(self) -> NodeCatalogItemOut:
        def ports(values: dict[str, PortDefinition]) -> list[PortCatalogOut]:
            return [
                PortCatalogOut(
                    name=name,
                    artifact_types=list(port.artifact_types),
                    required=port.required,
                    max_connections=port.max_connections,
                    input_contract=port.input_contract,
                    output_contract=port.output_contract,
                )
                for name, port in values.items()
            ]

        return NodeCatalogItemOut(
            type=self.type,
            family=self.family,
            display_name=self.display_name,
            description=self.description,
            entry=self.entry,
            terminal=self.terminal,
            runtime_status=self.runtime_status,
            runtime_owner=self.runtime_owner,
            runtime_job_types=list(self.runtime_job_types),
            inputs=ports(self.inputs),
            outputs=ports(self.outputs),
            config_schema=self.config_model.model_json_schema(),
            ui_hints=self.ui_hints or {},
            input_contract=self.input_contract
            or next((port.input_contract for port in self.inputs.values() if port.input_contract is not None), None),
            output_contract=self.output_contract
            or next((port.output_contract for port in self.outputs.values() if port.output_contract is not None), None),
            preserves_input_artifact=self.preserves_input_artifact
            or any(
                port.output_contract and port.output_contract.preserves_input_artifact
                for port in self.outputs.values()
            ),
        )


STORY = ("story.revision_ref",)
RESEARCHED_STORY = ("story.researched_revision_ref",)
ANY_STORY = STORY + RESEARCHED_STORY
COLLECTION_ARTICLE_ARTIFACT = "article.collection_added"
COLLECTION_ARTICLE = (COLLECTION_ARTICLE_ARTIFACT,)
STORY_SET = ("story.revision_set_ref",)
DRAFT_SET = ("draft.revision_set_ref",)
VALIDATED_DRAFT_SET = ("draft.validated_revision_set_ref",)
ANY_DRAFT_SET = DRAFT_SET + VALIDATED_DRAFT_SET

_ARTICLE_INPUT = ArtifactInputContract(
    all_of=["textual"],
    any_of=["article", "generatable"],
    accepted_kinds=["article", "research"],
)
_RESEARCH_INPUT = ArtifactInputContract(
    all_of=["textual"],
    any_of=["article", "generatable"],
    accepted_kinds=["article", "research"],
)
_GENERATE_INPUT = ArtifactInputContract(
    all_of=["generatable"],
    accepted_kinds=["article", "research"],
)
_REVIEWABLE_INPUT = ArtifactInputContract(all_of=["reviewable"])
_DRAFT_INPUT = ArtifactInputContract(all_of=["draft"], accepted_kinds=["draft"])
_APPROVED_DRAFT_INPUT = ArtifactInputContract(
    all_of=["approved", "publishable"],
    accepted_kinds=["draft"],
)
_SCHEDULE_INPUT = ArtifactInputContract(all_of=["schedule-context"], accepted_kinds=["schedule_event"])

_ARTICLE_OUTPUT = ArtifactOutputContract(
    kind="article",
    capabilities=["textual", "structured", "article", "reviewable", "generatable"],
)
_COLLECTION_ARTICLE_OUTPUT = ArtifactOutputContract(
    kind="article",
    capabilities=[
        "textual",
        "structured",
        "article",
        "reviewable",
        "generatable",
        "collection-context",
    ],
)
_SOURCE_ARTICLE_OUTPUT = ArtifactOutputContract(
    kind="article",
    capabilities=["textual", "structured", "article", "reviewable", "generatable", "source-context"],
)
_SCHEDULE_OUTPUT = ArtifactOutputContract(kind="schedule_event", capabilities=["structured", "schedule-context"])
_RESEARCH_OUTPUT = ArtifactOutputContract(
    kind="research",
    capabilities=["textual", "structured", "research", "reviewable", "generatable"],
)
_DRAFT_OUTPUT = ArtifactOutputContract(
    kind="draft",
    capabilities=["textual", "structured", "draft", "reviewable"],
)
_PRESERVE_DRAFT_OUTPUT = ArtifactOutputContract(
    kind="draft",
    capabilities=["structured"],
    preserves_input_artifact=True,
)
_PRESERVE_OUTPUT = ArtifactOutputContract(preserves_input_artifact=True)
_APPROVED_OUTPUT = ArtifactOutputContract(
    preserves_input_artifact=True,
    adds_capabilities=["approved", "publishable"],
)
_PUBLICATION_OUTPUT = ArtifactOutputContract(
    kind="publication",
    capabilities=["structured", "approved", "publishable"],
)


NODE_REGISTRY: dict[str, NodeDefinition] = {
    item.type: item
    for item in (
        NodeDefinition(
            "manual",
            "trigger",
            "Manual",
            "Start with an exact saved Story revision.",
            ManualConfig,
            {},
            {"story": PortDefinition(STORY, max_connections=None, output_contract=_ARTICLE_OUTPUT)},
            entry=True,
            runtime_status="existing",
            runtime_owner="api",
            runtime_job_types=("content_pack.generate", "content_pack.generate_telegram"),
            ui_hints={"icon": "mouse-pointer-click", "accent": "green"},
        ),
        NodeDefinition(
            "collection_article_added",
            "trigger",
            "Collection article added",
            "Start when a new article is saved to one Feed collection.",
            CollectionArticleAddedConfig,
            {},
            {
                "article": PortDefinition(
                    COLLECTION_ARTICLE,
                    max_connections=None,
                    output_contract=_COLLECTION_ARTICLE_OUTPUT,
                )
            },
            entry=True,
            terminal=True,
            runtime_status="existing",
            runtime_owner="compiler",
            runtime_job_types=("automation.run.start",),
            ui_hints={"icon": "file-text", "accent": "green", "settings_section": "feed"},
        ),
        NodeDefinition(
            "new_source_item",
            "trigger",
            "New Source Item",
            "Start after a genuinely new RSS, Atom, or public Telegram source item is persisted.",
            NewSourceItemConfig,
            {},
            {
                "item": PortDefinition(
                    ("source_item.ref", "content_item.ref"),
                    max_connections=None,
                    output_contract=_SOURCE_ARTICLE_OUTPUT,
                )
            },
            entry=True,
            terminal=True,
            runtime_owner="source",
            runtime_job_types=("automation.run.start",),
            ui_hints={"icon": "radio", "accent": "green", "settings_section": "sources"},
        ),
        NodeDefinition(
            "schedule",
            "trigger",
            "Schedule",
            "Start on a bounded daily or interval schedule.",
            ScheduleConfig,
            {},
            {"tick": PortDefinition(("run.signal",), max_connections=None, output_contract=_SCHEDULE_OUTPUT)},
            entry=True,
            runtime_status="extension",
            runtime_owner="scheduler",
            runtime_job_types=("automation.run.start",),
            ui_hints={"icon": "clock", "accent": "green"},
        ),
        NodeDefinition(
            "select_content",
            "select_filter",
            "Select content",
            "Select a bounded deterministic set of newsroom content.",
            SelectContentConfig,
            {"tick": PortDefinition(("run.signal",), required=False, input_contract=_SCHEDULE_INPUT)},
            {
                "stories": PortDefinition(
                    ("story.revision_set_ref",),
                    max_connections=None,
                    output_contract=_ARTICLE_OUTPUT,
                )
            },
            runtime_status="extension",
            runtime_owner="generation",
            runtime_job_types=("automation.run.start",),
            ui_hints={"icon": "list-filter", "accent": "blue"},
        ),
        NodeDefinition(
            "filter_content",
            "select_filter",
            "Filter content",
            "Pass or stop using deterministic allowlisted rules.",
            FilterContentConfig,
            {"story": PortDefinition(STORY + COLLECTION_ARTICLE, input_contract=_ARTICLE_INPUT)},
            {
                "accepted": PortDefinition(
                    STORY + COLLECTION_ARTICLE,
                    max_connections=None,
                    output_contract=_PRESERVE_OUTPUT,
                )
            },
            runtime_owner="generation",
            runtime_job_types=("telegram.route.process",),
            ui_hints={"icon": "filter", "accent": "blue"},
        ),
        NodeDefinition(
            "research",
            "research",
            "AI Research",
            "Add bounded source-grounded research evidence.",
            ResearchConfig,
            {"story": PortDefinition(STORY + COLLECTION_ARTICLE, input_contract=_RESEARCH_INPUT)},
            {"story": PortDefinition(RESEARCHED_STORY, max_connections=None, output_contract=_RESEARCH_OUTPUT)},
            runtime_owner="generation",
            runtime_job_types=("research_story",),
            ui_hints={"icon": "search", "accent": "purple", "settings_section": "llm-providers"},
        ),
        NodeDefinition(
            "generate_content_pack",
            "generate",
            "Generate content package",
            "Generate bounded reviewable platform drafts.",
            GenerateContentPackConfig,
            {"story": PortDefinition(ANY_STORY + STORY_SET + COLLECTION_ARTICLE, input_contract=_GENERATE_INPUT)},
            {"drafts": PortDefinition(DRAFT_SET, max_connections=None, output_contract=_DRAFT_OUTPUT)},
            runtime_owner="generation",
            runtime_job_types=("content_pack.generate", "content_pack.generate_telegram"),
            ui_hints={"icon": "sparkles", "accent": "purple", "settings_section": "llm-providers"},
        ),
        NodeDefinition(
            "validate",
            "validate",
            "Validate",
            "Apply fixed evidence and platform gates.",
            ValidateConfig,
            {"drafts": PortDefinition(DRAFT_SET, input_contract=_DRAFT_INPUT)},
            {"valid": PortDefinition(VALIDATED_DRAFT_SET, max_connections=None, output_contract=_PRESERVE_OUTPUT)},
            runtime_owner="compiler",
            ui_hints={"icon": "shield-check", "accent": "blue"},
        ),
        NodeDefinition(
            "human_review",
            "review",
            "Human Review",
            "Wait for approval of an exact immutable revision.",
            HumanReviewConfig,
            {"draft": PortDefinition(("draft.telegram_revision_ref",), input_contract=_REVIEWABLE_INPUT)},
            {
                "approved": PortDefinition(
                    ("draft.approved_telegram_revision_ref",),
                    max_connections=None,
                    output_contract=_APPROVED_OUTPUT,
                )
            },
            runtime_owner="api",
            ui_hints={"icon": "user-check", "accent": "purple"},
        ),
        NodeDefinition(
            "save_drafts",
            "output",
            "Save to Drafts",
            "Finish with persisted immutable draft revisions.",
            EmptyConfig,
            {"drafts": PortDefinition(ANY_DRAFT_SET, input_contract=_DRAFT_INPUT)},
            {},
            terminal=True,
            runtime_owner="compiler",
            ui_hints={"icon": "file-check", "accent": "amber"},
        ),
        NodeDefinition(
            "manual_package",
            "output",
            "Manual publishing package",
            "Create a reviewable package for manual publication.",
            ManualPackageConfig,
            {"drafts": PortDefinition(DRAFT_SET, input_contract=_DRAFT_INPUT)},
            {
                "package": PortDefinition(
                    ("export.manual_package_ref",),
                    max_connections=None,
                    output_contract=_PRESERVE_DRAFT_OUTPUT,
                )
            },
            terminal=True,
            runtime_owner="generation",
            runtime_job_types=("build_export",),
            ui_hints={"icon": "package", "accent": "amber"},
        ),
        NodeDefinition(
            "telegram_publish",
            "output",
            "Publish to Telegram",
            "Publish an approved exact revision through the publishing worker.",
            TelegramPublishConfig,
            {"draft": PortDefinition(("draft.approved_telegram_revision_ref",), input_contract=_APPROVED_DRAFT_INPUT)},
            {
                "publication": PortDefinition(
                    ("publication.telegram_ref",),
                    max_connections=None,
                    output_contract=_PUBLICATION_OUTPUT,
                )
            },
            terminal=True,
            runtime_owner="publishing",
            runtime_job_types=("telegram.publish",),
            ui_hints={"icon": "send", "accent": "amber", "settings_section": "telegram"},
        ),
    )
}


def node_catalog() -> AutomationNodeCatalogOut:
    return AutomationNodeCatalogOut(
        nodes=[definition.catalog_item() for definition in NODE_REGISTRY.values()],
        artifact_capabilities=list(ARTIFACT_CAPABILITIES),
        artifact_kinds=list(ARTIFACT_KINDS),
    )


__all__ = [
    "COLLECTION_ARTICLE_ARTIFACT",
    "NODE_REGISTRY",
    "NodeDefinition",
    "PortDefinition",
    "node_catalog",
]
