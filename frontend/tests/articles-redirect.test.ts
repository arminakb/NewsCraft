const redirect = vi.hoisted(() => vi.fn())

vi.mock("next/navigation", () => ({ redirect }))

import ArticlesRedirectPage from "@/app/articles/page"

describe("legacy Articles route", () => {
  beforeEach(() => redirect.mockReset())

  it("redirects to the canonical Feed route and preserves repeated query parameters", async () => {
    await ArticlesRedirectPage({
      searchParams: Promise.resolve({
        language: ["en", "fa"],
        topic: "AI",
        sort: "score",
      }),
    })

    expect(redirect).toHaveBeenCalledWith("/feed?language=en&language=fa&topic=AI&sort=score")
  })

  it("redirects a queryless request to Feed", async () => {
    await ArticlesRedirectPage({ searchParams: Promise.resolve({}) })

    expect(redirect).toHaveBeenCalledWith("/feed")
  })
})
