import { expect, test } from "@playwright/test"

import type { components } from "../lib/api/generated"
import { fulfillMockJson, installMockBackend } from "./support/mock-backend"

const blankWorkflowId = "33333333-3333-4333-8333-333333333333"
const blankWorkflow = automationDetail(blankWorkflowId)

const workflows = [
  automation(
    "11111111-1111-4111-8111-111111111111",
    "Breaking news pipeline",
    "active",
    "telegram",
    [
      stage("trigger", "manual", "Manual", "trigger"),
      stage("research", "research", "AI Research", "content"),
      stage("generate", "generate_content_pack", "Generate content package", "ai"),
      stage("draft", "save_drafts", "Save to Drafts", "draft", ["telegram"]),
    ],
  ),
  automation(
    "22222222-2222-4222-8222-222222222222",
    "Research-first draft",
    "paused",
    "draft",
    [
      stage("trigger", "manual", "Manual", "trigger"),
      stage("research", "research", "AI Research", "content"),
      stage("generate", "generate_content_pack", "Generate content package", "ai"),
      stage("draft", "save_drafts", "Save to Drafts", "draft", ["draft"]),
    ],
  ),
] satisfies components["schemas"]["AutomationOut"][]

test.beforeEach(async ({ page }) => {
  await installMockBackend(page, { automations: workflows })
  await page.route("**/api/backend/automations", async (route) => {
    if (route.request().method() !== "POST") return route.continue()
    const body = route.request().postDataJSON() as { name?: string }
    await fulfillMockJson(route, { ...blankWorkflow, name: body.name ?? blankWorkflow.name }, 201)
  })
  await page.route(`**/api/backend/automations/${blankWorkflowId}`, (route) => fulfillMockJson(route, blankWorkflow))
  await page.route("**/api/backend/automation-resource-catalog", (route) => fulfillMockJson(route, { resources: [] }))
})

test("workflow gallery keeps real previews, nested actions, and keyboard navigation", async ({ page }) => {
  await page.goto("/automations")

  await expect(page.locator("[data-workflow-card]")).toHaveCount(2)
  await expect(page.getByRole("img", { name: "Output platform: Telegram" })).toBeVisible()
  await expect(page.getByRole("img", { name: "Output platform: Draft" })).toBeVisible()
  await expect(page.locator("[data-platform-logo='telegram']").first()).toBeVisible()
  await expect(page.getByRole("img", { name: "Workflow stages: Manual, AI Research, AI generation, Save to Drafts." })).toBeVisible()
  await expect(page.getByRole("img", { name: "Success rate: 96%" }).first()).toContainText("96%")
  await expect(page.locator("[data-workflow-status='active'] [data-flow-motion='active']")).toBeVisible()
  await expect(page.locator("[data-workflow-status='paused'] [data-flow-motion='paused']")).toBeVisible()
  await expect(page.locator("[data-workflow-status='active'] [data-flow-connector][data-animated='true']")).toHaveCount(3)
  await expect(page.locator("[data-workflow-status='paused'] .workflow-flow-particle")).toHaveCount(0)

  const search = page.getByRole("searchbox", { name: "Search workflows" })
  await search.fill("research")
  await expect(page.locator("[data-workflow-card]")).toHaveCount(1)
  await expect(page.getByText("Research-first draft")).toBeVisible()
  await page.getByRole("button", { name: "Clear workflow search" }).click()
  await expect(page.locator("[data-workflow-card]")).toHaveCount(2)

  await page.getByRole("button", { name: "More actions for Breaking news pipeline" }).click()
  await page.getByRole("menuitem", { name: "Test workflow" }).click()
  await expect(page).toHaveURL(/\/automations\/11111111-1111-4111-8111-111111111111#test-studio$/, { timeout: 15_000 })

  await page.goto("/automations")
  const create = page.getByRole("button", { name: "Create new workflow" })
  await create.focus()
  await page.keyboard.press("Space")
  const nameDialog = page.getByRole("dialog", { name: "Name your workflow" })
  await expect(nameDialog).toBeVisible()
  await nameDialog.getByRole("textbox", { name: "Workflow name" }).fill("Morning newsroom")
  await nameDialog.getByRole("button", { name: "Create workflow" }).click()
  await expect(page).toHaveURL(new RegExp(`/automations/${blankWorkflowId}$`), { timeout: 15_000 })
  await expect(page.getByLabel("Workflow canvas", { exact: true })).toBeVisible()
  await expect(page.locator(".react-flow__node")).toHaveCount(0)
  await expect(page.getByText("No nodes available")).toBeVisible()
  await expect(page.getByRole("tab", { name: "Templates" })).toHaveCount(0)

  await page.goto("/automations/templates")
  await expect(page).toHaveURL(/\/automations$/)
  await expect(page.getByRole("tab", { name: "Templates" })).toHaveCount(0)

  await page.goto("/automations")
  const card = page.getByRole("button", { name: "Open workflow: Breaking news pipeline" })
  await card.focus()
  await page.keyboard.press("Enter")
  await expect(page).toHaveURL(/\/automations\/11111111-1111-4111-8111-111111111111$/, { timeout: 15_000 })
})

for (const setup of [
  { width: 1440, height: 1000, theme: "dark" },
  { width: 1440, height: 1000, theme: "light" },
  { width: 1024, height: 900, theme: "dark" },
  { width: 1024, height: 900, theme: "light" },
  { width: 768, height: 900, theme: "dark" },
  { width: 768, height: 900, theme: "light" },
  { width: 390, height: 844, theme: "dark" },
  { width: 390, height: 844, theme: "light" },
] as const) {
  test(`${setup.width}px ${setup.theme} gallery has no horizontal overflow`, async ({ page }) => {
    await page.setViewportSize({ width: setup.width, height: setup.height })
    await page.emulateMedia({ colorScheme: setup.theme, reducedMotion: "reduce" })
    await page.addInitScript((theme) => localStorage.setItem("newscraft-theme", theme), setup.theme)
    await page.goto("/automations")
    await expect(page.locator("[data-workflow-card]")).toHaveCount(2)
    await expect(page.locator(".workflow-flow-particle").first()).toHaveCSS("display", "none")
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`workflows-${setup.width}-${setup.theme}.png`), fullPage: true })
  })
}

