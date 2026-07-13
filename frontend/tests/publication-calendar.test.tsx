import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"

import { getPublicationCalendar } from "@/features/calendar/api"
import { PublicationCalendar } from "@/features/calendar/publication-calendar"
import type { CalendarEvent } from "@/features/calendar/types"

const revisionIds = {
  telegram: "11111111-1111-4111-8111-111111111111",
  instagram: "22222222-2222-4222-8222-222222222222",
  blog: "33333333-3333-4333-8333-333333333333",
}

const telegramEvent: CalendarEvent = {
  id: "telegram:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  kind: "telegram_publish",
  platform: "telegram",
  revisionId: revisionIds.telegram,
  title: "Daily update",
  startsAt: "2026-07-13T09:00:00+03:30",
  status: "scheduled",
  actionUrl: `/review/${revisionIds.telegram}`,
}

const instagramEvent: CalendarEvent = {
  id: "manual:bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  kind: "manual_publication",
  platform: "instagram",
  revisionId: revisionIds.instagram,
  title: "Daily update",
  startsAt: "2026-07-13T10:00:00+03:30",
  status: "ready",
  actionUrl: `/review/${revisionIds.instagram}`,
}

describe("PublicationCalendar", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("shows Telegram and manual events in the operator timezone with server-provided exact links", () => {
    renderCalendar({ events: [telegramEvent, instagramEvent], timezone: "Asia/Tehran" })

    expect(screen.getByRole("heading", { name: "July 2026" })).toBeInTheDocument()
    expect(screen.getByText("Telegram: Daily update")).toBeInTheDocument()
    expect(screen.getByText("Instagram: Daily update")).toBeInTheDocument()
    expect(screen.getByText("09:00")).toBeInTheDocument()
    expect(screen.getByText("10:00")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: `Open Telegram event: Daily update (${telegramEvent.id})` })).toHaveAttribute(
      "href",
      `/review/${revisionIds.telegram}`,
    )
    expect(screen.getByRole("link", { name: `Open Instagram event: Daily update (${instagramEvent.id})` })).toHaveAttribute(
      "href",
      `/review/${revisionIds.instagram}`,
    )
  })

  it("switches to a chronological list and filters only by persisted platform and status", () => {
    const cancelledBlog: CalendarEvent = {
      id: "manual:cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      kind: "manual_publication",
      platform: "blog",
      revisionId: revisionIds.blog,
      title: "Earlier analysis",
      startsAt: "2026-07-12T08:00:00+03:30",
      status: "cancelled",
      actionUrl: `/review/${revisionIds.blog}`,
    }
    renderCalendar({ events: [instagramEvent, telegramEvent, cancelledBlog], timezone: "Asia/Tehran" })

    fireEvent.click(screen.getByRole("button", { name: "Chronological list view" }))
    const list = screen.getByRole("list", { name: "Chronological publication events" })
    expect(within(list).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      expect.stringContaining("Blog: Earlier analysis"),
      expect.stringContaining("Telegram: Daily update"),
      expect.stringContaining("Instagram: Daily update"),
    ])

    fireEvent.change(screen.getByLabelText("Platform"), { target: { value: "instagram" } })
    expect(screen.getByText("Instagram: Daily update")).toBeInTheDocument()
    expect(screen.queryByText("Telegram: Daily update")).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "cancelled" } })
    expect(screen.getByText("No publication events match these filters.")).toBeInTheDocument()
    expect(screen.queryByText("Blog: Earlier analysis")).not.toBeInTheDocument()
  })

  it("requests inclusive-start/exclusive-end UTC month windows and navigates without inventing events", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(calendarResponse([]))
    renderCalendar({ timezone: "Asia/Tehran" })

    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1))
    expectCalendarRequest(fetchSpy.mock.calls[0][0], {
      start: "2026-06-30T20:30:00.000Z",
      end: "2026-07-31T20:30:00.000Z",
      timezone: "Asia/Tehran",
    })
    expect(await screen.findByText("No publication events in this calendar window.")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Next month" }))
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expectCalendarRequest(fetchSpy.mock.calls[1][0], {
      start: "2026-07-31T20:30:00.000Z",
      end: "2026-08-31T20:30:00.000Z",
      timezone: "Asia/Tehran",
    })
    expect(screen.getByRole("heading", { name: "August 2026" })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "Previous month" }))
    await waitFor(() => expect(screen.getByRole("heading", { name: "July 2026" })).toBeInTheDocument())
    expect(screen.getByRole("button", { name: "Today" })).toBeInTheDocument()
  })

  it("re-queries the same operator month using the selected timezone boundaries", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(calendarResponse([]))
    renderCalendar({ timezone: "Asia/Tehran" })
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(1))

    fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "UTC" } })
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expectCalendarRequest(fetchSpy.mock.calls[1][0], {
      start: "2026-07-01T00:00:00.000Z",
      end: "2026-08-01T00:00:00.000Z",
      timezone: "UTC",
    })
  })

  it("returns to the current month in the selected operator timezone", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2027-01-15T18:00:00Z"))
    try {
      renderCalendar({ events: [], timezone: "Asia/Tehran" })
      expect(screen.getByRole("heading", { name: "July 2026" })).toBeInTheDocument()

      fireEvent.click(screen.getByRole("button", { name: "Today" }))

      expect(screen.getByRole("heading", { name: "January 2027" })).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it("renders distinct loading, error with retry, and empty states", async () => {
    const pending = new Promise<Response>(() => undefined)
    vi.spyOn(globalThis, "fetch").mockReturnValueOnce(pending)
    const first = renderCalendar({ timezone: "Asia/Tehran" })
    expect(screen.getByRole("status", { name: "Loading publication calendar" })).toBeInTheDocument()
    first.unmount()
    vi.restoreAllMocks()

    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 503, statusText: "Calendar unavailable" }))
      .mockResolvedValueOnce(calendarResponse([]))
    renderCalendar({ timezone: "Asia/Tehran" })
    expect(await screen.findByRole("alert")).toHaveTextContent("Calendar unavailable")
    fireEvent.click(screen.getByRole("button", { name: "Retry calendar" }))
    expect(await screen.findByText("No publication events in this calendar window.")).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })
})

