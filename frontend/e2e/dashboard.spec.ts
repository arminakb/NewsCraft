import { expect, test } from "@playwright/test"

test.describe("NewsCraft dashboard", () => {
  test("desktop layout shows all primary dashboard regions without page overflow", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto("/")

    await expect(page.getByRole("navigation", { name: /dashboard navigation/i })).toBeVisible()
    await expect(page.getByText("PostgreSQL")).toBeVisible()
    await expect(page.getByRole("region", { name: /source details/i })).toBeVisible()
    await expect(page.getByText("Source health")).toBeVisible()
    await expect(page.getByRole("region", { name: /media extraction/i })).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(hasHorizontalOverflow).toBe(false)
  })

  test("mobile layout stacks content and opens source details as an overlay", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto("/")

    await expect(page.getByRole("button", { name: /run ingest/i })).toBeVisible()
    await expect(page.getByRole("region", { name: /source details/i })).toBeHidden()

    await page.getByRole("button", { name: /open dw persian details/i }).click()

    await expect(page.getByRole("region", { name: /source details/i })).toBeVisible()
    await expect(page.getByRole("heading", { name: "DW Persian" })).toBeVisible()
  })
})
