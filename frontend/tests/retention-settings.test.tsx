import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import RetentionPage from "@/app/settings/retention/page"
import {
  createRetentionPreview,
  enqueueRetentionRun,
  fetchRetentionPolicy,
  updateRetentionPolicy,
} from "@/features/operations/api"
import type {
  RetentionPolicy,
  RetentionPreview,
  RetentionRunAccepted,
} from "@/features/operations/types"
import { RetentionSettings } from "@/features/settings/retention-settings"
import { ApiError } from "@/lib/http"

vi.mock("@/features/operations/api", () => ({
  createRetentionPreview: vi.fn(),
  enqueueRetentionRun: vi.fn(),
  fetchRetentionPolicy: vi.fn(),
  updateRetentionPolicy: vi.fn(),
}))

const policy: RetentionPolicy = {
  id: "global",
  raw_payload_days: 30,
  completed_job_days: 90,
  attempt_metadata_days: 90,
  export_artifact_days: 14,
  unreferenced_media_days: 30,
  created_at: "2026-07-11T07:00:00Z",
  updated_at: "2026-07-11T08:00:00Z",
}

const preview: RetentionPreview = {
  run_id: "11111111-1111-4111-8111-111111111111",
  preview_token: "a".repeat(64),
  schema_revision: "0009_operational_retention",
  policy: {
    raw_payload_days: 30,
    completed_job_days: 90,
    attempt_metadata_days: 90,
    export_artifact_days: 14,
    unreferenced_media_days: 30,
  },
  candidates: [
    {
      category: "export_artifact",
      record_type: "media_asset",
      record_id: "99999999-9999-4999-8999-999999999999",
      operation: "expire",
      occurred_at: "2026-06-01T08:00:00Z",
      byte_length: 125_829_120,
    },
  ],
  counts: {
    raw_payload: {
      count: 3,
      byte_length: null,
      oldest_at: "2026-05-01T08:00:00Z",
      newest_at: "2026-05-03T08:00:00Z",
    },
    export_artifact: {
      count: 14,
      byte_length: 125_829_120,
      oldest_at: "2026-05-01T08:00:00Z",
      newest_at: "2026-06-01T08:00:00Z",
    },
  },
  previewed_at: "2026-07-11T08:00:00Z",
  preview_expires_at: "2026-07-11T09:00:00Z",
}

const accepted: RetentionRunAccepted = {
  job_id: "22222222-2222-4222-8222-222222222222",
  status: "queued",
  deduplicated: false,
}

