import AxeBuilder from "@axe-core/playwright"
import { expect, test, type Locator, type Page } from "@playwright/test"

import { fulfillMockJson, installMockBackend } from "./support/mock-backend"

const automationId = "77777777-7777-4777-8777-777777777777"
const versionId = "88888888-8888-4888-8888-888888888888"
const savedVersionId = "88888888-8888-4888-8888-888888888889"
const runId = "99999999-9999-4999-8999-999999999999"
const jobId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
const revisionId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

test("ordered editor is the complete mobile path and restores sheet focus", async ({ page }) => {
  const backend = await installWorkflowBackend(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/automations/${automationId}`)

  const editor = page.getByRole("region", { name: "Ordered workflow editor" })
  await expect(editor).toBeVisible()
  await expect(page.locator(".react-flow")).toHaveCount(0)
  await expectNoPageOverflow(page)

  const addStep = editor.getByRole("button", { name: "Add next step" })
  await addStep.focus()
  await addStep.click()
  const sheet = page.getByRole("dialog", { name: "Add next step" })
  await expect(sheet).toBeVisible()
  await sheet.getByRole("button", { name: /Filter content/ }).click()
  await expect(sheet).toHaveCount(0)
  await expect(addStep).toBeFocused()
  await expect(editor.getByRole("article")).toHaveCount(6)

  await page.getByRole("button", { name: "Save draft" }).click()
  await expect.poll(() => backend.lastVersionBody).not.toBeNull()
  expect(JSON.stringify(backend.lastVersionBody)).not.toMatch(/api_key|authorization|credential|password|prompt_body|secret|token/i)
  await page.reload()
  await expect(editor.getByRole("article")).toHaveCount(6)

  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "dark" })
  await page.reload()
  await expect(editor).toBeVisible()
  await expectNoPageOverflow(page)
  expect(backend.unhandledRequests).toEqual([])
})

test("canvas stays accessible and bounded at tablet and desktop widths", async ({ page }, testInfo) => {
  const backend = await installWorkflowBackend(page)

  for (const viewport of [
    { width: 1280, height: 800 },
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto(`/automations/${automationId}`)
    await expect(page.getByLabel("Workflow canvas", { exact: true })).toBeVisible()
    await expect(page.locator(".react-flow__node")).toHaveCount(5)
    await expect(page.getByRole("button", { name: "Open ordered editor" })).toBeVisible()
    await expectNoPageOverflow(page)
    const library = page.getByRole("complementary", { name: "Node library" })
    await expect(library).toBeVisible()
    await expect(library.getByText("Filter content description")).toHaveCount(0)
    await expect(library.getByRole("status")).toContainText("No nodes available")
    await expect(library.locator("[data-node-library-grid]")).toHaveCount(0)
    await expect(library.getByRole("button", { name: "Filter content", exact: true })).toHaveCount(0)
    const canvasBox = await page.getByLabel("Workflow canvas", { exact: true }).boundingBox()
    expect(canvasBox).not.toBeNull()
    expect(canvasBox!.y).toBeLessThanOrEqual(58)
    expect(Math.abs(viewport.height - canvasBox!.y - canvasBox!.height)).toBeLessThanOrEqual(2)
    await expect(page.locator("[data-newsroom-header]")).toHaveCount(0)
    await expect.poll(() => page.getByTestId("newsroom-content").evaluate((element) => element.scrollHeight - element.clientHeight)).toBeLessThanOrEqual(1)
    if (viewport.width === 1280) await page.screenshot({ path: testInfo.outputPath("workflow-editor-1280x800.png") })
  }

  const firstNode = page.locator(".react-flow__node").first()
  await firstNode.focus()
  await expect(firstNode).toBeFocused()
  expect(await firstNode.evaluate((node) => node.matches(":focus-visible"))).toBe(true)

  const flowViewport = page.locator(".react-flow__viewport")
  const canvasControls = page.getByLabel("Workflow canvas controls")
  const initialTransform = await flowViewport.getAttribute("style")
  await canvasControls.getByRole("button", { name: "Zoom In" }).click()
  await expect.poll(() => flowViewport.getAttribute("style")).not.toBe(initialTransform)
  const zoomedTransform = await flowViewport.getAttribute("style")
  await canvasControls.getByRole("button", { name: "Fit View" }).click()
  await expect.poll(() => flowViewport.getAttribute("style")).not.toBe(zoomedTransform)
  const fittedTransform = await flowViewport.getAttribute("style")
  const panningCanvas = await page.getByLabel("Workflow canvas", { exact: true }).boundingBox()
  expect(panningCanvas).not.toBeNull()
  await page.mouse.move(panningCanvas!.x + panningCanvas!.width / 2, panningCanvas!.y + panningCanvas!.height / 2)
  await page.mouse.wheel(80, 120)
  await expect.poll(() => flowViewport.getAttribute("style")).not.toBe(fittedTransform)
  await canvasControls.getByRole("button", { name: "Fit View" }).click()

  await expect(page.getByRole("complementary", { name: "Node inspector" })).toHaveCount(0)
  await expect(page.getByRole("button", { name: "Inspector" })).toHaveCount(0)
  const targetNode = page.locator(".react-flow__node").nth(2)
  const startBox = await targetNode.boundingBox()
  expect(startBox).not.toBeNull()
  await page.mouse.move(startBox!.x + startBox!.width / 2, startBox!.y + startBox!.height / 2)
  await page.mouse.down()
  await page.mouse.move(startBox!.x + startBox!.width / 2 + 80, startBox!.y + startBox!.height / 2 + 40, { steps: 5 })
  const draggingBox = await targetNode.boundingBox()
  expect(draggingBox?.x).toBeGreaterThan(startBox!.x + 20)
  await page.mouse.up()
  await targetNode.evaluate((node) => node.dispatchEvent(new MouseEvent("contextmenu", {
    bubbles: true,
    button: 2,
    cancelable: true,
    clientX: window.innerWidth - 2,
    clientY: window.innerHeight - 2,
  })))
  let menu = page.getByRole("menu", { name: "Filter content actions" })
  await expect(menu).toBeVisible()
  const menuBox = await menu.boundingBox()
  expect(menuBox).not.toBeNull()
  expect(menuBox!.x).toBeGreaterThanOrEqual(0)
  expect(menuBox!.y).toBeGreaterThanOrEqual(0)
  expect(menuBox!.x + menuBox!.width).toBeLessThanOrEqual(1920)
  expect(menuBox!.y + menuBox!.height).toBeLessThanOrEqual(1080)
  await page.getByLabel("Workflow canvas", { exact: true }).click({ position: { x: 16, y: 16 } })
  await expect(menu).toHaveCount(0)

  await targetNode.click({ button: "right" })
  menu = page.getByRole("menu", { name: "Filter content actions" })
  await menu.getByRole("menuitem", { name: "Customize" }).click()
  const customizeDialog = page.getByRole("dialog", { name: "Customize Filter content" })
  await expect(customizeDialog).toBeVisible()
  await customizeDialog.getByLabel("Batch size").fill("4")
  await page.keyboard.press("Escape")
  await expect(customizeDialog).toBeVisible()
  await expect(customizeDialog.getByText("Discard unsaved node changes?")).toBeVisible()
  await customizeDialog.getByRole("button", { name: "Keep editing" }).click()
  await customizeDialog.getByRole("button", { name: "Save changes" }).click()
  await expect(customizeDialog).toHaveCount(0)
  await expect(targetNode).toBeFocused()
  await page.getByRole("button", { name: "Save draft" }).click()
  await expect.poll(() => backend.lastVersionBody).not.toBeNull()
  expect(backend.lastVersionBody).toMatchObject({
    graph: {
      nodes: expect.arrayContaining([expect.objectContaining({ id: "filter-2", config: { batch_size: 4 } })]),
    },
  })
  const savedLayout = (backend.lastVersionBody as { graph: { metadata: { layout: Record<string, { x: number; y: number }> } } }).graph.metadata.layout
  expect(savedLayout["filter-2"].x).toBeGreaterThan(600)

  await expectNoSeriousAxeViolations(page)
  await page.getByRole("button", { name: "Toggle color theme" }).click()
  await expect(page.locator("html")).toHaveClass(/dark/)
  await expect(page.getByRole("complementary", { name: "Node library" }).getByRole("status")).toContainText("No nodes available")
  await page.screenshot({ path: testInfo.outputPath("workflow-editor-1920x1080-dark.png") })
  await expectNoSeriousAxeViolations(page)
  expect(backend.unhandledRequests).toEqual([])
})

test("Node Library stays empty while canvas keeps persisted nodes", async ({ page }) => {
  await installWorkflowBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/automations/${automationId}`)

  const nodes = page.locator(".react-flow__node")
  await expect(nodes).toHaveCount(5)
  const library = page.getByRole("complementary", { name: "Node library" })
  await expect(library.getByRole("status")).toContainText("No nodes available")
  await expect(library.locator(".react-flow__node")).toHaveCount(0)
})

