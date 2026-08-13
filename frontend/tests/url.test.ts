import { safeHttpUrl } from "@/lib/url"

describe("safeHttpUrl", () => {
  it("allows only absolute HTTP and HTTPS URLs", () => {
    expect(safeHttpUrl("https://example.com/article")).toBe("https://example.com/article")
    expect(safeHttpUrl("http://example.com/article")).toBe("http://example.com/article")
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull()
    expect(safeHttpUrl("data:text/html,unsafe")).toBeNull()
    expect(safeHttpUrl("/relative-source")).toBeNull()
    expect(safeHttpUrl("not a url")).toBeNull()
  })

  it("rejects embedded credentials", () => {
    expect(safeHttpUrl("https://user:secret@example.com/article")).toBeNull()
    expect(safeHttpUrl("https://user@example.com/article")).toBeNull()
  })

  it("treats absent values as unsafe", () => {
    expect(safeHttpUrl(null)).toBeNull()
    expect(safeHttpUrl(undefined)).toBeNull()
    expect(safeHttpUrl("")).toBeNull()
  })
})
