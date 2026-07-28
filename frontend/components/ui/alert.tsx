import {
  CheckCircle2,
  CircleAlert,
  Info,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

type AlertTone = "error" | "info" | "success" | "warning"

const toneClasses: Record<AlertTone, string> = {
  error: "border-destructive/30 bg-[var(--error-surface)] text-destructive",
  info: "border-border/60 bg-muted/50 text-foreground",
  success: "border-success/30 bg-[var(--success-surface)] text-success",
  warning: "border-warning/30 bg-[var(--warning-surface)] text-warning",
}

const toneIcons: Record<AlertTone, LucideIcon> = {
  error: CircleAlert,
  info: Info,
  success: CheckCircle2,
  warning: TriangleAlert,
}

function Alert({
  className,
  tone = "info",
  icon: Icon = toneIcons[tone],
  children,
  ...props
}: React.ComponentProps<"div"> & { tone?: AlertTone; icon?: LucideIcon }) {
  return (
    <div
      data-slot="alert"
      className={cn(
        "grid grid-cols-[auto_1fr] items-start gap-2 rounded-lg border p-3 text-[13px] leading-5",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 text-foreground">{children}</div>
    </div>
  )
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="alert-title" className={cn("font-semibold", className)} {...props} />
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div data-slot="alert-description" className={cn("mt-0.5 text-muted-foreground", className)} {...props} />
}

export { Alert, AlertDescription, AlertTitle, type AlertTone }
