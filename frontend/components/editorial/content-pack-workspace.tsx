"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { EvidencePanel } from "@/components/editorial/evidence-panel"
import { RevisionTimeline } from "@/components/editorial/revision-timeline"
import { VariantEditor } from "@/components/editorial/variant-editor"
import { Button } from "@/components/ui/button"
import { CopyExportActions } from "@/features/packages/components/copy-export-actions"
import { MediaPlan } from "@/features/packages/components/media-plan"
import { PlatformEditor } from "@/features/packages/components/platform-editor"
import { PlatformPreview } from "@/features/packages/components/platform-preview"
import {
  approvePlatformRevision,
  getPackage,
  getPlatformRevision,
  getPlatformRevisions,
  rejectPlatformRevision,
  saveManualPlatformRevision,
} from "@/features/packages/api"
import type {
  CitationRef,
  ContentPackageVariant,
  ManualPlatformEditRequest,
  Platform,
  PlatformPayload,
  PlatformRevision,
  TelegramRevision,
} from "@/features/packages/types"
import {
  getAIProviderOptions,
  getPromptVersionOptions,
  getStoryEvidence,
  regenerateVariant,
  saveVariantRevision,
} from "@/lib/editorial-api"
import type { EvidenceCitation, VariantRevision } from "@/lib/editorial-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

const platformOrder: Platform[] = ["telegram", "instagram", "x", "blog"]

