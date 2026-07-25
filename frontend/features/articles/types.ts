export type ArticleSort = "newest" | "score"

export type ArticleCoverageState = "ungrouped" | "incomplete" | "complete"

export type ArticleFacetValue = {
  value: string
  count: number
}

export type ArticleSourceFacet = {
  id: string
  name: string
  platform: string
  count: number
}

export type ArticleFacets = {
  languages: ArticleFacetValue[]
  topics: ArticleFacetValue[]
  contentTypes: ArticleFacetValue[]
  sources: ArticleSourceFacet[]
  coverage: Array<{ value: ArticleCoverageState; count: number }>
}

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

export type ArticleSource = {
  id: string | null
  name: string | null
  platform: string | null
  homepageUrl: string | null
}

export type ArticleImage = {
  id: string
  url: string
  kind: "image"
  width: number | null
  height: number | null
  altText: string | null
  fetchStatus: string
}

export type ArticleStorySummary = {
  id: string
  title: string
  editorialState: string
  complete: boolean
  score: number
}

export type ArticleSummary = {
  id: string
  title: string | null
  summary: string | null
  excerpt: string | null
  source: ArticleSource
  canonicalUrl: string | null
  publishedAt: string | null
  sortAt: string
  displayAt: string
  dateBasis: "published" | "collected"
  score: number
  contentType: string
  topic: string | null
  domain: string | null
  language: string | null
  direction: "ltr" | "rtl" | null
  coverage: {
    state: ArticleCoverageState
    stories: ArticleStorySummary[]
  }
  articleReadiness: { ready: boolean }
  image: ArticleImage | null
  hasImage: boolean
  marked: false
  markedAt: null
  saved: boolean
  savedCollectionIds: string[]
}

export type ArticlePage = {
  items: ArticleSummary[]
  nextCursor: string | null
  resultCount: number
}

export type ArticleCollection = {
  id: string
  name: string
  articleCount: number
  createdAt: string
  updatedAt: string
}
