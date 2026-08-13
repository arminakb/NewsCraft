import { expect, test } from "@playwright/test"

import type { components } from "../lib/api/generated"
import { fulfillMockJson, installMockBackend } from "./support/mock-backend"

test.use({ video: "on" })

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
  automation(
    "55555555-5555-4555-8555-555555555555",
    "Desk briefing pipeline",
    "active",
    "telegram",
    [
      stage("desk-trigger", "manual", "Manual", "trigger"),
      stage("desk-research", "research", "AI Research", "content"),
      stage("desk-generate", "generate_content_pack", "Generate content package", "ai"),
      stage("desk-draft", "save_drafts", "Save to Drafts", "draft", ["telegram"]),
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

  await expect(page.locator("[data-workflow-card]")).toHaveCount(3)
  await expect(page.getByRole("img", { name: "Output platform: Telegram" }).first()).toBeVisible()
  await expect(page.getByRole("img", { name: "Output platform: Draft" })).toBeVisible()
  await expect(page.locator("[data-platform-logo='telegram']").first()).toBeVisible()
  await expect(page.getByRole("img", { name: "Workflow stages: Manual, AI Research, AI generation, Save to Drafts." }).first()).toBeVisible()
  await expect(page.getByRole("img", { name: "Success rate: 96%" }).first()).toContainText("96%")
  await expect(page.locator("[data-workflow-status='active'] [data-flow-motion='active']").first()).toBeVisible()
  await expect(page.locator("[data-workflow-status='paused'] [data-flow-motion='paused']")).toBeVisible()
  await expect(page.locator("[data-workflow-status='active'] [data-flow-connector][data-animated='true']")).toHaveCount(6)
  await expect(page.locator("[data-workflow-status='paused'] [data-workflow-beam='animated']")).toHaveCount(0)

  const search = page.getByRole("searchbox", { name: "Search workflows" })
  await search.fill("Research-first")
  await expect(page.locator("[data-workflow-card]")).toHaveCount(1)
  await expect(page.getByText("Research-first draft")).toBeVisible()
  await page.getByRole("button", { name: "Clear workflow search" }).click()
  await expect(page.locator("[data-workflow-card]")).toHaveCount(3)

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

test("workflow card preview uses measured animated SVG beams", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "no-preference" })
  await page.goto("/automations")
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "no-preference" })

  const activeCard = page.locator("[data-workflow-status='active']").first()
  const preview = activeCard.locator("[data-flow-motion='active']")
  const beams = preview.locator("[data-flow-connector]")
  await expect(beams).toHaveCount(3)
  await expect(page.locator("[data-workflow-status='active'] [data-workflow-beam-glow]")).toHaveCount(6)
  await expect(preview.locator("[data-workflow-beam='animated']")).toHaveCount(3)
  await expect(preview.locator("[data-workflow-beam-moving-path]")).toHaveCount(3)
  await expect(preview.locator("[data-workflow-beam-glow]")).toHaveCount(3)
  await expect(preview.locator("[data-workflow-beam-highlight]")).toHaveCount(3)
  await expect(beams.locator("circle")).toHaveCount(0)
  await expect(preview.locator("linearGradient[data-workflow-beam-gradient]")).toHaveCount(3)
  await expect(preview.locator("filter[data-workflow-beam-filter] feGaussianBlur")).toHaveCount(3)
  await expect(preview.locator("clipPath[data-workflow-beam-clip]")).toHaveCount(3)
  await expect(preview.locator("animate")).toHaveCount(18)
  await expect(preview.locator("[data-workflow-beam-glow]").first()).toHaveAttribute("filter", /url\(#workflow-beam-/)
  const movingPath = preview.locator("[data-workflow-beam-moving-path]").first()
  await expect(preview).toHaveAttribute("data-reduced-motion", "false")
  await expect(movingPath).toHaveAttribute("pathLength", "100")
  await expect(movingPath).not.toHaveAttribute("stroke-dasharray")
  await expect(movingPath).toHaveAttribute("clip-path", /url\(#workflow-beam-/)
  const highlight = preview.locator("[data-workflow-beam-highlight]").first()
  await expect(highlight).toHaveAttribute("stroke-dasharray", "22 78")
  const highlightStart = await highlight.evaluate((node) => getComputedStyle(node).strokeDashoffset)
  await page.waitForTimeout(450)
  const highlightMid = await highlight.evaluate((node) => getComputedStyle(node).strokeDashoffset)
  expect(highlightMid).not.toBe(highlightStart)

  const gradient = preview.locator("linearGradient[data-workflow-beam-gradient]").first()
  const gradientStart = await gradient.evaluate((node) => (node as SVGLinearGradientElement).x1.animVal.value)
  await page.waitForTimeout(450)
  const gradientMid = await gradient.evaluate((node) => (node as SVGLinearGradientElement).x1.animVal.value)
  expect(gradientMid).not.toBe(gradientStart)
  const geometry = await beams.evaluateAll((connectors) => connectors.map((connector, index) => {
    const svg = connector as SVGSVGElement
    const svgRect = svg.getBoundingClientRect()
    const card = connector.closest("[data-flow-motion]")
    const nodes = [...card!.querySelectorAll<HTMLElement>("[data-stage-type]")]
    const from = nodes[index].getBoundingClientRect()
    const to = nodes[index + 1].getBoundingClientRect()
    const paths = [...svg.querySelectorAll<SVGPathElement>("path")]
    const match = paths[0]?.getAttribute("d")?.match(/^M\s*(-?[\d.]+),(-?[\d.]+)\s+H\s*(-?[\d.]+)$/)
    if (!match) return { horizontal: false, sourceSide: false, targetSide: false, aligned: false }
    const [, startX, startY, endX] = match.map(Number)
    return {
      horizontal: true,
      sourceSide: svgRect.left + startX > from.left + from.width / 2,
      targetSide: svgRect.left + endX < to.left + to.width / 2,
      aligned: Math.abs(startY - Number(match[2])) < 0.01,
    }
  }))
  expect(geometry.every((item) => item.horizontal && item.sourceSide && item.targetSide && item.aligned)).toBe(true)

  const ids = await page.evaluate(() => {
    const defs = [...document.querySelectorAll<SVGElement>("[data-workflow-beam-gradient], [data-workflow-beam-filter], [data-workflow-beam-clip]")]
    const references = [...document.querySelectorAll<SVGElement>("[data-workflow-beam-moving-path], [data-workflow-beam-glow]")]
      .map((element) => [element.getAttribute("stroke"), element.getAttribute("filter"), element.getAttribute("clip-path")])
      .flat()
      .filter((value): value is string => Boolean(value))
    return { ids: defs.map((element) => element.id), references }
  })
  expect(new Set(ids.ids).size).toBe(ids.ids.length)
  expect(ids.references.every((reference) => reference.includes("url(#workflow-beam-"))).toBe(true)

  const bounds = await activeCard.evaluate((card) => {
    const cardRect = card.getBoundingClientRect()
    const nodes = [...card.querySelectorAll<HTMLElement>("[data-stage-type]")].map((node) => {
      const rect = node.getBoundingClientRect()
      return { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom }
    })
    return { card: { left: cardRect.left, right: cardRect.right, top: cardRect.top, bottom: cardRect.bottom }, nodes }
  })
  expect(bounds.nodes.length).toBe(4)
  expect(bounds.nodes.every((node) => node.left >= bounds.card.left && node.right <= bounds.card.right && node.top >= bounds.card.top && node.bottom <= bounds.card.bottom)).toBe(true)
  expect(new Set(bounds.nodes.map((node) => Math.round((node.top + node.bottom) / 2))).size).toBe(1)

  await page.screenshot({ path: testInfo.outputPath("workflow-card-beam-frame-1.png"), fullPage: false })
  await page.waitForTimeout(1000)
  await page.screenshot({ path: testInfo.outputPath("workflow-card-beam-frame-2.png"), fullPage: false })
  await page.screenshot({ path: testInfo.outputPath("workflow-card-animated-beams.png"), fullPage: false })

  await page.emulateMedia({ colorScheme: "light", reducedMotion: "no-preference" })
  await page.reload()
  const lightPreview = page.locator("[data-workflow-status='active']").first().locator("[data-flow-motion='active']")
  await expect(lightPreview).toHaveAttribute("data-reduced-motion", "false")
  await expect(lightPreview.locator("[data-workflow-beam-glow]")).toHaveCount(3)
  await expect(lightPreview.locator("filter[data-workflow-beam-filter] feGaussianBlur")).toHaveCount(3)
  const lightGradient = lightPreview.locator("linearGradient[data-workflow-beam-gradient]").first()
  const lightGradientStart = await lightGradient.evaluate((node) => (node as SVGLinearGradientElement).x1.animVal.value)
  await page.waitForTimeout(450)
  const lightGradientMid = await lightGradient.evaluate((node) => (node as SVGLinearGradientElement).x1.animVal.value)
  expect(lightGradientMid).not.toBe(lightGradientStart)
  await page.screenshot({ path: testInfo.outputPath("workflow-card-beams-light.png"), fullPage: false })
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
    await expect(page.locator("[data-workflow-card]")).toHaveCount(3)
    await expect(page.locator("[data-workflow-beam='static']").first()).toBeVisible()
    await expect(page.locator("[data-workflow-beam-moving-path]")).toHaveCount(0)
    await expect(page.locator("[data-workflow-beam='static'] path").first()).toHaveAttribute("d", /\sH\s/)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    await page.screenshot({ path: test.info().outputPath(`workflows-${setup.width}-${setup.theme}.png`), fullPage: true })
  })
}

test("workflow card preview survives 125% zoom", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 900 })
  await page.emulateMedia({ colorScheme: "light", reducedMotion: "reduce" })
  await page.goto("/automations")
  await page.evaluate(() => { document.documentElement.style.zoom = "1.25" })

  await expect(page.locator("[data-workflow-card]").first()).toBeVisible()
  await expect(page.locator("[data-workflow-beam='static']").first()).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

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
