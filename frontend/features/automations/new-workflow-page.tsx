"use client"

import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useRouter, useSearchParams } from "next/navigation"
import { useEffect, useRef } from "react"

import { Button } from "@/components/ui/button"
import { ErrorState, LoadingState } from "@/components/ui/state-panel"
import { getApiErrorMessage } from "@/lib/http"

import { createAutomation } from "./automation-api"
import { emptyWorkflowGraph } from "./workflow-editor-state"

export function NewWorkflowPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()
  const name = searchParams.get("name")?.trim() ?? ""
  const started = useRef(false)
  const creation = useMutation({
    mutationFn: () => createAutomation({
      name: name || "New workflow",
      graph: emptyWorkflowGraph(),
      creationReason: "blank workflow created",
    }, idempotencyKey()),
    onSuccess: async (automation) => {
      await queryClient.invalidateQueries({ queryKey: ["automations"] })
      router.push(`/automations/${automation.id}`)
    },
  })

  useEffect(() => {
    if (started.current) return
    started.current = true
    creation.mutate()
  }, [creation])

  if (creation.isError) {
    return (
      <section className="nc-page">
        <ErrorState
          title="Could not create workflow"
          description={getApiErrorMessage(creation.error)}
          action={<Button variant="outline" onClick={() => creation.mutate()}>Retry creation</Button>}
        />
      </section>
    )
  }

  return <section className="nc-page" aria-live="polite"><LoadingState title="Creating blank workflow…" /></section>
}

function idempotencyKey() {
  return `workflow-create-${globalThis.crypto?.randomUUID?.() ?? Date.now()}`
}
