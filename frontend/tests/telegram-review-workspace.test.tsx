import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import { NoticeProvider } from "@/components/providers/notice-provider"
import { getAutomationControl } from "@/features/control/api"
import {
  approveTelegramDraft,
  editTelegramDraft,
  getTelegramDestinations,
  getTelegramDraft,
  getTelegramPublishJob,
  getTelegramRoute,
  publishTelegramDraft,
  rejectTelegramDraft,
} from "@/features/automations/telegram-api"
import { TelegramReviewWorkspace } from "@/features/review/telegram-review-workspace"

const push = vi.fn()

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))
vi.mock("@/features/control/api", () => ({ getAutomationControl: vi.fn() }))
vi.mock("@/features/automations/telegram-api", () => ({
  getTelegramDraft: vi.fn(),
  getTelegramPublishJob: vi.fn(),
  getTelegramRoute: vi.fn(),
  getTelegramDestinations: vi.fn(),
  editTelegramDraft: vi.fn(),
  approveTelegramDraft: vi.fn(),
  rejectTelegramDraft: vi.fn(),
  publishTelegramDraft: vi.fn(),
}))

const revision = {
  id: "11111111-1111-4111-8111-111111111111",
  platformVariantId: "21111111-1111-4111-8111-111111111111",
  parentRevisionId: null,
  revisionNumber: 1,
  content: {
    body: "متن بازنویسی",
    parseMode: "HTML",
    buttons: [],
    sourceItemId: "31111111-1111-4111-8111-111111111111",
    sourceUrl: "https://t.me/source/91",
    mediaPolicy: "preserve",
    mediaAssetIds: ["41111111-1111-4111-8111-111111111111"],
    direction: "rtl",
    dryRun: false,
  },
  contentHash: "a".repeat(64),
  evidenceMap: [],
  evidence: [{
    evidenceSnapshotId: "51111111-1111-4111-8111-111111111111",
    evidenceKey: "telegram.source.91",
    sourceUrl: "https://t.me/source/91",
    contentText: "متن دقیق منبع",
    contentSha256: "b".repeat(64),
  }],
  media: [{
    id: "41111111-1111-4111-8111-111111111111",
    kind: "image",
    mimeType: "image/jpeg",
    fetchStatus: "downloaded",
    checksumSha256: "c".repeat(64),
    previewUrl: "/api/backend/telegram/drafts/11111111-1111-4111-8111-111111111111/media/41111111-1111-4111-8111-111111111111",
  }],
  validationResults: [],
  approvalState: "pending_review",
  approvalNote: null,
  approvedAt: null,
  createdBy: "automation",
  createdAt: "2026-07-12T08:00:00Z",
  routeId: "61111111-1111-4111-8111-111111111111",
  dispatchId: "71111111-1111-4111-8111-111111111111",
  publishJobId: null,
  publishStatus: null,
  publication: null,
} as const

