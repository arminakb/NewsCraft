import nextConfig from "@/next.config"
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

    expect(redirect).toHaveBeenCalledWith("/settings/content#retention")
  })
})
