"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useEffect, useRef, useState, type RefObject } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { getLibraryResearchRun, type LibraryResearchRun } from "@/features/library/api"
import { bulkSetStoryEditorialState, getAIProviderOptions, getBrandOptions, getPromptVersionOptions, getResearchRuns, getStories, getStory, groupPendingStories, requestContentPack, setStoryEditorialState } from "@/lib/editorial-api"
import type { EditorialState, EvidenceDetail, JobAccepted, StoryFilters, StorySummary } from "@/lib/editorial-types"
import { getApiErrorMessage } from "@/lib/http"
import { editorialQueryKeys } from "@/lib/query-keys"
import { ManualIntakeDialog } from "./manual-intake-dialog"
import { ResearchPanel } from "./research-panel"
import { useEditorialModal } from "./use-editorial-modal"
import { DirectionBoundary } from "@/components/newsroom/direction-boundary"

const MAX_SELECTION = 200
type InboxDeepLink = { storyId: string; evidenceId: string | null; researchRunId: string | null }
export function StoryInbox({ initialStories }: { initialStories?: StorySummary[] }) {
  const client = useQueryClient()
  const [search, setSearch] = useState("")
  const [editorialState, setEditorialState] = useState<EditorialState | "">("inbox")
  const [completeness, setCompleteness] = useState<"" | "complete" | "incomplete">("")
  const [nextCursor, setNextCursor] = useState<string | null | undefined>()
  const [stories, setStories] = useState<StorySummary[]>(initialStories ?? [])
  const [selected, setSelected] = useState<string[]>([])
  const [openStory, setOpenStory] = useState<string | null>(null)
  const [researchStory, setResearchStory] = useState<string | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [job, setJob] = useState<JobAccepted | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [boundResearch, setBoundResearch] = useState<{ storyId: string; runId: string } | null>(null)
  const [deepLink, setDeepLink] = useState<InboxDeepLink | null>(null)
  const pageRequestTokenRef = useRef(0)
  const nextCursorRef = useRef<string | null | undefined>(undefined)
  const mountedRef = useRef(true)
  const filters: StoryFilters = { search: search || undefined, editorialState: editorialState || undefined, completeness: completeness || undefined, limit: 200 }
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const storyId = params.get("story_id")
    if (!storyId) return
    setDeepLink({
      storyId,
      evidenceId: params.get("evidence_id"),
      researchRunId: params.get("research_run_id"),
    })
    setOpenStory(storyId)
  }, [])
  const query = useQuery({ queryKey: editorialQueryKeys.stories(filters), queryFn: () => getStories(filters), initialData: initialStories && !search && editorialState === "inbox" && !completeness ? { items: initialStories, nextCursor: null } : undefined })
  const linkedStory = useQuery({
    queryKey: deepLink ? editorialQueryKeys.story(deepLink.storyId) : ["stories", "deep-link", "none"],
    queryFn: () => getStory(deepLink!.storyId),
    enabled: Boolean(deepLink?.storyId),
  })
  const linkedResearch = useQuery({
    queryKey: deepLink?.researchRunId ? ["library", "research", deepLink.researchRunId] : ["library", "research", "none"],
    queryFn: () => getLibraryResearchRun(deepLink!.researchRunId!),
    enabled: Boolean(deepLink?.researchRunId),
  })
  const visible = stories

  useEffect(() => {
    if (!query.data && !linkedStory.data) return
    const page = query.data?.items ?? []
    setStories(deduplicateStories(linkedStory.data ? [linkedStory.data, ...page] : page))
    if (query.data) {
      setNextCursor(query.data.nextCursor)
      nextCursorRef.current = query.data.nextCursor
    }
  }, [linkedStory.data, query.data])
  useEffect(() => {
    const run = linkedResearch.data
    if (!deepLink?.researchRunId || !run) return
    setBoundResearch(
      run.storyId === deepLink.storyId && run.status === "succeeded"
        ? { storyId: run.storyId, runId: run.id }
        : null,
    )
  }, [deepLink, linkedResearch.data])
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      pageRequestTokenRef.current += 1
    }
  }, [])

  const invalidate = async (id?: string) => { await client.invalidateQueries({ queryKey: ["stories"] }); if (id) await client.invalidateQueries({ queryKey: editorialQueryKeys.story(id) }) }
  const bulk = useMutation({ mutationFn: (state: "shortlisted" | "rejected") => bulkSetStoryEditorialState(selected, state), onSuccess: async (_result, state) => { const changed = [...selected]; if (editorialState && editorialState !== state) setStories((current) => current.filter((story) => !changed.includes(story.id))); setSelected([]); setActionError(null); await invalidate(); await Promise.all(changed.map((id) => client.invalidateQueries({ queryKey: editorialQueryKeys.story(id) }))) }, onError: (error) => setActionError(getApiErrorMessage(error)) })
  const grouping = useMutation({ mutationFn: () => groupPendingStories({ limit: 500 }), onSuccess: setJob, onError: (error) => setActionError(getApiErrorMessage(error)) })

  function changeFilters(action: () => void) {
    pageRequestTokenRef.current += 1
    nextCursorRef.current = undefined
    setNextCursor(undefined)
    setLoadingMore(false)
    setStories([])
    setSelected([])
    action()
  }
  async function loadMore() {
    const cursor = nextCursor === undefined ? query.data?.nextCursor : nextCursor
    if (!cursor) return
    const token = ++pageRequestTokenRef.current
    nextCursorRef.current = cursor
    setLoadingMore(true)
    setActionError(null)
    try {
      const next = await getStories({ ...filters, cursor })
      if (!mountedRef.current || token !== pageRequestTokenRef.current || nextCursorRef.current !== cursor) return
      setStories((current) => deduplicateStories([...current, ...next.items]))
      setNextCursor(next.nextCursor)
      nextCursorRef.current = next.nextCursor
    } catch (error) {
      if (!mountedRef.current || token !== pageRequestTokenRef.current) return
      setActionError(getApiErrorMessage(error, "More stories could not be loaded"))
    } finally {
      if (mountedRef.current && token === pageRequestTokenRef.current) setLoadingMore(false)
    }
  }

  return <section className="min-w-0 space-y-5 p-4 md:p-6" aria-labelledby="inbox-heading">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 id="inbox-heading" className="text-2xl font-semibold">Editorial Inbox</h1><p className="text-muted-foreground">Grouped stories with immutable evidence and truthful research status.</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" onClick={() => grouping.mutate()} disabled={grouping.isPending}>Group pending content</Button><Button onClick={() => setManualOpen(true)}>Add story</Button></div></header>
    {job ? <div role="status" className="rounded-lg border bg-muted/40 p-3">Intake queued · Job accepted · {job.status} · job {job.jobId}</div> : null}
    <div className="grid gap-3 md:grid-cols-3"><label className="grid gap-1"><span>Search stories</span><input className="min-h-10 rounded-lg border px-3" value={search} onChange={(event) => changeFilters(() => setSearch(event.target.value))} /></label><label className="grid gap-1"><span>Editorial state</span><select className="min-h-10 rounded-lg border px-3" value={editorialState} onChange={(event) => changeFilters(() => setEditorialState(event.target.value as EditorialState | ""))}><option value="">All states</option><option value="inbox">Inbox</option><option value="shortlisted">Shortlisted</option><option value="rejected">Rejected</option><option value="drafted">Drafted</option></select></label><label className="grid gap-1"><span>Completeness</span><select className="min-h-10 rounded-lg border px-3" value={completeness} onChange={(event) => changeFilters(() => setCompleteness(event.target.value as typeof completeness))}><option value="">All coverage</option><option value="complete">Complete</option><option value="incomplete">Incomplete</option></select></label></div>
    {visible.length ? <div className="flex flex-wrap items-center gap-2"><Button variant="ghost" onClick={() => setSelected(visible.slice(0, MAX_SELECTION).map((story) => story.id))}>Select up to 200 visible</Button>{visible.length > MAX_SELECTION ? <span className="text-xs text-muted-foreground">Selection is limited to 200 stories per bulk action.</span> : null}</div> : null}
    {selected.length ? <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3"><strong>{selected.length} stories selected</strong><Button onClick={() => bulk.mutate("shortlisted")} disabled={bulk.isPending}>Shortlist selected</Button><Button variant="destructive" onClick={() => bulk.mutate("rejected")} disabled={bulk.isPending}>Reject selected</Button><Button variant="ghost" onClick={() => setSelected([])}>Clear</Button></div> : null}
    {actionError ? <div role="alert" dir="auto" className="text-red-700">{actionError}</div> : null}
    {deepLink && linkedStory.isPending ? <div role="status">Loading linked story…</div> : null}
    {deepLink && linkedStory.isError ? <div role="alert" className="text-red-700">{getApiErrorMessage(linkedStory.error, "Linked story could not be loaded")}</div> : null}
    {deepLink?.researchRunId && linkedResearch.isPending ? <div role="status">Loading linked research run…</div> : null}
    {deepLink?.researchRunId && linkedResearch.isError ? <div role="alert" className="text-red-700">{getApiErrorMessage(linkedResearch.error, "Linked research run could not be loaded")}</div> : null}
    {deepLink?.researchRunId && linkedResearch.data ? <LinkedResearchRun run={linkedResearch.data} expectedStoryId={deepLink.storyId} /> : null}
    {boundResearch ? <div role="status">Generation is bound to succeeded research run {boundResearch.runId} for story {boundResearch.storyId}.</div> : null}
    {query.isError && visible.length ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(query.error, "Story list could not be loaded; showing the linked story only")}</div> : null}
    {query.isPending && !visible.length ? <div role="status" aria-label="Loading stories">Loading stories…</div> : query.isError && !visible.length ? <div className="space-y-2"><div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(query.error, "Stories could not be loaded")}</div><Button variant="outline" onClick={() => query.refetch()}>Retry stories</Button></div> : !visible.length ? <Card><CardContent className="p-8 text-center text-muted-foreground">No grouped stories match these filters.</CardContent></Card> : <div className="space-y-3">{visible.map((story) => <StoryRow key={story.id} story={story} focusedEvidenceId={deepLink?.storyId === story.id ? deepLink.evidenceId : null} researchRunId={boundResearch?.storyId === story.id ? boundResearch.runId : null} selected={selected.includes(story.id)} onSelect={(checked) => setSelected((current) => checked ? current.length < MAX_SELECTION ? [...current, story.id] : current : current.filter((id) => id !== story.id))} open={openStory === story.id} onOpen={() => setOpenStory(openStory === story.id ? null : story.id)} onResearch={() => setResearchStory(story.id)} onState={async (state) => { try { await setStoryEditorialState(story.id, state); if (editorialState && editorialState !== state) setStories((current) => current.filter((item) => item.id !== story.id)); setActionError(null); await invalidate(story.id) } catch (error) { setActionError(getApiErrorMessage(error)) } }} />)}</div>}
    {(nextCursor === undefined ? query.data?.nextCursor : nextCursor) ? <Button variant="outline" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "Loading more…" : "Load more stories"}</Button> : null}
    <ManualIntakeDialog open={manualOpen} onClose={(result) => { setManualOpen(false); if (result) { setJob(result); void invalidate() } }} />
    {researchStory ? <ResearchDialog storyId={researchStory} onClose={() => setResearchStory(null)} onCompleted={(runId) => setBoundResearch({ storyId: researchStory, runId })} /> : null}
  </section>
}

