import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"

import { getTelegramDrafts } from "@/features/automations/telegram-api"
import { fetchReconciliationCases } from "@/features/operations/api"
import { TelegramOutcomes } from "@/features/today/telegram-outcomes"
import { operationsQueryKeys } from "@/lib/query-keys"

vi.mock("@/features/automations/telegram-api", () => ({ getTelegramDrafts: vi.fn() }))
vi.mock("@/features/operations/api", () => ({ fetchReconciliationCases: vi.fn() }))
vi.mock("@/features/operations/reconciliation-panel", () => ({
  ReconciliationPanel: ({
    onResolved,
    value,
  }: {
    onResolved?: (result: unknown) => void | Promise<void>
    value: { ambiguousAt: string | null; publishJobId: string }
  }) => {
    const [mountedGeneration] = useState(value.ambiguousAt)
    return (
      <button
        data-testid="safe-reconciliation-panel"
        onClick={() => void onResolved?.({ reconciliationStatus: "requeued" })}
        type="button"
      >
        Safe reconciliation for {value.publishJobId}; mounted {mountedGeneration}
      </button>
    )
  },
}))

const publishJobId = "11111111-1111-4111-8111-111111111111"
const reconciliationCase = {
  publishJobId,
  ambiguousOperationKey: "telegram:publish:0",
  ambiguousAt: "2026-07-13T08:00:00Z",
  operations: [
    {
      operationKey: "telegram:publish:0",
      attemptCount: 1,
    },
  ],
}

it("discovers every authoritative case even when a newer draft supersedes its revision", async () => {
  vi.mocked(getTelegramDrafts).mockResolvedValue([
    {
      id: "21111111-1111-4111-8111-111111111111",
      platformVariantId: "31111111-1111-4111-8111-111111111111",
      parentRevisionId: null,
      generationAttemptId: null,
      revisionNumber: 1,
      content: {
        body: "Ambiguous Telegram draft",
        parseMode: "HTML",
        buttons: [],
        sourceItemId: null,
        sourceUrl: null,
        mediaPolicy: "preserve",
        mediaAssetIds: [],
        direction: "ltr",
        dryRun: false,
      },
      contentHash: "a".repeat(64),
      evidenceMap: [],
      evidence: [],
      media: [],
      validationResults: [],
      approvalState: "approved",
      approvalNote: null,
      approvedAt: "2026-07-13T08:00:00Z",
      createdBy: "automation",
      createdAt: "2026-07-13T08:00:00Z",
      routeId: null,
      dispatchId: null,
      publishJobId,
      publishStatus: "reconciliation_required",
      publication: null,
    },
    {
      id: "41111111-1111-4111-8111-111111111111",
      platformVariantId: "31111111-1111-4111-8111-111111111111",
      parentRevisionId: "21111111-1111-4111-8111-111111111111",
      generationAttemptId: null,
      revisionNumber: 2,
      content: {
        body: "Newer draft revision",
        parseMode: "HTML",
        buttons: [],
        sourceItemId: null,
        sourceUrl: null,
        mediaPolicy: "preserve",
        mediaAssetIds: [],
        direction: "ltr",
        dryRun: false,
      },
      contentHash: "b".repeat(64),
      evidenceMap: [],
      evidence: [],
      media: [],
      validationResults: [],
      approvalState: "pending_review",
      approvalNote: null,
      approvedAt: null,
      createdBy: "operator",
      createdAt: "2026-07-13T08:05:00Z",
      routeId: null,
      dispatchId: null,
      publishJobId: null,
      publishStatus: null,
      publication: null,
    },
  ])
  vi.mocked(fetchReconciliationCases).mockResolvedValue([reconciliationCase] as never)

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <TelegramOutcomes />
    </QueryClientProvider>,
  )

  const panel = await screen.findByTestId("safe-reconciliation-panel")
  expect(panel).toHaveTextContent(publishJobId)
  expect(fetchReconciliationCases).toHaveBeenCalledTimes(1)

  fireEvent.click(panel)
  await waitFor(() => expect(fetchReconciliationCases).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(getTelegramDrafts).toHaveBeenCalledTimes(2))

  client.setQueryData(operationsQueryKeys.reconciliations, [
    {
      ...reconciliationCase,
      ambiguousAt: "2026-07-13T08:10:00Z",
      operations: [{ ...reconciliationCase.operations[0], attemptCount: 2 }],
    },
  ])
  expect(await screen.findByText(/mounted 2026-07-13T08:10:00Z/)).toBeInTheDocument()
})
