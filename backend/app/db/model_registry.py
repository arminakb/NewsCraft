from app.automations.definitions.models import (
    Automation,
    AutomationNodeRun,
    AutomationRun,
    AutomationRuntimeProjection,
    AutomationTemplate,
    AutomationVersion,
)
from app.automations.models import AutomationRoute
from app.codex_gateway.models import (
    CodexConnection,
    CodexIdempotencyRecord,
    CodexPairingSession,
    CodexRateLimitBucket,
)
from app.db.base import Base
from app.db.models import (
    ArticleCollection,
    ArticleCollectionItem,
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
from app.llm_providers.models import LLMProvider
from app.manual_publication.models import ManualPublicationPlan
from app.operator_settings.models import DateTimeSettings
from app.publishing.models import (
    Destination,
    Publication,
    PublishAttempt,
    PublishJob,
    TelegramDestinationMigrationIssue,
    TelegramProxyProfile,
)
from app.research.models import ResearchAttempt, ResearchRun, ResearchSource
from app.retention.models import RetentionPolicy, RetentionRun
from app.security.models import EncryptedSecret, SecurityAuditEvent
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

_MAPPED_CLASSES = (
    Automation,
    AutomationVersion,
    AutomationTemplate,
    AutomationRuntimeProjection,
    AutomationRun,
    AutomationNodeRun,
    AutomationRoute,
    TelegramDestinationMigrationIssue,
    CodexConnection,
    CodexIdempotencyRecord,
    CodexPairingSession,
    CodexRateLimitBucket,
    ArticleCollection,
    ArticleCollectionItem,
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
    LLMProvider,
    ManualPublicationPlan,
    DateTimeSettings,
    Destination,
    TelegramProxyProfile,
    Publication,
    PublishAttempt,
    PublishJob,
    RetentionPolicy,
    RetentionRun,
    EncryptedSecret,
    SecurityAuditEvent,
    ResearchAttempt,
    ResearchRun,
    ResearchSource,
    Story,
    StoryEvidenceLink,
    StoryEvidenceSnapshot,
    StoryRevision,
)

__all__ = ["Base"]
