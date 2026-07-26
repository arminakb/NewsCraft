"use client"

import { useEffect, useMemo, useRef, useState } from "react"

import { Button } from "@/components/ui/button"
import { useDirtyNavigation } from "@/components/editorial/use-dirty-navigation"
import { ApiError, getApiErrorMessage } from "@/lib/http"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"
import type {
  CitationRef,
  ManualPlatformEditRequest,
  PlatformRevision,
} from "@/features/packages/types"

type RevisionFor<P extends PlatformRevision["platform"]> = Extract<PlatformRevision, { platform: P }>
type PayloadFor<P extends PlatformRevision["platform"]> = RevisionFor<P>["payload"]
type EditablePayload = PlatformRevision["payload"]
type ManualRevision = Exclude<PlatformRevision, RevisionFor<"telegram">>

export type TelegramEditRequest = {
  variantId: string
  baseRevisionId: string
  baseContentHash: string
  content: Pick<PayloadFor<"telegram">, "body" | "parseMode" | "buttons">
  mediaAssetIds: string[]
  editNote: string
}

export type PlatformEditorProps = {
  revision: PlatformRevision
  onSave?: (input: ManualPlatformEditRequest) => Promise<PlatformRevision | void> | PlatformRevision | void
  onTelegramSave?: (input: TelegramEditRequest) => Promise<PlatformRevision | void> | PlatformRevision | void
  onReload?: () => Promise<void> | void
  onDirtyChange?: (dirty: boolean) => void
  externalPending?: boolean
}

function clonePayload<T extends EditablePayload>(payload: T): T {
  return structuredClone(payload)
}

function citationIdentity(citation: CitationRef): string {
  return JSON.stringify([
    citation.evidenceKey,
    citation.evidenceSnapshotId,
    citation.sourceUrl,
    citation.locator,
    citation.excerptSha256,
  ])
}

function embeddedCitations(platform: ManualRevision["platform"], payload: EditablePayload): CitationRef[] {
  let citations: CitationRef[]
  switch (platform) {
    case "instagram":
      citations = (payload as PayloadFor<"instagram">).citations
      break
    case "x":
      citations = (payload as PayloadFor<"x">).posts.flatMap((post) => post.citations)
      break
    case "blog":
      citations = (payload as PayloadFor<"blog">).citations
      break
  }
  const seen = new Set<string>()
  return citations.filter((citation) => {
    const identity = citationIdentity(citation)
    if (seen.has(identity)) return false
    seen.add(identity)
    return true
  })
}

function buildManualRequest(
  revision: ManualRevision,
  payload: EditablePayload,
  editNote: string,
): ManualPlatformEditRequest {
  const base = {
    baseRevisionId: revision.id,
    baseContentHash: revision.contentHash,
    evidenceMap: embeddedCitations(revision.platform, payload),
    editNote,
  }
  switch (revision.platform) {
    case "instagram":
      return { ...base, payload: { platform: "instagram", content: payload as PayloadFor<"instagram"> } }
    case "x":
      return { ...base, payload: { platform: "x", content: payload as PayloadFor<"x"> } }
    case "blog":
      return { ...base, payload: { platform: "blog", content: payload as PayloadFor<"blog"> } }
  }
}

function localErrors(platform: PlatformRevision["platform"], payload: EditablePayload, editNote: string) {
  const errors: string[] = []
  if (!editNote.trim()) errors.push("Edit note is required")
  switch (platform) {
    case "telegram":
      if (!(payload as PayloadFor<"telegram">).body.trim()) errors.push("Telegram message is required")
      break
    case "instagram": {
      const value = payload as PayloadFor<"instagram">
      if (!value.hook.trim()) errors.push("Hook is required")
      if (!value.caption.trim()) errors.push("Caption is required")
      if (!value.cta.trim()) errors.push("Call to action is required")
      if (!value.altText.trim()) errors.push("Alt text is required")
      break
    }
    case "x":
      if ((payload as PayloadFor<"x">).posts.some((post) => !post.text.trim())) {
        errors.push("Every X post requires text")
      }
      break
    case "blog": {
      const value = payload as PayloadFor<"blog">
      if (!value.title.trim()) errors.push("Blog title is required")
      if (!value.bodyMarkdown.trim()) errors.push("Blog body is required")
      if (!value.seoDescription.trim()) errors.push("SEO description is required")
      break
    }
  }
  return errors
}

