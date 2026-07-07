"use client"

import { useQuery } from "@tanstack/react-query"

import { MediaStrip } from "@/components/dashboard/media-strip"
import { OperationsPageFrame } from "@/components/dashboard/pages/operations-page-frame"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
      <Card className="rounded-md py-0" size="sm">
        <CardHeader className="border-b px-3 py-3">
          <CardTitle className="text-base">Media metadata</CardTitle>
        </CardHeader>
        <CardContent className="px-0">
          <div className="overflow-x-auto">
            <div className="min-w-[820px]">
              <div className="grid grid-cols-[minmax(220px,1fr)_110px_90px_100px_130px_90px_90px] border-b px-3 py-2 text-xs text-muted-foreground">
                <span>Asset</span>
                <span>Fetch</span>
                <span>Quality</span>
                <span>Confidence</span>
                <span>Source type</span>
                <span>Role</span>
                <span>Primary</span>
              </div>
              <div className="divide-y">
                {mediaQuery.data.map((asset) => (
                  <div key={asset.id} className="grid grid-cols-[minmax(220px,1fr)_110px_90px_100px_130px_90px_90px] items-center gap-3 px-3 py-3 text-sm">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{asset.fileName}</div>
                      <div className="text-xs text-muted-foreground">{asset.dimensions} - {asset.size}</div>
                    </div>
                    <Badge variant="outline" className="h-6 rounded-md">{asset.fetchStatus ?? "unknown"}</Badge>
                    <span>{asset.quality ?? "unknown"}</span>
                    <span className="tabular-nums">{asset.confidence ?? "-"}</span>
                    <span>{asset.sourceType ?? "-"}</span>
                    <span>{asset.role ?? "-"}</span>
                    <span>{asset.isPrimary ? "Primary" : asset.isPrimaryCandidate ? "Candidate" : "-"}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </OperationsPageFrame>
  )
}