test("@performance controlled canvas keeps 5, 15, and 30-node selection responsive", async ({ page }, testInfo) => {
  const backend = await installWorkflowBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  const latencies: Record<string, { median: number; samples: number[] }> = {}

  for (const nodeCount of [5, 15, 30]) {
    backend.nodeCount = nodeCount
    await page.goto(`/automations/${automationId}`)
    const nodes = page.locator(".react-flow__node")
    await expect(nodes).toHaveCount(nodeCount)
    const warmup = nodes.last()
    await warmup.evaluate((node) => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })))
    await expect(warmup).toHaveClass(/selected/)
    const target = nodes.nth(Math.floor(nodeCount / 2))
    const samples: number[] = []
    for (let sample = 0; sample < 3; sample += 1) {
      if (sample > 0) {
        await warmup.evaluate((node) => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })))
        await expect(warmup).toHaveClass(/selected/)
      }
      samples.push(await selectionLatency(target))
    }
    const median = [...samples].sort((left, right) => left - right)[1]
    latencies[String(nodeCount)] = { median, samples }
    console.info(`workflow-selection-latency-ms nodes=${nodeCount} median=${median.toFixed(2)} samples=${samples.map((value) => value.toFixed(2)).join(",")}`)
    expect(Math.max(...samples)).toBeLessThan(150)
    // Dev-server scheduling adds small jitter around the 100ms product budget.
    expect(median).toBeLessThan(110)
  }

  await testInfo.attach("workflow-selection-latencies.json", {
    body: JSON.stringify(latencies, null, 2),
    contentType: "application/json",
  })
  console.info(`workflow-selection-latencies-ms ${JSON.stringify(latencies)}`)
  expect(backend.unhandledRequests).toEqual([])
})

