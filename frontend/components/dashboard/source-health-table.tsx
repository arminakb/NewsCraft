"use client"

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table"
import { ChevronRight } from "lucide-react"
import { useMemo, useState } from "react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge } from "@/components/dashboard/status-badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { SourcePlatform, SourceSummary } from "@/lib/types"

type SourceHealthTableProps = {
  sources: SourceSummary[]
  selectedSourceId: string
  onSelectSource: (sourceId: string) => void
}

const filters: { label: string; value: "all" | SourcePlatform }[] = [
  { label: "All", value: "all" },
  { label: "RSS", value: "rss" },
  { label: "Telegram", value: "telegram_public" },
]

export function SourceHealthTable({
  sources,
  selectedSourceId,
  onSelectSource,
}: SourceHealthTableProps) {
  const [filter, setFilter] = useState<"all" | SourcePlatform>("all")
  const visibleSources = filter === "all" ? sources : sources.filter((source) => source.platform === filter)
  const counts = {
    all: sources.length,
    rss: sources.filter((source) => source.platform === "rss").length,
    telegram: sources.filter((source) => source.platform === "telegram_public").length,
  }

  const columns = useMemo<ColumnDef<SourceSummary>[]>(
    () => [
      {
        header: "Type",
        cell: ({ row }) => <SourceIcon platform={row.original.platform} />,
      },
      {
        header: "Source",
        cell: ({ row }) => (
          <button
            type="button"
            className="min-w-0 text-left"
            aria-label={`Open ${row.original.name} details`}
            onClick={(event) => {
              event.stopPropagation()
              onSelectSource(row.original.id)
            }}
          >
            <div className="truncate font-medium">{row.original.name}</div>
            <div className="truncate text-xs text-muted-foreground">{row.original.url}</div>
          </button>
        ),
      },
      {
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        header: "Items (24h)",
        cell: ({ row }) => <span className="tabular-nums">{formatNumber(row.original.items24h)}</span>,
      },
      {
        header: "New (24h)",
        cell: ({ row }) => <span className="text-emerald-700 tabular-nums">{formatNumber(row.original.new24h)}</span>,
      },
      {
        header: "Failed (24h)",
        cell: ({ row }) => <span className="text-red-600 tabular-nums">{formatNumber(row.original.failed24h)}</span>,
      },
      {
        header: "Last success",
        cell: ({ row }) => row.original.lastSuccess ?? "-",
      },
      {
        header: "",
        id: "actions",
        cell: ({ row }) => (
          <button
            type="button"
            className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label={`Select ${row.original.name}`}
            onClick={(event) => {
              event.stopPropagation()
              onSelectSource(row.original.id)
            }}
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        ),
      },
    ],
    [onSelectSource]
  )

  const table = useReactTable({
    data: visibleSources,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <Card className="rounded-md py-0" size="sm">
      <CardHeader className="flex-row items-center border-b px-3 py-3">
        <CardTitle className="text-base">Source health</CardTitle>
        <div className="ml-auto flex items-center gap-2">
          <div role="tablist" aria-label="Source platform filter" className="flex items-center gap-1">
            {filters.map((item) => {
              const total = item.value === "all" ? counts.all : item.value === "rss" ? counts.rss : counts.telegram
              return (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  aria-selected={filter === item.value}
                  onClick={() => setFilter(item.value)}
                  className={cn(
                    "h-8 rounded-md border px-3 text-sm text-muted-foreground transition",
                    filter === item.value && "border-primary bg-cyan-50 text-primary"
                  )}
                >
                  {item.label} <span className="ml-1 tabular-nums">{total}</span>
                </button>
              )
            })}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-0">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id} className="h-9 whitespace-nowrap px-3 text-xs">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.length ? (
                table.getRowModel().rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-state={row.original.id === selectedSourceId ? "selected" : undefined}
                    onClick={() => onSelectSource(row.original.id)}
                    className="h-12 cursor-pointer data-[state=selected]:bg-cyan-50/50"
                  >
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className="px-3 py-2 text-sm">
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={columns.length} className="h-20 px-3 text-center text-sm text-muted-foreground">
                    No sources found
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
        <div className="flex h-9 items-center justify-end border-t px-3 text-sm text-muted-foreground">
          <span>Showing {visibleSources.length} of {counts.all}</span>
        </div>
      </CardContent>
    </Card>
  )
}
