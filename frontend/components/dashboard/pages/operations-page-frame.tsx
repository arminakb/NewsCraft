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
    <section aria-label={title} className="min-w-0 bg-slate-50 text-sm text-foreground dark:bg-background">
      <div className="min-w-0 bg-white dark:bg-background">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold">{title}</h1>
            <p className="text-sm text-muted-foreground">{subtitle}</p>
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
        <div className="min-w-0 space-y-4 p-4">{children}</div>
      </div>
    </section>
  )
}
