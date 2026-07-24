const redirect = vi.hoisted(() => vi.fn())

vi.mock("next/navigation", () => ({ redirect }))

import ContentRedirectPage from "@/app/content/[[...legacyPath]]/page"
import InboxRedirectPage from "@/app/inbox/[[...legacyPath]]/page"
import LibraryRedirectPage from "@/app/library/[[...legacyPath]]/page"
import MediaRedirectPage from "@/app/media/[[...legacyPath]]/page"

const legacyRoutes = [
  ["Inbox", InboxRedirectPage],
  ["Content", ContentRedirectPage],
  ["Library", LibraryRedirectPage],
  ["Media", MediaRedirectPage],
] as const

describe("legacy frontend routes", () => {
  beforeEach(() => redirect.mockReset())

  it.each(legacyRoutes)("redirects %s and nested paths to Feed", async (_label, page) => {
    await page({ searchParams: Promise.resolve({}) })

    expect(redirect).toHaveBeenCalledWith("/feed")
  })

  it.each(legacyRoutes)("preserves %s query parameters", async (_label, page) => {
    await page({
      searchParams: Promise.resolve({ language: ["en", "fa"], topic: "AI", sort: "score" }),
    })

    expect(redirect).toHaveBeenCalledWith("/feed?language=en&language=fa&topic=AI&sort=score")
  })
})
