"use client"

import { Clock3, Play, Radio } from "lucide-react"

import { Button } from "@/components/ui/button"

export function TopStatusBar({ onRunIngest, isRunning = false }: { onRunIngest: () => void; isRunning?: boolean }) {
  return (
    <header className="flex h-14 items-center justify-between border-b bg-white px-4">
      <h1 className="text-lg font-semibold">NewsCraft Ingestion</h1>
      <div className="hidden items-center gap-6 text-sm lg:flex">
        <StatusCell label="PostgreSQL" value="Healthy" />
        <StatusCell label="Proxy" value="Active" />
        <div className="flex items-center gap-3 border-l pl-6">
          <Clock3 className="size-4" aria-hidden="true" />
          <span>Last run</span>
          <span className="tabular-nums">09:32</span>
        </div>
      </div>
      <Button onClick={onRunIngest} disabled={isRunning} className="h-9 min-w-32 gap-2 rounded-md bg-primary">
        <Play className="size-4" aria-hidden="true" />
        {isRunning ? "Running" : "Run ingest"}
      </Button>
    </header>
  )
}

function StatusCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 border-l pl-6 first:border-l-0 first:pl-0">
      <Radio className="size-3 fill-emerald-600 text-emerald-600" aria-hidden="true" />
      <span>{label}</span>
      <span className="text-emerald-700">{value}</span>
    </div>
  )
}