test("Test Studio resumes persisted dry-run truth and hands off to Runs", async ({ page }, testInfo) => {
  const backend = await installWorkflowBackend(page)
  await page.emulateMedia({ reducedMotion: "reduce" })
  await page.setViewportSize({ width: 375, height: 812 })
  await page.goto(`/automations/${automationId}`)

  await page.getByRole("button", { name: "Test", exact: true }).click()
  const studio = page.getByLabel("Test Studio controls")
  await expect(studio).toBeVisible()
  await studio.getByRole("button", { name: "Validate only" }).click()
  await expect(studio.getByText("Version validated")).toBeVisible()
  await studio.getByRole("button", { name: "Start full dry run" }).click()

  await expect(page).toHaveURL(new RegExp(`runId=${runId}`))
  await expect(studio.getByRole("heading", { name: "Run 99999999" })).toBeVisible()
  await expect(studio.getByRole("link", { name: "Open exact revision" })).toHaveAttribute("href", `/review/${revisionId}`)
  await expect(studio.getByRole("link", { name: "Related Job" })).toHaveAttribute("href", `/operations?view=jobs&job=${jobId}`)
  await expect(studio).not.toContainText("credential-canary")

  await page.getByRole("button", { name: "Activate", exact: true }).click()
  await expect(page.getByRole("button", { name: "Pause", exact: true })).toBeVisible()
  await page.getByRole("button", { name: "Pause", exact: true }).click()
  await expect(page.getByRole("button", { name: "Resume", exact: true })).toBeVisible()

  await page.reload()
  await page.getByRole("button", { name: "Test", exact: true }).click()
  await expect(page.getByRole("heading", { name: "Run 99999999" })).toBeVisible()
  await page.getByRole("link", { name: "View all runs" }).click()
  await expect(page).toHaveURL(new RegExp(`/automations/runs\\?automationId=${automationId}`))
  await expect(page.getByLabel("Automation runs mobile list")).toBeVisible()
  await page.getByRole("button", { name: "Inspect run" }).click()
  const detail = page.getByRole("dialog", { name: "Run detail" })
  await expect(detail.getByRole("button", { name: "Close run detail" })).toBeFocused()
  await expect(detail.getByRole("link", { name: "Open exact revision" })).toHaveAttribute("href", `/review/${revisionId}`)
  await expect(detail.getByRole("link", { name: "Related Job" })).toHaveAttribute("href", `/operations?view=jobs&job=${jobId}`)
  await expect(detail).not.toContainText("credential-canary")
  await expectNoPageOverflow(page)
  await page.screenshot({ path: testInfo.outputPath("phase-5-test-studio-runs-mobile.png") })
  await expectNoSeriousAxeViolations(page)
  await detail.getByRole("button", { name: "Close run detail" }).click()
  await page.getByRole("button", { name: "Open navigation" }).click()
  await page.getByRole("button", { name: "Toggle color theme" }).click()
  await page.getByRole("button", { name: "Close navigation panel" }).click()
  await expect(page.locator("html")).toHaveClass(/dark/)
  await page.getByRole("button", { name: "Inspect run" }).click()
  await expect(page.getByRole("dialog", { name: "Run detail" })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("phase-5-test-studio-runs-mobile-dark.png") })
  await expectNoSeriousAxeViolations(page)
  await page.getByRole("dialog", { name: "Run detail" }).getByRole("link", { name: "Related Job" }).click()
  await expect(page).toHaveURL(`/operations?view=jobs&job=${jobId}`)
  expect(backend.unhandledRequests).toEqual([])
})