function automationDetail(id: string): components["schemas"]["AutomationDetailOut"] {
  const versionId = "44444444-4444-4444-8444-444444444444"
  const graph = {
    schema_version: 1 as const,
    entry_node_id: "",
    nodes: [],
    edges: [],
    output_node_ids: [],
    metadata: { layout: {} },
  }
  return {
    id,
    name: "Blank workflow",
    description: "Start with a blank workflow.",
    lifecycle: "inactive",
    owner_type: "operator_managed",
    revision: 1,
    active_version_id: null,
    draft_version_id: versionId,
    archived_at: null,
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-08-01T08:00:00Z",
    active_version: null,
    draft_version: {
      id: versionId,
      automation_id: id,
      version: 1,
      schema_version: 1,
      graph,
      graph_hash: "blank-workflow-hash",
      compiler_version: null,
      compiled_plan: {},
      validation_summary: {
        valid: false,
        graph_hash: "blank-workflow-hash",
        findings: [
          { code: "graph_entry_invalid", severity: "error", message: "Graph entry must reference one supported trigger node." },
          { code: "graph_output_invalid", severity: "error", message: "Graph must contain at least one terminal output." },
        ],
      },
      creation_actor_type: "human",
      creation_actor_id: "browser-test",
      creation_reason: "blank workflow",
      created_at: "2026-08-01T08:00:00Z",
    },
  }
}

function automation(
  id: string,
  name: string,
  lifecycle: "active" | "paused",
  platform: "telegram" | "draft",
  stages: components["schemas"]["AutomationPreviewStageOut"][],
): components["schemas"]["AutomationOut"] {
  return {
    id,
    name,
    description: "Static sequence caption must not render",
    lifecycle,
    owner_type: "operator_managed",
    revision: 2,
    active_version_id: "33333333-3333-4333-8333-333333333333",
    draft_version_id: null,
    archived_at: null,
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-08-01T08:00:00Z",
    preview: {
      version: 2,
      version_state: "active",
      stages,
      output_platforms: [platform],
      valid: true,
      run_count: 24,
      success_rate: 96,
      last_run_at: "2026-08-01T07:58:00Z",
      last_outcome: "succeeded",
    },
  }
}

function stage(
  nodeId: string,
  nodeType: string,
  label: string,
  category: components["schemas"]["AutomationPreviewStageOut"]["category"],
  platforms: components["schemas"]["AutomationPreviewStageOut"]["platforms"] = [],
): components["schemas"]["AutomationPreviewStageOut"] {
  return {
    node_id: nodeId,
    node_type: nodeType,
    label,
    category,
    platforms,
    needs_attention: false,
  }
}
