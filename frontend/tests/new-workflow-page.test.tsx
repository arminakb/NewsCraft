import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"

import { NewWorkflowPage } from "@/features/automations/new-workflow-page"
import * as api from "@/features/automations/automation-api"
import { queryKeys } from "@/lib/query-keys"

const push = vi.fn()
const searchParams = new URLSearchParams()

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => searchParams,
}))

vi.mock("@/features/automations/automation-api", () => ({
  createAutomation: vi.fn(),
}))

describe("NewWorkflowPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    searchParams.delete("name")
  })

  it("invalidates Automations list cache before navigating after creation", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const listKey = queryKeys.automations({ limit: 50 })
    queryClient.setQueryData(listKey, { items: [], nextCursor: null })
    const events: string[] = []
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")
      .mockImplementation(async (...args) => {
        events.push("invalidate")
        return QueryClient.prototype.invalidateQueries.apply(queryClient, args)
      })
    push.mockImplementation(() => events.push("push"))
    vi.mocked(api.createAutomation).mockResolvedValue({ id: "automation-2" } as never)

    render(
      <QueryClientProvider client={queryClient}>
        <NewWorkflowPage />
      </QueryClientProvider>,
    )

    await waitFor(() => expect(push).toHaveBeenCalledWith("/automations/automation-2"))
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["automations"] })
    expect(events).toEqual(["invalidate", "push"])
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryData(listKey)).toEqual({ items: [], nextCursor: null })
  })

  it("keeps creation error handling and skips cache invalidation on failure", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")
    vi.mocked(api.createAutomation).mockRejectedValue(new Error("creation failed"))

    render(
      <QueryClientProvider client={queryClient}>
        <NewWorkflowPage />
      </QueryClientProvider>,
    )

    expect(await screen.findByRole("alert")).toHaveTextContent("creation failed")
    expect(invalidateQueries).not.toHaveBeenCalled()
    expect(push).not.toHaveBeenCalled()
  })
})
