"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { requestResearch } from "@/lib/editorial-api"
import type { AIProviderOption, ResearchRunDetail, StoryDetail } from "@/lib/editorial-types"
import { getApiErrorMessage } from "@/lib/http"
import { editorialQueryKeys } from "@/lib/query-keys"

export function ResearchPanel({ story, providers, run }: { story: StoryDetail; providers: AIProviderOption[]; run: ResearchRunDetail | null }) {
  const queryClient = useQueryClient()
  const available = providers.filter((item) => item.capabilities.research)
  const [profileId, setProfileId] = useState(available[0]?.id ?? "")
  const [queryHint, setQueryHint] = useState("")
  const [outcome, setOutcome] = useState<string | null>(null)
  const selectedProvider = providers.find((item) => item.id === profileId && item.capabilities.research)
  useEffect(() => {
    if (!selectedProvider) setProfileId(available[0]?.id ?? "")
  }, [available, selectedProvider])
  const mutation = useMutation({
    mutationFn: (depth: "standard" | "deep") => {
      const current = providers.find((item) => item.id === profileId && item.capabilities.research)
      if (!current) throw new Error("Selected research provider is no longer available")
      return requestResearch(story.id, { mode: "manual", depth, providerProfileId: current.id, queryHint: queryHint.trim() || null })
    },
    onSuccess: async (result) => {
      setOutcome(result.disposition === "complete_without_research" ? "Coverage already complete" : "Research queued")
      await queryClient.invalidateQueries({ queryKey: editorialQueryKeys.researchRuns(story.id) })
      await queryClient.invalidateQueries({ queryKey: editorialQueryKeys.story(story.id) })
    },
  })
  const failed = run?.status === "failed"
  return <section className="space-y-4" aria-label="Research controls">
    {run ? <ResearchOutcome run={run} /> : null}
    <label className="grid gap-1 text-sm font-medium"><span>Research provider</span><select className="min-h-10 rounded-lg border bg-background px-3" value={profileId} onChange={(event) => setProfileId(event.target.value)}>
      <option value="">Select a profile</option>{providers.map((item) => <option key={item.id} value={item.id} disabled={!item.capabilities.research}>{item.name}{item.unavailableReason ? ` — ${item.unavailableReason}` : ""}</option>)}
    </select></label>
    <label className="grid gap-1 text-sm font-medium"><span>Research note (optional)</span><textarea className="min-h-20 rounded-lg border bg-background px-3 py-2" maxLength={500} value={queryHint} onChange={(event) => setQueryHint(event.target.value)} /></label>
    {mutation.error ? <div role="alert" dir="auto" className="text-red-700">{getApiErrorMessage(mutation.error, "Research could not be queued")}</div> : null}
    {outcome ? <div role="status">{outcome}</div> : null}
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => mutation.mutate("standard")} disabled={!selectedProvider || mutation.isPending}>{failed ? "Retry research" : "Research more"}</Button>
      <Button variant="outline" onClick={() => mutation.mutate("deep")} disabled={!selectedProvider || mutation.isPending}>Deep research</Button>
    </div>
  </section>
}

function ResearchOutcome({ run }: { run: ResearchRunDetail }) {
  if (["queued", "running"].includes(run.status)) return <div role="status">{run.status === "queued" ? "Research queued" : "Research in progress"}</div>
  if (run.status === "failed") return <div className="text-red-700">Research failed</div>
  if (run.status === "succeeded") return <div className="space-y-2"><div>Research completed</div>{run.sources.map((source) => <div key={source.id} className="flex flex-wrap items-center gap-2"><span>{source.title ?? "Fetched source"}</span><a className="text-primary underline" href={source.url} target="_blank" rel="noreferrer">Open fetched source</a></div>)}</div>
  return <div>Research {run.status}</div>
}
