import { expect, test } from "@playwright/test"

test.describe("NewsCraft dashboard", () => {
  test("layout shows empty dashboard regions without page overflow", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto("/")

    await expect(page.getByRole("navigation", { name: /dashboard navigation/i })).toBeVisible()
    await expect(page.getByText(/^(?:Backend connected|Backend unavailable|Checking backend)$/)).toBeVisible()
    await expect(page.getByText("Source health")).toBeVisible()
    await expect(page.getByRole("region", { name: /media extraction/i })).toBeVisible()
    await expect(page.getByText("No sources found")).toBeVisible()
    await expect(page.getByRole("region", { name: /ingestion runs/i }).getByText("No ingestion runs yet")).toBeVisible()
    await expect(page.getByText("No content items yet")).toBeVisible()
    await expect(page.getByText("No media assets yet")).toBeVisible()

    const hasHorizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
    expect(hasHorizontalOverflow).toBe(false)

    await page.setViewportSize({ width: 390, height: 844 })

    await expect(page.getByRole("button", { name: /run ingest/i })).toBeVisible()
    await expect(page.getByRole("region", { name: /source details/i })).toBeHidden()
    await expect(page.getByText("No sources found")).toBeVisible()
    await expect(page.getByText("No content items yet")).toBeVisible()
    await expect(page.getByRole("button", { name: /open dw persian details/i })).toHaveCount(0)
  })
})
