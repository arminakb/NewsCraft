import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { StoryInbox } from "@/components/editorial/story-inbox"
import * as api from "@/lib/editorial-api"
import type { StorySummary } from "@/lib/editorial-types"

vi.mock("@/lib/editorial-api", async () => ({ getStories: vi.fn(), getStory: vi.fn(), getStoryEvidence: vi.fn(), getAIProviderOptions: vi.fn(), getBrandOptions: vi.fn(), getPromptVersionOptions: vi.fn(), getResearchRuns: vi.fn(), groupPendingStories: vi.fn(), setStoryEditorialState: vi.fn(), bulkSetStoryEditorialState: vi.fn(), requestContentPack: vi.fn() }))

const incomplete: StorySummary = { id: "story-1", title: "Election timeline", evidenceCount: 2, latestEvidenceAt: "2026-07-12T08:00:00Z", completeness: { complete: false, score: 40, reasons: ["More sources needed"] }, editorialState: "inbox", status: "inbox", primaryLanguage: "en", evidenceSetHash: "a".repeat(64), createdAt: "2026-07-12T07:00:00Z", updatedAt: "2026-07-12T08:00:00Z" }

beforeEach(() => {
  window.history.replaceState({}, "", "/")
  vi.resetAllMocks()
  vi.mocked(api.getStories).mockResolvedValue({ items: [incomplete], nextCursor: null })
  const evidence = { id: "e-1", evidenceKey: "key", title: "Operator memo", contentText: "Operator content", contentSha256: "b".repeat(64), sourceUrl: null, authors: [], publishedAt: "2026-07-12T07:30:00Z", capturedAt: "2026-07-12T08:00:00Z" }
  vi.mocked(api.getStory).mockResolvedValue({ ...incomplete, evidence: [evidence] })
  vi.mocked(api.getStoryEvidence).mockResolvedValue([evidence])
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([])
  vi.mocked(api.getBrandOptions).mockResolvedValue([])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([])
  vi.mocked(api.getResearchRuns).mockResolvedValue([])
})

it("submits the succeeded research run binding from the regeneration link query", async () => {
  window.history.replaceState({}, "", "/inbox?story_id=story-1&research_run_id=run-1")
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([{ id: "provider-1", name: "Generation desk", providerType: "codex", defaultModel: "gpt-5", capabilities: { generation: true, research: true }, unavailableReason: null }])
  vi.mocked(api.getBrandOptions).mockResolvedValue([{ id: "brand-1", name: "News desk", isDefault: true }])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([{ id: "canonical-1", purpose: "canonical_story", version: 1, checksumSha256: "a".repeat(64), active: true }, { id: "telegram-1", purpose: "telegram_pack", version: 1, checksumSha256: "b".repeat(64), active: true }])
  vi.mocked(api.requestContentPack).mockResolvedValue({ jobId: "bound-pack", status: "queued", deduplicated: false })
  renderInbox()
  expect(await screen.findByText(/Generation is bound to succeeded research run run-1/)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByLabelText("Generation provider")).toHaveValue("provider-1"))
  fireEvent.click(screen.getByRole("button", { name: "Generate Telegram pack" }))
  await waitFor(() => expect(api.requestContentPack).toHaveBeenCalledWith("story-1", expect.objectContaining({ researchRunId: "run-1" })))
})

it("groups evidence and offers research from truthful completeness", async () => {
  renderInbox()
  expect(await screen.findByText("2 evidence items")).toBeInTheDocument()
  expect(screen.getByText("Coverage incomplete")).toBeInTheDocument()
  expect(screen.getByText("40%")).toBeInTheDocument()
  expect(screen.queryByText("4000%")).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Open Election timeline" }))
  expect(await screen.findByText("Operator-provided text")).toBeInTheDocument()
  expect(screen.getByText("Operator memo")).toBeInTheDocument()
  expect(screen.getByText(/Published/)).toBeInTheDocument()
  expect(screen.getByText(/Captured/)).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Open original source" })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Research more" }))
  expect(await screen.findByRole("dialog", { name: "Research story" })).toBeInTheDocument()
})

