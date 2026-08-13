import { act, render, screen } from "@testing-library/react"

import FlipClock from "@/components/ui/flip-clock"

describe("FlipClock", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-08-08T12:34:56"))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("renders local time and updates once per second", () => {
    render(<FlipClock />)

    const clock = screen.getByRole("timer")
    expect(clock).toHaveAttribute("data-time", "12:34:56")
    expect(clock).toHaveAttribute("aria-label", "Local time 12:34:56")

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(clock).toHaveAttribute("data-time", "12:34:57")
    expect(clock).toHaveAttribute("aria-label", "Local time 12:34:57")
  })

  it("rolls minutes using the browser's local time", () => {
    vi.setSystemTime(new Date("2026-08-08T12:34:59"))
    render(<FlipClock />)

    const clock = screen.getByRole("timer")
    expect(clock).toHaveAttribute("data-time", "12:34:59")

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(clock).toHaveAttribute("data-time", "12:35:00")
  })
})
