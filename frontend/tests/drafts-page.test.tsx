import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import DraftsPage from "@/app/drafts/page"
import { getContentPackRequests } from "@/lib/editorial-api"

vi.mock("@/lib/editorial-api", () => ({ getContentPackRequests: vi.fn() }))
vi.mock("@/features/drafts/telegram-draft-list", () => ({
  TelegramDraftList: () => <a href="/review/legacy-revision">Review legacy revision</a>,
}))

it("shows a durable provider failure and real job ID before a pack exists", async () => {
  vi.mocked(getContentPackRequests).mockResolvedValue([{ id: "request-1", jobId: "job-1", storyId: "story-1", status: "needs_review", lastFailure: "Provider response failed validation", createdAt: "2026-07-12T08:00:00Z", updatedAt: "2026-07-12T08:01:00Z", pack: null }])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(await screen.findByText("Job job-1")).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("Provider response failed validation")
  expect(screen.getByText("Review required before a pack can be created.")).toBeInTheDocument()
  expect(screen.queryByRole("link", { name: "Open editorial studio" })).not.toBeInTheDocument()
  expect(view.container.querySelector("main")).not.toBeInTheDocument()
})

it("keeps legacy Telegram drafts visible when durable requests fail", async () => {
  vi.mocked(getContentPackRequests).mockRejectedValue(new Error("request list unavailable"))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(await screen.findByRole("alert")).toHaveTextContent("request list unavailable")
  expect(screen.getByRole("link", { name: "Review legacy revision" })).toBeInTheDocument()
})

it("keeps legacy Telegram drafts visible while durable requests load", () => {
  vi.mocked(getContentPackRequests).mockReturnValue(new Promise(() => {}))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(screen.getByText("Loading durable draft requests…")).toBeInTheDocument()
  expect(screen.getByRole("link", { name: "Review legacy revision" })).toBeInTheDocument()
})
