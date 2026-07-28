import { CircleAlert, Inbox, LoaderCircle, type LucideIcon } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

function StatePanel({
  className,
  icon: Icon,
  title,
  description,
  action,
  children,
  ...props
}: React.ComponentProps<"div"> & {
  icon?: LucideIcon
  title?: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div
      data-slot="state-panel"
      className={cn("nc-state-panel flex min-h-24 flex-col items-center justify-center text-center", className)}
      {...props}
    >
      {Icon ? <Icon className="mb-2 size-6 text-muted-foreground" aria-hidden="true" /> : null}
      {title ? <h3 className="font-medium text-foreground">{title}</h3> : null}
      {description ? <p className="mt-1 max-w-prose text-muted-foreground">{description}</p> : null}
      {children}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  )
}

function EmptyState({
  icon = Inbox,
  ...props
}: Omit<React.ComponentProps<typeof StatePanel>, "icon"> & { icon?: LucideIcon }) {
  return <StatePanel data-slot="empty-state" icon={icon} {...props} />
}

function LoadingState({
  title = "Loading…",
  className,
  ...props
}: Omit<React.ComponentProps<typeof StatePanel>, "icon">) {
  return (
    <StatePanel
      data-slot="loading-state"
      role="status"
      icon={LoaderCircle}
      className={cn("[&_svg]:animate-spin", className)}
      {...props}
    >
      <span className="font-medium text-foreground">{title}</span>
    </StatePanel>
  )
}

function ErrorState({
  title = "Unable to load",
  ...props
}: Omit<React.ComponentProps<typeof StatePanel>, "icon">) {
  return (
    <StatePanel
      data-slot="error-state"
      role="alert"
      icon={CircleAlert}
      title={title}
      {...props}
    />
  )
}

export { EmptyState, ErrorState, LoadingState, StatePanel }