export function ContentPackWorkspace({ packId, initialRevisionId = null }: { packId: string; initialRevisionId?: string | null }) {
  const queryClient = useQueryClient()
  const [selectedVariantId, setSelectedVariantId] = useState<string | null>(null)
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(initialRevisionId)
  const [activeCitation, setActiveCitation] = useState<EvidenceCitation | null>(null)
  const [editorDirty, setEditorDirty] = useState(false)
  const [mediaError, setMediaError] = useState<string | null>(null)

  const pack = useQuery({ queryKey: queryKeys.contentPack(packId), queryFn: () => getPackage(packId) })
  const initialRevision = useQuery({
    queryKey: queryKeys.variantRevision(initialRevisionId ?? "unresolved"),
    queryFn: () => getPlatformRevision(initialRevisionId!),
    enabled: Boolean(initialRevisionId),
  })
  const variants = useMemo(
    () => [...(pack.data?.variants ?? [])].sort((left, right) => platformOrder.indexOf(left.platform) - platformOrder.indexOf(right.platform) || left.id.localeCompare(right.id)),
    [pack.data],
  )
  const intendedExportRevisions = useMemo(
    () => variants.map((variant) => ({
      variantId: variant.id,
      revisionId: variant.currentRevision?.id ?? null,
      approvalState: variant.currentRevision?.approvalState ?? null,
    })),
    [variants],
  )
  const initialVariantId = initialRevision.data?.variantId
  const activeVariant = variants.find((item) => item.id === selectedVariantId)
    ?? variants.find((item) => item.id === initialVariantId)
    ?? (!initialRevisionId || initialRevision.isError ? variants[0] : undefined)
  const revisionHistory = useQuery({
    queryKey: queryKeys.variantRevisions(activeVariant?.id ?? "unresolved"),
    queryFn: () => getPlatformRevisions(activeVariant!.id),
    enabled: Boolean(activeVariant),
  })
  const providers = useQuery({
    queryKey: queryKeys.editorialProviderOptions,
    queryFn: getAIProviderOptions,
    enabled: activeVariant?.platform === "telegram",
  })
  const prompts = useQuery({
    queryKey: queryKeys.editorialPromptOptions,
    queryFn: getPromptVersionOptions,
    enabled: activeVariant?.platform === "telegram",
  })
  const evidence = useQuery({
    queryKey: queryKeys.evidence(pack.data?.storyId ?? "unresolved"),
    queryFn: () => getStoryEvidence(pack.data!.storyId),
    enabled: Boolean(pack.data?.storyId),
  })

  const revisions = revisionHistory.data ?? (activeVariant?.currentRevision ? [activeVariant.currentRevision] : [])
  const revision = revisions.find((item) => item.id === selectedRevisionId)
    ?? (initialRevision.data?.variantId === activeVariant?.id ? initialRevision.data : undefined)
    ?? activeVariant?.currentRevision
    ?? revisions[0]
  const allowDiscard = () => !editorDirty || window.confirm("Discard unsaved revision edits?")

  const refreshPackageAndHistory = async (variantId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.contentPack(packId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.variantRevisions(variantId) }),
    ])
  }
  const cacheCreatedRevision = async (created: PlatformRevision) => {
    setSelectedRevisionId(created.id)
    setSelectedVariantId(created.variantId)
    setEditorDirty(false)
    queryClient.setQueryData(queryKeys.variantRevision(created.id), created)
    queryClient.setQueryData<PlatformRevision[]>(queryKeys.variantRevisions(created.variantId), (current) => upsertRevision(current, created))
    await refreshPackageAndHistory(created.variantId)
  }
  const refreshRevision = async (updated: PlatformRevision) => {
    queryClient.setQueryData(queryKeys.variantRevision(updated.id), updated)
    queryClient.setQueryData<PlatformRevision[]>(queryKeys.variantRevisions(updated.variantId), (current) => upsertRevision(current, updated))
    await Promise.all([
      refreshPackageAndHistory(updated.variantId),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDraft(updated.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDrafts() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramRoutes }),
    ])
  }
  const reloadLatestRevision = async (variantId: string) => {
    const updated = await getPlatformRevisions(variantId)
    queryClient.setQueryData(queryKeys.variantRevisions(variantId), updated)
    for (const item of updated) queryClient.setQueryData(queryKeys.variantRevision(item.id), item)
    const latest = latestRevision(updated)
    if (!latest) throw new Error("The latest revision is unavailable for this variant")
    setSelectedRevisionId(latest.id)
    setSelectedVariantId(variantId)
  }

  const telegramSave = useMutation({
    mutationFn: (input: Parameters<typeof saveVariantRevision>[1] & { variantId: string }) => saveVariantRevision(input.variantId, input),
    onSuccess: async (created) => {
      setSelectedRevisionId(created.id)
      setEditorDirty(false)
      await refreshPackageAndHistory(created.variantId)
    },
  })
  const manualSave = useMutation({
    mutationFn: (input: { variantId: string; request: ManualPlatformEditRequest }) => saveManualPlatformRevision(input.variantId, input.request),
    onSuccess: cacheCreatedRevision,
  })
  const approve = useMutation({
    mutationFn: ({ revisionId, expectedContentHash, note }: { revisionId: string; expectedContentHash: string; note: string | null }) => approvePlatformRevision(revisionId, { expectedContentHash, note }),
    onSuccess: refreshRevision,
  })
  const reject = useMutation({
    mutationFn: ({ revisionId, expectedContentHash, reason }: { revisionId: string; expectedContentHash: string; reason: string }) => rejectPlatformRevision(revisionId, { expectedContentHash, reason }),
    onSuccess: refreshRevision,
  })
  const regenerate = useMutation({
    mutationFn: (input: { variantId: string; providerProfileId: string; platformPromptTemplateVersionId: string; instruction: string | null }) => regenerateVariant(input.variantId, input),
    onSuccess: async (_job, input) => refreshPackageAndHistory(input.variantId),
  })
  const workspaceBusy = telegramSave.isPending || manualSave.isPending || approve.isPending || reject.isPending || regenerate.isPending

  const queryError = pack.error
    ?? initialRevision.error
    ?? revisionHistory.error
    ?? evidence.error
    ?? (activeVariant?.platform === "telegram" ? providers.error ?? prompts.error : null)
  if (queryError) return <main role="alert" className="p-6 text-red-700">{getApiErrorMessage(queryError, "Editorial workspace or captured evidence could not be loaded")}</main>
  const loading = pack.isPending
    || (Boolean(initialRevisionId) && initialRevision.isPending)
    || (Boolean(pack.data?.storyId) && evidence.isPending)
    || (Boolean(activeVariant) && revisionHistory.isPending)
    || (activeVariant?.platform === "telegram" && (providers.isPending || prompts.isPending))
  if (loading) return <main role="status" className="p-6">Loading editorial workspace and captured evidence…</main>
  if (!pack.data) return <main role="alert" className="p-6 text-red-700">Content package data is unavailable.</main>

  const chooseVariant = (variant: ContentPackageVariant) => {
    if (workspaceBusy || variant.id === activeVariant?.id || !allowDiscard()) return
    setSelectedVariantId(variant.id)
    setSelectedRevisionId(variant.currentRevision?.id ?? null)
    setActiveCitation(null)
    setEditorDirty(false)
    setMediaError(null)
  }
  const chooseRevision = (item: PlatformRevision) => {
    if (workspaceBusy || !allowDiscard()) return
    setSelectedRevisionId(item.id)
    setActiveCitation(null)
    setEditorDirty(false)
    setMediaError(null)
  }
  const reorderMedia = async (payload: PlatformPayload) => {
    if (!revision) return
    setMediaError(null)
    try {
      if (revision.platform === "telegram") {
        const telegramPayload = payload as TelegramRevision["payload"]
        await telegramSave.mutateAsync({
          variantId: revision.variantId,
          baseRevisionId: revision.id,
          baseContentHash: revision.contentHash,
          content: { body: telegramPayload.body, parseMode: telegramPayload.parseMode, buttons: telegramPayload.buttons },
          mediaAssetIds: telegramPayload.mediaAssetIds,
          editNote: "Reorder media assignments",
        })
      } else {
        await manualSave.mutateAsync({ variantId: revision.variantId, request: manualRequest(revision, payload, "Reorder media assignments") })
      }
    } catch (caught) {
      setMediaError(getApiErrorMessage(caught, "The reordered media plan could not be saved"))
    }
  }

  return <main className="min-w-0 space-y-4 p-4 md:p-6">
    <header><h1 className="text-2xl font-semibold">Multi-platform editorial studio</h1><p className="text-sm text-muted-foreground">Pack {pack.data.id} · {pack.data.status}</p></header>
    <div role="tablist" aria-label="Package platforms" className="flex flex-wrap gap-2 border-b pb-3">
      {variants.map((variant) => <button key={variant.id} type="button" role="tab" disabled={workspaceBusy} aria-selected={variant.id === activeVariant?.id} aria-controls={`platform-panel-${variant.id}`} className={`rounded-lg border px-3 py-2 text-sm ${variant.id === activeVariant?.id ? "bg-primary text-primary-foreground" : "bg-background"}`} onClick={() => chooseVariant(variant)}>{platformLabel(variant.platform)}</button>)}
    </div>
    {!activeVariant || !revision ? <section className="rounded-lg border p-4"><h2 className="font-semibold">No platform revision is ready</h2><p className="text-sm text-muted-foreground">Generation is pending for {activeVariant ? platformLabel(activeVariant.platform) : "this content package"}.</p></section> : <div id={`platform-panel-${activeVariant.id}`} role="tabpanel" aria-label={`${platformLabel(activeVariant.platform)} package`} className="space-y-4">
      <PlatformPreview revision={revision} />
      <div className="rounded-lg border p-4"><CopyExportActions key={revision.id} revision={revision} intendedRevisions={intendedExportRevisions} /></div>
      <div className="grid min-w-0 gap-4 min-[900px]:grid-cols-2">
        <div className="min-w-0 space-y-4">
          <EvidencePanel evidence={evidence.data ?? []} activeCitation={activeCitation} />
          <ExactEvidenceMap citations={revision.evidenceCitations} onSelect={(citation) => setActiveCitation(citation)} />
          <RevisionTimeline revisions={revisions} activeRevisionId={revision.id} onSelect={chooseRevision} disabled={workspaceBusy} />
        </div>
        <div className="min-w-0 space-y-4">
          {revision.platform === "telegram" ? <VariantEditor
            revision={telegramEditorRevision(revision)}
            availableProviders={providers.data ?? []}
            availablePromptVersions={prompts.data ?? []}
            onSave={(input) => telegramSave.mutateAsync(input)}
            onApprove={async (input) => {
              const updated = await approve.mutateAsync(input)
              if (updated.platform !== "telegram") throw new Error("Telegram approval returned a different platform")
              return telegramEditorRevision(updated)
            }}
            onReject={async (input) => {
              const updated = await reject.mutateAsync(input)
              if (updated.platform !== "telegram") throw new Error("Telegram rejection returned a different platform")
              return telegramEditorRevision(updated)
            }}
            onRegenerate={regenerate.mutateAsync}
            onReload={() => reloadLatestRevision(revision.variantId)}
            onDirtyChange={setEditorDirty}
            externalPending={telegramSave.isPending || approve.isPending || reject.isPending || regenerate.isPending}
          /> : <>
            <PlatformEditor
              revision={revision}
              onSave={(request) => manualSave.mutateAsync({ variantId: revision.variantId, request })}
              onReload={() => reloadLatestRevision(revision.variantId)}
              onDirtyChange={setEditorDirty}
              externalPending={manualSave.isPending || approve.isPending || reject.isPending}
            />
            <ManualReviewActions key={revision.id} revision={revision} dirty={editorDirty} pending={workspaceBusy} onApprove={(note) => approve.mutateAsync({ revisionId: revision.id, expectedContentHash: revision.contentHash, note })} onReject={(reason) => reject.mutateAsync({ revisionId: revision.id, expectedContentHash: revision.contentHash, reason })} />
          </>}
          <MediaPlan revision={revision} onReorder={editorDirty || workspaceBusy ? undefined : (payload) => void reorderMedia(payload)} />
          {mediaError ? <div role="alert" className="text-sm text-red-700">{mediaError}</div> : null}
          {revision.approvalState === "approved" && !workspaceBusy ? <a href={`/review/${revision.id}`} className="inline-flex text-primary underline">Preview, schedule, or publish approved revision</a> : <p className="text-sm text-muted-foreground">{workspaceBusy ? "Publishing handoff is unavailable while the revision update is saving." : "Publishing handoff is available only after approving this exact revision."}</p>}
        </div>
      </div>
    </div>}
  </main>
}