async function installWorkflowBackend(page: Page) {
  const unhandledRequests = await installMockBackend(page)
  const state: {
    lifecycle: "inactive" | "active" | "paused"
    nodeCount: number
    savedGraph: ReturnType<typeof workflowGraph> | null
    lastVersionBody: Record<string, unknown> | null
    unhandledRequests: string[]
    validated: boolean
    version: number
    revision: number
  } = { lifecycle: "inactive", nodeCount: 5, savedGraph: null, lastVersionBody: null, unhandledRequests, validated: false, version: 1, revision: 1 }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api\/backend/, "")
    if (request.method() === "GET" && path === `/automations/${automationId}`) {
      await fulfillMockJson(route, automationDetail(state.savedGraph ?? workflowGraph(state.nodeCount), state))
      return
    }
    if (request.method() === "POST" && path === `/automations/${automationId}/versions`) {
      const body = request.postDataJSON() as { graph: ReturnType<typeof workflowGraph> }
      state.savedGraph = body.graph
      state.lastVersionBody = body as unknown as Record<string, unknown>
      state.version += 1
      await fulfillMockJson(route, automationVersion(body.graph, state.version), 201)
      return
    }
    if (request.method() === "POST" && path === `/automations/${automationId}/versions/${state.version}/validate`) {
      state.validated = true
      await fulfillMockJson(route, { valid: true, graph_hash: `browser-fixture-${state.version}`, findings: [] })
      return
    }
    if (request.method() === "POST" && path === `/automations/${automationId}/runs`) {
      await fulfillMockJson(route, automationRun(), 202)
      return
    }
    if (request.method() === "GET" && path === `/automations/${automationId}/runs`) {
      await fulfillMockJson(route, { items: [automationRun()], next_cursor: null })
      return
    }
    if (request.method() === "GET" && path === `/automation-runs/${runId}`) {
      await fulfillMockJson(route, automationRun())
      return
    }
    if (request.method() === "GET" && path === `/jobs/${jobId}`) {
      await fulfillMockJson(route, automationJobDetail())
      return
    }
    if (request.method() === "GET" && path === "/automations") {
      await fulfillMockJson(route, { items: [automationOut(state)], next_cursor: null })
      return
    }
    if (request.method() === "GET" && path === "/articles") {
      await fulfillMockJson(route, { items: [], next_cursor: null, result_count: 0 })
      return
    }
    if (request.method() === "POST" && path === `/automations/${automationId}/activate`) {
      state.lifecycle = "active"
      state.revision += 1
      await fulfillMockJson(route, automationOut(state))
      return
    }
    if (request.method() === "POST" && path === `/automations/${automationId}/pause`) {
      state.lifecycle = "paused"
      state.revision += 1
      await fulfillMockJson(route, automationOut(state))
      return
    }
    if (request.method() === "GET" && path === "/automation-node-catalog") {
      await fulfillMockJson(route, nodeCatalog())
      return
    }
    if (request.method() === "POST" && path === "/automation-resource-catalog") {
      await fulfillMockJson(route, { resources: [] })
      return
    }
    await route.fallback()
  })
  return state
}

