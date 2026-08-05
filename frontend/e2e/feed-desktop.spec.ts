import { expect, test, type Locator, type Page, type Route } from "@playwright/test"

import { fulfillMockJson } from "./support/mock-backend"

const sourceId = "22222222-2222-4222-8222-222222222222"
const researchCollectionId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
const emptyCollectionId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
const createdCollectionId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

test("Feed renders a consistent responsive desktop card grid", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)

  for (const viewport of [
    { width: 1440, height: 1000, columns: 4 },
    { width: 1280, height: 800, columns: 3 },
    { width: 1024, height: 768, columns: 2 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto("/feed")
    await expect(page.getByRole("heading", { name: "Feed", exact: true })).toBeVisible()
    await expect(page.getByText("7 articles · source monitoring and saved collections", { exact: true })).toBeVisible()
    await expect(page.getByRole("article")).toHaveCount(6)
    await expect(page.getByPlaceholder("Search in articles")).toBeVisible()
    await expect(page.getByRole("button", { name: "Create new collection" })).toHaveAttribute("title", "New collection")
    await expect(page.getByRole("img", { name: "No article image" })).toBeVisible()
    await expect(page.getByRole("img", { name: /Image unavailable for/ })).toBeVisible()
    await expect(page.getByText("4 hours ago", { exact: true })).toBeVisible()
    await expect(page.getByText("1 day ago", { exact: true })).toBeVisible()
    await expect(page.getByText("3 weeks ago", { exact: true })).toBeVisible()
    await expect(page.getByText("2 months ago", { exact: true })).toBeVisible()

    const firstCard = page.getByRole("article").first()
    await expect(firstCard.getByRole("img", { name: "Editorial score: 51" })).toBeVisible()
    await expect(firstCard.getByText("News", { exact: true })).toHaveCount(1)
    await expect(firstCard.getByText("Article", { exact: true })).toHaveCount(0)
    const collectedTime = page.getByTitle(/Collected .+ \(publication time unavailable\)/)
    await expect(collectedTime).toHaveText("2 days ago")

    const sourceLink = firstCard.getByRole("link", { name: "Open original article: English editorial report 1" })
    await expect(sourceLink).toHaveText(/Source/)
    await expect(sourceLink).toHaveAttribute("target", "_blank")
    await expect(sourceLink).toHaveAttribute("rel", "noreferrer noopener")
    await sourceLink.focus()
    await expect(sourceLink).toBeFocused()
    expect(await sourceLink.evaluate((element) => getComputedStyle(element).outlineStyle)).not.toBe("none")

    const grid = page.getByLabel("Feed results")
    expect(await grid.evaluate((element) => getComputedStyle(element).gridTemplateColumns.split(" ").length))
      .toBe(viewport.columns)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    const mediaBox = await firstCard.locator(":scope > div").first().boundingBox()
    expect(mediaBox).not.toBeNull()
    expect(mediaBox!.width / mediaBox!.height).toBeCloseTo(16 / 9, 1)
    expect(await firstCard.getByRole("heading").evaluate((element) => getComputedStyle(element).webkitLineClamp)).toBe("3")

    const cards = await page.getByRole("article").evaluateAll((elements) => elements.map((element) => {
      const rect = element.getBoundingClientRect()
      return { y: Math.round(rect.y), height: Math.round(rect.height) }
    }))
    for (const y of new Set(cards.map((card) => card.y))) {
      expect(new Set(cards.filter((card) => card.y === y).map((card) => card.height)).size).toBe(1)
    }

    const scrollContainer = page.getByTestId("newsroom-content")
    expect(await scrollContainer.evaluate((element) => (element as HTMLElement).offsetWidth - element.clientWidth)).toBe(0)
    expect(await scrollContainer.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
    await page.getByRole("main").focus()
    await page.keyboard.press("End")
    await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
    const afterEnd = await scrollContainer.evaluate((element) => element.scrollTop)
    await page.keyboard.press("Control+Home")
    await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeLessThan(afterEnd)
    await waitForScrollToSettle(scrollContainer)
    const maxScroll = await scrollContainer.evaluate((element) => element.scrollHeight - element.clientHeight)
    if (maxScroll > 100) {
      await page.keyboard.press("PageDown")
      await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      await waitForScrollToSettle(scrollContainer)
      const afterPageDown = await scrollContainer.evaluate((element) => element.scrollTop)
      await page.keyboard.press("PageUp")
      await waitForScrollToSettle(scrollContainer)
      expect(await scrollContainer.evaluate((element) => element.scrollTop)).toBeLessThan(afterPageDown)
      await page.getByRole("button", { name: "Load more" }).focus()
      await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      await expect(page.getByRole("button", { name: "Load more" })).toBeFocused()
    }
    await scrollContainer.evaluate((element) => element.scrollTo(0, 0))
    await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBe(0)
    if (maxScroll > 100) {
      await page.mouse.move(viewport.width - 108, viewport.height / 2)
      await page.mouse.wheel(0, 480)
      await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      const afterWheel = await scrollContainer.evaluate((element) => element.scrollTop)
      await page.keyboard.press("Control+Home")
      await expect.poll(() => scrollContainer.evaluate((element) => element.scrollTop)).toBeLessThan(afterWheel)
    }

    const persian = page.getByRole("heading", { name: "گزارش فارسی هوش مصنوعی" })
    await expect(persian).toHaveAttribute("dir", "rtl")
    await expect(persian).toHaveAttribute("lang", "fa")
    await expect(page.locator("bdi", { hasText: "خبرگزاری نمونه" })).toHaveAttribute("dir", "auto")
    await page.screenshot({
      path: testInfo.outputPath(`feed-4f-${viewport.width}x${viewport.height}.png`),
      fullPage: true,
    })
  }

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

async function waitForScrollToSettle(container: Locator) {
  await container.evaluate(async (element) => {
    let previous = element.scrollTop
    let stableFrames = 0
    while (stableFrames < 3) {
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
      const current = element.scrollTop
      stableFrames = current === previous ? stableFrames + 1 : 0
      previous = current
    }
  })
}

test("Feed images keep accessible alt text and stable missing or broken fallbacks", async ({ page }) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/feed")

  await expect(page.getByRole("img", { name: "Editorial newsroom" })).toBeVisible()
  await expect(page.getByRole("img", { name: "No article image" })).toBeVisible()
  await expect(page.getByRole("img", { name: "Image unavailable for English editorial report 4" })).toBeVisible()

  const fallback = page.getByRole("img", { name: "Image unavailable for English editorial report 4" })
  const mediaBox = await fallback.locator("..").boundingBox()
  expect(mediaBox).not.toBeNull()
  expect(mediaBox!.width / mediaBox!.height).toBeCloseTo(16 / 9, 1)

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("article details load lazily, stay accessible and responsive, and reuse cached content", async ({ page }) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto("/feed")

  const trigger = page.getByRole("button", { name: "View article details: English editorial report 1" })
  await expect(trigger).toBeVisible()
  expect(diagnostics.articleDetailQueries).toEqual([])
  await trigger.click()

  let dialog = page.getByRole("dialog", { name: "English editorial report 1" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByText("Source-provided content")).toBeVisible()
  await expect(dialog.getByText(/^Complete normalized article body paragraph 1\./)).toBeVisible()
  await expect(dialog.getByText("Reporter One")).toBeVisible()
  await expect(dialog.getByText("Wire Desk", { exact: true }).first()).toBeVisible()
  const original = dialog.getByRole("link", { name: "Open original source" })
  await expect(original).toHaveAttribute("href", "https://wire.example/report-1")
  await expect(original).toHaveAttribute("rel", "noopener noreferrer")
  await expect(original).toHaveAttribute("target", "_blank")
  const scrollRegion = dialog.getByTestId("article-detail-scroll-region")
  expect(await scrollRegion.evaluate((element) => element.scrollHeight > element.clientHeight)).toBe(true)
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)

  await page.keyboard.press("Escape")
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()

  await trigger.press("Enter")
  dialog = page.getByRole("dialog", { name: "English editorial report 1" })
  await expect(dialog.getByText("Source-provided content")).toBeVisible()
  expect(diagnostics.articleDetailQueries).toHaveLength(1)
  await dialog.getByRole("button", { name: "Close article details" }).click()
  await expect(trigger).toBeFocused()

  await trigger.press("Space")
  await expect(page.getByRole("dialog", { name: "English editorial report 1" })).toBeVisible()
  await page.getByRole("button", { name: "Close article details" }).click()
  expect(diagnostics.articleDetailQueries).toHaveLength(1)

  await page.setViewportSize({ width: 390, height: 844 })
  await trigger.click()
  dialog = page.getByRole("dialog", { name: "English editorial report 1" })
  const bounds = await dialog.boundingBox()
  expect(bounds).not.toBeNull()
  expect(bounds!.width).toBeLessThanOrEqual(382)
  expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
  await dialog.getByRole("button", { name: "Close article details" }).click()

  await page.getByRole("button", { name: "Save article to collection" }).first().click()
  await expect(page.getByRole("dialog", { name: "Save to Collection" })).toBeVisible()
  await expect(page.getByRole("dialog", { name: "English editorial report 1" })).toHaveCount(0)
  expect(diagnostics.articleDetailQueries).toHaveLength(1)

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("Feed mobile keeps collections and primary controls page-bounded", async ({ page }) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/feed")

  const collections = page.getByRole("complementary", { name: "Collections" })
  await expect(collections).toBeVisible()
  await expect(collections.getByRole("button", { name: "All articles" })).toBeVisible()
  await expect(collections.getByRole("button", { name: "Research" })).toBeVisible()
  await expect(collections.getByRole("button", { name: "Create new collection" })).toBeVisible()
  await expect(page.getByRole("searchbox", { name: "Search articles" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Filter articles" })).toBeVisible()
  await expect(page.getByRole("combobox", { name: "Sort articles" })).toBeVisible()

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await collections.getByRole("button", { name: "Research" }).click()
  await expect(page).toHaveURL(new RegExp(`collection_id=${researchCollectionId}`))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("article search preserves URL state, pagination, and history", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/feed?language=en&collection_id=${researchCollectionId}&sort=score`)

  const search = page.getByRole("searchbox", { name: "Search articles" })
  const searchShell = search.locator("..")
  const idleStyle = await searchShell.evaluate((element) => {
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return { borderColor: style.borderColor, boxShadow: style.boxShadow, width: rect.width, height: rect.height }
  })
  await search.click()
  expect(await searchShell.evaluate((element) => getComputedStyle(element).boxShadow)).toBe("none")
  await page.getByRole("button", { name: /Filter articles/ }).focus()
  await page.keyboard.press("Shift+Tab")
  await expect(search).toBeFocused()
  const keyboardStyle = await searchShell.evaluate((element) => {
    const style = getComputedStyle(element)
    const rect = element.getBoundingClientRect()
    return { borderColor: style.borderColor, boxShadow: style.boxShadow, width: rect.width, height: rect.height }
  })
  expect(keyboardStyle.borderColor).not.toBe(idleStyle.borderColor)
  expect(keyboardStyle.boxShadow).toBe("none")
  expect({ width: keyboardStyle.width, height: keyboardStyle.height }).toEqual({ width: idleStyle.width, height: idleStyle.height })
  await page.locator("html").evaluate((element) => element.classList.add("dark"))
  const darkStyle = await searchShell.evaluate((element) => {
    const style = getComputedStyle(element)
    return { borderColor: style.borderColor, backgroundColor: style.backgroundColor, boxShadow: style.boxShadow }
  })
  expect(darkStyle.borderColor).not.toBe(darkStyle.backgroundColor)
  expect(darkStyle.boxShadow).toBe("none")
  await page.locator("html").evaluate((element) => element.classList.remove("dark"))
  await search.fill("  ENGLISH EDITORIAL  ")
  await expect(page).toHaveURL(`/feed?language=en&collection_id=${researchCollectionId}&sort=score&q=ENGLISH+EDITORIAL`)
  await expect(page.getByText("1 article · source monitoring and saved collections", { exact: true })).toBeVisible()
  expect(diagnostics.articleQueries.at(-1)).toContain("q=ENGLISH+EDITORIAL")
  expect(diagnostics.articleQueries.at(-1)).toContain(`collection_id=${researchCollectionId}`)
  expect(diagnostics.articleQueries.at(-1)).toContain("language=en")
  expect(diagnostics.articleQueries.at(-1)).toContain("sort=score")

  await page.getByRole("button", { name: "Clear search input" }).click()
  await expect(page).toHaveURL(`/feed?language=en&collection_id=${researchCollectionId}&sort=score`)
  await expect(page.getByText("2 articles · source monitoring and saved collections", { exact: true })).toBeVisible()

  await page.getByRole("button", { name: "All articles" }).click()
  await expect(page).toHaveURL("/feed?language=en&sort=score")
  await search.fill("English editorial")
  await expect(page.getByText("5 articles · source monitoring and saved collections", { exact: true })).toBeVisible()
  await expect(page.getByRole("article")).toHaveCount(3)
  await page.getByRole("button", { name: "Load more" }).click()
  await expect(page.getByRole("article")).toHaveCount(5)
  expect(diagnostics.articleQueries.at(-1)).toContain("q=English+editorial")
  expect(diagnostics.articleQueries.at(-1)).toContain("cursor=search-page-2")

  await page.goBack()
  await expect(page).toHaveURL("/feed?language=en&sort=score")
  await expect(search).toHaveValue("")
  await page.goForward()
  await expect(page).toHaveURL("/feed?language=en&sort=score&q=English+editorial")
  await expect(search).toHaveValue("English editorial")
  await page.reload()
  await expect(search).toHaveValue("English editorial")

  await search.fill("گزارش فارسی")
  await expect(page.getByRole("heading", { name: "گزارش فارسی هوش مصنوعی" })).toBeVisible()
  await expect(page.getByText("1 article · source monitoring and saved collections", { exact: true })).toBeVisible()
  await search.fill("missing title")
  await expect(page.getByText("No articles match “missing title”")).toBeVisible()
  await page.getByRole("button", { name: "Clear article search" }).click()
  await expect(page.getByText("7 articles · source monitoring and saved collections", { exact: true })).toBeVisible()

  const createCollection = page.getByRole("button", { name: "Create new collection" })
  await createCollection.focus()
  await expect(page.getByRole("tooltip", { name: "New collection" })).toBeVisible()
  await createCollection.click()
  await expect(page.getByRole("textbox", { name: "Collection name" })).toBeFocused()
  await page.keyboard.press("Escape")
  await expect(createCollection).toBeFocused()

  await page.screenshot({ path: testInfo.outputPath("feed-4f-search-1440x1000.png"), fullPage: true })
  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("left sidebar exposes every route with labels, states, and keyboard movement", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/feed")

  const rail = page.getByRole("complementary", { name: "Global navigation" })
  const collections = page.getByRole("complementary", { name: "Collections" })
  await rail.getByRole("button", { name: "Open sidebar" }).click()
  await expect(rail).toHaveAttribute("data-sidebar-state", "expanded")
  const railBounds = await rail.boundingBox()
  const collectionBounds = await collections.boundingBox()
  expect(railBounds?.width).toBe(260)
  expect(railBounds?.x).toBe(0)
  expect(collectionBounds?.x).toBeGreaterThanOrEqual(260)
  expect(collectionBounds!.x + collectionBounds!.width).toBeLessThanOrEqual(620)

  const expectedNavigation = [
    ["Today", "/"],
    ["Sources", "/sources"],
    ["Feed", "/feed"],
    ["Automations", "/automations"],
    ["Operations Center", "/operations"],
    ["Settings", "/settings?section=llm-providers"],
  ] as const
  for (const [label, href] of expectedNavigation) {
    const link = rail.getByRole("link", { name: label })
    await expect(link).toHaveAttribute("href", href)
    if (label !== "Settings") await expect(link.getByText(label, { exact: true })).toBeVisible()
  }
  await expect(rail.getByRole("link", { name: "Feed" })).toHaveAttribute("aria-current", "page")
  await expect(rail.getByRole("link", { name: "Inbox" })).toHaveCount(0)
  const themeToggle = rail.getByRole("button", { name: "Toggle color theme" })
  await expect(themeToggle).toBeVisible()
  await expect(rail.getByRole("button")).toHaveCount(2)
  await expect(page.getByRole("dialog", { name: /navigation/i })).toHaveCount(0)

  const lightSidebar = await rail.evaluate((element) => getComputedStyle(element).backgroundColor)
  await themeToggle.click()
  await expect(page.locator("html")).toHaveClass(/dark/)
  expect(await rail.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(lightSidebar)
  await themeToggle.click()
  await expect(page.locator("html")).not.toHaveClass(/dark/)

  const feed = rail.getByRole("link", { name: "Feed" })
  const idleBackground = await feed.evaluate((element) => getComputedStyle(element).backgroundColor)
  await feed.hover()
  await expect
    .poll(() => feed.evaluate((element) => getComputedStyle(element).backgroundColor))
    .not.toBe(idleBackground)
  await feed.focus()
  await page.keyboard.press("ArrowDown")
  await expect(rail.getByRole("link", { name: "Automations" })).toBeFocused()
  await page.keyboard.press("End")
  await expect(rail.getByRole("link", { name: "Settings" })).toBeFocused()
  await expect(page.getByRole("tooltip")).toHaveCount(0)
  await page.keyboard.press("Home")
  await expect(rail.getByRole("link", { name: "Today" })).toBeFocused()

  const desktopNavigation = rail.getByRole("navigation", { name: "Newsroom navigation" })
  expect(await desktopNavigation.evaluate((element) => ({
    horizontal: element.scrollWidth > element.clientWidth,
    vertical: element.scrollHeight > element.clientHeight,
  }))).toEqual({ horizontal: false, vertical: false })
  const settingsBounds = await rail.getByRole("link", { name: "Settings" }).boundingBox()
  expect(settingsBounds!.y + settingsBounds!.height).toBeLessThanOrEqual(1000)
  expect(settingsBounds!.y).toBeGreaterThan(900)
  await page.screenshot({ path: testInfo.outputPath("feed-left-navigation-1440x1000.png"), fullPage: true })

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("filters, sort, URL history, and cursor pagination coexist", async ({ page }) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/feed?language=en")
  await expect(page.getByRole("article")).toHaveCount(6)

  await page.getByRole("button", { name: "Load more" }).click()
  await expect(page.getByRole("article")).toHaveCount(7)
  expect(diagnostics.articleQueries.at(-1)).toContain("language=en")
  expect(diagnostics.articleQueries.at(-1)).toContain("cursor=page-2")

  await page.getByRole("button", { name: /Filter articles/ }).click()
  await page.getByRole("checkbox", { name: /AI/ }).check()
  await page.getByRole("checkbox", { name: /Tech/ }).check()
  await page.getByRole("button", { name: "Apply filters" }).click()
  await expect(page).toHaveURL(/\/feed\?language=en&topic=AI&topic=Tech$/)
  await expect(page.getByRole("button", { name: "Remove filter EN" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Remove filter AI" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Remove filter Tech" })).toBeVisible()
  expect(diagnostics.articleQueries.at(-1)).not.toContain("cursor=")

  await page.getByRole("combobox", { name: "Sort articles" }).selectOption("score")
  await expect(page).toHaveURL(/sort=score/)
  expect(diagnostics.articleQueries.at(-1)).toContain("sort=score")
  expect(diagnostics.articleQueries.at(-1)).toContain("language=en")
  expect(diagnostics.articleQueries.at(-1)).toContain("topic=AI")
  expect(diagnostics.articleQueries.at(-1)).toContain("topic=Tech")

  await page.goBack()
  await expect(page.getByRole("combobox", { name: "Sort articles" })).toHaveValue("newest")
  await page.getByRole("button", { name: "Remove filter AI" }).click()
  await expect(page).toHaveURL(/language=en&topic=Tech$/)
  await page.getByRole("button", { name: "Clear all" }).click()
  await expect(page).toHaveURL("/feed")

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("collections selection, creation, errors, and URL history coexist with Feed", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/feed?language=en")

  const sidebar = page.getByRole("complementary", { name: "Collections" })
  await expect(sidebar).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Research.*2 articles/ })).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Empty.*0 articles/ })).toBeVisible()

  await sidebar.getByRole("button", { name: /Research.*2 articles/ }).click()
  await expect(page).toHaveURL(`/feed?language=en&collection_id=${researchCollectionId}`)
  await expect(sidebar.getByRole("button", { name: /Research.*2 articles/ })).toHaveAttribute("aria-current", "page")
  await expect(page.getByRole("article")).toHaveCount(2)
  expect(diagnostics.articleQueries.at(-1)).toContain(`collection_id=${researchCollectionId}`)
  expect(diagnostics.articleQueries.at(-1)).toContain("language=en")

  await page.getByRole("combobox", { name: "Sort articles" }).selectOption("score")
  await expect(page).toHaveURL(new RegExp(`collection_id=${researchCollectionId}.*sort=score|sort=score.*collection_id=${researchCollectionId}`))
  expect(diagnostics.articleQueries.at(-1)).toContain("sort=score")
  expect(diagnostics.articleQueries.at(-1)).toContain(`collection_id=${researchCollectionId}`)

  await page.goBack()
  await expect(page.getByRole("combobox", { name: "Sort articles" })).toHaveValue("newest")
  await expect(sidebar.getByRole("button", { name: /Research.*2 articles/ })).toHaveAttribute("aria-current", "page")
  await page.goBack()
  await expect(page).toHaveURL("/feed?language=en")
  await expect(sidebar.getByRole("button", { name: "All articles" })).toHaveAttribute("aria-current", "page")
  await page.goForward()
  await expect(sidebar.getByRole("button", { name: /Research.*2 articles/ })).toHaveAttribute("aria-current", "page")

  await sidebar.getByRole("button", { name: /Empty.*0 articles/ }).click()
  await expect(page.getByText("Empty is empty")).toBeVisible()
  await expect(page.getByText(/Use Save to Collection/)).toBeVisible()

  await sidebar.getByRole("button", { name: "Create new collection" }).click()
  const dialog = page.getByRole("dialog", { name: "New Collection" })
  const nameInput = dialog.getByRole("textbox", { name: "Collection name" })
  await expect(nameInput).toBeFocused()
  await dialog.getByRole("button", { name: "Cancel" }).click()
  await expect(dialog).toBeHidden()
  await expect(sidebar.getByRole("button", { name: "Create new collection" })).toBeFocused()

  await sidebar.getByRole("button", { name: "Create new collection" }).click()
  await expect(nameInput).toBeFocused()
  await expect(nameInput).toHaveValue("")
  await page.screenshot({ path: testInfo.outputPath("feed-4c1-dialog-1440x1000.png"), fullPage: true })
  await nameInput.fill("  Reading Queue  ")
  await dialog.getByRole("button", { name: "Create collection" }).click()
  await expect(dialog).toBeHidden()
  await expect(page).toHaveURL(new RegExp(`collection_id=${createdCollectionId}`))
  await expect(sidebar.getByRole("button", { name: /Reading Queue.*0 articles/ })).toHaveAttribute("aria-current", "page")
  await expect(page.getByText("Reading Queue is empty")).toBeVisible()

  await sidebar.getByRole("button", { name: "Create new collection" }).click()
  const duplicateDialog = page.getByRole("dialog", { name: "New Collection" })
  await duplicateDialog.getByRole("textbox", { name: "Collection name" }).fill("research")
  await duplicateDialog.getByRole("button", { name: "Create collection" }).click()
  await expect(duplicateDialog.getByRole("alert")).toHaveText("article collection name already exists")
  await duplicateDialog.getByRole("button", { name: "Cancel" }).click()

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath("feed-4c1-1440x1000.png"), fullPage: true })
  expect(diagnostics.consoleErrors).toEqual([
    "Failed to load resource: the server responded with a status of 409 (Conflict)",
  ])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual(["409 /api/backend/article-collections"])
})

test("collection management renames and deletes while preserving URL state", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(`/feed?language=en&collection_id=${researchCollectionId}&sort=score`)
  const sidebar = page.getByRole("complementary", { name: "Collections" })

  const allFeed = sidebar.getByRole("button", { name: "All articles" })
  await allFeed.click({ button: "right" })
  await expect(page.getByRole("menu")).toHaveCount(0)
  await page.getByRole("heading", { name: "Feed" }).click({ button: "right" })
  await expect(page.getByRole("menu")).toHaveCount(0)

  const researchRow = sidebar.getByRole("button", { name: /Research.*2 articles/ })
  await researchRow.click({ button: "right", position: { x: 140, y: 22 } })
  const pointerMenu = page.getByRole("menu", { name: "Manage Research" })
  await expect(pointerMenu.getByRole("menuitem", { name: "Rename" })).toBeFocused()
  const menuBounds = await pointerMenu.boundingBox()
  expect(menuBounds).not.toBeNull()
  expect(menuBounds!.x).toBeGreaterThanOrEqual(8)
  expect(menuBounds!.x + menuBounds!.width).toBeLessThanOrEqual(1432)
  expect(menuBounds!.y + menuBounds!.height).toBeLessThanOrEqual(992)
  await page.keyboard.press("Escape")
  await expect(pointerMenu).toBeHidden()
  await expect(researchRow).toBeFocused()

  await page.keyboard.press("Shift+F10")
  const keyboardMenu = page.getByRole("menu", { name: "Manage Research" })
  await expect(keyboardMenu.getByRole("menuitem", { name: "Rename" })).toBeFocused()
  await page.screenshot({ path: testInfo.outputPath("feed-4e-context-1440x1000.png"), fullPage: true })
  await page.keyboard.press("ArrowDown")
  await expect(keyboardMenu.getByRole("menuitem", { name: "Delete" })).toBeFocused()
  await page.keyboard.press("ArrowUp")
  await page.keyboard.press("Enter")
  const renameDialog = page.getByRole("dialog", { name: "Rename Collection" })
  const renameInput = renameDialog.getByRole("textbox", { name: "Collection name" })
  await expect(renameInput).toBeFocused()
  await expect(renameInput).toHaveValue("Research")
  await expect(renameDialog.getByRole("button", { name: "Rename" })).toBeDisabled()
  await renameInput.fill("  Editorial Research  ")
  await renameDialog.getByRole("button", { name: "Rename" }).click()
  await expect(renameDialog).toBeHidden()
  const renamedRow = sidebar.getByRole("button", { name: /Editorial Research.*2 articles/ })
  await expect(renamedRow).toHaveAttribute("aria-current", "page")
  await expect(page).toHaveURL(`/feed?language=en&collection_id=${researchCollectionId}&sort=score`)
  await expect(renamedRow).toBeFocused()

  await page.keyboard.press("ContextMenu")
  await page.getByRole("menuitem", { name: "Rename" }).click()
  const duplicateDialog = page.getByRole("dialog", { name: "Rename Collection" })
  await duplicateDialog.getByRole("textbox", { name: "Collection name" }).fill("empty")
  await duplicateDialog.getByRole("button", { name: "Rename" }).click()
  await expect(duplicateDialog.getByRole("alert")).toHaveText("article collection name already exists")
  await duplicateDialog.getByRole("button", { name: "Cancel" }).click()

  const emptyRow = sidebar.getByRole("button", { name: /Empty.*0 articles/ })
  await emptyRow.click({ button: "right" })
  await page.getByRole("heading", { name: "Feed" }).click()
  await expect(page.getByRole("menu")).toHaveCount(0)
  await emptyRow.focus()
  await page.keyboard.press("Shift+F10")
  await page.getByRole("menuitem", { name: "Delete" }).click()
  const emptyDelete = page.getByRole("dialog", { name: "Delete Collection?" })
  await expect(emptyDelete).toContainText("Empty contains 0 saved articles")
  await expect(emptyDelete).toContainText("Articles themselves are not deleted from NewsCraft")
  await page.screenshot({ path: testInfo.outputPath("feed-4d-delete-1440x1000.png"), fullPage: true })
  await emptyDelete.getByRole("button", { name: "Delete Collection" }).click()
  await expect(emptyDelete).toBeHidden()
  await expect(sidebar.getByRole("button", { name: /Empty.*0 articles/ })).toHaveCount(0)
  await expect(page).toHaveURL(`/feed?language=en&collection_id=${researchCollectionId}&sort=score`)

  await renamedRow.click({ button: "right" })
  await page.getByRole("menuitem", { name: "Delete" }).click()
  const selectedDelete = page.getByRole("dialog", { name: "Delete Collection?" })
  await selectedDelete.getByRole("button", { name: "Delete Collection" }).click()
  await expect(selectedDelete).toBeHidden()
  await expect(page).toHaveURL("/feed?language=en&sort=score")
  await expect(sidebar.getByRole("button", { name: "All articles" })).toHaveAttribute("aria-current", "page")
  await expect(page.getByRole("article")).toHaveCount(6)

  expect(diagnostics.consoleErrors).toEqual([
    "Failed to load resource: the server responded with a status of 409 (Conflict)",
  ])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([
    `409 /api/backend/article-collections/${researchCollectionId}`,
  ])
})

test("save dialog edits multiple memberships and reconciles Feed and sidebar state", async ({ page }, testInfo) => {
  const diagnostics = await installFeedBackend(page)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto("/feed")

  const sidebar = page.getByRole("complementary", { name: "Collections" })
  const thirdCard = page.getByRole("article").nth(2)
  const trigger = thirdCard.getByRole("button", { name: "Save article to collection" })
  trigger.focus()
  await trigger.click()
  const dialog = page.getByRole("dialog", { name: "Save to Collection" })
  const research = dialog.getByRole("checkbox", { name: /Research.*2 articles/ })
  const empty = dialog.getByRole("checkbox", { name: /Empty.*0 articles/ })
  await expect(research).toBeFocused()
  await expect(research).not.toBeChecked()
  await research.check()
  await empty.check()

  await dialog.getByRole("textbox", { name: "Create a collection" }).fill("  Reading Queue  ")
  await dialog.getByRole("button", { name: "Create" }).click()
  await expect(dialog.getByRole("checkbox", { name: /Reading Queue.*0 articles/ })).toBeChecked()
  await page.screenshot({ path: testInfo.outputPath("feed-4c2-dialog-1440x1000.png"), fullPage: true })
  await dialog.getByRole("button", { name: "Apply" }).click()
  await expect(dialog).toBeHidden()
  await expect(thirdCard.getByRole("button", { name: "Save article to collection" })).toHaveAttribute("aria-pressed", "true")
  await expect(sidebar.getByRole("button", { name: /Research.*3 articles/ })).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Empty.*1 article/ })).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Reading Queue.*1 article/ })).toBeVisible()
  await expect(page.locator(":focus")).toHaveAttribute("aria-label", "Save article to collection")

  await page.reload()
  const persistedCard = page.getByRole("article").nth(2)
  await expect(persistedCard.getByRole("button", { name: "Save article to collection" })).toHaveAttribute("aria-pressed", "true")
  await persistedCard.getByRole("button", { name: "Save article to collection" }).click()
  const persistedDialog = page.getByRole("dialog", { name: "Save to Collection" })
  await expect(persistedDialog.getByRole("checkbox", { name: /Research/ })).toBeChecked()
  await expect(persistedDialog.getByRole("checkbox", { name: /Empty/ })).toBeChecked()
  await expect(persistedDialog.getByRole("checkbox", { name: /Reading Queue/ })).toBeChecked()
  await persistedDialog.getByRole("button", { name: "Cancel" }).click()

  await sidebar.getByRole("button", { name: /Empty.*1 article/ }).click()
  await expect(page.getByRole("article")).toHaveCount(1)
  await page.getByRole("article").getByRole("button", { name: "Remove article from Empty" }).click()
  await expect(page.getByRole("dialog", { name: "Save to Collection" })).toHaveCount(0)
  await expect(page.getByRole("article")).toHaveCount(0)
  await expect(page.getByText("Empty is empty")).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Empty.*0 articles/ })).toBeVisible()
  await sidebar.getByRole("button", { name: /Research.*3 articles/ }).click()
  await expect(page.getByRole("heading", { name: "English editorial report 3" })).toBeVisible()
  await page.screenshot({ path: testInfo.outputPath("feed-4c2-save-1440x1000.png"), fullPage: true })

  expect(diagnostics.consoleErrors).toEqual([])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([])
})

test("save dialog keeps confirmed server truth after a partial mutation failure", async ({ page }) => {
  const diagnostics = await installFeedBackend(page, { failFirstMembershipMutation: true })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto("/feed")

  await page.getByRole("article").nth(2).getByRole("button", { name: /Save/ }).click()
  const dialog = page.getByRole("dialog", { name: "Save to Collection" })
  const research = dialog.getByRole("checkbox", { name: /Research/ })
  await research.check()
  await dialog.getByRole("button", { name: "Apply" }).click()
  await expect(dialog.getByRole("alert")).toContainText("Confirmed memberships were reloaded")
  await expect(research).not.toBeChecked()
  await research.check()
  await dialog.getByRole("button", { name: "Apply" }).click()
  await expect(dialog).toBeHidden()

  expect(diagnostics.consoleErrors).toEqual([
    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  ])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([
    `503 /api/backend/article-collections/${researchCollectionId}/articles/11111111-1111-4111-8111-000000000003`,
  ])
})

test("direct collection removal keeps the card on failure and retries safely", async ({ page }) => {
  const diagnostics = await installFeedBackend(page, { failFirstMembershipMutation: true })
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto(`/feed?collection_id=${researchCollectionId}`)
  const sidebar = page.getByRole("complementary", { name: "Collections" })
  await expect(page.getByRole("article")).toHaveCount(2)

  await page.getByRole("article").first().getByRole("button", { name: "Remove article from Research" }).click()
  await expect(page.getByRole("alert").filter({ hasText: "temporary membership failure" })).toBeVisible()
  await expect(page.getByRole("article")).toHaveCount(2)
  await expect(page.getByRole("dialog", { name: "Save to Collection" })).toHaveCount(0)
  await page.getByRole("button", { name: "Retry removal" }).click()
  await expect(page.getByRole("article")).toHaveCount(1)
  await expect(page.getByText("1 article · source monitoring and saved collections", { exact: true })).toBeVisible()
  await expect(sidebar.getByRole("button", { name: /Research.*1 article/ })).toBeVisible()
  await expect(page).toHaveURL(`/feed?collection_id=${researchCollectionId}`)

  expect(diagnostics.consoleErrors).toEqual([
    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  ])
  expect(diagnostics.pageErrors).toEqual([])
  expect(diagnostics.failedRequests).toEqual([])
  expect(diagnostics.badResponses).toEqual([
    `503 /api/backend/article-collections/${researchCollectionId}/articles/11111111-1111-4111-8111-000000000001`,
  ])
})

async function installFeedBackend(page: Page, options: { failFirstMembershipMutation?: boolean } = {}) {
  const collections = [
    collectionWire(researchCollectionId, "Research", 2),
    collectionWire(emptyCollectionId, "Empty", 0),
  ]
  const memberships = new Map<string, Set<string>>([
    [articleId(1), new Set([researchCollectionId])],
    [articleId(2), new Set([researchCollectionId])],
  ])
  let failNextMembershipMutation = options.failFirstMembershipMutation ?? false
  const diagnostics = {
    consoleErrors: [] as string[],
    pageErrors: [] as string[],
    failedRequests: [] as string[],
    badResponses: [] as string[],
    articleQueries: [] as string[],
    articleDetailQueries: [] as string[],
  }
  page.on("console", (message) => {
    if (message.type() === "error") diagnostics.consoleErrors.push(message.text())
  })
  page.on("pageerror", (error) => diagnostics.pageErrors.push(error.message))
  page.on("requestfailed", (request) => diagnostics.failedRequests.push(request.url()))
  page.on("response", (response) => {
    if (response.status() >= 400) {
      diagnostics.badResponses.push(`${response.status()} ${new URL(response.url()).pathname}`)
    }
  })

  await page.route("https://assets.example/**", async (route) => {
    const broken = route.request().url().endsWith("broken.png")
    await route.fulfill({
      status: 200,
      contentType: "image/png",
      body: broken
        ? Buffer.from("invalid image bytes")
        : Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"),
    })
  })

  await page.route("**/api/backend/**", async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api\/backend/, "")
    if (path === "/operator-settings/date-time") return fulfillJson(route, {
      timezone: "Asia/Tehran", updated_at: "2026-07-21T08:00:00Z",
    })
    if (path === "/automation-control") return fulfillJson(route, {
      global_pause: false, dry_run: true, pause_reason: null, paused_at: null, updated_at: "2026-07-21T08:00:00Z",
    })
    if (path === "/jobs/summary") return fulfillJson(route, { queued: 0, running: 0, attention: 0, succeeded_today: 0 })
    if (path === "/article-collections" && route.request().method() === "GET") {
      return fulfillJson(route, collections.map((collection) => ({
        ...collection,
        article_count: [...memberships.values()].filter((ids) => ids.has(collection.id)).length,
      })))
    }
    if (path === "/article-collections" && route.request().method() === "POST") {
      const body = route.request().postDataJSON() as { name?: string }
      const name = body.name?.trim() ?? ""
      if (collections.some((collection) => collection.name.toLocaleLowerCase() === name.toLocaleLowerCase())) {
        return fulfillUncontractedJson(route, { detail: "article collection name already exists" }, 409)
      }
      const created = collectionWire(createdCollectionId, name, 0)
      collections.push(created)
      return fulfillJson(route, created, 201)
    }
    const collectionMatch = path.match(/^\/article-collections\/([^/]+)$/)
    if (collectionMatch && route.request().method() === "PATCH") {
      const collection = collections.find((item) => item.id === collectionMatch[1])
      if (!collection) return fulfillUncontractedJson(route, { detail: "article collection not found" }, 404)
      const body = route.request().postDataJSON() as { name?: string }
      const name = body.name?.trim() ?? ""
      if (collections.some((item) => item.id !== collection.id && item.name.toLocaleLowerCase() === name.toLocaleLowerCase())) {
        return fulfillUncontractedJson(route, { detail: "article collection name already exists" }, 409)
      }
      collection.name = name
      collection.updated_at = "2026-07-22T08:00:00Z"
      return fulfillJson(route, {
        ...collection,
        article_count: [...memberships.values()].filter((ids) => ids.has(collection.id)).length,
      })
    }
    if (collectionMatch && route.request().method() === "DELETE") {
      const index = collections.findIndex((collection) => collection.id === collectionMatch[1])
      if (index === -1) return fulfillUncontractedJson(route, { detail: "article collection not found" }, 404)
      const [deleted] = collections.splice(index, 1)
      for (const articleMemberships of memberships.values()) articleMemberships.delete(deleted.id)
      // API unit coverage verifies the real endpoint's 204 contract.
      return fulfillUncontractedJson(route, {})
    }
    const membershipMatch = path.match(/^\/article-collections\/([^/]+)\/articles\/([^/]+)$/)
    if (membershipMatch && ["PUT", "DELETE"].includes(route.request().method())) {
      const [, collectionId, requestedArticleId] = membershipMatch
      if (failNextMembershipMutation) {
        failNextMembershipMutation = false
        return fulfillUncontractedJson(route, { detail: "temporary membership failure" }, 503)
      }
      if (!collections.some((collection) => collection.id === collectionId)) {
        return fulfillUncontractedJson(route, { detail: "article collection not found" }, 404)
      }
      const articleMemberships = memberships.get(requestedArticleId) ?? new Set<string>()
      if (route.request().method() === "PUT") articleMemberships.add(collectionId)
      else articleMemberships.delete(collectionId)
      memberships.set(requestedArticleId, articleMemberships)
      // Playwright's Chromium route shim reports fulfilled 204 requests as net::ERR_ABORTED.
      // Use an empty 200 here; API unit coverage verifies production's real 204 contract.
      return fulfillUncontractedJson(route, {})
    }
    if (path === "/articles/facets") return fulfillJson(route, facets())
    const articleDetailMatch = path.match(/^\/articles\/([^/]+)$/)
    if (articleDetailMatch) {
      diagnostics.articleDetailQueries.push(articleDetailMatch[1])
      const index = Number(articleDetailMatch[1].slice(-12))
      return fulfillJson(route, articleDetail(index))
    }
    if (path === "/articles") {
      diagnostics.articleQueries.push(url.search)
      const collectionId = url.searchParams.get("collection_id")
      if (collectionId && !collections.some((collection) => collection.id === collectionId)) {
        return fulfillUncontractedJson(route, { detail: "article collection not found" }, 404)
      }
      const titleQuery = url.searchParams.get("q")?.trim().toLocaleLowerCase() ?? ""
      const matchingIndexes = Array.from({ length: 7 }, (_, index) => index + 1)
        .filter((index) => !titleQuery || article(index).title.toLocaleLowerCase().includes(titleQuery))
      if (collectionId) {
        const items = matchingIndexes
          .filter((index) => memberships.get(articleId(index))?.has(collectionId))
          .map((index) => article(index, [...(memberships.get(articleId(index)) ?? [])]))
        return fulfillJson(route, { items, next_cursor: null, result_count: items.length })
      }
      if (titleQuery) {
        const offset = url.searchParams.has("cursor") ? 3 : 0
        const items = matchingIndexes.slice(offset, offset + 3)
          .map((index) => article(index, [...(memberships.get(articleId(index)) ?? [])]))
        return fulfillJson(route, {
          items,
          next_cursor: offset + 3 < matchingIndexes.length ? "search-page-2" : null,
          result_count: matchingIndexes.length,
        })
      }
      if (url.searchParams.has("cursor")) {
        return fulfillJson(route, { items: [article(1, [...(memberships.get(articleId(1)) ?? [])]), article(7, [...(memberships.get(articleId(7)) ?? [])])], next_cursor: null, result_count: 7 })
      }
      return fulfillJson(route, {
        items: Array.from({ length: 6 }, (_, index) => article(index + 1, [...(memberships.get(articleId(index + 1)) ?? [])])),
        next_cursor: "page-2",
        result_count: 7,
      })
    }
    return fulfillJson(route, { detail: `Unhandled test request: ${path}` }, 501)
  })
  return diagnostics
}

function collectionWire(id: string, name: string, articleCount: number) {
  return {
    id,
    name,
    article_count: articleCount,
    created_at: "2026-07-21T08:00:00Z",
    updated_at: "2026-07-21T08:00:00Z",
  }
}

function article(index: number, savedCollectionIds: string[] = []) {
  const persian = index === 2
  const ageByIndex = [0, 4 * 60 * 60_000, 24 * 60 * 60_000, 21 * 24 * 60 * 60_000, 60 * 24 * 60 * 60_000, 8 * 60 * 60_000, 2 * 24 * 60 * 60_000]
  const displayAt = new Date(Date.now() - (ageByIndex[index] ?? 60 * 60_000)).toISOString()
  const image = index === 3 ? null : {
    id: `44444444-4444-4444-8444-${String(index).padStart(12, "0")}`,
    url: index === 4 ? "https://assets.example/broken.png" : `https://assets.example/${index}.png`,
    kind: "image",
    width: 1200,
    height: 675,
    alt_text: index === 1 ? "Editorial newsroom" : null,
    fetch_status: "remote_only",
  }
  return {
    id: articleId(index),
    title: persian ? "گزارش فارسی هوش مصنوعی" : index === 5 ? "A deliberately longer English headline that proves multi-line card titles stay aligned" : `English editorial report ${index}`,
    summary: "Hidden summary",
    excerpt: null,
    source: { id: sourceId, name: persian ? "خبرگزاری نمونه" : "Wire Desk", platform: "rss", homepage_url: "https://wire.example" },
    canonical_url: `https://wire.example/report-${index}`,
    published_at: index === 6 ? null : displayAt,
    sort_at: displayAt,
    display_at: displayAt,
    date_basis: index === 6 ? "collected" : "published",
    score: 50 + index,
    content_type: index === 1 || index === 4 ? "article" : index === 2 ? "news" : index % 2 ? "news" : "analysis",
    topic: index === 1 || index === 4 ? "News" : index === 2 ? "NEWS" : index % 2 ? "AI" : "Tech",
    domain: "wire.example",
    language: persian ? "fa" : "en",
    direction: persian ? "rtl" : "ltr",
    coverage: { state: "complete", stories: [] },
    article_readiness: { ready: true },
    image,
    has_image: image !== null,
    saved: savedCollectionIds.length > 0,
    saved_collection_ids: savedCollectionIds,
  }
}

function articleDetail(index: number) {
  return {
    ...article(index),
    article_readiness: { ready: true, reason: "Ready for rewrite", blockers: [] },
    content_text: Array.from(
      { length: 24 },
      (_, paragraph) => `Complete normalized article body paragraph ${paragraph + 1}. ${"Grounded source text. ".repeat(10)}`,
    ).join("\n\n"),
    content_origin: "source_provided",
    sanitized_html: null,
    authors: ["Reporter One"],
    tags: ["AI", "news"],
    media: [],
    story_links: [],
    evidence_references: [],
    advanced: {
      item_type: "article",
      status: "new",
      rewrite_bucket: "technical_article",
      classification_reasons: [],
      source_tier: "A",
      freshness_bucket: "fresh",
      quality_status: "good",
      title_quality: "meaningful",
      title_was_generated: false,
      content_intent: null,
      duplicate_of_id: null,
      date_source: "source",
      date_parse_status: "parsed",
      created_at: "2026-07-21T08:01:00Z",
      updated_at: "2026-07-21T08:01:00Z",
      raw_classification: { content_type: "news", topic: "AI", language: "en" },
    },
  }
}

function articleId(index: number) {
  return `11111111-1111-4111-8111-${String(index).padStart(12, "0")}`
}

function facets() {
  return {
    languages: [{ value: "en", count: 6 }, { value: "fa", count: 1 }],
    topics: [{ value: "AI", count: 4 }, { value: "Tech", count: 3 }],
    content_types: [{ value: "news", count: 4 }, { value: "analysis", count: 3 }],
    sources: [{ id: sourceId, name: "Wire Desk", platform: "rss", count: 7 }],
    coverage: [{ value: "complete", count: 7 }],
  }
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await fulfillMockJson(route, body, status)
}

async function fulfillUncontractedJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}
