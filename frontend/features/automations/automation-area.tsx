"use client"

import { Workflow } from "lucide-react"
import Link from "next/link"
import type React from "react"

import { PageHeader } from "@/components/ui/page-header"
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs"

export function AutomationArea({
  title,
  description,
  actions,
  children,
  flush = false,
  showHeader = true,
}: {
  title: string
  description?: string
  actions?: React.ReactNode
  children: React.ReactNode
  flush?: boolean
  showHeader?: boolean
}) {
  return (
    <section
      className={flush ? "flex min-h-full min-w-0 flex-col min-[900px]:h-dvh min-[900px]:overflow-hidden" : "nc-page"}
      {...(showHeader ? { "aria-labelledby": "automations-heading" } : { "aria-label": title })}
    >
      {showHeader ? (
        <div className={flush ? "border-b bg-background px-4 pt-4 min-[768px]:px-6" : undefined}>
          <PageHeader title={title} titleId="automations-heading" description={description} actions={actions} />
          <AutomationTabs className="mt-2" />
        </div>
      ) : (
        <AutomationTabs />
      )}
      {children}
    </section>
  )
}

function AutomationTabs({ className }: { className?: string }) {
  return (
    <Tabs value="workflows" className={className}>
      <TabsList aria-label="Automation views">
        <TabsTab value="workflows" nativeButton={false} render={<Link href="/automations" />}>
          <Workflow aria-hidden="true" className="size-4" />
          Workflows
        </TabsTab>
      </TabsList>
    </Tabs>
  )
}