describe("TelegramReviewWorkspace", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getTelegramDraft).mockResolvedValue(revision as never)
    vi.mocked(getTelegramRoute).mockResolvedValue({
      id: revision.routeId,
      destinationId: "81111111-1111-4111-8111-111111111111",
      pausedAt: null,
      enabled: true,
    } as never)
    vi.mocked(getTelegramDestinations).mockResolvedValue([{ id: "81111111-1111-4111-8111-111111111111", healthStatus: "healthy", enabled: true, configured: true }] as never)
    vi.mocked(getAutomationControl).mockResolvedValue({ globalPause: false, dryRun: false, pauseReason: null, pausedAt: null, updatedAt: "2026-07-12T08:00:00Z" })
    vi.mocked(editTelegramDraft).mockResolvedValue({ ...revision, id: "91111111-1111-4111-8111-111111111111", revisionNumber: 2 } as never)
    vi.mocked(approveTelegramDraft).mockResolvedValue({ ...revision, approvalState: "approved" } as never)
    vi.mocked(rejectTelegramDraft).mockResolvedValue({ ...revision, approvalState: "rejected" } as never)
    vi.mocked(publishTelegramDraft).mockResolvedValue({ revision, job: { publishJobId: "a1111111-1111-4111-8111-111111111111", workflowJobId: "b1111111-1111-4111-8111-111111111111", status: "queued" } } as never)
    vi.mocked(getTelegramPublishJob).mockResolvedValue({
      publishJobId: "a1111111-1111-4111-8111-111111111111",
      status: "dispatching",
      receipts: [{ operationIndex: 0, status: "dispatching" }],
      publication: null,
    } as never)
  })

  it("shows exact evidence and album beside an RTL exact-revision editor", async () => {
    renderWorkspace()

    expect(await screen.findByText("متن دقیق منبع")).toHaveAttribute("dir", "auto")
    expect(screen.getByText("image · image/jpeg")).toBeInTheDocument()
    expect(screen.getByRole("img", { name: "Captured image 1" })).toHaveAttribute("src", revision.media[0].previewUrl)
    const editor = screen.getByRole("textbox", { name: "Telegram body" })
    expect(editor).toHaveAttribute("dir", "rtl")
    expect(editor).toHaveValue("متن بازنویسی")
    expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
  })

  it("does not request a preview for media that is not downloaded and checksum verified", async () => {
    vi.mocked(getTelegramDraft).mockResolvedValue({
      ...revision,
      media: [{ ...revision.media[0], fetchStatus: "failed", checksumSha256: null }],
    } as never)
    renderWorkspace()

    expect(await screen.findByText("Captured media preview unavailable")).toBeInTheDocument()
    expect(screen.queryByRole("img", { name: "Captured image 1" })).not.toBeInTheDocument()
  })

  it("saves a complete child revision and navigates to that exact child", async () => {
    renderWorkspace()
    const editor = await screen.findByRole("textbox", { name: "Telegram body" })
    fireEvent.change(editor, { target: { value: "متن ویرایش شده" } })
    expect(screen.getByRole("button", { name: "Approve exact revision" })).toBeDisabled()
    expect(screen.getByText(/Save editor changes as a new revision/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Save as new revision" }))

    await waitFor(() => expect(editTelegramDraft).toHaveBeenCalledWith(revision.id, {
      content: { body: "متن ویرایش شده", parse_mode: "HTML", buttons: [] },
      media_asset_ids: revision.content.mediaAssetIds,
    }))
    expect(push).toHaveBeenCalledWith("/review/91111111-1111-4111-8111-111111111111")
  })

  it("approves by exact hash and reports the durable publish job", async () => {
    vi.mocked(getTelegramDraft)
      .mockResolvedValueOnce(revision as never)
      .mockResolvedValue({ ...revision, approvalState: "approved" } as never)
    renderWorkspace()
    await screen.findByRole("textbox", { name: "Telegram body" })
    fireEvent.click(screen.getByRole("button", { name: "Approve exact revision" }))
    await waitFor(() => expect(approveTelegramDraft).toHaveBeenCalledWith(revision.id, revision.contentHash))
    await waitFor(() => expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeEnabled())
    fireEvent.click(screen.getByRole("button", { name: "Publish exact revision" }))
    expect(await screen.findByText(/Queued.*a1111111/i)).toBeInTheDocument()
    expect(await screen.findByText("Durable status: dispatching")).toBeInTheDocument()
    expect(getTelegramPublishJob).toHaveBeenCalledWith("a1111111-1111-4111-8111-111111111111")
  })

  it.each([
    ["global pause", { control: { globalPause: true }, route: {}, destination: {}, content: {} }],
    ["global dry run", { control: { dryRun: true }, route: {}, destination: {}, content: {} }],
    ["route paused", { control: {}, route: { pausedAt: "2026-07-12T09:00:00Z" }, destination: {}, content: {} }],
    ["destination unhealthy", { control: {}, route: {}, destination: { healthStatus: "unhealthy" }, content: {} }],
    ["destination unavailable", { control: {}, route: {}, destination: { configured: false }, content: {} }],
    ["manual media replacement", { control: {}, route: {}, destination: {}, content: { mediaPolicy: "replace_manually" } }],
  ])("shows the independent %s blocker", async (label, state) => {
    vi.mocked(getAutomationControl).mockResolvedValue({ globalPause: false, dryRun: false, pauseReason: null, pausedAt: null, updatedAt: "2026-07-12T08:00:00Z", ...state.control } as never)
    vi.mocked(getTelegramRoute).mockResolvedValue({ id: revision.routeId, destinationId: "81111111-1111-4111-8111-111111111111", pausedAt: null, enabled: true, ...state.route } as never)
    vi.mocked(getTelegramDestinations).mockResolvedValue([{ id: "81111111-1111-4111-8111-111111111111", healthStatus: "healthy", enabled: true, configured: true, ...state.destination }] as never)
    vi.mocked(getTelegramDraft).mockResolvedValue({ ...revision, approvalState: "approved", content: { ...revision.content, ...state.content } } as never)

    renderWorkspace()

    expect(await screen.findByText(new RegExp(label, "i"))).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Publish exact revision" })).toBeDisabled()
  })
})

function workspaceTree() {
  return (
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NoticeProvider><TelegramReviewWorkspace revisionId={revision.id} /></NoticeProvider>
    </QueryClientProvider>
  )
}

function renderWorkspace() {
  return render(workspaceTree())
}
