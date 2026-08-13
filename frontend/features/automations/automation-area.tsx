"use client"

import { Workflow } from "lucide-react"
import Link from "next/link"
import type React from "react"

import { PageHeader } from "@/components/ui/page-header"
import { Tabs, TabsList, TabsTab } from "@/components/ui/tabs"

const sections = [
  { value: "workflows", label: "Workflows", href: "/automations", icon: Workflow },
] as const

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
          <AutomationTabs active="workflows" className="mt-2" />
        </div>
      ) : (
        <AutomationTabs active="workflows" />
      )}
      {children}
    </section>
  )
}

function AutomationTabs({ active, className }: { active: string; className?: string }) {
  return (
    <Tabs value={active} className={className}>
      <TabsList aria-label="Automation views">
        {sections.map((section) => {
          const Icon = section.icon
          return (
            <TabsTab key={section.value} value={section.value} nativeButton={false} render={<Link href={section.href} />}>
              <Icon aria-hidden="true" className="size-4" />
              {section.label}
            </TabsTab>
          )
        })}
      </TabsList>
    </Tabs>
  )
}
