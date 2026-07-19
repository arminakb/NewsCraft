import { expect, test, type Page } from "@playwright/test"

import { installMockBackend, type MockStory } from "./support/mock-backend"

const STORY_COUNT = 10_000
const PAGE_SIZE = 100

const stories = Array.from({ length: STORY_COUNT }, (_, index) => ({
  id: `performance-story-${index + 1}`,
  title: `Performance story ${index + 1}`,
  status: "inbox",
  primary_language: "en",
  evidence_count: 2,
  latest_evidence_at: "2026-07-13T08:00:00Z",
  completeness: { complete: false, score: 40, reasons: ["More sources needed"] },
  evidence_set_hash: index.toString(16).padStart(64, "0"),
  created_at: "2026-07-13T07:00:00Z",
  updated_at: "2026-07-13T08:00:00Z",
})) satisfies MockStory[]

for (const availableStoryCount of [200, 1_000, 10_000]) {
  test(`keeps a ${availableStoryCount.toLocaleString("en-US")}-story inbox within its page and interaction budgets`, async ({ page }) => {
    const unhandledRequests = await installMockBackend(page, { stories: stories.slice(0, availableStoryCount) })

    await page.goto("/inbox")
    const rows = page.locator("[data-story-row]")
    await expect(rows).toHaveCount(PAGE_SIZE)

    const initialUsableMs = await page.evaluate(() => {
      const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming
      return performance.now() - navigation.responseStart
    })
    expect(initialUsableMs).toBeLessThanOrEqual(1_500)

    const selectionFeedbackMs = await clickAndPaint(page, "Select visible page")
    expect(selectionFeedbackMs).toBeLessThanOrEqual(100)
    await expect(page.getByText("100 stories selected", { exact: true })).toBeVisible()

    await page.getByRole("button", { name: "Load next page" }).click()
    await expect(page.getByRole("checkbox", { name: "Select Performance story 101" })).toBeVisible()
    await expect(rows).toHaveCount(PAGE_SIZE)
    await expect(page.getByRole("checkbox", { name: "Select Performance story 1", exact: true })).toHaveCount(0)

    const selectSecondPageMs = await clickAndPaint(page, "Select visible page")
    expect(selectSecondPageMs).toBeLessThanOrEqual(100)
    await expect(page.getByText("200 stories selected", { exact: true })).toBeVisible()

    const singleToggleMs = await page.evaluate(async () => {
      const checkbox = document.querySelector<HTMLInputElement>("[data-story-row] input[type=checkbox]")
      if (!checkbox) throw new Error("Story checkbox was not rendered")
      const startedAt = performance.now()
      checkbox.click()
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
      return performance.now() - startedAt
    })
    expect(singleToggleMs).toBeLessThanOrEqual(100)

    expect(unhandledRequests, "Unhandled backend requests in inbox performance test").toEqual([])
  })
}

async function clickAndPaint(page: Page, text: string) {
  return page.evaluate(async (buttonText) => {
    const button = Array.from(document.querySelectorAll("button"))
      .find((candidate) => candidate.textContent === buttonText) as HTMLButtonElement | undefined
    if (!button) throw new Error(`${buttonText} button was not rendered`)
    const startedAt = performance.now()
    button.click()
    await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
    return performance.now() - startedAt
  }, text)
}