it("generates a durable pack using only configured IDs and active prompt versions", async () => {
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([
    { id: "no-generation", name: "Research only", providerType: "openrouter", defaultModel: "model", capabilities: { generation: false, research: true }, unavailableReason: "Generation unavailable" },
    { id: "provider-1", name: "Generation desk", providerType: "codex", defaultModel: "gpt-5", capabilities: { generation: true, research: true }, unavailableReason: null },
  ])
  vi.mocked(api.getBrandOptions).mockResolvedValue([{ id: "brand-1", name: "News desk", isDefault: true }])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([
    { id: "canonical-1", purpose: "canonical_story", version: 2, checksumSha256: "a".repeat(64), active: true },
    { id: "telegram-1", purpose: "telegram_pack", version: 4, checksumSha256: "b".repeat(64), active: true },
  ])
  vi.mocked(api.requestContentPack).mockResolvedValue({ jobId: "pack-job", status: "queued", deduplicated: false })
  renderInbox()
  fireEvent.click(await screen.findByRole("button", { name: "Open Election timeline" }))
  expect(await screen.findByRole("option", { name: /Research only/ })).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Generation provider"), { target: { value: "provider-1" } })
  fireEvent.click(screen.getByRole("button", { name: "Generate Telegram pack" }))
  await waitFor(() => expect(api.requestContentPack).toHaveBeenCalledWith("story-1", {
    brandProfileId: "brand-1",
    generationProviderProfileId: "provider-1",
    canonicalPromptTemplateVersionId: "canonical-1",
    platformPromptTemplateVersionId: "telegram-1",
    researchRunId: null,
  }))
  expect(await screen.findByText(/pack-job/)).toBeInTheDocument()
})

it("deduplicates loaded pages and immediately removes shortlisted stories from the inbox filter", async () => {
  vi.mocked(api.getStories)
    .mockResolvedValueOnce({ items: [incomplete], nextCursor: "cursor-1" })
    .mockResolvedValueOnce({ items: [incomplete, { ...incomplete, id: "story-2", title: "Second story" }], nextCursor: null })
    .mockResolvedValue({ items: [{ ...incomplete, id: "story-2", title: "Second story" }], nextCursor: null })
  vi.mocked(api.setStoryEditorialState).mockResolvedValue({ ...incomplete, editorialState: "shortlisted", status: "shortlisted" })
  renderInbox()
  await screen.findByText("Election timeline")
  fireEvent.click(screen.getByRole("button", { name: "Load more stories" }))
  expect(await screen.findByText("Second story")).toBeInTheDocument()
  expect(screen.getAllByText("Election timeline")).toHaveLength(1)
  fireEvent.click(screen.getAllByRole("button", { name: "Shortlist" })[0])
  await waitFor(() => expect(screen.queryByText("Election timeline")).not.toBeInTheDocument())
  expect(screen.getByText("Second story")).toBeInTheDocument()
})

it("ignores a deferred load-more page after filters change", async () => {
  let resolveOldPage!: (value: { items: StorySummary[]; nextCursor: string | null }) => void
  const oldPage = new Promise<{ items: StorySummary[]; nextCursor: string | null }>((resolve) => { resolveOldPage = resolve })
  vi.mocked(api.getStories)
    .mockResolvedValueOnce({ items: [incomplete], nextCursor: "cursor-1" })
    .mockReturnValueOnce(oldPage)
    .mockResolvedValue({ items: [{ ...incomplete, id: "search-story", title: "Search result" }], nextCursor: null })
  renderInbox()
  await screen.findByText("Election timeline")
  fireEvent.click(screen.getByRole("button", { name: "Load more stories" }))
  fireEvent.change(screen.getByLabelText("Search stories"), { target: { value: "updated" } })
  expect(await screen.findByText("Search result")).toBeInTheDocument()
  resolveOldPage({ items: [{ ...incomplete, id: "stale-story", title: "Stale old page" }], nextCursor: "stale-cursor" })
  await waitFor(() => expect(screen.queryByText("Stale old page")).not.toBeInTheDocument())
  expect(screen.queryByRole("button", { name: "Load more stories" })).not.toBeInTheDocument()
})

