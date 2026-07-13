from app.automations.models import AutomationRoute
from app.db.base import Base
from app.db.models import (
    ContentDraft,
    ContentItem,
    IngestRun,
    ItemIdentity,
    ItemMedia,
    MediaAsset,
    RawPayload,
    RewriteCandidate,
    Source,
    SourceItem,
)
from app.generation.models import (
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
)
from app.jobs.models import AutomationControl, RuntimeHeartbeat, WorkflowEvent, WorkflowJob, WorkflowSchedule
from app.manual_publication.models import ManualPublicationPlan
from app.publishing.models import Destination, Publication, PublishAttempt, PublishJob
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

_MAPPED_CLASSES = (
    AutomationRoute,
    ContentDraft,
    ContentItem,
    IngestRun,
    ItemIdentity,
    ItemMedia,
    MediaAsset,
    RawPayload,
    RewriteCandidate,
    Source,
    SourceItem,
    AIProviderProfile,
    BrandProfile,
    ContentPack,
    GenerationAttempt,
    GenerationRun,
    PlatformVariant,
    PlatformVariantRevision,
    PromptTemplate,
    PromptTemplateVersion,
    AutomationControl,
    RuntimeHeartbeat,
    WorkflowEvent,
    WorkflowJob,
    WorkflowSchedule,
    ManualPublicationPlan,
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    ResearchAttempt,
    ResearchRun,
    ResearchSource,
    Story,
    StoryEvidenceLink,
    StoryEvidenceSnapshot,
    StoryRevision,
)

__all__ = ["Base"]
