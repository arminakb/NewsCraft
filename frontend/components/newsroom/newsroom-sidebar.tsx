"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Activity,
  Bot,
  CalendarDays,
  Clock3,
  Database,
  FileText,
  ImageIcon,
  ListTodo,
  Library,
  Inbox,
  Newspaper,
  Settings,
  SquarePen,
} from "lucide-react"

import { Separator } from "@/components/ui/separator"
import type { JobSummary } from "@/features/jobs/types"
import { cn } from "@/lib/utils"

export const newsroomNavItems = [
  { label: "Today", href: "/", icon: Newspaper },
  { label: "Inbox", href: "/inbox", icon: Inbox },
  { label: "Job Queue", href: "/jobs", icon: ListTodo },
  { label: "Automations", href: "/automations", icon: Bot },
  { label: "Drafts", href: "/drafts", icon: FileText },
  { label: "Review & Publish", href: "/drafts?approval_state=pending_review", activeHref: "/review", icon: SquarePen },
  { label: "Calendar", href: "/calendar", icon: CalendarDays },
  { label: "Library", href: "/library", icon: Library },
  { label: "Sources", href: "/sources", icon: Database },
  { label: "Content", href: "/content", icon: FileText },
  { label: "Ingestion Runs", href: "/runs", icon: Clock3 },
  { label: "Media", href: "/media", icon: ImageIcon },
  { label: "Diagnostics", href: "/diagnostics", icon: Activity },
  { label: "Content Settings", href: "/settings/content", icon: Settings },
] as const

export function NewsroomSidebar({ summary }: { summary?: JobSummary }) {
  const pathname = usePathname()

  return (
    <aside className="hidden min-h-screen border-r bg-sidebar text-sidebar-foreground min-[900px]:flex min-[900px]:w-[248px] min-[900px]:flex-col">
      <div className="px-5 py-5">
        <div className="text-2xl font-semibold text-primary">NewsCraft</div>
        <div className="mt-1 text-sm text-slate-600">Newsroom Command Center</div>
      </div>
      <Separator />
      <nav aria-label="Newsroom navigation" className="flex-1 space-y-1 p-3">
        {newsroomNavItems.map((item, index) => (
          <div key={item.href}>
            {index === 8 ? <Separator className="my-3" /> : null}
            <NewsroomLink item={item} active={isCurrentPath(pathname, "activeHref" in item ? item.activeHref : item.href)} />
          </div>
        ))}
      </nav>
      <div className="p-3">
        {summary ? (
          <div className="space-y-2 rounded-md border bg-white p-3 text-sm shadow-sm" aria-label="Job summary">
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Queue</span>
              <span className="font-medium tabular-nums">{summary.queued} queued</span>
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-muted-foreground">Attention</span>
              <span className={cn("font-medium tabular-nums", summary.attention > 0 && "text-amber-700")}>
                {summary.attention} need attention
              </span>
            </div>
          </div>
        ) : null}
      </div>
    </aside>
  )
}

export function isCurrentPath(pathname: string, href: string) {
  return href === "/" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`)
}

function NewsroomLink({
  item,
  active,
}: {
  item: (typeof newsroomNavItems)[number]
  active: boolean
}) {
  const Icon = item.icon

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors",
        active ? "bg-sidebar-accent text-sidebar-accent-foreground" : "hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon className="size-5" aria-hidden="true" />
      {item.label}
    </Link>
  )
}