function StoryRow({ story, focusedEvidenceId, researchRunId, selected, onSelect, open, onOpen, onResearch, onState }: { story: StorySummary; focusedEvidenceId: string | null; researchRunId: string | null; selected: boolean; onSelect: (value: boolean) => void; open: boolean; onOpen: () => void; onResearch: () => void; onState: (state: "shortlisted" | "rejected") => Promise<void> }) {
  const detail = useQuery({ queryKey: editorialQueryKeys.story(story.id), queryFn: () => getStory(story.id), enabled: open })
  const focusedEvidenceRef = useRef<HTMLElement>(null)
  const hasFocusedEvidence = Boolean(
    focusedEvidenceId && detail.data?.evidence.some((evidence) => evidence.id === focusedEvidenceId),
  )
  useEffect(() => {
    if (open && hasFocusedEvidence) focusedEvidenceRef.current?.focus()
  }, [hasFocusedEvidence, open])

  return <Card size="sm"><CardContent className="space-y-3">
    <div className="grid gap-3 md:grid-cols-[auto_minmax(0,1fr)_auto]">
      <input type="checkbox" aria-label={`Select ${story.title}`} checked={selected} onChange={(event) => onSelect(event.target.checked)} />
      <button type="button" className="min-h-11 min-w-11 text-left min-[900px]:min-h-0 min-[900px]:min-w-0" aria-expanded={open} aria-label={`Open ${story.title}`} onClick={onOpen}>
        <DirectionBoundary as="strong" language={story.primaryLanguage} className="block truncate">{story.title}</DirectionBoundary>
        <span className="block text-muted-foreground"><span>{story.evidenceCount} evidence items</span> · latest {story.latestEvidenceAt ? new Date(story.latestEvidenceAt).toLocaleString() : "not recorded"}</span>
      </button>
      <div className="flex flex-wrap gap-2"><Badge variant={story.completeness.complete ? "secondary" : "outline"}>{story.completeness.complete ? "Coverage complete" : "Coverage incomplete"}</Badge><Badge variant="outline">{story.completeness.score}%</Badge></div>
    </div>
    {story.completeness.reasons.length ? <p className="text-sm text-muted-foreground">{story.completeness.reasons.join(" · ")}</p> : null}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" onClick={() => void onState("shortlisted")}>Shortlist</Button>
      <Button size="sm" variant="destructive" onClick={() => void onState("rejected")}>Reject</Button>
      {!story.completeness.complete ? <Button size="sm" variant="outline" onClick={onResearch}>Research more</Button> : null}
      <Link className="inline-flex min-h-11 min-w-11 items-center px-2 text-primary underline min-[900px]:min-h-7 min-[900px]:min-w-0" href={`/drafts?story_id=${story.id}`}>Open editorial studio</Link>
    </div>
    {open ? <div className="space-y-4 border-t pt-3">
      {detail.isPending ? <div role="status">Loading evidence…</div> : detail.isError ? <div role="alert">{getApiErrorMessage(detail.error)}</div> : <div className="space-y-3">
        {detail.data?.evidence.map((evidence) => <EvidenceArticle
          evidence={evidence}
          focusRef={evidence.id === focusedEvidenceId ? focusedEvidenceRef : undefined}
          focused={evidence.id === focusedEvidenceId}
          key={evidence.id}
        />)}
        {focusedEvidenceId && !hasFocusedEvidence ? <div role="alert">Evidence snapshot {focusedEvidenceId} is not part of this story.</div> : null}
      </div>}
      <GenerationControls storyId={story.id} researchRunId={researchRunId} />
    </div> : null}
  </CardContent></Card>
}

