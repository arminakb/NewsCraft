"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { EvidencePanel } from "@/components/editorial/evidence-panel"
import { RevisionTimeline } from "@/components/editorial/revision-timeline"
import { VariantEditor } from "@/components/editorial/variant-editor"
import { approveVariantRevision, getAIProviderOptions, getContentPack, getPromptVersionOptions, getStoryEvidence, regenerateVariant, rejectVariantRevision, saveVariantRevision } from "@/lib/editorial-api"
import type { EvidenceCitation, VariantRevision } from "@/lib/editorial-types"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

export function ContentPackWorkspace({ packId, initialRevisionId = null }: { packId: string; initialRevisionId?: string | null }) {
  const queryClient = useQueryClient()
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(initialRevisionId)
  const [activeCitation, setActiveCitation] = useState<EvidenceCitation | null>(null)
  const [editorDirty, setEditorDirty] = useState(false)
  const pack = useQuery({ queryKey: queryKeys.contentPack(packId), queryFn: () => getContentPack(packId) })
  const providers = useQuery({ queryKey: queryKeys.editorialProviderOptions, queryFn: getAIProviderOptions })
  const prompts = useQuery({ queryKey: queryKeys.editorialPromptOptions, queryFn: getPromptVersionOptions })
  const evidence = useQuery({ queryKey: queryKeys.evidence(pack.data?.storyId ?? "unresolved"), queryFn: () => getStoryEvidence(pack.data!.storyId), enabled: Boolean(pack.data?.storyId) })
  const revisions = useMemo(() => pack.data?.variants.flatMap((variant) => pack.data.variantRevisions[variant.id] ?? []) ?? [], [pack.data])
  const revision = revisions.find((item) => item.id === selectedRevisionId) ?? revisions[0]
  const allowDiscard = () => !editorDirty || window.confirm("Discard unsaved revision edits?")
  const refresh = async () => { await queryClient.invalidateQueries({ queryKey: queryKeys.contentPack(packId) }) }
  const refreshRevision = async (updated: VariantRevision) => {
    queryClient.setQueryData(queryKeys.variantRevision(updated.id), updated)
    queryClient.setQueryData(queryKeys.contentPack(packId), (current: typeof pack.data) => current ? { ...current, variantRevisions: { ...current.variantRevisions, [updated.variantId]: (current.variantRevisions[updated.variantId] ?? []).map((item) => item.id === updated.id ? updated : item) } } : current)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.contentPack(packId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.variantRevision(updated.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.variantRevisions(updated.variantId) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDraft(updated.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramDrafts() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.telegramRoutes }),
    ])
  }
  const reloadLatestRevision = async (variantId: string) => {
    const updated = await getContentPack(packId)
    queryClient.setQueryData(queryKeys.contentPack(packId), updated)
    const latest = [...(updated.variantRevisions[variantId] ?? [])].sort((left, right) =>
      right.revisionNumber - left.revisionNumber
      || right.createdAt.localeCompare(left.createdAt)
      || right.id.localeCompare(left.id)
    )[0]
    if (!latest) throw new Error("The latest revision is unavailable for this variant")
    setSelectedRevisionId(latest.id)
  }
  const save = useMutation({ mutationFn: (input: Parameters<NonNullable<React.ComponentProps<typeof VariantEditor>["onSave"]>>[0]) => saveVariantRevision(input.variantId, { baseRevisionId: input.baseRevisionId, baseContentHash: input.baseContentHash, content: input.content, mediaAssetIds: input.mediaAssetIds, editNote: input.editNote }), onSuccess: async (created) => { setSelectedRevisionId(created.id); await refresh() } })
  const approve = useMutation({ mutationFn: (input: { revisionId: string; expectedContentHash: string; note: string | null }) => approveVariantRevision(input.revisionId, input), onSuccess: refreshRevision })
  const reject = useMutation({ mutationFn: (input: { revisionId: string; expectedContentHash: string; reason: string }) => rejectVariantRevision(input.revisionId, { reason: input.reason }, input.expectedContentHash), onSuccess: refreshRevision })
  const regenerate = useMutation({ mutationFn: (input: { variantId: string; providerProfileId: string; platformPromptTemplateVersionId: string; instruction: string | null }) => regenerateVariant(input.variantId, input), onSuccess: refresh })
  if (pack.isError || providers.isError || prompts.isError || evidence.isError) return <main role="alert" className="p-6 text-red-700">{getApiErrorMessage(pack.error ?? providers.error ?? prompts.error ?? evidence.error, "Editorial workspace or captured evidence could not be loaded")}</main>
  if (pack.isPending || providers.isPending || prompts.isPending || evidence.isPending) return <main role="status" className="p-6">Loading editorial workspace and captured evidence…</main>
  if (!pack.data || !revision) return <main className="p-6"><h1 className="text-2xl font-semibold">Content pack</h1><p className="text-muted-foreground">Generation is pending. No revision is ready yet.</p></main>
  return <main className="min-w-0 space-y-4 p-4 md:p-6"><header><h1 className="text-2xl font-semibold">Telegram editorial studio</h1><p className="text-sm text-muted-foreground">Pack {pack.data.id} · {pack.data.status}</p></header><div className="grid min-w-0 gap-4 min-[900px]:grid-cols-2"><div className="min-w-0 space-y-4"><EvidencePanel evidence={evidence.data ?? []} activeCitation={activeCitation} />{revision.evidenceMap.length ? <section aria-label="Exact evidence map" className="space-y-2"><h2 className="font-semibold">Exact content/evidence map</h2>{revision.evidenceMap.map((citation, index) => <button key={`${citation.evidenceSnapshotId}-${index}`} type="button" className="block w-full rounded border p-2 text-left" onClick={() => setActiveCitation(citation)}><strong>{citation.evidenceKey}</strong><span className="block text-xs">Snapshot {citation.evidenceSnapshotId} · {citation.locator}</span><span className="block break-all text-xs">Excerpt hash {citation.excerptSha256}</span>{citation.sourceUrl ? <span className="block break-all text-xs">{citation.sourceUrl}</span> : <span className="block text-xs">Operator-provided text</span>}</button>)}</section> : <p>No evidence citations are stored for this revision.</p>}<RevisionTimeline revisions={revisions} activeRevisionId={revision.id} onSelect={(item) => { if (!allowDiscard()) return; setSelectedRevisionId(item.id); setActiveCitation(null) }} /></div><div className="min-w-0 space-y-4"><VariantEditor revision={revision} availableProviders={providers.data} availablePromptVersions={prompts.data} onSave={save.mutateAsync} onApprove={approve.mutateAsync} onReject={reject.mutateAsync} onRegenerate={regenerate.mutateAsync} onReload={() => reloadLatestRevision(revision.variantId)} onDirtyChange={setEditorDirty} />{revision.approvalState === "approved" ? <a href={`/review/${revision.id}`} className="inline-flex text-primary underline">Preview, schedule, or publish approved revision</a> : <p className="text-sm text-muted-foreground">Publishing handoff is available only after approving this exact revision.</p>}</div></div></main>
}
