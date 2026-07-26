import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { submitReconciliationDecision } from "@/features/operations/api"
import { ReconciliationPanel } from "@/features/operations/reconciliation-panel"
import type {
  ReconciliationCase,
  ReconciliationDecisionResult,
} from "@/features/operations/types"

vi.mock("@/features/operations/api", () => ({
  submitReconciliationDecision: vi.fn(),
}))

const pendingCase: ReconciliationCase = {
  publish_job_id: "11111111-1111-4111-8111-111111111111",
  status: "pending",
  publish_status: "reconciliation_required",
  workflow_job_id: "22222222-2222-4222-8222-222222222222",
  platform_variant_revision_id: "33333333-3333-4333-8333-333333333333",
  destination: {
    id: "44444444-4444-4444-8444-444444444444",
    name: "کانال خبر",
    target_ref: "@newscraft",
  },
  operations: [
    {
      operation_index: 1,
      operation_key: "telegram:publish:1",
      method: "sendMessage",
      request_hash: "sha256:second",
      status: "pending",
      attempt_count: 0,
      remote_message_ids: [],
      sent_at: null,
    },
    {
      operation_index: 0,
      operation_key: "telegram:publish:0",
      method: "sendMessage",
      request_hash: "sha256:first",
      status: "ambiguous",
      attempt_count: 1,
      remote_message_ids: [],
      sent_at: "2026-07-11T08:00:00Z",
    },
  ],
  ambiguous_operation_key: "telegram:publish:0",
  ambiguous_at: "2026-07-11T08:00:05Z",
  ambiguity_reason: "پاسخ تلگرام پس از ارسال ذخیره نشد",
}

const publishableCase: ReconciliationCase = {
  ...pendingCase,
  operations: pendingCase.operations.map((operation) =>
    operation.operation_key === pendingCase.ambiguous_operation_key
      ? operation
      : { ...operation, status: "succeeded" },
  ),
}

