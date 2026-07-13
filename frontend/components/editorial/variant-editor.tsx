"use client"

import { useEffect, useMemo, useState } from "react"
import { Button } from "@/components/ui/button"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import type { AIProviderOption, JobAccepted, PromptVersionOption, VariantRevision } from "@/lib/editorial-types"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

type ApproveInput = { revisionId: string; expectedContentHash: string; note: string | null }
type SaveInput = { variantId: string; baseRevisionId: string; baseContentHash: string; content: { body: string; parseMode: "HTML"; buttons: VariantRevision["content"]["buttons"] }; mediaAssetIds: string[]; editNote: string }
type EditableState = SaveInput["content"] & { mediaAssetIds: string[] }
const editableFrom = (revision: VariantRevision): EditableState => ({ body: revision.content.body, parseMode: revision.content.parseMode, buttons: revision.content.buttons.map((item) => ({ ...item })), mediaAssetIds: [...revision.content.mediaAssetIds] })

export function VariantEditor({ revision, availableProviders = [], availablePromptVersions = [], onSave, onApprove, onReject, onRegenerate, onReload, onDirtyChange, externalPending = false }: { revision: VariantRevision; availableProviders?: AIProviderOption[]; availablePromptVersions?: PromptVersionOption[]; onSave?: (input: SaveInput) => Promise<VariantRevision>; onApprove?: (input: ApproveInput) => Promise<VariantRevision>; onReject?: (input: { revisionId: string; expectedContentHash: string; reason: string }) => Promise<VariantRevision>; onRegenerate?: (input: { variantId: string; providerProfileId: string; platformPromptTemplateVersionId: string; instruction: string | null }) => Promise<JobAccepted>; onReload?: () => Promise<void> | void; onDirtyChange?: (dirty: boolean) => void; externalPending?: boolean }) {
  const [form, setForm] = useState<EditableState>(() => editableFrom(revision))
  const [baseline, setBaseline] = useState<EditableState>(() => editableFrom(revision))
  const [stashed, setStashed] = useState<EditableState | null>(null)
  const [editNote, setEditNote] = useState("Operator edit")
  const [rejectionReason, setRejectionReason] = useState("")
  const [providerId, setProviderId] = useState("")
  const [promptId, setPromptId] = useState("")
  const [instruction, setInstruction] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const busy = pending || externalPending
  useEffect(() => { const next = editableFrom(revision); setForm(next); setBaseline(next); setOutcome(null) }, [revision.id])
  const dirty = JSON.stringify(form) !== JSON.stringify(baseline)
  useDirtyNavigation(dirty || externalPending, externalPending ? "A revision update is still saving. Leave this page?" : "Discard unsaved revision edits?")
  useEffect(() => { onDirtyChange?.(dirty) }, [dirty, onDirtyChange])
  const formErrors = [...(!form.body.trim() ? ["Telegram message is required"] : []), ...form.buttons.flatMap((item, index) => !item.text.trim() || !/^https?:\/\//.test(item.url) ? [`Button ${index + 1} requires text and an HTTP(S) URL`] : []), ...(form.mediaAssetIds.some((id) => !id.trim()) ? ["Media assignments cannot be empty"] : []), ...(!editNote.trim() ? ["Edit note is required"] : [])]
  const valid = formErrors.length === 0
  const generationProviders = availableProviders.filter((item) => item.capabilities.generation)
  const prompts = availablePromptVersions.filter((item) => item.active && item.purpose === "telegram_pack")
  const run = async (operation: () => Promise<unknown>, success: string) => { setPending(true); setError(null); try { await operation(); setOutcome(success); return true } catch (caught) { setError(caught instanceof ApiError && caught.status === 409 ? "A newer revision exists. Reload before saving." : getApiErrorMessage(caught)); return false } finally { setPending(false) } }
  const reloadLatest = async () => {
    setStashed({ body: form.body, parseMode: form.parseMode, buttons: form.buttons.map((item) => ({ ...item })), mediaAssetIds: [...form.mediaAssetIds] })
    setPending(true)
    try { await onReload?.() }
    catch (caught) { setError(getApiErrorMessage(caught, "Latest revision could not be loaded")) }
    finally { setPending(false) }
  }
  const validationErrors = useMemo(() => revision.validationResults.filter((item) => !item.ok), [revision.validationResults])
  return <section aria-labelledby="variant-editor-heading" className="min-w-0 space-y-4"><h2 id="variant-editor-heading" className="text-lg font-semibold">Exact revision editor</h2><p className="break-all text-xs text-muted-foreground">Loaded revision {revision.id} · hash {revision.contentHash}</p>
    <label className="grid gap-1"><span>Telegram message</span><DirectionBoundary as="textarea" aria-label="Telegram message" disabled={busy} direction={revision.content.direction} className="min-h-64 rounded-lg border p-3" value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} /></label>
    <label className="grid gap-1"><span>Parse mode</span><select aria-label="Parse mode" disabled={busy} className="rounded-lg border p-2" value={form.parseMode} onChange={() => setForm({ ...form, parseMode: "HTML" })}><option value="HTML">HTML</option></select></label>
    <fieldset disabled={busy} className="space-y-2 rounded-lg border p-3"><legend>Telegram buttons</legend>{form.buttons.map((button, index) => <div key={index} className="grid gap-2 sm:grid-cols-[1fr_2fr_auto]"><DirectionBoundary as="input" language={null} aria-label={`Button ${index + 1} text`} className="rounded border p-2" value={button.text} onChange={(event) => setForm({ ...form, buttons: form.buttons.map((item, itemIndex) => itemIndex === index ? { ...item, text: event.target.value } : item) })} /><input aria-label={`Button ${index + 1} URL`} className="rounded border p-2" value={button.url} onChange={(event) => setForm({ ...form, buttons: form.buttons.map((item, itemIndex) => itemIndex === index ? { ...item, url: event.target.value } : item) })} /><Button type="button" variant="outline" onClick={() => setForm({ ...form, buttons: form.buttons.filter((_, itemIndex) => itemIndex !== index) })}>Remove button {index + 1}</Button></div>)}<Button type="button" variant="outline" disabled={form.buttons.length >= 8} onClick={() => setForm({ ...form, buttons: [...form.buttons, { text: "", url: "" }] })}>Add button</Button></fieldset>
    <label className="grid gap-1"><span>Media asset assignments</span><input aria-label="Media asset assignments" disabled={busy} className="rounded-lg border p-2" value={form.mediaAssetIds.join(", ")} onChange={(event) => setForm({ ...form, mediaAssetIds: event.target.value.split(",").map((item) => item.trim()).filter(Boolean) })} /></label>
    <div className="grid gap-2 text-sm sm:grid-cols-2"><div>Parse mode: {revision.content.parseMode}</div><div>Media policy: {revision.content.mediaPolicy}</div><div>Direction: {revision.content.direction}</div><div>Dry run: {revision.content.dryRun ? "yes" : "no"}</div><div>Source provenance: {revision.content.sourceUrl ?? "Operator-provided text"}</div><div>Evidence citations: {revision.evidenceMap.length}</div></div>
    {dirty ? <div role="status" className="text-amber-800">Changes will create a pending review revision</div> : null}
    <label className="grid gap-1"><span>Edit note</span><DirectionBoundary as="input" language={null} disabled={busy} className="rounded-lg border p-2" value={editNote} onChange={(event) => setEditNote(event.target.value)} /></label>
    {formErrors.map((message) => <div key={message} role="alert" className="text-sm text-red-700">{message}</div>)}{validationErrors.map((result) => <div key={result.gate} role="alert" className="text-sm text-red-700">{result.gate}: {result.reason ?? "failed"}</div>)}
    <div className="flex flex-wrap gap-2"><Button disabled={!dirty || !valid || busy || !onSave} onClick={() => void (async () => { if (await run(() => onSave!({ variantId: revision.variantId, baseRevisionId: revision.id, baseContentHash: revision.contentHash, content: { body: form.body, parseMode: form.parseMode, buttons: form.buttons }, mediaAssetIds: form.mediaAssetIds, editNote: editNote.trim() }), "New pending review revision created")) setBaseline(form) })()}>Save new revision</Button><Button disabled={dirty || !valid || busy || validationErrors.length > 0 || revision.approvalState !== "pending_review" || !onApprove} onClick={() => void run(() => onApprove!({ revisionId: revision.id, expectedContentHash: revision.contentHash, note: null }), "Revision approved")}>Approve revision</Button></div>
    <label className="grid gap-1"><span>Rejection reason</span><DirectionBoundary as="textarea" language={null} disabled={busy} className="rounded-lg border p-2" value={rejectionReason} onChange={(event) => setRejectionReason(event.target.value)} /></label><Button variant="outline" disabled={dirty || busy || !rejectionReason.trim() || revision.approvalState !== "pending_review" || !onReject} onClick={() => void run(() => onReject!({ revisionId: revision.id, expectedContentHash: revision.contentHash, reason: rejectionReason.trim() }), "Revision rejected")}>Reject revision</Button>
    {generationProviders.length && prompts.length ? <fieldset disabled={busy} className="grid gap-3 rounded-lg border p-3"><legend>Regenerate from exact evidence</legend><label>AI provider<select aria-label="AI provider" className="ms-2 rounded border p-2" value={providerId} onChange={(event) => setProviderId(event.target.value)}><option value="">Select provider</option>{generationProviders.map((provider) => <option key={provider.id} value={provider.id} disabled={Boolean(provider.unavailableReason)}>{provider.name} · {provider.providerType} · {provider.defaultModel ?? "default"}{provider.unavailableReason ? ` unavailable: ${provider.unavailableReason}` : ""}</option>)}</select></label><label>Telegram pack prompt<select aria-label="Telegram pack prompt" className="ms-2 rounded border p-2" value={promptId} onChange={(event) => setPromptId(event.target.value)}><option value="">Select prompt</option>{prompts.map((prompt) => <option key={prompt.id} value={prompt.id}>Version {prompt.version}</option>)}</select></label><label className="grid gap-1">Regeneration instruction<DirectionBoundary as="textarea" language={null} className="rounded border p-2" value={instruction} onChange={(event) => setInstruction(event.target.value)} /></label><Button disabled={!providerId || !promptId || busy || !onRegenerate} onClick={() => void run(() => onRegenerate!({ variantId: revision.variantId, providerProfileId: providerId, platformPromptTemplateVersionId: promptId, instruction: instruction.trim() || null }), "Regeneration queued")}>Regenerate</Button></fieldset> : null}
    {error ? <div role="alert" className="space-y-2 text-red-700"><p>{error}</p>{error.startsWith("A newer") ? <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void reloadLatest()}>Reload latest</Button><span>Your unsaved edits stay available to reapply.</span></div> : null}</div> : null}{stashed && JSON.stringify(form) !== JSON.stringify(stashed) ? <Button variant="outline" disabled={externalPending} onClick={() => { setForm(stashed); setStashed(null); setError(null) }}>Reapply my edits</Button> : null}{outcome ? <div role="status" className="text-green-700">{outcome}</div> : null}
  </section>
}