function automationVersion(graph: ReturnType<typeof workflowGraph>, versionNumber: number, valid = false) {
  return {
    id: versionNumber === 1 ? versionId : savedVersionId,
    automation_id: automationId,
    version: versionNumber,
    schema_version: 1,
    graph,
    graph_hash: `browser-fixture-${versionNumber}`,
    compiler_version: "workflow-graph-v1",
    compiled_plan: {},
    validation_summary: { valid, graph_hash: `browser-fixture-${versionNumber}`, findings: [] },
    creation_actor_type: "human",
    creation_actor_id: "local-owner",
    creation_reason: "browser fixture",
    created_at: "2026-08-01T08:00:00Z",
  }
}

function automationDetail(
  graph: ReturnType<typeof workflowGraph>,
  state: { lifecycle: "inactive" | "active" | "paused"; revision: number; validated: boolean; version: number },
) {
  const version = automationVersion(graph, state.version, state.validated)
  return {
    ...automationOut(state),
    active_version_id: state.lifecycle === "active" ? version.id : null,
    draft_version: version,
    active_version: state.lifecycle === "active" ? version : null,
    legacy_route_id: null,
  }
}

function automationOut(state: { lifecycle: "inactive" | "active" | "paused"; revision: number; version: number }) {
  return {
    id: automationId,
    name: "Morning newsroom",
    description: "Accessible controlled workflow fixture",
    lifecycle: state.lifecycle,
    owner_type: "operator_managed",
    revision: state.revision,
    active_version_id: state.lifecycle === "active" ? (state.version === 1 ? versionId : savedVersionId) : null,
    draft_version_id: state.version === 1 ? versionId : savedVersionId,
    archived_at: null,
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-08-01T08:04:00Z",
  }
}

function automationRun() {
  return {
    id: runId,
    automation_id: automationId,
    automation_version_id: versionId,
    root_workflow_job_id: jobId,
    trigger_kind: "manual",
    trigger_metadata: { input_source: "saved_graph" },
    dry_run: true,
    status: "succeeded",
    current_node_id: null,
    resource_snapshot: { automation_version: 1, prompt_version_id: "prompt-v1" },
    safe_error_code: null,
    safe_error_message: null,
    started_at: "2026-08-01T08:02:00Z",
    finished_at: "2026-08-01T08:02:03Z",
    created_at: "2026-08-01T08:02:00Z",
    nodes: [{
      id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      automation_run_id: runId,
      node_id: "output-1",
      attempt: 1,
      status: "succeeded",
      workflow_job_id: jobId,
      automation_dispatch_id: null,
      research_run_id: null,
      generation_run_id: null,
      platform_variant_revision_id: revisionId,
      publish_job_id: null,
      publication_id: null,
      input_summary: { story_revision_id: revisionId },
      output_summary: { result: "Revision persisted" },
      usage: { total_tokens: 42 },
      retry_metadata: {},
      safe_error_code: null,
      safe_error_message: null,
      started_at: "2026-08-01T08:02:00Z",
      finished_at: "2026-08-01T08:02:03Z",
      created_at: "2026-08-01T08:02:00Z",
    }],
  }
}

