"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowLeft, FilePlus2, LayoutTemplate, LoaderCircle } from "lucide-react"
import Link from "next/link"
import { useRouter, useSearchParams } from "next/navigation"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button, buttonVariants } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/state-panel"
import { StatusBadge } from "@/components/ui/status-badge"
import { getApiErrorMessage } from "@/lib/http"
import { queryKeys } from "@/lib/query-keys"

import { createAutomationFromTemplate, getAutomationTemplates } from "./automation-api"
import type { AutomationTemplate } from "./automation-types"
import { AutomationArea } from "./automation-area"

export function AutomationTemplatesPage({ creationMode = false }: { creationMode?: boolean }) {
  const templates = useQuery({ queryKey: queryKeys.automationTemplates, queryFn: ({ signal }) => getAutomationTemplates(signal) })
  const preferBlank = useSearchParams().get("blank") === "true"
  const sorted = templates.data ? [...templates.data].sort((a, b) => {
    if (!preferBlank) return a.name.localeCompare(b.name)
    return Number(b.seedKey === "blank-workflow") - Number(a.seedKey === "blank-workflow")
  }) : []

  return (
    <AutomationArea
      title={creationMode ? "Create workflow" : "Templates"}
      description={creationMode ? "Choose a server-managed starting point. Every copy starts inactive and editable." : "Reusable, capability-aware workflow starting points from backend truth."}
      actions={creationMode ? <Link className={buttonVariants({ variant: "outline" })} href="/automations"><ArrowLeft aria-hidden="true" />Back to workflows</Link> : <Link className={buttonVariants()} href="/automations/new"><FilePlus2 aria-hidden="true" />New workflow</Link>}
    >
      {templates.isPending ? <LoadingState title="Loading templates…" /> : null}
      {templates.isError ? (
        <ErrorState
          title="Templates unavailable"
          description={getApiErrorMessage(templates.error)}
          action={<Button variant="outline" onClick={() => void templates.refetch()}>Retry templates</Button>}
        />
      ) : null}
      {templates.data && !templates.data.length ? (
        <EmptyState icon={LayoutTemplate} title="No templates available" description="Server has not exposed any active workflow templates." />
      ) : null}
      {sorted.length ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3" aria-label="Workflow templates">
          {sorted.map((template) => <TemplateCard key={template.id} template={template} creationMode={creationMode} preferred={preferBlank && template.seedKey === "blank-workflow"} />)}
        </div>
      ) : null}
    </AutomationArea>
  )
}

function TemplateCard({ template, creationMode, preferred }: { template: AutomationTemplate; creationMode: boolean; preferred: boolean }) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: () => createAutomationFromTemplate(template.seedKey, {}, idempotencyKey(template.seedKey)),
    onSuccess: async (automation) => {
      await queryClient.invalidateQueries({ queryKey: ["automations"] })
      router.push(`/automations/${automation.id}`)
    },
  })
  const stepNames = template.graphSeed.nodes.map((node) => node.type.split("_").map(capitalize).join(" "))

  return (
    <Card className={preferred ? "ring-2 ring-primary/35" : undefined}>
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge tone="neutral">{capitalize(template.complexity)}</StatusBadge>
          <span className="text-xs text-muted-foreground">{template.graphSeed.nodes.length} steps</span>
        </div>
        <CardTitle>{template.name}</CardTitle>
        <p className="text-[13px] text-muted-foreground" dir="auto">{template.description}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Workflow</p>
          <ol className="mt-2 space-y-1 text-[13px]">
            {stepNames.map((name, index) => <li key={`${name}-${index}`} className="flex gap-2"><span className="tabular-nums text-muted-foreground">{index + 1}.</span><span>{name}</span></li>)}
          </ol>
        </div>
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Requires</p>
          <p className="mt-1 text-[13px] text-muted-foreground">{template.capabilityRequirements.map((item) => item.replaceAll("_", " ")).join(" · ")}</p>
        </div>
        {mutation.isError ? <Alert tone="error" role="alert"><AlertDescription>{getApiErrorMessage(mutation.error)}</AlertDescription></Alert> : null}
      </CardContent>
      <CardFooter className="justify-end">
        <Button disabled={mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? <LoaderCircle className="animate-spin" aria-hidden="true" /> : <FilePlus2 aria-hidden="true" />}
          {mutation.isPending ? "Creating draft…" : creationMode ? "Use this template" : "Create from template"}
        </Button>
      </CardFooter>
    </Card>
  )
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

function idempotencyKey(seed: string) {
  return `template-${seed}-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}
