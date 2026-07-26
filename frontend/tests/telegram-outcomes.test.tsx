import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"

import { getTelegramPublicationOutcomes } from "@/features/automations/telegram-api"
import { fetchReconciliationCases } from "@/features/operations/api"
import { TelegramOutcomes } from "@/features/today/telegram-outcomes"
import { operationsQueryKeys } from "@/lib/query-keys"

vi.mock("@/features/automations/telegram-api", () => ({ getTelegramPublicationOutcomes: vi.fn() }))
vi.mock("@/features/operations/api", () => ({ fetchReconciliationCases: vi.fn() }))
vi.mock("@/features/operations/reconciliation-panel", () => ({
  ReconciliationPanel: ({
    onResolved,
    value,
  }: {
    onResolved?: (result: unknown) => void | Promise<void>
    value: { ambiguous_at: string | null; publish_job_id: string }
  }) => {
    const [mountedGeneration] = useState(value.ambiguous_at)
    return (
      <button
        data-testid="safe-reconciliation-panel"
        onClick={() => void onResolved?.({ reconciliationStatus: "requeued" })}
        type="button"
      >
        Safe reconciliation for {value.publish_job_id}; mounted {mountedGeneration}
      </button>
    )
  },
}))

const publishJobId = "11111111-1111-4111-8111-111111111111"
const reconciliationCase = {
  publish_job_id: publishJobId,
  ambiguous_operation_key: "telegram:publish:0",
  ambiguous_at: "2026-07-13T08:00:00Z",
  operations: [
    {
      operation_key: "telegram:publish:0",
      attempt_count: 1,
    },
  ],
}

it("discovers every authoritative case even when a newer draft supersedes its revision", async () => {
  vi.mocked(getTelegramPublicationOutcomes).mockResolvedValue([
    {
      revisionId: "21111111-1111-4111-8111-111111111111",
      platformVariantId: "31111111-1111-4111-8111-111111111111",
      revisionNumber: 1,
      approvalState: "approved",
      routeId: null,
      dispatchId: null,
      publishJobId,
      publishStatus: "reconciliation_required",
      publication: null,
    },
    {
      revisionId: "41111111-1111-4111-8111-111111111111",
      platformVariantId: "31111111-1111-4111-8111-111111111111",
      revisionNumber: 2,
      approvalState: "pending_review",
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
  await waitFor(() => expect(getTelegramPublicationOutcomes).toHaveBeenCalledTimes(2))

  client.setQueryData(operationsQueryKeys.reconciliations, [
    {
      ...reconciliationCase,
      ambiguous_at: "2026-07-13T08:10:00Z",
      operations: [{ ...reconciliationCase.operations[0], attempt_count: 2 }],
    },
  ])
  expect(await screen.findByText(/mounted 2026-07-13T08:10:00Z/)).toBeInTheDocument()
})
