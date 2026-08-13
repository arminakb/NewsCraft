import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { useState } from "react"

import {
  createManualPublicationPlan,
  getManualPublicationPlanForRevision,
} from "@/features/packages/api"
import { ManualPublishingChecklist } from "@/features/packages/components/manual-publishing-checklist"
import type { ManualPublicationPlan } from "@/features/packages/types"
import { packageQueryKeys } from "@/lib/query-keys"

const ids = {
  plan: "11111111-1111-4111-8111-111111111111",
  revision: "22222222-2222-4222-8222-222222222222",
  pack: "33333333-3333-4333-8333-333333333333",
  otherRevision: "44444444-4444-4444-8444-444444444444",
}

const initialChecklist = {
  copy_reviewed: false,
  citations_verified: false,
  media_and_alt_text_ready: false,
  platform_requirements_rechecked: false,
}

const plannedInstagram: ManualPublicationPlan = {
  id: ids.plan,
  platformVariantRevisionId: ids.revision,
  platform: "instagram",
  scheduledFor: "2026-07-14T08:00:00Z",
  displayTimezone: "Asia/Tehran",
  status: "planned",
  checklistState: initialChecklist,
  externalUrl: null,
  operatorNote: null,
  completedAt: null,
  createdAt: "2026-07-13T08:00:00Z",
  updatedAt: "2026-07-13T08:00:00Z",
}

beforeEach(() => vi.restoreAllMocks())

it("creates a plan for the exact approved revision, schedule, and operator timezone", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(planWire()))

  await createManualPublicationPlan(ids.revision, "2026-07-14T08:00:00Z", "Asia/Tehran")

  expect(fetchSpy).toHaveBeenCalledWith(
    "/api/backend/manual-publication-plans",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        revision_id: ids.revision,
        scheduled_for: "2026-07-14T08:00:00Z",
        display_timezone: "Asia/Tehran",
      }),
    }),
  )
})

it("rejects a plan response that drifted to a different scheduled instant", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(planWire({
    scheduled_for: "2026-07-14T09:00:00Z",
  })))

  await expect(createManualPublicationPlan(
    ids.revision,
    "2026-07-14T08:00:00Z",
    "Asia/Tehran",
  )).rejects.toThrow("Manual publication plan response identity mismatch")
})

it("resumes the latest persisted plan for the exact revision with a revision-scoped key", async () => {
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(planWire()))

  const plan = await getManualPublicationPlanForRevision(ids.revision)

  expect(plan?.id).toBe(ids.plan)
  expect(fetchSpy).toHaveBeenCalledWith(
    `/api/backend/platform-variant-revisions/${ids.revision}/manual-publication-plan`,
    undefined,
  )
  expect(packageQueryKeys.manualPlanForRevision(ids.revision)).toEqual([
    "manual-publication-plans",
    "revision",
    ids.revision,
  ])
})

it("returns null for a revision without a plan and rejects a foreign revision projection", async () => {
  vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response("Not found", { status: 404, statusText: "Not Found" }))
    .mockResolvedValueOnce(jsonResponse(planWire({
      platform_variant_revision_id: ids.otherRevision,
    })))

  await expect(getManualPublicationPlanForRevision(ids.revision)).resolves.toBeNull()
  await expect(getManualPublicationPlanForRevision(ids.revision)).rejects.toThrow(
    "Manual publication plan response identity mismatch",
  )
})

it("persists canonical checklist progress and enables manual completion only when ready", async () => {
  let checklist = { ...initialChecklist }
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
    const body = JSON.parse(String(init?.body)) as { checklist_state: Record<string, boolean> }
    checklist = { ...checklist, ...body.checklist_state }
    return jsonResponse(planWire({
      checklist_state: checklist,
      status: Object.values(checklist).every(Boolean) ? "ready" : "planned",
    }))
  })
  renderChecklist(plannedInstagram)

  const publish = screen.getByRole("button", { name: "Mark as published" })
  expect(publish).toBeDisabled()
  for (const checkbox of screen.getAllByRole("checkbox")) {
    fireEvent.click(checkbox)
    await waitFor(() => expect(checkbox).toBeChecked())
  }

  await waitFor(() => expect(publish).toBeEnabled())
  expect(fetchSpy).toHaveBeenLastCalledWith(
    `/api/backend/manual-publication-plans/${ids.plan}/checklist`,
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ checklist_state: { platform_requirements_rechecked: true } }),
    }),
  )
})

it("optimistically checks an item only after retaining a rollback snapshot", async () => {
  let resolveUpdate!: (response: Response) => void
  const update = new Promise<Response>((resolve) => { resolveUpdate = resolve })
  vi.spyOn(globalThis, "fetch").mockReturnValue(update)
  renderChecklist(plannedInstagram)

  const checkbox = screen.getByRole("checkbox", { name: "Copy reviewed" })
  fireEvent.click(checkbox)
  expect(checkbox).toBeChecked()

  await act(async () => {
    resolveUpdate(new Response("Persistence unavailable", { status: 503, statusText: "Unavailable" }))
  })

  await waitFor(() => expect(checkbox).not.toBeChecked())
  expect(screen.getByRole("alert")).toHaveTextContent("Persistence unavailable")
})

