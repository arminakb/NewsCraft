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
    await expect(library.locator("[data-node-library-grid]").first()).toBeVisible()
    await expect(library.getByRole("button", { name: "Filter content", exact: true })).toBeVisible()
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
  await expect(page.getByRole("complementary", { name: "Node library" }).getByRole("button", { name: "Filter content", exact: true })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("workflow-editor-1920x1080-dark.png") })
  await expectNoSeriousAxeViolations(page)
  expect(backend.unhandledRequests).toEqual([])
})

test("Node Library keeps available nodes separate from persisted canvas nodes", async ({ page }) => {
  await installWorkflowBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/automations/${automationId}`)

  const nodes = page.locator(".react-flow__node")
  await expect(nodes).toHaveCount(5)
  const library = page.getByRole("complementary", { name: "Node library" })
  await expect(library.getByRole("button", { name: "Filter content", exact: true })).toBeVisible()
  await expect(library.locator(".react-flow__node")).toHaveCount(0)
})

test("Needs attention opens grouped validation findings and stays usable in dark mode", async ({ page }) => {
  const findings = Array.from({ length: 7 }, (_value, index) => ({
    code: `node_config_invalid_${index}`,
    severity: "error" as const,
    message: `Configuration issue ${index + 1} requires review.`,
    node_id: "filter-1",
    edge_index: null,
    field_path: `config.rule${index + 1}`,
    recovery_action: "Update the step configuration.",
  }))
  const backend = await installWorkflowBackend(page, { validationFindings: findings })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(`/automations/${automationId}`)

  const trigger = page.getByRole("button", { name: "Needs attention, 7 issues" })
  await expect(trigger).toBeVisible()
  await trigger.focus()
  await page.keyboard.press("Enter")

  let dialog = page.getByRole("dialog", { name: "Needs attention" })
  await expect(dialog).toBeVisible()
  await expect(dialog).toContainText("7 issues found.")
  await expect(dialog.getByRole("heading", { name: "Filter content" })).toBeVisible()
  await expect(dialog.getByRole("listitem")).toHaveCount(7)
  await expect(dialog.locator(".overflow-y-auto")).toHaveCount(1)
  const dialogBox = await dialog.boundingBox()
  expect(dialogBox).not.toBeNull()
  expect(dialogBox!.height).toBeLessThanOrEqual(844 - 32)
  await expectNoSeriousAxeViolations(page)

  await page.keyboard.press("Escape")
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await page.getByRole("button", { name: "Open navigation" }).click()
  await page.getByRole("button", { name: "Toggle color theme" }).click()
  await page.getByRole("button", { name: "Close navigation panel" }).click()
  await expect(page.locator("html")).toHaveClass(/dark/)
  await trigger.focus()
  await page.keyboard.press("Enter")
  dialog = page.getByRole("dialog", { name: "Needs attention" })
  await expect(dialog).toBeVisible()
  await expectNoSeriousAxeViolations(page)
  await dialog.getByRole("button", { name: "Close needs attention" }).click()
  expect(backend.unhandledRequests).toEqual([])
})

test("Collection Article Added accepts article processing nodes and preserves the graph", async ({ page }) => {
  const backend = await installWorkflowBackend(page, {
    initialGraph: emptyWorkflowGraphFixture(),
    catalog: collectionArticleNodeCatalog(),
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/automations/${automationId}`)

  const canvas = page.getByLabel("Workflow canvas", { exact: true })
  const library = page.getByRole("complementary", { name: "Node library" })
  await expect(canvas).toBeVisible()
  await expect(page.locator(".react-flow__node")).toHaveCount(0)
  await library.getByRole("button", { name: "Collection article added", exact: true }).click()
  await expect(page.locator(".react-flow__node")).toHaveCount(1)

  const triggerNode = page.locator('.react-flow__node[data-id="collection-article-added-1"]')
  await triggerNode.click({ button: "right" })
  const triggerMenu = page.getByRole("menu", { name: /Select a Feed collection/ })
  await triggerMenu.getByRole("menuitem", { name: "Customize" }).click()
  const customizeDialog = page.getByRole("dialog", { name: "Customize Collection article added" })
  await expect(customizeDialog).toBeVisible()
  await customizeDialog.getByLabel("Feed collection").selectOption("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
  await customizeDialog.getByRole("button", { name: "Save changes" }).click()
  await expect(customizeDialog).toHaveCount(0)

  await library.getByRole("button", { name: "Save to Drafts", exact: true }).click()
  await expect(page.getByTestId("newsroom-content").getByRole("status")).toContainText("Save to Drafts cannot accept output from Collection article added")
  await library.getByRole("button", { name: "Filter content", exact: true }).dragTo(canvas)
  await library.getByRole("button", { name: "AI Research", exact: true }).dragTo(canvas)
  await library.getByRole("button", { name: "Generate content package", exact: true }).dragTo(canvas)
  await library.getByRole("button", { name: "Save to Drafts", exact: true }).dragTo(canvas)

  await expect(page.locator(".react-flow__node")).toHaveCount(5)
  const cardMetrics = await page.locator(".react-flow__node").evaluateAll((nodes) => Object.fromEntries(nodes.map((node) => {
    const card = node.querySelector<HTMLElement>(".nc-workflow-node-card")
    if (!card) throw new Error("Workflow node card is missing")
    const cardRect = card.getBoundingClientRect()
    const leftHandle = card.querySelector<HTMLElement>(".target")?.getBoundingClientRect()
    const rightHandle = card.querySelector<HTMLElement>(".source")?.getBoundingClientRect()
    return [node.getAttribute("data-id"), {
      width: Number.parseFloat(getComputedStyle(card).width),
      minWidth: Number.parseFloat(getComputedStyle(card).minWidth),
      leftEdgeOffset: leftHandle ? Math.abs(leftHandle.left + leftHandle.width / 2 - cardRect.left) : null,
      rightEdgeOffset: rightHandle ? Math.abs(rightHandle.left + rightHandle.width / 2 - cardRect.right) : null,
      verticalOffset: rightHandle ? Math.abs(rightHandle.top + rightHandle.height / 2 - (cardRect.top + cardRect.height / 2)) : null,
    }]
  })))
  expect(cardMetrics["filter-content-1"].width).toBeGreaterThanOrEqual(cardMetrics["filter-content-1"].minWidth)
  expect(cardMetrics["generate-content-pack-1"].width).toBeGreaterThan(cardMetrics["filter-content-1"].width)
  expect(cardMetrics["generate-content-pack-1"].leftEdgeOffset).toBeLessThan(1)
  expect(cardMetrics["generate-content-pack-1"].rightEdgeOffset).toBeLessThan(1)
  expect(cardMetrics["generate-content-pack-1"].verticalOffset).toBeLessThan(1)
  await expect(page.getByRole("region", { name: "Morning newsroom" }).getByRole("alert")).toHaveCount(0)
  await page.getByRole("button", { name: "Save draft" }).click()
  await expect.poll(() => backend.lastVersionBody).not.toBeNull()
  expect(backend.lastVersionBody).toMatchObject({
    graph: {
      entry_node_id: "collection-article-added-1",
      output_node_ids: ["save-drafts-1"],
      edges: [
        { source_node_id: "collection-article-added-1", source_port: "article", target_node_id: "filter-content-1", target_port: "story" },
        { source_node_id: "filter-content-1", source_port: "accepted", target_node_id: "research-1", target_port: "story" },
        { source_node_id: "research-1", source_port: "story", target_node_id: "generate-content-pack-1", target_port: "story" },
        { source_node_id: "generate-content-pack-1", source_port: "drafts", target_node_id: "save-drafts-1", target_port: "drafts" },
      ],
    },
  })

  await page.reload()
  await expect(page.locator(".react-flow__node")).toHaveCount(5)
  await page.getByRole("button", { name: "Open ordered editor" }).click()
  const ordered = page.getByRole("dialog", { name: "Ordered workflow editor" })
  await expect(ordered).toBeVisible()
  await expect(ordered.getByRole("article")).toHaveCount(5)
  await expect(backend.unhandledRequests).toEqual([])
})