function EvidenceArticle({ evidence, focusRef, focused }: { evidence: EvidenceDetail; focusRef?: RefObject<HTMLElement | null>; focused: boolean }) {
  return <article
    aria-current={focused ? "true" : undefined}
    aria-label={`Evidence snapshot ${evidence.id}`}
    className="rounded-lg border p-3"
    ref={focusRef}
    tabIndex={-1}
  >
    {!evidence.sourceUrl ? <div className="text-sm font-medium">Operator-provided text</div> : null}
    {evidence.title ? <DirectionBoundary language={null} className="font-medium">{evidence.title}</DirectionBoundary> : evidence.sourceUrl ? <div className="font-medium">Untitled source</div> : null}
    {evidence.publishedAt ? <div className="text-xs text-muted-foreground">Published {new Date(evidence.publishedAt).toLocaleString()}</div> : null}
    <div className="text-xs text-muted-foreground">Captured {new Date(evidence.capturedAt).toLocaleString()}</div>
    <div className="text-xs text-muted-foreground">Snapshot {evidence.contentSha256.slice(0, 12)}</div>
    <DirectionBoundary as="p" language={null} className="mt-2 line-clamp-5 whitespace-pre-wrap break-words">{evidence.contentText}</DirectionBoundary>
    {evidence.sourceUrl ? <a className="mt-2 inline-flex text-primary underline" href={evidence.sourceUrl} target="_blank" rel="noreferrer">Open original source</a> : null}
  </article>
}

