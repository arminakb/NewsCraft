import * as React from "react"

import { cn } from "@/lib/utils"

function PageHeader({
  className,
  contentClassName,
  title,
  titleId,
  description,
  descriptionProps,
  actions,
}: {
  className?: string
  contentClassName?: string
  title: React.ReactNode
  titleId?: string
  description?: React.ReactNode
  descriptionProps?: React.ComponentProps<"p">
  actions?: React.ReactNode
}) {
  return (
    <header className={cn("nc-page-header", className)} data-slot="page-header">
      <div className={cn("min-w-0", contentClassName)}>
        <h1 id={titleId} className="nc-page-title">{title}</h1>
        {description ? <p {...descriptionProps} className={cn("nc-page-description", descriptionProps?.className)}>{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}

export { PageHeader }