function ExactEvidenceMap({ citations, onSelect }: { citations: CitationRef[]; onSelect: (citation: CitationRef) => void }) {
  if (!citations.length) return <p>No evidence citations are stored for this revision.</p>
  return <section aria-label="Exact evidence map" className="space-y-2"><h2 className="font-semibold">Exact content/evidence map</h2>{citations.map((citation, index) => <button key={`${citation.evidenceSnapshotId}-${index}`} type="button" className="block w-full rounded border p-2 text-left" onClick={() => onSelect(citation)}><strong>{citation.evidenceKey}</strong><span className="block text-xs">Snapshot {citation.evidenceSnapshotId} · {citation.locator}</span><span className="block break-all text-xs">Excerpt hash {citation.excerptSha256}</span>{citation.sourceUrl ? <span className="block break-all text-xs">{citation.sourceUrl}</span> : <span className="block text-xs">Operator-provided text</span>}</button>)}</section>
}

function ManualReviewActions({ revision, dirty, pending, onApprove, onReject }: { revision: Exclude<PlatformRevision, TelegramRevision>; dirty: boolean; pending: boolean; onApprove: (note: string | null) => Promise<unknown>; onReject: (reason: string) => Promise<unknown> }) {
  const [rejectionReason, setRejectionReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const validationErrors = revision.validation.filter((issue) => issue.severity === "error")
  const run = async (operation: () => Promise<unknown>, message: string) => {
    setError(null)
    setOutcome(null)
    try { await operation(); setOutcome(message) }
    catch (caught) { setError(getApiErrorMessage(caught, "The review decision could not be saved")) }
  }
  return <section aria-labelledby="manual-review-heading" className="space-y-3 rounded-lg border p-3"><h2 id="manual-review-heading" className="font-semibold">Exact manual revision review</h2><div className="flex flex-wrap gap-2"><Button type="button" disabled={dirty || pending || validationErrors.length > 0 || revision.approvalState !== "pending_review"} onClick={() => void run(() => onApprove(null), "Revision approved")}>Approve revision</Button></div><label className="grid gap-1"><span>Rejection reason</span><textarea aria-label="Rejection reason" disabled={pending} className="rounded-lg border p-2" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} /></label><Button type="button" variant="outline" disabled={dirty || pending || !rejectionReason.trim() || revision.approvalState !== "pending_review"} onClick={() => void run(() => onReject(rejectionReason.trim()), "Revision rejected")}>Reject revision</Button>{validationErrors.map((issue) => <div key={`${issue.code}-${issue.path}`} role="alert" className="text-sm text-red-700">{issue.message}</div>)}{error ? <div role="alert" className="text-sm text-red-700">{error}</div> : null}{outcome ? <div role="status" className="text-sm text-green-700">{outcome}</div> : null}</section>
}