describe("calendar API truth boundary", () => {
  beforeEach(() => vi.restoreAllMocks())

  it("strictly decodes server events and rejects unsafe action links", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(calendarResponse([calendarWire(telegramEvent)]))
      .mockResolvedValueOnce(calendarResponse([{ ...calendarWire(telegramEvent), action_url: "https://evil.example/review" }]))

    await expect(getPublicationCalendar({
      start: "2026-06-30T20:30:00.000Z",
      end: "2026-07-31T20:30:00.000Z",
      timezone: "Asia/Tehran",
    })).resolves.toEqual({ events: [telegramEvent], timezone: "Asia/Tehran" })
    await expect(getPublicationCalendar({
      start: "2026-06-30T20:30:00.000Z",
      end: "2026-07-31T20:30:00.000Z",
      timezone: "Asia/Tehran",
    })).rejects.toThrow("Invalid calendar event action URL")
    expect(fetchSpy).toHaveBeenCalledTimes(2)
  })

  it("rejects response timezone drift and unknown projection fields", async () => {
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(calendarResponse([], "UTC"))
      .mockResolvedValueOnce(calendarResponse([{ ...calendarWire(instagramEvent), inferred_live_state: "published" }]))
    const request = {
      start: "2026-06-30T20:30:00.000Z",
      end: "2026-07-31T20:30:00.000Z",
      timezone: "Asia/Tehran",
    }

    await expect(getPublicationCalendar(request)).rejects.toThrow("Calendar response timezone mismatch")
    await expect(getPublicationCalendar(request)).rejects.toThrow("Invalid calendar event")
  })
})

function renderCalendar({
  events,
  timezone,
}: {
  events?: CalendarEvent[]
  timezone: string
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <PublicationCalendar
        events={events}
        timezone={timezone}
        initialDate={new Date("2026-07-13T08:00:00Z")}
      />
    </QueryClientProvider>,
  )
}

function calendarWire(event: CalendarEvent) {
  return {
    id: event.id,
    kind: event.kind,
    platform: event.platform,
    revision_id: event.revisionId,
    title: event.title,
    starts_at: event.startsAt,
    status: event.status,
    action_url: event.actionUrl,
  }
}

function calendarResponse(events: unknown[], timezone = "Asia/Tehran") {
  return new Response(JSON.stringify({ items: events, timezone }), {
    status: 200,
    headers: { "content-type": "application/json" },
  })
}

function expectCalendarRequest(
  input: string | URL | Request,
  expected: { start: string; end: string; timezone: string },
) {
  const url = new URL(String(input), "https://newscraft.test")
  expect(url.pathname).toBe("/api/backend/calendar")
  expect(url.searchParams.get("start")).toBe(expected.start)
  expect(url.searchParams.get("end")).toBe(expected.end)
  expect(url.searchParams.get("timezone")).toBe(expected.timezone)
}
