import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"

import {
  getDateTimeSettings,
  updateDateTimeSettings,
} from "@/features/settings/date-time-api"
import { DateTimeSection } from "@/features/settings/date-time-section"

vi.mock("@/features/settings/date-time-api", () => ({
  getDateTimeSettings: vi.fn(),
  updateDateTimeSettings: vi.fn(),
}))

describe("DateTimeSection", () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDateTimeSettings).mockResolvedValue({
      timezone: "Asia/Tehran",
      updatedAt: "2026-07-28T11:00:00Z",
    })
  })

  it("offers a searchable combobox and rejects invalid timezone identifiers", async () => {
    renderSection()
    const input = await screen.findByRole("combobox", { name: "Application timezone" })

    expect(input).toHaveAttribute("list")
    expect(document.querySelector('option[value="America/New_York"]')).toHaveTextContent(
      "America/New_York — New York",
    )

    fireEvent.change(input, { target: { value: "Mars/Olympus" } })
    fireEvent.blur(input)
    expect(screen.getByRole("alert")).toHaveTextContent("valid IANA timezone")
    expect(screen.getByRole("button", { name: "Save timezone" })).toBeDisabled()
  })

  it("persists a valid timezone and publishes success feedback", async () => {
    vi.mocked(updateDateTimeSettings).mockResolvedValue({
      timezone: "Europe/London",
      updatedAt: "2026-07-28T11:10:00Z",
    })
    renderSection()
    const input = await screen.findByRole("combobox", { name: "Application timezone" })

    fireEvent.change(input, { target: { value: "Europe/London" } })
    fireEvent.click(screen.getByRole("button", { name: "Save timezone" }))

    await waitFor(() => expect(updateDateTimeSettings).toHaveBeenCalledWith(
      "Europe/London",
      expect.any(Object),
    ))
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Timezone saved as Europe/London — London.",
    )
    expect(input).toHaveValue("Europe/London")
  })
})

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <DateTimeSection />
    </QueryClientProvider>,
  )
}