function telegramEditorRevision(revision: TelegramRevision): VariantRevision {
  return {
    id: revision.id,
    variantId: revision.variantId,
    contentPackId: revision.contentPackId,
    storyId: revision.storyId,
    parentRevisionId: revision.parentRevisionId,
    generationAttemptId: revision.generationAttemptId,
    revisionNumber: revision.revisionNumber,
    content: {
      body: revision.payload.body,
      parseMode: revision.payload.parseMode,
      buttons: revision.payload.buttons,
      mediaAssetIds: revision.payload.mediaAssetIds,
      sourceUrl: revision.payload.sourceUrl,
      mediaPolicy: revision.payload.mediaPolicy,
      direction: revision.payload.direction,
      dryRun: revision.payload.dryRun,
    },
    contentHash: revision.contentHash,
    evidenceMap: revision.evidenceCitations,
    validationResults: revision.validationResults,
    approvalState: revision.approvalState,
    approvalNote: revision.approvalNote,
    approvedAt: revision.approvedAt,
    createdBy: revision.createdBy,
    origin: revision.origin,
    createdAt: revision.createdAt,
    providerProfile: revision.providerProfile,
    resolvedModel: revision.resolvedModel,
  }
}

function upsertRevision(current: PlatformRevision[] | undefined, revision: PlatformRevision) {
  return [...(current ?? []).filter((item) => item.id !== revision.id), revision].sort((left, right) => right.revisionNumber - left.revisionNumber || right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id))
}