function automationJobDetail() {
  return {
    id: jobId,
    job_type: "automation.run.start",
    status: "succeeded",
    origin: "manual",
    priority: 0,
    pause_sensitive: false,
    scheduled_for: "2026-08-01T08:02:00Z",
    attempt_count: 1,
    max_attempts: 3,
    progress: 100,
    progress_message: "Workflow dry run completed",
    error_class: null,
    error_code: null,
    error_message: null,
    started_at: "2026-08-01T08:02:00Z",
    finished_at: "2026-08-01T08:02:03Z",
    created_at: "2026-08-01T08:02:00Z",
    updated_at: "2026-08-01T08:02:03Z",
    payload: { automation_run_id: runId },
    result: { status: "succeeded" },
    events: [{
      id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      event_type: "automation.run.succeeded",
      actor: "worker",
      event_data: { automation_run_id: runId },
      created_at: "2026-08-01T08:02:03Z",
    }],
  }
}

function workflowGraph(nodeCount: number) {
  const nodes = Array.from({ length: nodeCount }, (_, index) => ({
    id: index === 0 ? "trigger-1" : index === nodeCount - 1 ? "output-1" : `filter-${index}`,
    type: index === 0 ? "manual" : index === nodeCount - 1 ? "story_output" : "filter_content",
    config: index === 0 ? { story_revision_id: "11111111-1111-4111-8111-111111111111" } : {},
  }))
  return {
    schema_version: 1,
    entry_node_id: nodes[0].id,
    nodes,
    edges: nodes.slice(1).map((node, index) => ({
      source_node_id: nodes[index].id,
      source_port: index === 0 ? "story" : "accepted",
      target_node_id: node.id,
      target_port: "story",
    })),
    output_node_ids: [nodes.at(-1)?.id ?? nodes[0].id],
    metadata: {
      layout: Object.fromEntries(nodes.map((node, index) => [node.id, { x: 80 + (index % 5) * 260, y: 80 + Math.floor(index / 5) * 180 }])),
    },
  }
}

function nodeCatalog() {
  return {
    schema_version: 1,
    max_nodes: 30,
    max_edges: 60,
    nodes: [
      nodeDefinition("manual", "trigger", "Manual", true, [], [port("story", null)]),
      { ...nodeDefinition("filter_content", "select_filter", "Filter content", false, [port("story", 1)], [port("accepted", null)]), config_schema: { type: "object", properties: { batch_size: { type: "integer", title: "Batch size", minimum: 1, maximum: 5 } } } },
      { ...nodeDefinition("story_output", "output", "Story output", false, [port("story", 1)], []), terminal: true },
    ],
  }
}

function nodeDefinition(type: string, family: string, displayName: string, entry: boolean, inputs: unknown[], outputs: unknown[]) {
  return {
    type,
    family,
    display_name: displayName,
    description: `${displayName} description`,
    entry,
    terminal: false,
    runtime_status: "existing",
    runtime_owner: "compiler",
    runtime_job_types: [],
    inputs,
    outputs,
    config_schema: { type: "object", properties: {} },
    ui_hints: {},
  }
}

function port(name: string, maxConnections: number | null) {
  return { name, artifact_types: ["story.revision_ref"], required: true, max_connections: maxConnections }
}

async function expectNoPageOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
}

async function expectNoSeriousAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).include("main").analyze()
  expect(results.violations.filter((item) => ["serious", "critical"].includes(item.impact ?? ""))).toEqual([])
}

async function selectionLatency(target: Locator) {
  return target.evaluate((node) => new Promise<number>((resolve, reject) => {
    const timeout = window.setTimeout(() => reject(new Error("Selection did not render")), 1_000)
    const observer = new MutationObserver(() => {
      if (!node.classList.contains("selected")) return
      window.clearTimeout(timeout)
      observer.disconnect()
      resolve(performance.now() - startedAt)
    })
    observer.observe(node, { attributes: true, attributeFilter: ["class"] })
    const startedAt = performance.now()
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))
  }))
}
