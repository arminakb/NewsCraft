import { CircleAlert, CirclePause, LoaderCircle, ShieldCheck } from "lucide-react"

export type ControlDisplayState = "checking" | "unavailable" | "paused" | "active"

const controlLabels = {
  checking: { label: "Checking controls", Icon: LoaderCircle, className: "text-muted-foreground" },
  unavailable: { label: "Control state unavailable", Icon: CircleAlert, className: "text-destructive" },
  paused: { label: "Automation paused", Icon: CirclePause, className: "text-warning" },
  active: { label: "Controls available", Icon: ShieldCheck, className: "text-success" },
} satisfies Record<ControlDisplayState, { label: string; Icon: typeof CircleAlert; className: string }>

export function NewsroomHeader({ controlState }: { controlState: ControlDisplayState }) {
  const status = controlLabels[controlState]

  return (
    <header className="sticky top-0 z-30 flex min-h-14 min-w-0 items-center justify-between gap-3 border-b border-border/50 bg-card/95 px-4 py-2 shadow-xs backdrop-blur">
      <div className="min-w-0">
        <div className="truncate text-base font-semibold">NewsCraft</div>
        <div className="text-xs text-muted-foreground min-[900px]:hidden">Newsroom Command Center</div>
      </div>
      <div className={`inline-flex min-h-11 min-w-0 items-center gap-1.5 text-[13px] ${status.className}`}>
        <status.Icon className="size-4 shrink-0" aria-hidden="true" strokeWidth={1.5} />
        <span className="truncate" dir={controlState === "unavailable" ? "auto" : undefined}>
          {status.label}
        </span>
      </div>
    </header>
  )
}
