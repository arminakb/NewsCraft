import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import {
  getTelegramDestinations,
  getTelegramDispatches,
  getTelegramPublicationContext,
  getTelegramPublishJob,
  getTelegramRoute,
  publishTelegramDraft,
} from "@/features/automations/telegram-api"
import { getAutomationControl } from "@/features/control/api"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"

vi.mock("@/features/control/api", () => ({ getAutomationControl: vi.fn() }))
vi.mock("@/features/automations/telegram-api", () => ({
  getTelegramPublicationContext: vi.fn(),
  getTelegramDispatches: vi.fn(),
  getTelegramPublishJob: vi.fn(),
  getTelegramRoute: vi.fn(),
  getTelegramDestinations: vi.fn(),
  publishTelegramDraft: vi.fn(),
}))

const revision = {
  id: "11111111-1111-4111-8111-111111111111",
  variantId: "21111111-1111-4111-8111-111111111111",
  contentPackId: "31111111-1111-4111-8111-111111111111",
  storyId: "41111111-1111-4111-8111-111111111111",
  parentRevisionId: null,
  generationAttemptId: null,
  revisionNumber: 1,
  platform: "telegram",
  payload: {
    platform: "telegram",
    body: "متن بازنویسی",
    parseMode: "HTML",
    buttons: [],
    sourceItemId: null,
    sourceUrl: "https://t.me/source/91",
    mediaPolicy: "preserve",
    mediaAssetIds: [],
    direction: "rtl",
    dryRun: false,
  },
  contentHash: "a".repeat(64),
  evidenceCitations: [],
  manualChecklist: [],
  validationResults: [],
  validation: [],
  mediaPlan: [],
  sourceMedia: [],
  approvalState: "approved",
  approvalNote: null,
  approvedAt: "2026-07-12T08:00:00Z",
  createdBy: "automation",
  origin: "automation",
  providerProfile: null,
  resolvedModel: null,
  promptVersion: null,
  createdAt: "2026-07-12T08:00:00Z",
} as const

const context = {
  id: revision.id,
  routeId: "61111111-1111-4111-8111-111111111111",
  dispatchId: "71111111-1111-4111-8111-111111111111",
  publishJobId: null,
}

describe("TelegramReviewWorkspace", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getTelegramPublicationContext).mockResolvedValue(context as never)
    vi.mocked(getTelegramDispatches).mockResolvedValue([{
      id: context.dispatchId,
      storyId: revision.storyId,
      status: "generated",
      errorCode: null,
    }] as never)
    vi.mocked(getTelegramRoute).mockResolvedValue({
      id: context.routeId,
      destinationId: "81111111-1111-4111-8111-111111111111",
      pausedAt: null,
      enabled: true,
    } as never)
    vi.mocked(getTelegramDestinations).mockResolvedValue([{
      id: "81111111-1111-4111-8111-111111111111",
      healthStatus: "healthy",
      enabled: true,
      configured: true,
    }] as never)
    vi.mocked(getAutomationControl).mockResolvedValue({
      globalPause: false,
      dryRun: false,
      pauseReason: null,
      pausedAt: null,
      updatedAt: "2026-07-12T08:00:00Z",
    })
    vi.mocked(publishTelegramDraft).mockResolvedValue({
      revision: context,
      job: {
        publishJobId: "a1111111-1111-4111-8111-111111111111",
        workflowJobId: "b1111111-1111-4111-8111-111111111111",
        status: "queued",
      },
    } as never)
    vi.mocked(getTelegramPublishJob).mockResolvedValue({
      publishJobId: "a1111111-1111-4111-8111-111111111111",
      status: "dispatching",
      receipts: [{ operationIndex: 0, status: "dispatching" }],
      publication: null,
    } as never)
  })

  it("publishes only the approved exact hash and reports the durable job", async () => {
    renderWorkspace()
    const publish = await screen.findByRole("button", { name: "Publish exact revision" })
    await waitFor(() => expect(publish).toBeEnabled())
    fireEvent.click(publish)

    await waitFor(() => expect(publishTelegramDraft).toHaveBeenCalledWith(revision.id, revision.contentHash))
    expect(await screen.findByText(/Queued.*a1111111/i)).toBeInTheDocument()
    expect(await screen.findByText("Durable status: dispatching")).toBeInTheDocument()
  })

  it("does not duplicate edit and approval controls", async () => {
    renderWorkspace()
    expect(await screen.findByText("Telegram publication handoff")).toBeInTheDocument()
    expect(screen.queryByRole("textbox", { name: "Telegram body" })).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Approve exact revision" })).not.toBeInTheDocument()
  })

  it("requires canonical approval before publish", async () => {
    renderWorkspace({ ...revision, approvalState: "pending_review", approvedAt: null })
    expect(await screen.findByText("Approve this exact revision before publishing.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
  })

  it.each([
    ["global pause", { control: { globalPause: true }, route: {}, destination: {}, payload: {} }],
    ["global dry run", { control: { dryRun: true }, route: {}, destination: {}, payload: {} }],
    ["route paused", { control: {}, route: { pausedAt: "2026-07-12T09:00:00Z" }, destination: {}, payload: {} }],
    ["destination unhealthy", { control: {}, route: {}, destination: { healthStatus: "unhealthy" }, payload: {} }],
    ["destination unavailable", { control: {}, route: {}, destination: { configured: false }, payload: {} }],
    ["manual media replacement", { control: {}, route: {}, destination: {}, payload: { mediaPolicy: "replace_manually" } }],
  ])("shows the independent %s blocker", async (label, state) => {
    vi.mocked(getAutomationControl).mockResolvedValue({
      globalPause: false,
      dryRun: false,
      pauseReason: null,
      pausedAt: null,
      updatedAt: "2026-07-12T08:00:00Z",
      ...state.control,
    } as never)
    vi.mocked(getTelegramRoute).mockResolvedValue({
      id: context.routeId,
      destinationId: "81111111-1111-4111-8111-111111111111",
      pausedAt: null,
      enabled: true,
      ...state.route,
    } as never)
    vi.mocked(getTelegramDestinations).mockResolvedValue([{
      id: "81111111-1111-4111-8111-111111111111",
      healthStatus: "healthy",
      enabled: true,
      configured: true,
      ...state.destination,
    }] as never)

    renderWorkspace({ ...revision, payload: { ...revision.payload, ...state.payload } })

    expect(await screen.findByText(new RegExp(label, "i"))).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
  })

  it("fails closed when the expected dispatch is unavailable", async () => {
    vi.mocked(getTelegramDispatches).mockResolvedValue([])
    renderWorkspace()
    expect(await screen.findByText(/Expected dispatch is unavailable/i)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
  })
})

function renderWorkspace(value: typeof revision | Record<string, unknown> = revision) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoticeProvider><TelegramReviewWorkspace revision={value as never} /></NoticeProvider>
    </QueryClientProvider>,
  )
}