it("records publication without an external URL and invalidates durable projections", async () => {
  const ready: ManualPublicationPlan = {
    ...plannedInstagram,
    status: "ready",
    checklistState: Object.fromEntries(Object.keys(initialChecklist).map((key) => [key, true])),
  }
  const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(jsonResponse(planWire({
    checklist_state: ready.checklistState,
    status: "manual_published",
    external_url: null,
    operator_note: "Checked on the public account",
    completed_at: "2026-07-13T10:00:00Z",
  })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  renderChecklist(ready, client)

  const publish = screen.getByRole("button", { name: "Mark as published" })
  expect(publish).toBeEnabled()
  fireEvent.change(screen.getByLabelText("Operator note (optional)"), {
    target: { value: "Checked on the public account" },
  })
  expect(screen.getByLabelText("Operator note (optional)")).toHaveAttribute("data-testid", "direction-boundary")
  expect(screen.getByLabelText("Operator note (optional)")).toHaveAttribute("dir", "auto")
  expect(publish).toBeEnabled()
  fireEvent.click(publish)

  await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith(
    `/api/backend/manual-publication-plans/${ids.plan}/mark-published`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        external_url: null,
        note: "Checked on the public account",
      }),
    }),
  ))
  expect(await screen.findByRole("status")).toHaveTextContent("Manual publication recorded")
  expect(screen.getByText("Checked on the public account")).toHaveAttribute("dir", "auto")
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["manual-publication-plans", ids.plan] })
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["content-packs", ids.pack] })
})

it("reconciles a checklist 409 to the exact revision's terminal persisted plan", async () => {
  const published = planWire({
    checklist_state: Object.fromEntries(Object.keys(initialChecklist).map((key) => [key, true])),
    status: "manual_published",
    external_url: null,
    operator_note: "Completed in another tab",
    completed_at: "2026-07-13T10:00:00Z",
    updated_at: "2026-07-13T10:00:00Z",
  })
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Plan became terminal" }), { status: 409, statusText: "Conflict" }))
    .mockResolvedValueOnce(jsonResponse(published))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  renderChecklistWithParentSync(plannedInstagram, client)

  fireEvent.click(screen.getByRole("checkbox", { name: "Copy reviewed" }))

  expect(await screen.findByText("Status: Published manually")).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("Plan became terminal")
  expect(client.getQueryData(packageQueryKeys.manualPlan(ids.plan))).toMatchObject({ status: "manual_published" })
  expect(client.getQueryData(packageQueryKeys.manualPlanForRevision(ids.revision))).toMatchObject({ status: "manual_published" })
  expect(fetchSpy).toHaveBeenNthCalledWith(
    2,
    `/api/backend/platform-variant-revisions/${ids.revision}/manual-publication-plan`,
    undefined,
  )
})

it("reconciles a completion 409 without hiding the concurrent URL-less evidence", async () => {
  const ready: ManualPublicationPlan = {
    ...plannedInstagram,
    status: "ready",
    checklistState: Object.fromEntries(Object.keys(initialChecklist).map((key) => [key, true])),
  }
  const fetchSpy = vi.spyOn(globalThis, "fetch")
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Plan was already completed" }), { status: 409, statusText: "Conflict" }))
    .mockResolvedValueOnce(jsonResponse(planWire({
      checklist_state: ready.checklistState,
      status: "manual_published",
      external_url: null,
      operator_note: null,
      completed_at: "2026-07-13T10:05:00Z",
      updated_at: "2026-07-13T10:05:00Z",
    })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  renderChecklistWithParentSync(ready, client)

  fireEvent.click(screen.getByRole("button", { name: "Mark as published" }))

  expect(await screen.findByText("Status: Published manually")).toBeInTheDocument()
  expect(screen.getByRole("alert")).toHaveTextContent("Plan was already completed")
  expect(screen.getByText("No publication URL was recorded.")).toBeInTheDocument()
  expect(client.getQueryData(packageQueryKeys.manualPlanForRevision(ids.revision))).toMatchObject({
    status: "manual_published",
    externalUrl: null,
  })
  expect(fetchSpy).toHaveBeenNthCalledWith(
    2,
    `/api/backend/platform-variant-revisions/${ids.revision}/manual-publication-plan`,
    undefined,
  )
})

it("rejects unsafe publication URLs before making a request", () => {
  const ready: ManualPublicationPlan = {
    ...plannedInstagram,
    status: "ready",
    checklistState: Object.fromEntries(Object.keys(initialChecklist).map((key) => [key, true])),
  }
  const fetchSpy = vi.spyOn(globalThis, "fetch")
  renderChecklist(ready)

  fireEvent.change(screen.getByLabelText("Publication URL"), {
    target: { value: "javascript:alert(1)" },
  })

  expect(screen.getByRole("button", { name: "Mark as published" })).toBeDisabled()
  expect(screen.getByText("Enter the public HTTP or HTTPS URL.")).toBeInTheDocument()
  expect(fetchSpy).not.toHaveBeenCalled()
})

function renderChecklist(
  plan: ManualPublicationPlan,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  return render(
    <QueryClientProvider client={client}>
      <ManualPublishingChecklist plan={plan} contentPackId={ids.pack} />
    </QueryClientProvider>,
  )
}

function renderChecklistWithParentSync(
  initialPlan: ManualPublicationPlan,
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  function Harness() {
    const [plan, setPlan] = useState(initialPlan)
    return <ManualPublishingChecklist plan={plan} contentPackId={ids.pack} onPlanChange={setPlan} />
  }

  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  )
}

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  })
}

function planWire(overrides: Record<string, unknown> = {}) {
  return {
    id: ids.plan,
    platform_variant_revision_id: ids.revision,
    platform: "instagram",
    scheduled_for: "2026-07-14T08:00:00Z",
    display_timezone: "Asia/Tehran",
    status: "planned",
    checklist_state: initialChecklist,
    external_url: null,
    operator_note: null,
    completed_at: null,
    created_at: "2026-07-13T08:00:00Z",
    updated_at: "2026-07-13T08:00:00Z",
    ...overrides,
  }
}
