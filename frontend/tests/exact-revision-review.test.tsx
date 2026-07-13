import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { ExactRevisionReview } from "@/components/editorial/exact-revision-review"
import * as packageApi from "@/features/packages/api"
import type { PlatformRevision } from "@/features/packages/types"
import { ApiError } from "@/lib/http"
import { packageQueryKeys } from "@/lib/query-keys"

vi.mock("@/components/editorial/content-pack-workspace", () => ({
  ContentPackWorkspace: ({ packId }: { packId: string }) => <div>Package workspace {packId}</div>,
}))
vi.mock("@/features/review/telegram-review-workspace", () => ({
  TelegramReviewWorkspace: () => <div>Telegram publish controls</div>,
}))
vi.mock("@/features/packages/api", () => ({ createManualPublicationPlan: vi.fn(), getManualPublicationPlanForRevision: vi.fn(), getPlatformRevision: vi.fn() }))

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

const storedPlan = {
  id: "plan-1",
  platformVariantRevisionId: baseRevision.id,
  platform: "instagram" as const,
  scheduledFor: "2026-07-14T08:00:00Z",
  displayTimezone: "Asia/Tehran",
  status: "planned" as const,
  checklistState: { copy_reviewed: false },
  externalUrl: null,
  operatorNote: null,
  completedAt: null,
  createdAt: "2026-07-13T08:00:00Z",
  updatedAt: "2026-07-13T08:00:00Z",
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(packageApi.getManualPublicationPlanForRevision).mockResolvedValue(null)
})

it("keeps an approved manual revision out of Telegram publish controls", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByRole("region", { name: "Manual publication handoff" })).toBeInTheDocument()
  expect(screen.getByText(/Instagram is a manual publication platform/i)).toBeInTheDocument()
  expect(screen.queryByText("Telegram publish controls")).not.toBeInTheDocument()
})

it("creates a durable manual plan for the exact approved revision before showing its checklist", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  vi.mocked(packageApi.createManualPublicationPlan).mockResolvedValue(storedPlan)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  fireEvent.change(await screen.findByLabelText("Scheduled time (UTC)"), { target: { value: "2026-07-14T08:00" } })
  fireEvent.change(screen.getByLabelText("Display timezone"), { target: { value: "Asia/Tehran" } })
  fireEvent.click(screen.getByRole("button", { name: "Create manual publication plan" }))

  await waitFor(() => expect(packageApi.createManualPublicationPlan).toHaveBeenCalledWith(
    baseRevision.id,
    "2026-07-14T08:00:00.000Z",
    "Asia/Tehran",
  ))
  expect(await screen.findByText(/Instagram plan plan-1 · exact revision revision-instagram/)).toBeInTheDocument()
  expect(screen.getByRole("status")).toHaveTextContent("Manual publication plan created")
})

it("rehydrates the persisted exact-revision plan after a disconnected review remount", async () => {
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  vi.mocked(packageApi.getManualPublicationPlanForRevision).mockResolvedValue(storedPlan)

  const first = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)
  expect(await screen.findByText(/Instagram plan plan-1 · exact revision revision-instagram/)).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Create manual publication plan" })).not.toBeInTheDocument()
  first.unmount()

  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)
  expect(await screen.findByText(/Instagram plan plan-1 · exact revision revision-instagram/)).toBeInTheDocument()
  expect(packageApi.getManualPublicationPlanForRevision).toHaveBeenCalledTimes(2)
})

it("truthfully restores URL-less manual completion evidence after a disconnected remount", async () => {
  const publishedPlan = {
    ...storedPlan,
    status: "manual_published" as const,
    checklistState: { copy_reviewed: true },
    operatorNote: "Verified on the public account",
    completedAt: "2026-07-13T10:00:00Z",
    updatedAt: "2026-07-13T10:00:00Z",
  }
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  vi.mocked(packageApi.getManualPublicationPlanForRevision).mockResolvedValue(publishedPlan)

  const first = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)
  expect(await screen.findByText("Status: Published manually")).toBeInTheDocument()
  first.unmount()

  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByText("Status: Published manually")).toBeInTheDocument()
  expect(screen.getByRole("region", { name: "Manual publication completion evidence" })).toHaveTextContent("2026-07-13T10:00:00Z")
  expect(screen.getByText("No publication URL was recorded.")).toBeInTheDocument()
  expect(screen.getByText("Verified on the public account")).toBeInTheDocument()
  expect(screen.queryByRole("button", { name: "Mark as published" })).not.toBeInTheDocument()
  expect(packageApi.getManualPublicationPlanForRevision).toHaveBeenCalledTimes(2)
})

