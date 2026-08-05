import { safeArticleUrl, selectEditorialContent } from "@/features/articles/article-detail-dialog"
import type { ArticleDetail } from "@/features/articles/types"

describe("article detail content selection", () => {
  it("prefers complete normalized content over excerpt and summary", () => {
    expect(selectEditorialContent(detail({
      contentText: "Complete normalized body",
      contentOrigin: "source_provided",
      excerpt: "Short excerpt",
      summary: "Short summary",
    }))).toEqual({
      kind: "body",
      label: "Source-provided content",
      text: "Complete normalized body",
    })
  })

  it("labels excerpt-only content without claiming it is a full article", () => {
    expect(selectEditorialContent(detail({
      contentText: "Publisher excerpt only",
      contentOrigin: "source_excerpt",
    }))).toEqual({
      kind: "excerpt",
      label: "Source excerpt",
      text: "Publisher excerpt only",
    })
  })

  it("falls back through excerpt and summary to an unavailable state", () => {
    expect(selectEditorialContent(detail({
      contentText: null,
      contentOrigin: "unavailable",
      excerpt: "Fallback excerpt",
      summary: "Fallback summary",
    })).label).toBe("Source excerpt")
    expect(selectEditorialContent(detail({
      contentText: null,
      contentOrigin: "unavailable",
      excerpt: null,
      summary: null,
    }))).toEqual({ kind: "unavailable", label: "Content unavailable", text: null })
  })

  it("allows only absolute HTTP and HTTPS source URLs", () => {
    expect(safeArticleUrl("https://example.com/article")).toBe("https://example.com/article")
    expect(safeArticleUrl("http://example.com/article")).toBe("http://example.com/article")
    expect(safeArticleUrl("javascript:alert(1)")).toBeNull()
    expect(safeArticleUrl("data:text/html,unsafe")).toBeNull()
    expect(safeArticleUrl("/relative-source")).toBeNull()
  })
})

function detail(overrides: Partial<ArticleDetail>): ArticleDetail {
  return {
    contentText: null,
    contentOrigin: "unavailable",
    excerpt: null,
    summary: null,
    ...overrides,
  } as ArticleDetail
}
