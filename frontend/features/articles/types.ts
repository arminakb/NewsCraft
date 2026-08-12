import type { components } from "@/lib/api/generated"
import type { Camelized } from "@/lib/camelize"

type Schemas = components["schemas"]

export type ArticleSort = "newest" | "score"

export type ArticleCoverageState = Schemas["ArticleCoverageOut"]["state"]
export type ArticleFacetValue = Camelized<Schemas["ArticleFacetValueOut"]>
export type ArticleSourceFacet = Camelized<Schemas["ArticleSourceFacetOut"]>
export type ArticleFacets = Camelized<Schemas["ArticleFacetsOut"]>

export type ArticleFilters = {
  languages: string[]
  topics: string[]
  contentTypes: string[]
  sourceIds: string[]
  coverage: ArticleCoverageState[]
  hasImage: boolean | null
  scoreMin: number | null
  scoreMax: number | null
  dateFrom: string | null
  dateTo: string | null
}

export type ArticleImage = Camelized<Schemas["ArticleImageOut"]>
export type ArticleSummary = Camelized<Schemas["ArticleSummaryOut"]>
export type ArticleDetail = Camelized<Schemas["ArticleDetailOut"]>
export type ArticlePage = Camelized<Schemas["ArticleListOut"]>
export type ArticleCollection = Camelized<Schemas["ArticleCollectionOut"]>
export type FeedSummary = Camelized<Schemas["FeedSummaryOut"]>
export type FeedClearResult = Camelized<Schemas["FeedClearOut"]>