it("restores a cancelled record and creates a new exact-revision plan after disconnect", async () => {
  const cancelledPlan = {
    ...storedPlan,
    status: "cancelled" as const,
    updatedAt: "2026-07-13T09:00:00Z",
  }
  const replacementPlan = {
    ...storedPlan,
    id: "plan-2",
    scheduledFor: "2026-07-15T09:30:00.000Z",
    createdAt: "2026-07-13T09:05:00Z",
    updatedAt: "2026-07-13T09:05:00Z",
  }
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  vi.mocked(packageApi.getManualPublicationPlanForRevision).mockResolvedValue(cancelledPlan)
  vi.mocked(packageApi.createManualPublicationPlan).mockResolvedValue(replacementPlan)

  const first = render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)
  expect(await screen.findByText("Status: Cancelled")).toBeInTheDocument()
  first.unmount()

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByText("Status: Cancelled")).toBeInTheDocument()
  expect(screen.getByText("Cancelled plans remain in publication history and cannot be edited.")).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Scheduled time (UTC)"), { target: { value: "2026-07-15T09:30" } })
  fireEvent.click(screen.getByRole("button", { name: "Create new manual publication plan" }))

  await waitFor(() => expect(packageApi.createManualPublicationPlan).toHaveBeenCalledWith(
    baseRevision.id,
    "2026-07-15T09:30:00.000Z",
    "Asia/Tehran",
  ))
  expect(await screen.findByText(/Instagram plan plan-2 · exact revision revision-instagram/)).toBeInTheDocument()
  expect(client.getQueryData(packageQueryKeys.manualPlan("plan-2"))).toEqual(replacementPlan)
  expect(client.getQueryData(packageQueryKeys.manualPlanForRevision(baseRevision.id))).toEqual(replacementPlan)
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["calendar"] })
  expect(packageApi.getManualPublicationPlanForRevision).toHaveBeenCalledTimes(2)
})

it("reconciles a concurrent create conflict from revision-scoped persisted truth", async () => {
  const cancelledPlan = {
    ...storedPlan,
    status: "cancelled" as const,
    updatedAt: "2026-07-13T09:00:00Z",
  }
  const concurrentPlan = {
    ...storedPlan,
    id: "plan-from-other-tab",
    scheduledFor: "2026-07-15T10:00:00Z",
    createdAt: "2026-07-13T09:10:00Z",
    updatedAt: "2026-07-13T09:10:00Z",
  }
  vi.mocked(packageApi.getPlatformRevision).mockResolvedValue(baseRevision)
  vi.mocked(packageApi.getManualPublicationPlanForRevision)
    .mockResolvedValueOnce(cancelledPlan)
    .mockResolvedValueOnce(concurrentPlan)
  vi.mocked(packageApi.createManualPublicationPlan).mockRejectedValue(
    new ApiError("Conflict", 409, JSON.stringify({ detail: "Another tab created the active plan" })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  render(<QueryClientProvider client={client}><ExactRevisionReview revisionId={baseRevision.id} /></QueryClientProvider>)

  expect(await screen.findByText("Status: Cancelled")).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText("Scheduled time (UTC)"), { target: { value: "2026-07-15T09:30" } })
  fireEvent.click(screen.getByRole("button", { name: "Create new manual publication plan" }))

  expect(await screen.findByText(/Instagram plan plan-from-other-tab · exact revision revision-instagram/)).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("Another tab created the active plan")
  expect(client.getQueryData(packageQueryKeys.manualPlan("plan-from-other-tab"))).toEqual(concurrentPlan)
  expect(client.getQueryData(packageQueryKeys.manualPlanForRevision(baseRevision.id))).toEqual(concurrentPlan)
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["calendar"] })
  expect(packageApi.getManualPublicationPlanForRevision).toHaveBeenCalledTimes(2)
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
