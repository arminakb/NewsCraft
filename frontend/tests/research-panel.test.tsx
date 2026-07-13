import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ResearchPanel } from "@/components/editorial/research-panel"
import { requestResearch } from "@/lib/editorial-api"
import type { AIProviderOption, ResearchRunDetail, StoryDetail } from "@/lib/editorial-types"

vi.mock("@/lib/editorial-api", async () => ({ requestResearch: vi.fn(), getResearchRun: vi.fn() }))

const providers: AIProviderOption[] = [
  { id: "disabled", name: "Generation only", providerType: "fake", defaultModel: null, capabilities: { generation: true, research: false }, unavailableReason: "Research unavailable" },
  { id: "profile-1", name: "Research desk", providerType: "codex", defaultModel: "gpt-5", capabilities: { generation: true, research: true }, unavailableReason: null },
]
const story = { id: "story-1", title: "Story", evidenceCount: 2, latestEvidenceAt: "2026-07-12T08:00:00Z", completeness: { complete: false, score: 40, reasons: [] }, editorialState: "inbox", status: "inbox", primaryLanguage: "en", evidenceSetHash: "a".repeat(64), createdAt: "2026-07-12T07:00:00Z", updatedAt: "2026-07-12T08:00:00Z", evidence: [] } satisfies StoryDetail

it("selects configured research profile IDs and queues deep research", async () => {
  vi.mocked(requestResearch).mockResolvedValue({ disposition: "enqueued", runId: "run-1", jobId: "job-1", completeness: story.completeness })
  renderPanel(<ResearchPanel story={story} providers={providers} run={null} />)
  expect(screen.getByRole("option", { name: /Generation only/ })).toBeDisabled()
  fireEvent.change(screen.getByLabelText("Research provider"), { target: { value: "profile-1" } })
  fireEvent.click(screen.getByRole("button", { name: "Deep research" }))
  await waitFor(() => expect(requestResearch).toHaveBeenCalledWith("story-1", expect.objectContaining({ providerProfileId: "profile-1", depth: "deep", mode: "manual" })))
  expect(await screen.findByText("Research queued")).toBeInTheDocument()
})

it("shows pending, failed, and completed research truth", () => {
  const pending = run({ status: "queued" })
  const view = renderPanel(<ResearchPanel story={story} providers={providers} run={pending} />)
  expect(screen.getByText("Research queued")).toBeInTheDocument()
  view.rerender(wrapper(<ResearchPanel story={story} providers={providers} run={run({ status: "failed" })} />))
  expect(screen.getByRole("button", { name: "Retry research" })).toBeInTheDocument()
  view.rerender(wrapper(<ResearchPanel story={story} providers={providers} run={run({ status: "succeeded", sources: [{ id: "source-1", url: "https://example.com/source", title: "Verified source", contentSha256: "b".repeat(64), publishedAt: "2026-07-12T09:00:00Z" }] })} />))
  expect(screen.getByRole("link", { name: "Open fetched source" })).toHaveAttribute("href", "https://example.com/source")
})

it("resets a stale provider selection and refuses submission after capability loss", async () => {
  vi.mocked(requestResearch).mockClear()
  vi.mocked(requestResearch).mockResolvedValue({ disposition: "enqueued", runId: "run-1", jobId: "job-1", completeness: story.completeness })
  const view = renderPanel(<ResearchPanel story={story} providers={providers} run={null} />)
  fireEvent.change(screen.getByLabelText("Research provider"), { target: { value: "profile-1" } })
  view.rerender(wrapper(<ResearchPanel story={story} providers={providers.map((item) => item.id === "profile-1" ? { ...item, capabilities: { ...item.capabilities, research: false } } : item)} run={null} />))
  await waitFor(() => expect(screen.getByLabelText("Research provider")).toHaveValue(""))
  const submit = screen.getByRole("button", { name: "Research more" })
  expect(submit).toBeDisabled()
  fireEvent.click(submit)
  expect(requestResearch).not.toHaveBeenCalled()
})

it("binds only a completed succeeded run with a durable result revision", async () => {
  const completed = vi.fn()
  const view = renderPanel(<ResearchPanel story={story} providers={providers} run={run({ status: "queued" })} onCompleted={completed} />)
  expect(completed).not.toHaveBeenCalled()
  view.rerender(wrapper(<ResearchPanel story={story} providers={providers} run={run({ status: "failed" })} onCompleted={completed} />))
  expect(completed).not.toHaveBeenCalled()
  view.rerender(wrapper(<ResearchPanel story={story} providers={providers} run={run({ status: "succeeded", resultStoryRevisionId: "story-revision-2" })} onCompleted={completed} />))
  await waitFor(() => expect(completed).toHaveBeenCalledWith("run-1"))
})

function renderPanel(node: React.ReactNode) { return render(wrapper(node)) }
function wrapper(node: React.ReactNode) { return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{node}</QueryClientProvider> }
function run(overrides: Partial<ResearchRunDetail>): ResearchRunDetail { return { id: "run-1", storyId: "story-1", requestedMode: "manual", status: "queued", provider: { id: "profile-1", name: "Research desk", providerType: "codex" }, budget: { maxQueries: 4, maxPages: 8, maxElapsedSeconds: 60 }, requestedModel: "gpt-5", resolvedModel: null, evidenceSetHash: "a".repeat(64), completeness: story.completeness, attempts: [], sources: [], resultStoryRevisionId: null, ...overrides } }