function latestRevision(revisions: PlatformRevision[]) {
  return [...revisions].sort((left, right) => right.revisionNumber - left.revisionNumber || right.createdAt.localeCompare(left.createdAt) || right.id.localeCompare(left.id))[0]
}

function manualRequest(revision: Exclude<PlatformRevision, TelegramRevision>, payload: PlatformPayload, editNote: string): ManualPlatformEditRequest {
  const evidenceMap = orderedDistinctCitations(revision.platform, payload)
  if (revision.platform === "instagram") return { baseRevisionId: revision.id, baseContentHash: revision.contentHash, payload: { platform: "instagram", content: payload as Extract<PlatformRevision, { platform: "instagram" }>["payload"] }, evidenceMap, editNote }
  if (revision.platform === "x") return { baseRevisionId: revision.id, baseContentHash: revision.contentHash, payload: { platform: "x", content: payload as Extract<PlatformRevision, { platform: "x" }>["payload"] }, evidenceMap, editNote }
  return { baseRevisionId: revision.id, baseContentHash: revision.contentHash, payload: { platform: "blog", content: payload as Extract<PlatformRevision, { platform: "blog" }>["payload"] }, evidenceMap, editNote }
}

function orderedDistinctCitations(platform: Exclude<Platform, "telegram">, payload: PlatformPayload) {
  const citations = platform === "instagram"
    ? (payload as Extract<PlatformRevision, { platform: "instagram" }>["payload"]).citations
    : platform === "x"
      ? (payload as Extract<PlatformRevision, { platform: "x" }>["payload"]).posts.flatMap((post) => post.citations)
      : (payload as Extract<PlatformRevision, { platform: "blog" }>["payload"]).citations
  const seen = new Set<string>()
  return citations.filter((citation) => {
    const key = JSON.stringify([citation.evidenceSnapshotId, citation.evidenceKey, citation.sourceUrl, citation.locator, citation.excerptSha256])
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function platformLabel(platform: Platform) {
  if (platform === "telegram") return "Telegram"
  if (platform === "instagram") return "Instagram"
  if (platform === "x") return "X"
  return "Blog"
}
