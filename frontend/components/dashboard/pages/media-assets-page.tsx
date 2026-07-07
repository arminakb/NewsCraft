"use client"

import { useQuery } from "@tanstack/react-query"

import { MediaStrip } from "@/components/dashboard/media-strip"
import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { getMediaAssets } from "@/lib/api-client"
import { queryKeys } from "@/lib/query-keys"
import type { MediaTile } from "@/lib/types"

export function MediaAssetsPage({ initialMedia }: { initialMedia: MediaTile[] }) {
  const mediaQuery = useQuery({
    queryKey: queryKeys.media,
    queryFn: getMediaAssets,
    initialData: initialMedia,
    enabled: process.env.NODE_ENV !== "test",
  })

  return (
    <OperationsPageFrame title="Media Assets" subtitle="Inspect extracted images and downloaded media candidates.">
      <MediaStrip media={mediaQuery.data} />
    </OperationsPageFrame>
  )
}