function LinkedResearchRun({ run, expectedStoryId }: { run: LibraryResearchRun; expectedStoryId: string }) {
  if (run.storyId !== expectedStoryId) {
    return <div role="alert" className="text-red-700">Linked research run does not belong to the requested story.</div>
  }
  return <section aria-label="Linked research run" className="space-y-1 rounded-lg border p-3" role="region">
    <h2 className="font-semibold">Research run {run.id}</h2>
    <p>{run.status.replaceAll("_", " ")} · {run.backend ?? "No backend"} · {run.attemptCount} attempts · {run.sourceCount} sources</p>
    <p className="text-sm text-muted-foreground">Budget {run.budget.maxQueries} queries · {run.budget.maxPages} pages · {run.budget.maxElapsedSeconds} seconds</p>
    {run.resultRevisionId ? <p className="text-sm text-muted-foreground">Story revision {run.resultRevisionId}</p> : null}
    {run.errorSummary ? <p className="text-sm text-red-700">{run.errorSummary}</p> : null}
  </section>
}

function GenerationControls({ storyId, researchRunId }: { storyId: string; researchRunId: string | null }) {
  const providers = useQuery({ queryKey: editorialQueryKeys.editorialProviderOptions, queryFn: getAIProviderOptions })
  const brands = useQuery({ queryKey: editorialQueryKeys.editorialBrandOptions, queryFn: getBrandOptions })
  const prompts = useQuery({ queryKey: editorialQueryKeys.editorialPromptOptions, queryFn: getPromptVersionOptions })
  const generationProviders = providers.data?.filter((item) => item.capabilities.generation) ?? []
  const [providerId, setProviderId] = useState("")
  const [brandId, setBrandId] = useState("")
  const [canonicalPromptId, setCanonicalPromptId] = useState("")
  const [telegramPromptId, setTelegramPromptId] = useState("")
  const [outcome, setOutcome] = useState<string | null>(null)
  const selectedProvider = providers.data?.find((item) => item.id === providerId && item.capabilities.generation)
  const selectedBrand = brands.data?.find((item) => item.id === brandId)
  const canonicalPrompts = prompts.data?.filter((item) => item.active && item.purpose === "canonical_story") ?? []
  const telegramPrompts = prompts.data?.filter((item) => item.active && item.purpose === "telegram_pack") ?? []
  const canonical = canonicalPrompts.find((item) => item.id === canonicalPromptId)
  const telegram = telegramPrompts.find((item) => item.id === telegramPromptId)
  useEffect(() => { if (!selectedProvider) setProviderId(generationProviders[0]?.id ?? "") }, [generationProviders, selectedProvider])
  useEffect(() => { if (!selectedBrand) setBrandId(brands.data?.length ? (brands.data.find((item) => item.isDefault) ?? brands.data[0]).id : "") }, [brands.data, selectedBrand])
  useEffect(() => { if (!canonical) setCanonicalPromptId(canonicalPrompts[0]?.id ?? "") }, [canonical, canonicalPrompts])
  useEffect(() => { if (!telegram) setTelegramPromptId(telegramPrompts[0]?.id ?? "") }, [telegram, telegramPrompts])
  const generate = useMutation({ mutationFn: () => {
    const currentProvider = providers.data?.find((item) => item.id === providerId && item.capabilities.generation)
    const currentBrand = brands.data?.find((item) => item.id === brandId)
    const currentCanonical = prompts.data?.find((item) => item.id === canonical?.id && item.active && item.purpose === "canonical_story")
    const currentTelegram = prompts.data?.find((item) => item.id === telegram?.id && item.active && item.purpose === "telegram_pack")
    if (!currentProvider || !currentBrand || !currentCanonical || !currentTelegram) throw new Error("Generation options changed; select current options")
    return requestContentPack(storyId, { brandProfileId: currentBrand.id, generationProviderProfileId: currentProvider.id, canonicalPromptTemplateVersionId: currentCanonical.id, platformPromptTemplateVersionId: currentTelegram.id, researchRunId })
  }, onSuccess: (job) => setOutcome(`Content pack queued · job ${job.jobId}`), onError: (error) => setOutcome(getApiErrorMessage(error, "Content pack could not be queued")) })
  const loading = providers.isPending || brands.isPending || prompts.isPending
  const error = providers.isError || brands.isError || prompts.isError
  return <section className="space-y-3 rounded-lg border p-3" aria-label="Content pack generation"><h3 className="font-semibold">Generate content pack</h3>{loading ? <div role="status">Loading generation options…</div> : error ? <div role="alert">Generation options could not be loaded</div> : <><label className="grid gap-1"><span>Brand profile</span><select className="min-h-10 rounded-lg border px-3" value={brandId} onChange={(event) => setBrandId(event.target.value)}>{brands.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="grid gap-1"><span>Generation provider</span><select className="min-h-10 rounded-lg border px-3" value={providerId} onChange={(event) => setProviderId(event.target.value)}><option value="">Select a profile</option>{providers.data?.map((item) => <option key={item.id} value={item.id} disabled={!item.capabilities.generation}>{item.name}{item.unavailableReason ? ` — ${item.unavailableReason}` : ""}</option>)}</select></label><label className="grid gap-1"><span>Canonical story prompt</span><select className="min-h-10 rounded-lg border px-3" value={canonicalPromptId} onChange={(event) => setCanonicalPromptId(event.target.value)}>{canonicalPrompts.map((item) => <option key={item.id} value={item.id}>Version {item.version} · {item.id}</option>)}</select></label><label className="grid gap-1"><span>Telegram pack prompt</span><select className="min-h-10 rounded-lg border px-3" value={telegramPromptId} onChange={(event) => setTelegramPromptId(event.target.value)}>{telegramPrompts.map((item) => <option key={item.id} value={item.id}>Version {item.version} · {item.id}</option>)}</select></label><Button onClick={() => generate.mutate()} disabled={generate.isPending || !selectedBrand || !selectedProvider || !canonical || !telegram}>Generate Telegram pack</Button>{outcome ? <div role={generate.isError ? "alert" : "status"}>{outcome}</div> : null}</>}</section>
}

function deduplicateStories(items: StorySummary[]) { return Array.from(new Map(items.map((story) => [story.id, story])).values()) }

function ResearchDialog({ storyId, onClose, onCompleted }: { storyId: string; onClose: () => void; onCompleted: (runId: string) => void }) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const initialFocusRef = useRef<HTMLButtonElement>(null)
  useEditorialModal({ open: true, containerRef: dialogRef, initialFocusRef, onClose })
  const story = useQuery({ queryKey: editorialQueryKeys.story(storyId), queryFn: () => getStory(storyId) })
  const providers = useQuery({ queryKey: editorialQueryKeys.editorialProviderOptions, queryFn: getAIProviderOptions })
  const runs = useQuery({ queryKey: editorialQueryKeys.researchRuns(storyId), queryFn: () => getResearchRuns(storyId), refetchInterval: (query) => query.state.data?.some((run) => ["queued", "running"].includes(run.status)) ? 2_000 : false })
  return <div ref={dialogRef} tabIndex={-1} className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-label="Research story"><div className="max-h-[90vh] w-full max-w-xl space-y-4 overflow-y-auto rounded-xl bg-white p-5"><div className="flex justify-between gap-3"><h2 className="text-lg font-semibold">Research story</h2><Button ref={initialFocusRef} variant="ghost" onClick={onClose}>Close research</Button></div>{story.isPending || providers.isPending || runs.isPending ? <div role="status">Loading research options…</div> : story.isError || providers.isError || runs.isError ? <div role="alert">Research options could not be loaded</div> : <ResearchPanel story={story.data!} providers={providers.data!} run={runs.data?.[0] ?? null} onCompleted={onCompleted} />}</div></div>
}
