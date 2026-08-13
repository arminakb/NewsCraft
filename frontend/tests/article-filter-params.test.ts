import { appendArticleFilterParams } from "@/features/articles/filter-params"
import { EMPTY_ARTICLE_FILTERS, readArticleState, writeArticleState } from "@/features/articles/filter-state"
import type { ArticleFilters } from "@/features/articles/types"

const sourceId = "22222222-2222-4222-8222-222222222222"

function filters(): ArticleFilters {
  return {
    ...EMPTY_ARTICLE_FILTERS,
    languages: ["en"],
    topics: ["AI", "Tech"],
    contentTypes: ["news"],
    sourceIds: [sourceId],
    coverage: ["complete"],
    hasImage: true,
    scoreMin: 20,
    scoreMax: 80,
    dateFrom: "2026-07-01",
    dateTo: "2026-07-21",
  }
}

describe("Article filter params", () => {
  it("keeps bare calendar dates for the browser URL", () => {
    const params = new URLSearchParams()
    appendArticleFilterParams(params, filters(), { mode: "url" })

    expect(params.toString()).toBe(
      `language=en&topic=AI&topic=Tech&content_type=news&source_id=${sourceId}`
      + "&coverage=complete&has_image=true&score_min=20&score_max=80"
      + "&date_from=2026-07-01&date_to=2026-07-21",
    )
  })

  it("converts calendar dates into display-timezone instants for the backend", () => {
    const params = new URLSearchParams()
    appendArticleFilterParams(params, filters(), { mode: "request", timezone: "Asia/Tehran" })

    expect(params.get("date_from")).toBe("2026-06-30T20:30:00.000Z")
    expect(params.get("date_to")).toBe("2026-07-21T20:30:00.000Z")
    expect(params.getAll("topic")).toEqual(["AI", "Tech"])
  })

  it("emits nothing for absent filters", () => {
    const params = new URLSearchParams()
    appendArticleFilterParams(params, undefined, { mode: "url" })
    appendArticleFilterParams(params, EMPTY_ARTICLE_FILTERS, { mode: "request", timezone: "UTC" })

    expect(params.toString()).toBe("")
  })

  it("round-trips URL state through the single reader", () => {
    const written = writeArticleState(new URLSearchParams("page=3&cursor=abc"), "score", filters())

    expect(written.get("page")).toBeNull()
    expect(written.get("cursor")).toBeNull()
    expect(readArticleState(written)).toEqual({ sort: "score", query: "", filters: filters() })
  })
})
