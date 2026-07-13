import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { ExactRevisionReview } from "@/components/editorial/exact-revision-review"
import * as packageApi from "@/features/packages/api"
import type { PlatformRevision } from "@/features/packages/types"

vi.mock("@/components/editorial/content-pack-workspace", () => ({
  ContentPackWorkspace: ({ packId }: { packId: string }) => <div>Package workspace {packId}</div>,
}))
vi.mock("@/features/review/telegram-review-workspace", () => ({
  TelegramReviewWorkspace: () => <div>Telegram publish controls</div>,
}))
vi.mock("@/features/packages/api", () => ({ getPlatformRevision: vi.fn() }))

const baseRevision = {
  id: "revision-instagram",
  platform: "instagram",
  variantId: "variant-instagram",
  contentPackId: "pack-1",
  storyId: "story-1",
  parentRevisionId: null,
  generationAttemptId: null,
  revisionNumber: 1,
  content: {
    hook: "Grounded hook",
    caption: "Grounded caption",
    cta: "Read more",
    hashtags: [],
    alt_text: "Summary card",
    carousel: [],
    citations: [],
    manual_checklist: ["Verify copy"],
  },
  contentHash: "a".repeat(64),
  evidenceMap: [],
  validationResults: [],
  approvalState: "approved",
  approvalNote: null,
  approvedAt: "2026-07-13T08:00:00Z",
  createdBy: "generation",
  origin: "generation",
  createdAt: "2026-07-13T08:00:00Z",
  providerProfile: null,
  resolvedModel: null,
} as unknown as PlatformRevision

beforeEach(() => vi.resetAllMocks())

it("keeps an approved manual revision out of Telegram publish controls", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByRole("region", { name: "Manual publication handoff" })).toBeInTheDocument()
  expect(screen.getByText(/Instagram is a manual publication platform/i)).toBeInTheDocument()
  expect(screen.queryByText("Telegram publish controls")).not.toBeInTheDocument()
})

it("does not describe an unapproved manual revision as a publication handoff", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue({ ...baseRevision, approvalState: "pending_review", approvedAt: null } as PlatformRevision)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByRole("region", { name: "Manual publication unavailable" })).toBeInTheDocument()
  expect(screen.getByText(/Approve this exact Instagram revision before manual publication handoff/i)).toBeInTheDocument()
  expect(screen.queryByRole("region", { name: "Manual publication handoff" })).not.toBeInTheDocument()
})

it("preserves the Telegram preview, scheduling, and publish handoff", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue({ ...baseRevision, id: "revision-telegram", platform: "telegram" } as PlatformRevision)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId="revision-telegram" /></QueryClientProvider>)

  expect(await screen.findByText("Telegram publish controls")).toBeInTheDocument()
  expect(screen.queryByRole("region", { name: "Manual publication handoff" })).not.toBeInTheDocument()
})
