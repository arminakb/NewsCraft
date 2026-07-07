"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Activity,
  AlertTriangle,
  ChevronLeft,
  Clock3,
  Database,
  FileText,
  ImageIcon,
  LayoutDashboard,
  Rss,
  Send,
} from "lucide-react"

import { Button, buttonVariants } from "@/components/ui/button"
import { Separator } from "@/components/ui/separator"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { DashboardSnapshot } from "@/lib/types"

const navItems = [
  { label: "Overview", href: "/", icon: LayoutDashboard },
  { label: "Sources", href: "/sources", icon: Database },
  { label: "Runs", href: "/runs", icon: Clock3 },
  { label: "Content Items", href: "/content", icon: FileText },
  { label: "Media", href: "/media", icon: ImageIcon },
  { label: "Diagnostics", href: "/diagnostics", icon: Activity },
]

export function AppSidebar({ counts }: { counts: DashboardSnapshot["counts"] }) {
  const pathname = usePathname()

  return (
    <aside className="hidden min-h-screen border-r bg-sidebar text-sidebar-foreground md:flex md:flex-col">
      <div className="px-5 py-5">
        <div className="text-2xl font-semibold text-primary">NewsCraft</div>
        <div className="mt-1 text-sm text-foreground">Ingestion</div>
      </div>
      <Separator />
      <nav aria-label="Dashboard navigation" className="flex-1 space-y-1 p-3">
        {navItems.map((item) => (
          <Link
            key={item.label}
            href={item.href}
            aria-current={pathname === item.href ? "page" : undefined}
            className={cn(
              buttonVariants({ variant: pathname === item.href ? "secondary" : "ghost" }),
              "h-10 w-full justify-start gap-3 rounded-md px-3"
            )}
          >
            <item.icon className="size-5" aria-hidden="true" />
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="p-3">
        <div className="space-y-3 rounded-md border bg-white p-3 text-sm shadow-sm">
          <Metric icon={Rss} label="RSS feeds" value={counts.rssFeeds} className="text-orange-500" />
          <Metric icon={Send} label="Telegram channels" value={counts.telegramChannels} className="text-sky-500" />
          <Metric icon={FileText} label="Content items" value={counts.contentItems} />
          <Metric icon={ImageIcon} label="Media assets" value={counts.mediaAssets} />
          <Metric icon={AlertTriangle} label="Warnings" value={counts.warnings} className="text-amber-500" />
        </div>
      </div>
      <Button variant="ghost" className="m-3 h-10 justify-start gap-3">
        <ChevronLeft className="size-5" aria-hidden="true" />
        Collapse
      </Button>
    </aside>
  )
}

function Metric({
  icon: Icon,
  label,
  value,
  className,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  className?: string
}) {
  return (
    <div className="flex items-center gap-3">
      <Icon className={`size-5 ${className ?? "text-slate-500"}`} aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{label}</span>
      <span className={className ?? "text-foreground"}>{formatNumber(value)}</span>
    </div>
  )
}