test("workflow node cards size future labels without moving handles off the card edges", async ({ page }) => {
  await installWorkflowBackend(page, {
    initialGraph: nodeCardSizingGraph(),
    catalog: nodeCardSizingCatalog(),
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/automations/${automationId}`)

  await expect(page.locator(".react-flow__node")).toHaveCount(7)
  const cardMetrics = await page.locator(".react-flow__node").evaluateAll((nodes) => nodes.map((node) => {
    const card = node.querySelector<HTMLElement>(".nc-workflow-node-card")
    if (!card) throw new Error("Workflow node card is missing")
    const cardRect = card.getBoundingClientRect()
    const style = getComputedStyle(card)
    const leftHandle = card.querySelector<HTMLElement>(".target")?.getBoundingClientRect()
    const rightHandle = card.querySelector<HTMLElement>(".source")?.getBoundingClientRect()
    return {
      label: card.querySelector<HTMLElement>(".nc-workflow-node-title")?.textContent?.trim(),
      width: Number.parseFloat(style.width),
      minWidth: Number.parseFloat(style.minWidth),
      maxWidth: Number.parseFloat(style.maxWidth),
      leftEdgeOffset: leftHandle ? Math.abs(leftHandle.left + leftHandle.width / 2 - cardRect.left) : null,
      rightEdgeOffset: rightHandle ? Math.abs(rightHandle.left + rightHandle.width / 2 - cardRect.right) : null,
      verticalOffset: rightHandle ? Math.abs(rightHandle.top + rightHandle.height / 2 - (cardRect.top + cardRect.height / 2)) : null,
    }
  }))
  const byLabel = Object.fromEntries(cardMetrics.map((metric) => [metric.label, metric]))
  expect(byLabel.Review.width).toBe(byLabel.Review.minWidth)
  expect(byLabel.Publish.width).toBe(byLabel.Publish.minWidth)
  expect(byLabel["AI Generate"].width).toBeGreaterThan(byLabel.Review.width)
  expect(byLabel["AI Research"].width).toBeGreaterThan(byLabel.Review.width)
  expect(byLabel["Scheduled Trigger"].width).toBeGreaterThan(byLabel["AI Generate"].width)
  expect(byLabel["Collection Article Added"].width).toBeGreaterThan(byLabel["Scheduled Trigger"].width)
  expect(byLabel["New Source Item"].width).toBeGreaterThan(byLabel.Review.width)
  for (const metric of cardMetrics) {
    expect(metric.width).toBeLessThanOrEqual(metric.maxWidth)
    if (metric.leftEdgeOffset !== null) expect(metric.leftEdgeOffset).toBeLessThan(1)
    if (metric.rightEdgeOffset !== null) expect(metric.rightEdgeOffset).toBeLessThan(1)
    if (metric.verticalOffset !== null) expect(metric.verticalOffset).toBeLessThan(1)
  }
  const firstEdgeEndpoint = await page.locator(".react-flow__edge-path").first().evaluate((element) => {
    const path = element as SVGPathElement
    const point = path.getPointAtLength(0)
    const matrix = path.getScreenCTM()
    if (!matrix) return null
    return { x: point.x * matrix.a + point.y * matrix.c + matrix.e, y: point.x * matrix.b + point.y * matrix.d + matrix.f }
  })
  const firstSourceCenter = await page.locator('[data-id="future-node-0"] .source').evaluate((element) => {
    const rect = element.getBoundingClientRect()
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }
  })
  expect(firstEdgeEndpoint).not.toBeNull()
  expect(Math.abs(firstEdgeEndpoint!.x - firstSourceCenter.x)).toBeLessThan(2)
  expect(Math.abs(firstEdgeEndpoint!.y - firstSourceCenter.y)).toBeLessThan(2)
})

test("node actions preserve configuration, clean edges, and persist across reloads", async ({ page }) => {
  const backend = await installWorkflowBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/automations/${automationId}`)

  const original = page.locator('.react-flow__node[data-id="filter-2"]')
  await original.click({ button: "right" })
  let menu = page.getByRole("menu", { name: "Filter content actions" })
  await menu.getByRole("menuitem", { name: "Customize" }).click()
  const customizeDialog = page.getByRole("dialog", { name: "Customize Filter content" })
  await customizeDialog.getByLabel("Batch size").fill("4")
  await customizeDialog.getByRole("button", { name: "Save changes" }).click()
  await expect(customizeDialog).toHaveCount(0)

  await original.click({ button: "right" })
  menu = page.getByRole("menu", { name: "Filter content actions" })
  await menu.getByRole("menuitem", { name: "Duplicate" }).click()
  const duplicate = page.locator('.react-flow__node[data-id="filter-content-1"]')
  await expect(duplicate).toBeVisible()
  await expect(page.locator(".react-flow__node")).toHaveCount(6)

  await page.getByRole("button", { name: "Save draft" }).click()
  await expect.poll(() => backend.lastVersionBody).not.toBeNull()
  const duplicateSave = backend.lastVersionBody as { graph: { nodes: Array<{ id: string; config: Record<string, unknown> }>; edges: Array<{ source_node_id: string; target_node_id: string }> } }
  const savedDuplicate = duplicateSave.graph.nodes.find((node) => node.id === "filter-content-1")
  expect(savedDuplicate?.config).toMatchObject({ batch_size: 4 })
  expect(duplicateSave.graph.nodes.find((node) => node.id === "filter-2")?.config).toEqual({ batch_size: 4 })

  await page.reload()
  await expect(page.locator('.react-flow__node[data-id="filter-content-1"]')).toBeVisible()
  await expect(page.locator(".react-flow__node")).toHaveCount(6)

  await page.locator('.react-flow__node[data-id="filter-content-1"]').click({ button: "right" })
  menu = page.getByRole("menu", { name: "Filter content actions" })
  await menu.getByRole("menuitem", { name: "Delete" }).click()
  await expect(page.locator('.react-flow__node[data-id="filter-content-1"]')).toHaveCount(0)
  await expect(page.locator(".react-flow__node")).toHaveCount(5)

  await page.getByRole("button", { name: "Save draft" }).click()
  await expect.poll(() => (backend.lastVersionBody as { graph?: unknown } | null)?.graph).not.toBeNull()
  const deleteSave = backend.lastVersionBody as { graph: { nodes: Array<{ id: string }>; edges: Array<{ source_node_id: string; target_node_id: string }> } }
  expect(deleteSave.graph.nodes.some((node) => node.id === "filter-content-1")).toBe(false)
  expect(deleteSave.graph.edges.some((edge) => edge.source_node_id === "filter-content-1" || edge.target_node_id === "filter-content-1")).toBe(false)

  await page.reload()
  await expect(page.locator('.react-flow__node[data-id="filter-content-1"]')).toHaveCount(0)
  await expect(page.locator('.react-flow__node[data-id="filter-2"]')).toBeVisible()
  expect(backend.unhandledRequests).toEqual([])
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

type WorkflowBackendOptions = {
  initialGraph?: ReturnType<typeof workflowGraph>
  catalog?: ReturnType<typeof nodeCatalog>
  validationFindings?: Array<{
    code: string
    severity: "error" | "warning"
    message: string
    node_id: string | null
    edge_index: number | null
    field_path: string | null
    recovery_action: string | null
  }>
}

async function installWorkflowBackend(page: Page, options: WorkflowBackendOptions = {}) {
  const unhandledRequests = await installMockBackend(page)
  const state: {
    lifecycle: "inactive" | "active" | "paused"
    nodeCount: number
    initialGraph: ReturnType<typeof workflowGraph> | null
    savedGraph: ReturnType<typeof workflowGraph> | null
    lastVersionBody: Record<string, unknown> | null
    unhandledRequests: string[]
    validated: boolean
    validationFindings: WorkflowBackendOptions["validationFindings"]
    version: number
    revision: number
  } = {
    lifecycle: "inactive",
    nodeCount: options.initialGraph?.nodes.length ?? 5,
    initialGraph: options.initialGraph ?? null,
    savedGraph: null,
    lastVersionBody: null,
    unhandledRequests,
    validated: false,
    validationFindings: options.validationFindings ?? [],
    version: 1,
    revision: 1,
  }

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname.replace(/^\/api\/backend/, "")
    if (request.method() === "GET" && path === `/automations/${automationId}`) {
      await fulfillMockJson(route, automationDetail(state.savedGraph ?? state.initialGraph ?? workflowGraph(state.nodeCount), state))
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
    if (request.method() === "GET" && path === "/article-collections") {
      await fulfillMockJson(route, [{
        id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        name: "Reading queue",
        article_count: 1,
        created_at: "2026-08-01T08:00:00Z",
        updated_at: "2026-08-01T08:00:00Z",
      }])
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
      await fulfillMockJson(route, options.catalog ?? nodeCatalog())
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

function automationVersion(graph: ReturnType<typeof workflowGraph>, versionNumber: number, valid = false, findings: WorkflowBackendOptions["validationFindings"] = []) {
  return {
    id: versionNumber === 1 ? versionId : savedVersionId,
    automation_id: automationId,
    version: versionNumber,
    schema_version: 1,
    graph,
    graph_hash: `browser-fixture-${versionNumber}`,
    compiler_version: "workflow-graph-v1",
    compiled_plan: {},
    validation_summary: { valid, graph_hash: `browser-fixture-${versionNumber}`, findings },
    creation_actor_type: "human",
    creation_actor_id: "local-owner",
    creation_reason: "browser fixture",
    created_at: "2026-08-01T08:00:00Z",
  }
}

function automationDetail(
  graph: ReturnType<typeof workflowGraph>,
  state: { lifecycle: "inactive" | "active" | "paused"; revision: number; validated: boolean; validationFindings: WorkflowBackendOptions["validationFindings"]; version: number },
) {
  const version = automationVersion(graph, state.version, state.validated, state.validationFindings)
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

function emptyWorkflowGraphFixture(): ReturnType<typeof workflowGraph> {
  return {
    schema_version: 1,
    entry_node_id: "",
    nodes: [],
    edges: [],
    output_node_ids: [],
    metadata: { layout: {} },
  }
}

function collectionArticleNodeCatalog() {
  const collectionArticle = "article.collection_added"
  const story = "story.revision_ref"
  const researchedStory = "story.researched_revision_ref"
  const draftSet = "draft.revision_set_ref"
  const validatedDraftSet = "draft.validated_revision_set_ref"
  return {
    schema_version: 1,
    max_nodes: 30,
    max_edges: 60,
    nodes: [
      {
        ...nodeDefinition("collection_article_added", "trigger", "Collection article added", true, [], [port("article", null, [collectionArticle])]),
        terminal: true,
        config_schema: {
          type: "object",
          properties: {
            collection_id: { type: "string", title: "Feed collection" },
          },
        },
      },
      nodeDefinition("filter_content", "select_filter", "Filter content", false, [port("story", 1, [story, collectionArticle])], [port("accepted", null, [story, collectionArticle])]),
      nodeDefinition("research", "research", "AI Research", false, [port("story", 1, [story, collectionArticle])], [port("story", null, [researchedStory])]),
      {
        ...nodeDefinition("generate_content_pack", "generate", "Generate content package", false, [port("story", 1, [story, researchedStory, "story.revision_set_ref", collectionArticle])], [port("drafts", null, [draftSet])]),
        config_schema: {
          type: "object",
          properties: {
            editorial_profile_id: { type: "string", default: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee" },
            provider_profile_id: { type: "string", default: "ffffffff-ffff-4fff-8fff-ffffffffffff" },
            prompt_version_ids: { type: "array", items: { type: "string" }, default: ["11111111-1111-4111-8111-111111111111"] },
          },
        },
      },
      { ...nodeDefinition("save_drafts", "output", "Save to Drafts", false, [port("drafts", 1, [draftSet, validatedDraftSet])], []), terminal: true },
    ],
  }
}

function nodeCardSizingGraph(): ReturnType<typeof workflowGraph> {
  const types = [
    "future_review",
    "future_publish",
    "future_generate",
    "future_research",
    "future_scheduled",
    "future_collection",
    "future_source",
  ]
  const nodes = types.map((type, index) => ({ id: `future-node-${index}`, type, config: {} }))
  return {
    schema_version: 1,
    entry_node_id: nodes[0].id,
    nodes,
    edges: nodes.slice(1).map((node, index) => ({
      source_node_id: nodes[index].id,
      source_port: "output",
      target_node_id: node.id,
      target_port: "input",
    })),
    output_node_ids: [nodes.at(-1)?.id ?? nodes[0].id],
    metadata: {
      layout: Object.fromEntries(nodes.map((node, index) => [node.id, { x: 80 + index * 260, y: 80 }])),
    },
  }
}

function nodeCardSizingCatalog() {
  const definitions = [
    ["future_review", "review", "Review", "user-check"],
    ["future_publish", "output", "Publish", "package"],
    ["future_generate", "generate", "AI Generate", "sparkles"],
    ["future_research", "research", "AI Research", "search"],
    ["future_scheduled", "trigger", "Scheduled Trigger", "clock"],
    ["future_collection", "trigger", "Collection Article Added", "file-text"],
    ["future_source", "trigger", "New Source Item", "radio"],
  ] as const
  return {
    schema_version: 1,
    max_nodes: 30,
    max_edges: 60,
    nodes: definitions.map(([type, family, displayName, icon], index) => ({
      ...nodeDefinition(type, family, displayName, index === 0, index === 0 ? [] : [port("input", 1)], index === definitions.length - 1 ? [] : [port("output", null)]),
      terminal: index === definitions.length - 1,
      ui_hints: { icon },
    })),
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

function port(name: string, maxConnections: number | null, artifactTypes = ["story.revision_ref"]) {
  return { name, artifact_types: artifactTypes, required: true, max_connections: maxConnections }
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
