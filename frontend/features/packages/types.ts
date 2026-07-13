export type Platform = "telegram" | "instagram" | "x" | "blog"
export type ManualPlatform = Exclude<Platform, "telegram">

export type TelegramButton = {
  text: string
  url: string
}

export type CitationRef = {
  evidenceSnapshotId: string
  evidenceKey: string
  sourceUrl: string | null
  locator: string
  excerptSha256: string
}

export type MediaAssignment = {
  mediaAssetId: string | null
  role: "hero" | "slide" | "post" | "inline"
  order: number
  altText: string
  manualBrief: string | null
  imagePrompt: string | null
}

export type SourceMedia = {
  id: string
  kind: string
  mimeType: string | null
  width: number | null
  height: number | null
  durationSeconds: string | null
  byteLength: number | null
  checksumSha256: string | null
  fetchStatus: string
  available: boolean
  role: string
  order: number
}

/** The exact nine Release 2 keys stored for a Telegram variant. */
export type TelegramPayload = {
  body: string
  parseMode: "HTML"
  buttons: TelegramButton[]
  sourceItemId: string | null
  sourceUrl: string | null
  mediaPolicy: "preserve" | "omit" | "replace_manually"
  mediaAssetIds: string[]
  direction: "ltr" | "rtl"
  dryRun: boolean
}

export type InstagramSlide = {
  order: number
  headline: string
  body: string
  media: MediaAssignment
}

export type InstagramPayload = {
  hook: string
  caption: string
  cta: string
  hashtags: string[]
  altText: string
  carousel: InstagramSlide[]
  citations: CitationRef[]
  manualChecklist: string[]
}

export type XPost = {
  order: number
  text: string
  media: MediaAssignment[]
  citations: CitationRef[]
}

export type XPayload = {
  mode: "single" | "thread"
  posts: XPost[]
  linkStrategy: "first_post" | "last_post" | "each_post" | "no_link"
  manualChecklist: string[]
}

export type BlogPayload = {
  title: string
  slug: string
  excerpt: string
  bodyMarkdown: string
  headings: string[]
  citations: CitationRef[]
  tags: string[]
  seoDescription: string
  heroMedia: MediaAssignment | null
  canonicalSources: string[]
  manualChecklist: string[]
}

export type PlatformPayload = TelegramPayload | InstagramPayload | XPayload | BlogPayload

export type ValidationResult = {
  gate: string
  ok: boolean
  reason: string | null
}

export type ValidationIssue = {
  code: string
  path: string
  message: string
  severity: "error" | "warning"
}

export type RevisionState = "draft" | "pending_review" | "approved" | "rejected"

export type RevisionProvider = {
  id: string
  name: string
  providerType: string
}

export type RevisionPromptVersion = {
  id: string
  version: number
  outputSchemaVersion: string
  checksumSha256: string
}

export type PlatformRevisionBase<
  P extends Platform,
  Payload extends PlatformPayload,
  Plan extends string[] | MediaAssignment[],
> = {
  id: string
  platform: P
  variantId: string
  contentPackId: string
  storyId: string
  parentRevisionId: string | null
  generationAttemptId: string | null
  revisionNumber: number
  payload: Payload
  contentHash: string
  evidenceCitations: CitationRef[]
  manualChecklist: string[]
  validationResults: ValidationResult[]
  validation: ValidationIssue[]
  mediaPlan: Plan
  sourceMedia: SourceMedia[]
  approvalState: RevisionState
  approvalNote: string | null
  approvedAt: string | null
  createdBy: string
  origin: "operator" | "generation" | "automation"
  providerProfile: RevisionProvider | null
  resolvedModel: string | null
  promptVersion: RevisionPromptVersion | null
  createdAt: string
}

export type TelegramRevision = PlatformRevisionBase<"telegram", TelegramPayload, string[]>
export type InstagramRevision = PlatformRevisionBase<"instagram", InstagramPayload, MediaAssignment[]>
export type XRevision = PlatformRevisionBase<"x", XPayload, MediaAssignment[]>
export type BlogRevision = PlatformRevisionBase<"blog", BlogPayload, MediaAssignment[]>

// Descriptive aliases keep component imports readable without creating a
// second revision shape.
export type TelegramPlatformRevision = TelegramRevision
export type InstagramPlatformRevision = InstagramRevision
export type XPlatformRevision = XRevision
export type BlogPlatformRevision = BlogRevision

export type PlatformRevision = TelegramRevision | InstagramRevision | XRevision | BlogRevision

export type ManualPayloadByPlatform = {
  instagram: InstagramPayload
  x: XPayload
  blog: BlogPayload
}

export type ManualPlatformEditPayload = {
  [P in ManualPlatform]: { platform: P; content: ManualPayloadByPlatform[P] }
}[ManualPlatform]

export type ManualPlatformEditRequest<P extends ManualPlatform = ManualPlatform> = {
  baseRevisionId: string
  baseContentHash: string
  payload: Extract<ManualPlatformEditPayload, { platform: P }>
  evidenceMap: CitationRef[]
  editNote: string
}

export type ContentPackageVariant = {
  id: string
  platform: Platform
  currentRevision: PlatformRevision | null
}

export type ContentPackage = {
  id: string
  storyId: string
  storyRevisionId: string
  brandProfileId: string
  status: string
  createdAt: string
  updatedAt: string
  variants: ContentPackageVariant[]
}

export type ExportFormat = "json" | "markdown" | "html" | "zip"
export type ExportJobStatus = "queued" | "running" | "succeeded" | "failed" | "needs_review" | "cancelled"

export type ExportRequest = {
  revisionIds: string[] | null
  formats: ExportFormat[]
  includeMedia: boolean
}

export type ExportJobAccepted = {
  jobId: string
  status: ExportJobStatus
  deduplicated: boolean
}

export type ExportVariantIdentity = {
  platform: Platform
  platformVariantId: string
  revisionId: string
  contentHash: string
  approvalState: "approved"
  evidenceUrls: string[]
}

export type ExportFileIdentity = {
  fileName: string
  sha256: string
  byteLength: number
  kind: "json" | "markdown" | "html" | "media"
  platform: Platform
  revisionId: string
  mediaAssetId: string | null
}

export type ExportManifest = {
  schemaVersion: "newscraft-export-v1"
  contentPackId: string
  storyRevisionId: string
  createdAt: string
  variants: ExportVariantIdentity[]
  files: ExportFileIdentity[]
}

export type CompleteExportArtifact = {
  exportId: string
  contentPackId: string
  state: "complete"
  manifestFile: "manifest.json"
  manifestSha256: string
  archiveFile: "bundle.zip" | null
  archiveSha256: string | null
  manifest: ExportManifest
}

export type ExpiredExportArtifact = {
  exportId: string
  contentPackId: string
  state: "expired"
  expiredAt: string
}

export type ExportArtifact = CompleteExportArtifact | ExpiredExportArtifact

export type ExportOutcome = {
  exportId: string
  status: ExportJobStatus
  finishedAt: string | null
  artifact: ExportArtifact | null
  downloads: string[]
  errorCode: string | null
  errorMessage: string | null
}

export type ManualPublicationStatus = "planned" | "ready" | "manual_published" | "cancelled"

export type ManualPublicationPlan = {
  id: string
  platformVariantRevisionId: string
  platform: ManualPlatform
  scheduledFor: string
  displayTimezone: string
  status: ManualPublicationStatus
  checklistState: Record<string, boolean>
  externalUrl: string | null
  operatorNote: string | null
  completedAt: string | null
  createdAt: string
  updatedAt: string
}