describe("ReconciliationPanel", () => {
  beforeEach(() => vi.resetAllMocks())

  it("renders the durable verification evidence in operation order with RTL-safe prose", () => {
    render(<ReconciliationPanel value={pendingCase} />)

    expect(screen.getByText("کانال خبر").closest("[dir]"))
      .toHaveAttribute("dir", "auto")
    expect(screen.getByText("پاسخ تلگرام پس از ارسال ذخیره نشد").closest("[dir]"))
      .toHaveAttribute("dir", "auto")
    expect(screen.getAllByText("@newscraft")).toHaveLength(2)
    expect(screen.getByText("Jul 11, 2026, 11:30 AM")).toBeInTheDocument()

    const operations = screen.getAllByTestId("reconciliation-operation")
    expect(within(operations[0]).getByText("telegram:publish:0")).toBeInTheDocument()
    expect(within(operations[0]).getByText("sha256:first")).toBeInTheDocument()
    expect(within(operations[1]).getByText("telegram:publish:1")).toBeInTheDocument()
    expect(within(operations[1]).getByText("sha256:second")).toBeInTheDocument()
    expect(screen.getByText("Verify in Telegram before choosing an outcome")).toBeInTheDocument()
    expect(screen.getByText(/Compare the persisted operation key and request hash/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Confirm published" })).toBeDisabled()
    expect(screen.getByText(/published confirmation is unavailable until every other operation has succeeded/i))
      .toBeInTheDocument()
  })

  it("selects not-published without mutation and requires a five-character verification note", async () => {
    const deferred = createDeferred<ReconciliationDecisionResult>()
    vi.mocked(submitReconciliationDecision).mockReturnValue(deferred.promise)
    render(<ReconciliationPanel value={pendingCase} />)

    expect(screen.queryByRole("button", { name: "Confirm and queue retry" })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "Confirm not published" }))

    expect(submitReconciliationDecision).not.toHaveBeenCalled()
    const submit = screen.getByRole("button", { name: "Confirm and queue retry" })
    expect(submit).toBeDisabled()

    fireEvent.change(screen.getByLabelText("Verification note"), { target: { value: "four" } })
    expect(submit).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Verification note"), {
      target: { value: "Checked the destination channel" },
    })
    expect(submit).toBeEnabled()

    fireEvent.click(submit)
    expect(submitReconciliationDecision).toHaveBeenCalledWith(pendingCase.publish_job_id, {
      outcome: "not_published",
      operatorNote: "Checked the destination channel",
    })
    expect(screen.getByRole("button", { name: "Queuing retry…" })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Confirm published" })).toBeDisabled()

    deferred.resolve(requeuedResult)
    expect(await screen.findByRole("status")).toHaveTextContent("Publication was queued for a safe retry")
  })

  it("validates one positive unique remote ID for a single-message operation", async () => {
    vi.mocked(submitReconciliationDecision).mockResolvedValue(publishedResult)
    render(<ReconciliationPanel value={publishableCase} />)

    fireEvent.click(screen.getByRole("button", { name: "Confirm published" }))
    fireEvent.change(screen.getByLabelText("Verification note"), {
      target: { value: "Matched the Telegram message" },
    })
    const remoteIds = screen.getByLabelText("Verified remote message IDs")
    const submit = screen.getByRole("button", { name: "Confirm published message" })

    fireEvent.change(remoteIds, { target: { value: "0" } })
    expect(submit).toBeDisabled()
    expect(screen.getByRole("alert")).toHaveTextContent("positive, unique integers")

    fireEvent.change(remoteIds, { target: { value: "9201, 9201" } })
    expect(submit).toBeDisabled()
    fireEvent.change(remoteIds, { target: { value: "9201, 9202" } })
    expect(submit).toBeDisabled()
    expect(screen.getByRole("alert")).toHaveTextContent("exactly one remote message ID")

    fireEvent.change(remoteIds, { target: { value: "9201" } })
    fireEvent.change(screen.getByLabelText("Telegram permalink (optional)"), {
      target: { value: "https://t.me/newscraft/9201" },
    })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    await waitFor(() => {
      expect(submitReconciliationDecision).toHaveBeenCalledWith(pendingCase.publish_job_id, {
        outcome: "published",
        remoteMessageIds: [9201],
        permalink: "https://t.me/newscraft/9201",
        operatorNote: "Matched the Telegram message",
      })
    })
    expect(await screen.findByRole("status")).toHaveTextContent("Publication was confirmed")
  })

  it("allows multiple positive unique IDs only for sendMediaGroup and reports submission errors", async () => {
    vi.mocked(submitReconciliationDecision).mockRejectedValue(new Error("Decision could not be saved"))
    const mediaGroupCase: ReconciliationCase = {
      ...publishableCase,
      operations: publishableCase.operations.map((operation) =>
        operation.operation_key === publishableCase.ambiguous_operation_key
          ? { ...operation, method: "sendMediaGroup" }
          : operation,
      ),
    }
    render(<ReconciliationPanel value={mediaGroupCase} />)

    fireEvent.click(screen.getByRole("button", { name: "Confirm published" }))
    fireEvent.change(screen.getByLabelText("Verified remote message IDs"), {
      target: { value: "9201" },
    })
    fireEvent.change(screen.getByLabelText("Verification note"), {
      target: { value: "Verified the album in Telegram" },
    })
    expect(screen.getByRole("button", { name: "Confirm published messages" })).toBeDisabled()
    expect(screen.getByRole("alert")).toHaveTextContent("at least two remote message IDs")

    fireEvent.change(screen.getByLabelText("Verified remote message IDs"), {
      target: { value: "9201, 9202" },
    })
    const submit = screen.getByRole("button", { name: "Confirm published messages" })
    expect(submit).toBeEnabled()
    fireEvent.click(submit)

    expect(await screen.findByRole("alert")).toHaveTextContent("Decision could not be saved")
    expect(submit).toBeEnabled()
  })

  it("keeps form labels unique when multiple reconciliation cases are listed", () => {
    render(
      <>
        <ReconciliationPanel value={pendingCase} />
        <ReconciliationPanel
          value={{
            ...pendingCase,
            publish_job_id: "66666666-6666-4666-8666-666666666666",
            destination: { ...pendingCase.destination, target_ref: "@newscraft_archive" },
          }}
        />
      </>,
    )

    const panels = screen.getAllByRole("region", { name: /Telegram reconciliation for/ })
    for (const panel of panels) {
      fireEvent.click(within(panel).getByRole("button", { name: "Confirm published" }))
    }
    const controlIds = Array.from(document.querySelectorAll("input[id], textarea[id]"))
      .map((control) => control.id)
    expect(new Set(controlIds).size).toBe(controlIds.length)
  })
})

const requeuedResult: ReconciliationDecisionResult = {
  publishJobId: pendingCase.publish_job_id,
  reconciliationStatus: "requeued",
  job: {
    job_id: pendingCase.workflow_job_id!,
    status: "queued",
    deduplicated: false,
  },
  receipts: [],
}

const publishedResult: ReconciliationDecisionResult = {
  id: "55555555-5555-4555-8555-555555555555",
  publishJobId: pendingCase.publish_job_id,
  destinationId: pendingCase.destination.id,
  platformVariantRevisionId: pendingCase.platform_variant_revision_id,
  remoteMessageIds: [9201],
  permalink: "https://t.me/newscraft/9201",
  payloadHash: "sha256:payload",
  publishedAt: "2026-07-11T08:10:00Z",
  reconciliationStatus: "confirmed",
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}
