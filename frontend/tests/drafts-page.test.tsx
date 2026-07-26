import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import DraftsPage from "@/app/drafts/page"
import { getContentPackRequests } from "@/features/editorial/api"

vi.mock("@/features/editorial/api", () => ({ getContentPackRequests: vi.fn() }))

it("shows a durable provider failure and real job ID before a pack exists", async () => {
  vi.mocked(getContentPackRequests).mockResolvedValue([{ id: "request-1", jobId: "job-1", storyId: "story-1", status: "needs_review", lastFailure: "Provider response failed validation", createdAt: "2026-07-12T08:00:00Z", updatedAt: "2026-07-12T08:01:00Z", pack: null }])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(await screen.findByText("job-1")).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("Provider response failed validation")
  expect(screen.getByText("Review required before a pack can be created.")).toBeInTheDocument()
  expect(screen.getByText("Advanced details — blocker").closest("details")).toHaveAttribute("open")
  expect(view.container.querySelector("main")).not.toBeInTheDocument()
})

it("shows an error when durable requests fail", async () => {
  vi.mocked(getContentPackRequests).mockRejectedValue(new Error("request list unavailable"))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(await screen.findByRole("alert")).toHaveTextContent("request list unavailable")
  expect(screen.getByRole("button", { name: "Retry drafts" })).toBeInTheDocument()
})

it("shows loading while durable requests load", () => {
  vi.mocked(getContentPackRequests).mockReturnValue(new Promise(() => {}))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)
  expect(screen.getByText("Loading drafts…")).toBeInTheDocument()
})

it("filters review and ready-for-handoff packages without exposing IDs by default", async () => {
  vi.mocked(getContentPackRequests).mockResolvedValue([
    {
      id: "review-request",
      jobId: "review-job",
      storyId: "review-story",
      status: "succeeded",
      lastFailure: null,
      createdAt: "2026-07-12T08:00:00Z",
      updatedAt: "2026-07-12T08:01:00Z",
      pack: {
        id: "review-pack",
        storyId: "review-story",
        storyRevisionId: "story-revision",
        brandProfileId: "brand",
        status: "draft",
        createdAt: "2026-07-12T08:00:00Z",
        updatedAt: "2026-07-12T08:01:00Z",
        lastFailure: null,
        jobId: "review-job",
        variants: [],
      },
    },
    {
      id: "ready-request",
      jobId: "ready-job",
      storyId: "ready-story",
      status: "ready",
      lastFailure: null,
      createdAt: "2026-07-12T08:00:00Z",
      updatedAt: "2026-07-12T08:02:00Z",
      pack: {
        id: "ready-pack",
        storyId: "ready-story",
        storyRevisionId: "story-revision-2",
        brandProfileId: "brand",
        status: "ready",
        createdAt: "2026-07-12T08:00:00Z",
        updatedAt: "2026-07-12T08:02:00Z",
        lastFailure: null,
        jobId: "ready-job",
        variants: [],
      },
    },
  ])
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><DraftsPage /></QueryClientProvider>)

  expect(await screen.findByRole("link", { name: "Continue review" })).toHaveAttribute("href", "/drafts/review-pack")
  expect(screen.getByText("review-job").closest("details")).not.toHaveAttribute("open")
  fireEvent.click(screen.getByRole("button", { name: /Ready for handoff/ }))
  expect(screen.getByRole("link", { name: "Open handoff" })).toHaveAttribute("href", "/drafts/ready-pack")
  expect(screen.queryByRole("link", { name: "Continue review" })).not.toBeInTheDocument()
})
