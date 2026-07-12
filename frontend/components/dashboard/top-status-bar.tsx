"use client"

import { CircleAlert, CircleCheck, LoaderCircle, Play } from "lucide-react"

import { Button } from "@/components/ui/button"

type ConnectionState = "checking" | "connected" | "unavailable"

export function TopStatusBar({
  onRunIngest,
  isRunning = false,
  connectionState,
  lastRunLabel,
}: {
  onRunIngest: () => void
  isRunning?: boolean
  connectionState: ConnectionState
  lastRunLabel: string | null
}) {
  const status = {
    checking: { label: "Checking backend", Icon: LoaderCircle, className: "text-slate-500" },
    connected: { label: "Backend connected", Icon: CircleCheck, className: "text-emerald-700" },
    unavailable: { label: "Backend unavailable", Icon: CircleAlert, className: "text-red-700" },
  }[connectionState]

  return (
    <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b bg-white px-4 py-2">
      <h1 className="text-lg font-semibold">NewsCraft</h1>
      <div className="flex items-center gap-4 text-sm">
        <span className={`inline-flex items-center gap-2 ${status.className}`}>
          <status.Icon className="size-4" aria-hidden="true" />
          {status.label}
        </span>
        <span className="hidden text-muted-foreground lg:inline">{lastRunLabel ?? "No ingestion runs yet"}</span>
        <Button onClick={onRunIngest} disabled={isRunning} className="h-9 min-w-32 gap-2 rounded-md bg-primary">
          <Play className="size-4" aria-hidden="true" />
          {isRunning ? "Running" : "Run ingest"}
        </Button>
      </div>
    </header>
  )
}
