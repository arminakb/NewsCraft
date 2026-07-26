import { CircleAlert, CirclePause, LoaderCircle, ShieldCheck } from "lucide-react"

export type ControlDisplayState = "checking" | "unavailable" | "paused" | "active"

const controlLabels = {
  checking: { label: "Checking controls", Icon: LoaderCircle, className: "text-slate-600 dark:text-slate-300" },
  unavailable: { label: "Control state unavailable", Icon: CircleAlert, className: "text-red-700 dark:text-red-300" },
  paused: { label: "Automation paused", Icon: CirclePause, className: "text-amber-700 dark:text-amber-300" },
  active: { label: "Controls available", Icon: ShieldCheck, className: "text-emerald-700 dark:text-emerald-300" },
} satisfies Record<ControlDisplayState, { label: string; Icon: typeof CircleAlert; className: string }>

export function NewsroomHeader({ controlState }: { controlState: ControlDisplayState }) {
  const status = controlLabels[controlState]

  return (
    <header className="sticky top-0 z-30 flex min-h-14 min-w-0 items-center justify-between gap-3 border-b bg-white/95 px-4 py-2 backdrop-blur dark:bg-background/95">
      <div className="min-w-0">
        <div className="truncate text-base font-semibold min-[900px]:text-lg">NewsCraft</div>
        <div className="text-xs text-muted-foreground min-[900px]:hidden">Newsroom Command Center</div>
      </div>
      <div className={`inline-flex min-h-11 min-w-0 items-center gap-2 text-sm ${status.className}`}>
        <status.Icon className="size-4 shrink-0" aria-hidden="true" />
        <span className="truncate" dir={controlState === "unavailable" ? "auto" : undefined}>
          {status.label}
        </span>
      </div>
    </header>
  )
}
