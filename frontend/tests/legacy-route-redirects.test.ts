import nextConfig from "@/next.config"
import CalendarRoute from "@/app/calendar/page"
import DiagnosticsRoute from "@/app/diagnostics/page"
import JobsRoute from "@/app/jobs/page"
import RetentionRoute from "@/app/settings/retention/page"
import { redirect } from "next/navigation"

vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
}))

describe("legacy frontend routes", () => {
  it("redirects removed sections to surviving workflows", async () => {
    const redirects = await nextConfig.redirects?.()

    expect(redirects).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "/inbox", destination: "/" }),
      expect.objectContaining({ source: "/runs", destination: "/sources" }),
    ]))
  })

  it("redirects old Retention bookmarks to the integrated Settings section", () => {
    RetentionRoute()

    expect(redirect).toHaveBeenCalledWith("/settings?section=retention")
  })

  it("redirects old Calendar bookmarks to Date & Time settings", () => {
    CalendarRoute()

    expect(redirect).toHaveBeenCalledWith("/settings?section=date-time")
  })

  it("redirects Jobs bookmarks and preserves deep-link state", async () => {
    await JobsRoute({ searchParams: Promise.resolve({ status: "attention", job: "job-1" }) })

    expect(redirect).toHaveBeenCalledWith("/operations?view=jobs&status=attention&job=job-1")
  })

  it("redirects Diagnostics bookmarks to its unified view", async () => {
    await DiagnosticsRoute({ searchParams: Promise.resolve({}) })

    expect(redirect).toHaveBeenCalledWith("/operations?view=diagnostics")
  })
})
