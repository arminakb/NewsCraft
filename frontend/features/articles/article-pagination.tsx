"use client"

import * as React from "react"

import {
  Pagination,
  PaginationEllipsis,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from "@/components/ui/pagination"

type PageItem = number | "..."

export function ArticlePagination({
  currentPage,
  totalPages,
  disabled = false,
  onPageChange,
}: {
  currentPage: number
  totalPages: number
  disabled?: boolean
  onPageChange: (page: number) => void
}) {
  const isMobile = useMediaQuery("(max-width: 640px)")
  const isTablet = useMediaQuery("(max-width: 768px)")
  const delta = isMobile ? 1 : isTablet ? 1 : 2
  const visiblePages = getVisiblePages(totalPages, currentPage, delta)

  if (totalPages <= 1) return null

  return (
    <div className="w-full overflow-x-auto" data-testid="feed-pagination">
      <Pagination aria-label="Feed pagination" className="flex-wrap min-w-fit">
        <PaginationPrevious
          aria-label="Previous page"
          disabled={disabled || currentPage === 1}
          onClick={() => onPageChange(Math.max(1, currentPage - 1))}
          size={isMobile ? "sm" : "default"}
        >
          {isMobile ? "Prev" : "Previous"}
        </PaginationPrevious>

        {visiblePages.map((page, index) => page === "..." ? (
          <PaginationEllipsis key={`ellipsis-${index}`} />
        ) : (
          <PaginationItem
            aria-label={`Go to page ${page}`}
            disabled={disabled || page === currentPage}
            isActive={page === currentPage}
            key={page}
            onClick={() => onPageChange(page)}
            size={isMobile ? "sm" : "default"}
          >
            {page}
          </PaginationItem>
        ))}

        <PaginationNext
          aria-label="Next page"
          disabled={disabled || currentPage === totalPages}
          onClick={() => onPageChange(Math.min(totalPages, currentPage + 1))}
          size={isMobile ? "sm" : "default"}
        >
          Next
        </PaginationNext>
      </Pagination>
    </div>
  )
}

export function getVisiblePages(totalPages: number, currentPage: number, delta: number): PageItem[] {
  if (totalPages <= 7) return Array.from({ length: totalPages }, (_, index) => index + 1)

  const rangeWithDots: PageItem[] = [1]
  let startPage = Math.max(2, currentPage - delta)
  let endPage = Math.min(totalPages - 1, currentPage + delta)

  if (currentPage === 1) {
    endPage = Math.min(totalPages - 1, 1 + (delta * 2))
  } else if (currentPage === totalPages) {
    startPage = Math.max(2, totalPages - (delta * 2))
  } else {
    startPage = Math.max(2, Math.min(startPage, currentPage))
    endPage = Math.min(totalPages - 1, Math.max(endPage, currentPage))
  }

  if (startPage > 2) rangeWithDots.push("...")
  for (let page = startPage; page <= endPage; page += 1) {
    if (page !== 1 && page !== totalPages) rangeWithDots.push(page)
  }
  if (endPage < totalPages - 1) rangeWithDots.push("...")
  if (totalPages > 1) rangeWithDots.push(totalPages)
  return rangeWithDots
}

function useMediaQuery(query: string) {
  const [matches, setMatches] = React.useState(false)

  React.useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const media = window.matchMedia(query)
    const update = () => setMatches(media.matches)
    update()
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", update)
      return () => media.removeEventListener("change", update)
    }
    media.addListener(update)
    return () => media.removeListener(update)
  }, [query])

  return matches
}
