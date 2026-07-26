import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { addTextStory, changeStoryState, getInboxStories } from "@/features/inbox/api"
import { InboxPage } from "@/features/inbox/inbox-page"

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(),
  replace: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}))

vi.mock("@/features/inbox/api", () => ({
  addTextStory: vi.fn(),
  changeStoryState: vi.fn(),
  getInboxStories: vi.fn(),
}))

describe("InboxPage", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    navigation.params = new URLSearchParams()
    vi.mocked(getInboxStories).mockResolvedValue([
      {
        id: "11111111-1111-4111-8111-111111111111",
        title: "A consequential regional story",
        status: "inbox",
        primaryLanguage: "fa",
        evidenceCount: 2,
        latestEvidenceAt: "2026-07-26T08:00:00Z",
        completeness: { complete: false, score: 60, reasons: ["independent_sources"] },
        updatedAt: "2026-07-26T08:00:00Z",
      },
    ])
    vi.mocked(changeStoryState).mockResolvedValue()
    vi.mocked(addTextStory).mockResolvedValue()
  })

  it("defaults to decisions and keeps one primary row action", async () => {
    renderInbox()

    expect(await screen.findByRole("heading", { name: "A consequential regional story" })).toBeInTheDocument()
    expect(getInboxStories).toHaveBeenCalledWith("needs-decision")
    expect(screen.getByRole("link", { name: "Needs decision" })).toHaveAttribute("aria-current", "page")
    expect(screen.getByRole("link", { name: "Ready to generate" })).toHaveAttribute(
      "href",
      "/inbox?view=ready-to-generate",
    )
    expect(screen.getByText("Research 60%")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Shortlist" }))
    await waitFor(() =>
      expect(changeStoryState).toHaveBeenCalledWith("11111111-1111-4111-8111-111111111111", "shortlisted"),
    )
    expect(screen.getByLabelText("More actions for A consequential regional story")).toBeInTheDocument()
  })

  it("keeps rejection behind secondary actions", async () => {
    renderInbox()
    await screen.findByRole("heading", { name: "A consequential regional story" })

    fireEvent.click(screen.getByLabelText("More actions for A consequential regional story"))
    fireEvent.click(screen.getByRole("button", { name: "Reject" }))

    await waitFor(() =>
      expect(changeStoryState).toHaveBeenCalledWith("11111111-1111-4111-8111-111111111111", "rejected"),
    )
  })

  it("sends generation-ready stories to the job queue", async () => {
    navigation.params = new URLSearchParams("view=ready-to-generate")
    renderInbox()

    expect(await screen.findByRole("link", { name: "Open job queue" })).toHaveAttribute("href", "/jobs")
  })

  it("queues manually pasted source text from the direct Add story action", async () => {
    renderInbox()
    fireEvent.click(screen.getByRole("button", { name: "Add story" }))

    const dialog = screen.getByRole("dialog", { name: "Add story" })
    fireEvent.change(within(dialog).getByLabelText("Title"), { target: { value: "  Manual story  " } })
    fireEvent.change(within(dialog).getByLabelText("Source label"), { target: { value: "  Reporter notes  " } })
    fireEvent.change(within(dialog).getByLabelText("Source URL (optional)"), {
      target: { value: "https://example.com/source" },
    })
    fireEvent.change(within(dialog).getByLabelText("Source text"), {
      target: { value: "This is long enough source text for the manual story intake." },
    })
    fireEvent.click(within(dialog).getByRole("button", { name: "Add to Inbox" }))

    await waitFor(() =>
      expect(addTextStory).toHaveBeenCalledWith({
        title: "Manual story",
        sourceLabel: "Reporter notes",
        sourceUrl: "https://example.com/source",
        text: "This is long enough source text for the manual story intake.",
      }),
    )
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/inbox"))
  })
})

function renderInbox() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <NoticeProvider>
        <InboxPage />
      </NoticeProvider>
    </QueryClientProvider>,
  )
}
