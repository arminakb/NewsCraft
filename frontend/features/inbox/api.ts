import { apiRequest } from "@/lib/http"

export type InboxView = "needs-decision" | "ready-to-generate" | "research-incomplete"

export type InboxStory = {
  id: string
  title: string
  status: "inbox" | "shortlisted" | "rejected" | "drafted"
  primaryLanguage: string
  evidenceCount: number
  latestEvidenceAt: string | null
  completeness: {
    complete: boolean
    score: number
    reasons: string[]
  }
  updatedAt: string
}

type StoryWire = {
  id: string
  title: string
  status: InboxStory["status"]
  primary_language: string
  evidence_count: number
  latest_evidence_at: string | null
  completeness: {
    complete: boolean
    score: number
    reasons: string[]
  }
  updated_at: string
}

type StoryPageWire = {
  items: StoryWire[]
  next_cursor: string | null
}

const VIEW_FILTERS: Record<InboxView, { editorialState: "inbox" | "shortlisted"; completeness?: "complete" | "incomplete" }> = {
  "needs-decision": { editorialState: "inbox" },
  "ready-to-generate": { editorialState: "shortlisted", completeness: "complete" },
  "research-incomplete": { editorialState: "shortlisted", completeness: "incomplete" },
}

export async function getInboxStories(view: InboxView): Promise<InboxStory[]> {
  const filter = VIEW_FILTERS[view]
  const params = new URLSearchParams({ editorial_state: filter.editorialState, limit: "200" })
  if (filter.completeness) params.set("completeness", filter.completeness)
  const page = await apiRequest<StoryPageWire>(`/stories?${params.toString()}`)
  return page.items.map((story) => ({
    id: story.id,
    title: story.title,
    status: story.status,
    primaryLanguage: story.primary_language,
    evidenceCount: story.evidence_count,
    latestEvidenceAt: story.latest_evidence_at,
    completeness: story.completeness,
    updatedAt: story.updated_at,
  }))
}

export async function changeStoryState(
  storyId: string,
  state: "inbox" | "shortlisted" | "rejected",
): Promise<void> {
  await apiRequest(`/stories/${encodeURIComponent(storyId)}/editorial-state`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ state }),
  })
}

export async function addTextStory(input: {
  title: string
  text: string
  sourceLabel: string
  sourceUrl: string | null
}): Promise<void> {
  await apiRequest("/stories/manual", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      kind: "text",
      title: input.title,
      text: input.text,
      source_label: input.sourceLabel,
      source_url: input.sourceUrl || null,
    }),
  })
}
