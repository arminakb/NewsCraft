"""Model registry for Alembic autogenerate.

The import block below *is* the registry: importing every module that defines
mapped classes is what populates ``Base.metadata``, and ``alembic/env.py``
targets that metadata. There is deliberately no separate tuple of mapped
classes — such a list is never read, drifts silently out of date, and gives a
false sense of completeness. ``tests/test_model_registry.py`` fails loudly if a
module defining mapped classes is ever added without an import here (without
which ``alembic revision --autogenerate`` would emit ``DROP TABLE``).
"""

# ruff: noqa: F401  (these imports exist for their registration side effect)

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
from app.source_collections.models import (
    IngestRunSourceSnapshot,
    SourceCollection,
    SourceCollectionIngestionSubscription,
    SourceCollectionMembership,
)
from app.stories.models import Story, StoryEvidenceLink, StoryEvidenceSnapshot, StoryRevision

__all__ = ["Base"]