it("drops a generation selection when cached capabilities change and refuses stale submission", async () => {
  const enabled = { id: "provider-1", name: "Generation desk", providerType: "codex" as const, defaultModel: "gpt-5", capabilities: { generation: true, research: true }, unavailableReason: null }
  vi.mocked(api.getAIProviderOptions).mockResolvedValue([enabled])
  vi.mocked(api.getBrandOptions).mockResolvedValue([{ id: "brand-1", name: "News desk", isDefault: true }])
  vi.mocked(api.getPromptVersionOptions).mockResolvedValue([
    { id: "canonical-1", purpose: "canonical_story", version: 1, checksumSha256: "a".repeat(64), active: true },
    { id: "telegram-1", purpose: "telegram_pack", version: 1, checksumSha256: "b".repeat(64), active: true },
  ])
  const view = renderInbox()
  fireEvent.click(await screen.findByRole("button", { name: "Open Election timeline" }))
  await waitFor(() => expect(screen.getByLabelText("Generation provider")).toHaveValue("provider-1"))
  view.client.setQueryData(["settings", "ai-provider-profiles", "editorial-options"], [{ ...enabled, capabilities: { generation: false, research: true } }])
  await waitFor(() => expect(screen.getByLabelText("Generation provider")).toHaveValue(""))
  const submit = screen.getByRole("button", { name: "Generate Telegram pack" })
  expect(submit).toBeDisabled()
  fireEvent.click(submit)
  expect(api.requestContentPack).not.toHaveBeenCalled()
})

it("traps research dialog focus, closes on Escape, and restores the opener", async () => {
  renderInbox()
  const opener = await screen.findByRole("button", { name: "Research more" })
  opener.focus()
  fireEvent.click(opener)
  const dialog = await screen.findByRole("dialog", { name: "Research story" })
  const close = within(dialog).getByRole("button", { name: "Close research" })
  await waitFor(() => expect(close).toHaveFocus())
  fireEvent.keyDown(document, { key: "Tab", shiftKey: true })
  expect(dialog).toContainElement(document.activeElement as HTMLElement)
  fireEvent.keyDown(document, { key: "Escape" })
  expect(screen.queryByRole("dialog", { name: "Research story" })).not.toBeInTheDocument()
  await waitFor(() => expect(opener).toHaveFocus())
})

it("filters, keeps bounded selection on failure, and supports bulk state changes", async () => {
  vi.mocked(api.getStories).mockResolvedValue({ items: Array.from({ length: 201 }, (_, index) => ({ ...incomplete, id: `story-${index + 1}`, title: `Story ${index + 1}` })), nextCursor: null })
  vi.mocked(api.bulkSetStoryEditorialState).mockRejectedValue(new Error("conflict"))
  renderInbox()
  await screen.findAllByRole("checkbox", { name: /Select Story/ })
  fireEvent.click(screen.getByRole("button", { name: "Select up to 200 visible" }))
  expect(screen.getByText("200 stories selected")).toBeInTheDocument()
  fireEvent.click(screen.getByRole("button", { name: "Reject selected" }))
  expect(await screen.findByRole("alert")).toHaveTextContent("conflict")
  expect(screen.getByText("200 stories selected")).toBeInTheDocument()
})

it("queues durable grouping and displays the accepted job", async () => {
  vi.mocked(api.groupPendingStories).mockResolvedValue({ jobId: "job-group", status: "queued", deduplicated: false })
  renderInbox()
  fireEvent.click(await screen.findByRole("button", { name: "Group pending content" }))
  expect(await screen.findByText(/job-group/)).toBeInTheDocument()
})

function renderInbox() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { client, ...render(<QueryClientProvider client={client}><StoryInbox /></QueryClientProvider>) }
}
