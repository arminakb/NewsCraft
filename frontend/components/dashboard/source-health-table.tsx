"use client"

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table"
import { ChevronRight, Trash2 } from "lucide-react"
import { useMemo, useState } from "react"

import { SourceIcon } from "@/components/dashboard/source-icon"
import { StatusBadge } from "@/components/dashboard/status-badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import type {
  SourcePlatform,
  SourceSummary,
} from "@/features/operations/ingestion-types"

type SourceHealthTableProps = {
  sources: SourceSummary[]
  selectedSourceId: string
  onDeleteSource?: (source: SourceSummary) => void
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
  onDeleteSource,
  onSelectSource,
}: SourceHealthTableProps) {
  const [filter, setFilter] = useState<"all" | SourcePlatform>("all")
  const visibleSources = useMemo(
    () => filter === "all" ? sources : sources.filter((source) => source.platform === filter),
    [filter, sources]
  )
  const counts = {
    all: sources.length,
    rss: sources.filter((source) => source.platform === "rss").length,
    telegram: sources.filter((source) => source.platform === "telegram_public").length,
  }

  const columns = useMemo<ColumnDef<SourceSummary>[]>(
    () => [
      {
        id: "type",
        header: "Type",
        cell: ({ row }) => <SourceIcon platform={row.original.platform} />,
      },
      {
        id: "source",
        header: "Source",
        cell: ({ row }) => (
          <button
            type="button"
            className="w-full min-w-0 text-left"
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
        id: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        id: "items",
        header: "Items",
        cell: ({ row }) => <span className="tabular-nums">{formatNumber(row.original.items24h)}</span>,
      },
      {
        id: "failed",
        header: "Failed",
        cell: ({ row }) => <span className="text-red-600 tabular-nums">{formatNumber(row.original.failed24h)}</span>,
      },
      {
        id: "lastSuccess",
        header: "Last success",
        cell: ({ row }) => row.original.lastSuccess ?? "-",
      },
      {
        header: "",
        id: "actions",
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1">
            {onDeleteSource ? (
              <Button
                aria-label={`Delete ${row.original.name}`}
                className="text-red-700 hover:bg-red-50 hover:text-red-800"
                onClick={(event) => {
                  event.stopPropagation()
                  onDeleteSource(row.original)
                }}
                size="icon-sm"
                type="button"
                variant="ghost"
              >
                <Trash2 className="size-4" aria-hidden="true" />
              </Button>
            ) : null}
            <Button
              aria-label={`Select ${row.original.name}`}
              onClick={(event) => {
                event.stopPropagation()
                onSelectSource(row.original.id)
              }}
              size="icon-sm"
              type="button"
              variant="ghost"
            >
              <ChevronRight className="size-4" aria-hidden="true" />
            </Button>
          </div>
        ),
      },
    ],
    [onDeleteSource, onSelectSource]
  )

  const table = useReactTable({
    data: visibleSources,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <Card className="rounded-md py-0" size="sm">
      <CardHeader className="flex-row flex-wrap items-center gap-2 border-b px-3 py-3">
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
                  tabIndex={filter === item.value ? 0 : -1}
                  onClick={() => setFilter(item.value)}
                  className={cn(
                    "h-8 rounded-md border px-2.5 text-sm text-muted-foreground transition",
                    filter === item.value && "border-primary bg-cyan-50 text-primary dark:border-cyan-700 dark:bg-cyan-950/50 dark:text-cyan-100"
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
        <Table className="table-fixed">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={cn("h-9 whitespace-nowrap px-2 text-xs", columnClassName(header.column.id))}
                  >
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
                  className="h-12 cursor-pointer data-[state=selected]:bg-cyan-50/50 dark:data-[state=selected]:bg-cyan-950/35"
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn("overflow-hidden px-2 py-2 text-sm", columnClassName(cell.column.id))}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-20 px-2 text-center text-sm text-muted-foreground">
                  No sources found
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        <div className="flex h-9 items-center justify-end border-t px-3 text-sm text-muted-foreground">
          <span>Showing {visibleSources.length} of {counts.all}</span>
        </div>
      </CardContent>
    </Card>
  )
}

function columnClassName(columnId: string) {
  switch (columnId) {
    case "type":
      return "w-11"
    case "source":
      return "w-[38%] min-w-40"
    case "status":
      return "w-24"
    case "items":
    case "failed":
      return "w-16 text-right"
    case "lastSuccess":
      return "hidden w-28 2xl:table-cell"
    case "actions":
      return "w-20 text-right"
    default:
      return ""
  }
}
