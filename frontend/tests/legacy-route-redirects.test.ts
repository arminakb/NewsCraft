import nextConfig from "@/next.config"

describe("legacy frontend routes", () => {
  it("redirects removed sections to surviving workflows", async () => {
    const redirects = await nextConfig.redirects?.()

    expect(redirects).toEqual(expect.arrayContaining([
      expect.objectContaining({ source: "/inbox", destination: "/" }),
      expect.objectContaining({ source: "/runs", destination: "/sources" }),
    ]))
  })
})