describe("RetentionSettings", () => {
  beforeEach(() => vi.resetAllMocks())

  it("renders five bounded policy fields and truthful nullable preview totals", () => {
    render(<RetentionSettings policy={policy} preview={preview} />)

    expect(screen.getByLabelText("Raw payload retention days")).toHaveAttribute("min", "7")
    expect(screen.getByLabelText("Raw payload retention days")).toHaveAttribute("max", "3650")
    expect(screen.getByLabelText("Completed job retention days")).toHaveAttribute("min", "14")
    expect(screen.getByLabelText("Attempt metadata retention days")).toHaveAttribute("min", "14")
    expect(screen.getByLabelText("Export artifact retention days")).toHaveAttribute("min", "1")
    expect(screen.getByLabelText("Unreferenced media retention days")).toHaveAttribute("min", "7")
    expect(screen.getAllByRole("spinbutton")).toHaveLength(5)

    expect(screen.getByText("14 export artifacts · 120 MB")).toBeInTheDocument()
    expect(screen.getByText("3 raw payloads · size unknown")).toBeInTheDocument()
    expect(screen.queryByText(/0 KB/)).not.toBeInTheDocument()
    expect(screen.queryByText("99999999-9999-4999-8999-999999999999")).not.toBeInTheDocument()

    const cleanup = screen.getByRole("button", { name: "Run cleanup" })
    expect(cleanup).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA " },
    })
    expect(cleanup).toBeDisabled()
    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA" },
    })
    expect(cleanup).toBeEnabled()
  })

  it("invalidates preview and typed confirmation on edits and saves before allowing a fresh preview", async () => {
    vi.mocked(updateRetentionPolicy).mockResolvedValue({
      ...policy,
      export_artifact_days: 21,
      updated_at: "2026-07-11T08:30:00Z",
    })
    vi.mocked(createRetentionPreview).mockResolvedValue({
      ...preview,
      preview_token: "b".repeat(64),
      policy: { ...preview.policy, export_artifact_days: 21 },
    })
    render(<RetentionSettings policy={policy} preview={preview} />)

    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA" },
    })
    fireEvent.change(screen.getByLabelText("Export artifact retention days"), {
      target: { value: "21" },
    })

    expect(screen.queryByText("14 export artifacts · 120 MB")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Type DELETE PREVIEWED DATA")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Preview cleanup" })).toBeDisabled()

    fireEvent.click(screen.getByRole("button", { name: "Save retention policy" }))
    await waitFor(() => {
      expect(updateRetentionPolicy).toHaveBeenCalledWith({
        raw_payload_days: 30,
        completed_job_days: 90,
        attempt_metadata_days: 90,
        export_artifact_days: 21,
        unreferenced_media_days: 30,
      })
    })
    expect(await screen.findByRole("status")).toHaveTextContent("Retention policy saved")
    expect(screen.getByRole("button", { name: "Preview cleanup" })).toBeEnabled()

    fireEvent.click(screen.getByRole("button", { name: "Preview cleanup" }))
    expect(await screen.findByText("14 export artifacts · 120 MB")).toBeInTheDocument()
    expect(createRetentionPreview).toHaveBeenCalledWith()
    expect(screen.getByLabelText("Type DELETE PREVIEWED DATA")).toHaveValue("")
    expect(screen.getByRole("button", { name: "Run cleanup" })).toBeDisabled()
  })

  it("synchronizes clean fields to refetched server policy and invalidates stale preview truth", async () => {
    vi.mocked(createRetentionPreview).mockResolvedValue(preview)
    const view = render(<RetentionSettings policy={policy} />)
    fireEvent.click(screen.getByRole("button", { name: "Preview cleanup" }))
    expect(await screen.findByText("14 export artifacts · 120 MB")).toBeInTheDocument()
    expect(screen.getByRole("status")).toHaveTextContent("Cleanup preview is ready")
    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA" },
    })

    view.rerender(
      <RetentionSettings
        policy={{
          ...policy,
          raw_payload_days: 45,
          updated_at: "2026-07-11T08:45:00Z",
        }}
      />,
    )

    await waitFor(() => expect(screen.getByLabelText("Raw payload retention days")).toHaveValue(45))
    expect(screen.queryByText("14 export artifacts · 120 MB")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Type DELETE PREVIEWED DATA")).not.toBeInTheDocument()
    expect(screen.queryByText(/Cleanup preview is ready/)).not.toBeInTheDocument()
  })

  it("rejects a preview whose server policy snapshot differs from the saved policy", async () => {
    vi.mocked(createRetentionPreview).mockResolvedValue({
      ...preview,
      policy: { ...preview.policy, raw_payload_days: 45 },
    })
    render(<RetentionSettings policy={policy} />)

    fireEvent.click(screen.getByRole("button", { name: "Preview cleanup" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("Retention policy changed while previewing. Create a fresh preview.")
    expect(screen.queryByText("14 export artifacts · 120 MB")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Type DELETE PREVIEWED DATA")).not.toBeInTheDocument()
  })

  it("cannot reinstall an old preview after policy truth changes in flight", async () => {
    const deferred = createDeferred<RetentionPreview>()
    vi.mocked(createRetentionPreview).mockReturnValue(deferred.promise)
    const view = render(<RetentionSettings policy={policy} />)

    fireEvent.click(screen.getByRole("button", { name: "Preview cleanup" }))
    view.rerender(
      <RetentionSettings
        policy={{
          ...policy,
          raw_payload_days: 45,
          updated_at: "2026-07-11T08:45:00Z",
        }}
      />,
    )
    deferred.resolve(preview)

    await waitFor(() => expect(screen.queryByLabelText("Creating cleanup preview")).not.toBeInTheDocument())
    expect(screen.queryByText("14 export artifacts · 120 MB")).not.toBeInTheDocument()
    expect(screen.queryByLabelText("Type DELETE PREVIEWED DATA")).not.toBeInTheDocument()
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Retention policy changed while previewing. Create a fresh preview.",
    )
  })

  it("updates the retention policy query cache after a successful save", async () => {
    const saved = {
      ...policy,
      export_artifact_days: 21,
      updated_at: "2026-07-11T08:30:00Z",
    }
    vi.mocked(fetchRetentionPolicy).mockResolvedValue(policy)
    vi.mocked(updateRetentionPolicy).mockResolvedValue(saved)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <RetentionPage />
      </QueryClientProvider>,
    )

    await screen.findByLabelText("Export artifact retention days")
    fireEvent.change(screen.getByLabelText("Export artifact retention days"), {
      target: { value: "21" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Save retention policy" }))

    await waitFor(() => {
      expect(queryClient.getQueryData(["operations", "retention-policy"])).toEqual(saved)
    })
  })

  it("submits only the opaque token and clears preview and confirmation for every run", async () => {
    vi.mocked(enqueueRetentionRun).mockResolvedValue(accepted)
    render(<RetentionSettings policy={policy} preview={preview} />)

    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Run cleanup" }))

    await waitFor(() => expect(enqueueRetentionRun).toHaveBeenCalledWith(preview.preview_token))
    expect(JSON.stringify(vi.mocked(enqueueRetentionRun).mock.calls)).not.toContain(
      "99999999-9999-4999-8999-999999999999",
    )
    expect(screen.queryByLabelText("Type DELETE PREVIEWED DATA")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Run cleanup" })).not.toBeInTheDocument()
    expect(await screen.findByRole("status")).toHaveTextContent(accepted.job_id)
  })

  it("clears a conflicting preview and requires a fresh preview after a 409", async () => {
    vi.mocked(enqueueRetentionRun).mockRejectedValue(
      new ApiError(
        "Conflict",
        409,
        JSON.stringify({ detail: "retention preview has expired; create a new preview" }),
      ),
    )
    render(<RetentionSettings policy={policy} preview={preview} />)

    fireEvent.change(screen.getByLabelText("Type DELETE PREVIEWED DATA"), {
      target: { value: "DELETE PREVIEWED DATA" },
    })
    fireEvent.click(screen.getByRole("button", { name: "Run cleanup" }))

    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("Preview expired or changed. Create a fresh preview before cleanup.")
    expect(alert).toHaveAttribute("dir", "auto")
    expect(screen.queryByText("14 export artifacts · 120 MB")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Run cleanup" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Preview cleanup" })).toBeEnabled()
  })

  it("shows accessible loading and RTL-safe retryable errors on the retention page", async () => {
    const deferred = createDeferred<RetentionPolicy>()
    vi.mocked(fetchRetentionPolicy).mockReturnValueOnce(deferred.promise)
    const pending = renderRetentionPage()
    expect(screen.getByRole("status", { name: "Loading retention settings" })).toBeInTheDocument()
    pending.unmount()

    vi.mocked(fetchRetentionPolicy).mockRejectedValueOnce(new Error("سیاست نگهداری در دسترس نیست"))
    renderRetentionPage()
    const alert = await screen.findByRole("alert")
    expect(alert).toHaveTextContent("سیاست نگهداری در دسترس نیست")
    expect(alert).toHaveAttribute("dir", "auto")
    expect(screen.getByRole("button", { name: "Retry retention settings" })).toBeEnabled()
  })
})

function renderRetentionPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <RetentionPage />
    </QueryClientProvider>,
  )
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