export function PlatformEditor({
  revision,
  onSave,
  onTelegramSave,
  onReload,
  onDirtyChange,
  externalPending = false,
}: PlatformEditorProps) {
  const [draft, setDraft] = useState<EditablePayload>(() => clonePayload(revision.payload))
  const [baseline, setBaseline] = useState<EditablePayload>(() => clonePayload(revision.payload))
  const [editNote, setEditNote] = useState("Operator edit")
  const [pending, setPending] = useState(false)
  const [awaitingBaseRevisionId, setAwaitingBaseRevisionId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const preserveOnNextRevision = useRef(false)
  const draftPlatform = useRef(revision.platform)
  const draftRevisionId = useRef(revision.id)
  const currentRevisionId = useRef(revision.id)
  currentRevisionId.current = revision.id

  useEffect(() => {
    const next = clonePayload(revision.payload)
    const mayPreserve = preserveOnNextRevision.current && draftPlatform.current === revision.platform
    setBaseline(next)
    if (!mayPreserve) setDraft(next)
    preserveOnNextRevision.current = false
    draftPlatform.current = revision.platform
    draftRevisionId.current = revision.id
    setAwaitingBaseRevisionId(null)
    setOutcome(null)
  }, [revision.id])

  const draftMatchesPlatform = draftPlatform.current === revision.platform
  const draftMatchesRevision = draftMatchesPlatform && draftRevisionId.current === revision.id
  const preservingAcrossRevision = draftMatchesPlatform && preserveOnNextRevision.current
  const activeDraft = draftMatchesRevision || preservingAcrossRevision ? draft : revision.payload
  const activeBaseline = draftMatchesRevision ? baseline : revision.payload
  const dirty = useMemo(() => JSON.stringify(activeDraft) !== JSON.stringify(activeBaseline), [activeDraft, activeBaseline])
  const errors = useMemo(() => localErrors(revision.platform, activeDraft, editNote), [revision.platform, activeDraft, editNote])
  const awaitingNextRevision = awaitingBaseRevisionId === revision.id
  const busy = pending || awaitingNextRevision || externalPending
  const approvalFenced = dirty || awaitingNextRevision || externalPending
  useDirtyNavigation(approvalFenced)
  useEffect(() => onDirtyChange?.(approvalFenced), [approvalFenced, onDirtyChange])

  function updateDraft(value: EditablePayload) {
    draftPlatform.current = revision.platform
    draftRevisionId.current = revision.id
    setDraft(value)
  }

  async function save() {
    if (!dirty || errors.length > 0 || busy) return
    const savedBaseRevisionId = revision.id
    const callback = revision.platform === "telegram" ? onTelegramSave : onSave
    if (!callback) return
    setPending(true)
    setError(null)
    setOutcome(null)
    try {
      if (revision.platform === "telegram") {
        const content = activeDraft as PayloadFor<"telegram">
        await onTelegramSave!({
          variantId: revision.variantId,
          baseRevisionId: revision.id,
          baseContentHash: revision.contentHash,
          content: { body: content.body, parseMode: content.parseMode, buttons: content.buttons },
          mediaAssetIds: [...content.mediaAssetIds],
          editNote: editNote.trim(),
        })
      } else {
        await onSave!(buildManualRequest(revision, activeDraft, editNote.trim()))
      }
      setAwaitingBaseRevisionId(currentRevisionId.current === savedBaseRevisionId ? savedBaseRevisionId : null)
      setOutcome("New pending review revision created")
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status === 409
          ? "A newer revision exists. Reload the latest revision before saving."
          : getApiErrorMessage(caught, "The revision could not be saved"),
      )
    } finally {
      setPending(false)
    }
  }

  async function reloadLatest() {
    preserveOnNextRevision.current = true
    setPending(true)
    try {
      await onReload?.()
    } catch (caught) {
      preserveOnNextRevision.current = false
      setError(getApiErrorMessage(caught, "The latest revision could not be loaded"))
    } finally {
      setPending(false)
    }
  }

  return (
    <section aria-labelledby="platform-editor-heading" className="min-w-0 space-y-4">
      <div>
        <h2 id="platform-editor-heading" className="text-lg font-semibold">Platform editor</h2>
      </div>

      <details className="rounded-lg border p-3" open={revision.validation.some((issue) => issue.severity === "error")}>
        <summary className="cursor-pointer font-medium">
          Advanced revision identity{revision.validation.some((issue) => issue.severity === "error") ? " — validation blocker" : ""}
        </summary>
        <p className="mt-2 break-all text-xs text-muted-foreground">
          Loaded {revision.platform} revision {revision.id} · hash {revision.contentHash}
        </p>
      </details>

      <fieldset disabled={busy} className="contents">
        <legend className="sr-only">Editable {revision.platform} revision fields</legend>
        {revision.platform === "telegram" ? (
          <TelegramFields
            value={activeDraft as PayloadFor<"telegram">}
            onChange={(value) => updateDraft(value)}
          />
        ) : null}
        {revision.platform === "instagram" ? (
          <InstagramFields
            value={activeDraft as PayloadFor<"instagram">}
            onChange={(value) => updateDraft(value)}
          />
        ) : null}
        {revision.platform === "x" ? (
          <XFields value={activeDraft as PayloadFor<"x">} onChange={(value) => updateDraft(value)} />
        ) : null}
        {revision.platform === "blog" ? (
          <BlogFields value={activeDraft as PayloadFor<"blog">} onChange={(value) => updateDraft(value)} />
        ) : null}

        <label className="grid gap-1">
          <span>Edit note</span>
          <DirectionBoundary
            as="input"
            language={null}
            aria-label="Edit note"
            className="rounded-lg border p-2"
            maxLength={500}
            value={editNote}
            onChange={(event) => setEditNote(event.target.value)}
          />
        </label>
      </fieldset>

      {dirty ? <div role="status" className="text-sm text-amber-800">Saving creates a new pending review revision.</div> : null}
      {errors.map((message) => <div key={message} role="alert" className="text-sm text-red-700">{message}</div>)}
      {revision.validation.map((issue) => (
        <div key={`${issue.code}:${issue.path}:${issue.message}`} role="alert" className="text-sm text-red-700">
          {issue.message}
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          disabled={!dirty || errors.length > 0 || busy || (revision.platform === "telegram" ? !onTelegramSave : !onSave)}
          onClick={() => void save()}
        >
          Save new revision
        </Button>
        {error?.startsWith("A newer revision") && onReload ? (
          <Button type="button" variant="outline" disabled={busy} onClick={() => void reloadLatest()}>
            Reload latest
          </Button>
        ) : null}
      </div>
      {error ? <div role="alert" className="text-sm text-red-700">{error}</div> : null}
      {outcome ? <div role="status" className="text-sm text-green-700">{outcome}</div> : null}
    </section>
  )
}

function TelegramFields({ value, onChange }: { value: PayloadFor<"telegram">; onChange: (value: PayloadFor<"telegram">) => void }) {
  return (
    <label className="grid gap-1">
      <span>Telegram message</span>
      <DirectionBoundary
        as="textarea"
        aria-label="Telegram message"
        className="min-h-56 rounded-lg border p-3"
        direction={value.direction}
        value={value.body}
        onChange={(event) => onChange({ ...value, body: event.target.value })}
      />
      <span className="text-xs text-muted-foreground">{value.body.length} characters</span>
    </label>
  )
}

function InstagramFields({ value, onChange }: { value: PayloadFor<"instagram">; onChange: (value: PayloadFor<"instagram">) => void }) {
  return (
    <div className="grid gap-3">
      <CountedField label="Hook" value={value.hook} limit={180} onChange={(hook) => onChange({ ...value, hook })} />
      <CountedField label="Caption" value={value.caption} limit={2200} multiline onChange={(caption) => onChange({ ...value, caption })} />
      <CountedField label="Call to action" value={value.cta} limit={300} onChange={(cta) => onChange({ ...value, cta })} />
      <label className="grid gap-1">
        <span>Hashtags</span>
        <DirectionBoundary
          as="input"
          language={null}
          aria-label="Hashtags"
          className="rounded-lg border p-2"
          value={value.hashtags.join(", ")}
          onChange={(event) => onChange({ ...value, hashtags: commaList(event.target.value) })}
        />
      </label>
      <CountedField label="Alt text" value={value.altText} limit={1000} multiline onChange={(altText) => onChange({ ...value, altText })} />
      {value.carousel.map((slide, index) => (
        <fieldset key={`${slide.order}:${index}`} className="grid gap-2 rounded-lg border p-3">
          <legend>Slide {slide.order}</legend>
          <CountedField label={`Slide ${slide.order} headline`} value={slide.headline} limit={120} onChange={(headline) => onChange({ ...value, carousel: value.carousel.map((item, itemIndex) => itemIndex === index ? { ...item, headline } : item) })} />
          <CountedField label={`Slide ${slide.order} body`} value={slide.body} limit={500} multiline onChange={(body) => onChange({ ...value, carousel: value.carousel.map((item, itemIndex) => itemIndex === index ? { ...item, body } : item) })} />
        </fieldset>
      ))}
    </div>
  )
}

function XFields({ value, onChange }: { value: PayloadFor<"x">; onChange: (value: PayloadFor<"x">) => void }) {
  return (
    <div className="grid gap-3">
      {value.posts.map((post, index) => (
        <CountedField
          key={`${post.order}:${index}`}
          label={`Post ${post.order}`}
          value={post.text}
          limit={280}
          multiline
          onChange={(text) => onChange({
            ...value,
            posts: value.posts.map((item, itemIndex) => itemIndex === index ? { ...item, text } : item),
          })}
        />
      ))}
    </div>
  )
}

function BlogFields({ value, onChange }: { value: PayloadFor<"blog">; onChange: (value: PayloadFor<"blog">) => void }) {
  return (
    <div className="grid gap-3">
      <CountedField label="Blog title" value={value.title} limit={120} onChange={(title) => onChange({ ...value, title })} />
      <CountedField label="Slug" value={value.slug} limit={120} onChange={(slug) => onChange({ ...value, slug })} />
      <CountedField label="Excerpt" value={value.excerpt} limit={300} multiline onChange={(excerpt) => onChange({ ...value, excerpt })} />
      <CountedField label="Blog body" value={value.bodyMarkdown} multiline onChange={(bodyMarkdown) => onChange({ ...value, bodyMarkdown })} />
      <label className="grid gap-1">
        <span>Headings</span>
        <DirectionBoundary as="textarea" language={null} aria-label="Headings" className="rounded-lg border p-2" value={value.headings.join("\n")} onChange={(event) => onChange({ ...value, headings: lineList(event.target.value) })} />
      </label>
      <label className="grid gap-1">
        <span>Tags</span>
        <DirectionBoundary as="input" language={null} aria-label="Tags" className="rounded-lg border p-2" value={value.tags.join(", ")} onChange={(event) => onChange({ ...value, tags: commaList(event.target.value) })} />
      </label>
      <CountedField label="SEO description" value={value.seoDescription} limit={160} multiline onChange={(seoDescription) => onChange({ ...value, seoDescription })} />
      <label className="grid gap-1">
        <span>Canonical sources</span>
        <textarea aria-label="Canonical sources" className="rounded-lg border p-2" value={value.canonicalSources.join("\n")} onChange={(event) => onChange({ ...value, canonicalSources: lineList(event.target.value) })} />
      </label>
    </div>
  )
}

function CountedField({ label, value, limit, multiline = false, onChange }: { label: string; value: string; limit?: number; multiline?: boolean; onChange: (value: string) => void }) {
  const control = multiline ? (
    <DirectionBoundary as="textarea" language={null} aria-label={label} className="min-h-28 rounded-lg border p-2" value={value} onChange={(event) => onChange(event.target.value)} />
  ) : (
    <DirectionBoundary as="input" language={null} aria-label={label} className="rounded-lg border p-2" value={value} onChange={(event) => onChange(event.target.value)} />
  )
  return (
    <label className="grid gap-1">
      <span>{label}</span>
      {control}
      <span className="text-xs text-muted-foreground">{value.length}{limit ? `/${limit}` : ""} characters</span>
    </label>
  )
}

function commaList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean)
}

function lineList(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}
