import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"

import { getTelegramDrafts } from "@/features/automations/telegram-api"
import { TelegramDraftList } from "@/features/drafts/telegram-draft-list"

vi.mock("@/features/automations/telegram-api", () => ({ getTelegramDrafts: vi.fn() }))

it("renders persisted Telegram draft copy through its stored direction boundary", async () => {
  vi.mocked(getTelegramDrafts).mockResolvedValue([{
    id: "11111111-1111-4111-8111-111111111111",
    platformVariantId: "21111111-1111-4111-8111-111111111111",
    parentRevisionId: null,
    revisionNumber: 1,
    content: {
      body: "متن پیش نویس",
      parseMode: "HTML",
      buttons: [],
      sourceItemId: null,
      sourceUrl: null,
      mediaPolicy: "preserve",
      mediaAssetIds: [],
      direction: "rtl",
      dryRun: false,
    },
    contentHash: "a".repeat(64),
    evidenceMap: [],
    evidence: [],
    media: [],
    validationResults: [],
    approvalState: "pending_review",
    approvalNote: null,
    approvedAt: null,
    createdBy: "automation",
    createdAt: "2026-07-13T08:00:00Z",
    routeId: null,
    dispatchId: null,
    publishJobId: null,
    publishStatus: null,
    publication: null,
  }] as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><TelegramDraftList /></QueryClientProvider>)

  const copy = await screen.findByText("متن پیش نویس")
  expect(copy).toHaveAttribute("data-testid", "direction-boundary")
  expect(copy).toHaveAttribute("dir", "rtl")
  expect(copy).not.toHaveAttribute("lang")
})
