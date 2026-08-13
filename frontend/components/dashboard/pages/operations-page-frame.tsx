import { PageHeader } from "@/components/ui/page-header"

export function OperationsPageFrame({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string
  subtitle: string
  actions?: React.ReactNode
  children: React.ReactNode
  enableQueries?: boolean
}) {
  return (
    <section aria-label={title} className="min-w-0 bg-background text-sm text-foreground">
      <div className="min-w-0">
        <PageHeader
          className="min-h-16 items-center border-border/50 bg-card px-4 py-3 md:px-6"
          title={title}
          description={subtitle}
          actions={actions}
        />
        <div className="min-w-0 space-y-4 p-4 md:p-5 lg:p-6">{children}</div>
      </div>
    </section>
  )
}
