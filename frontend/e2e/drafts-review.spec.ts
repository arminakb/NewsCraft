import { expect, test } from "@playwright/test"

test("Drafts separates review, handoff, and failed work at mobile width", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.route("**/api/backend/content-pack-requests", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify([
        request("review", "succeeded", "draft"),
        request("ready", "ready", "ready"),
        {
          ...request("failed", "failed", null),
          last_failure: "Provider output failed validation",
        },
      ]),
    })
  })

  await page.goto("/drafts")

  await expect(page.getByRole("heading", { name: "Drafts" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Continue review" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Open handoff" })).toHaveCount(0)

  await page.getByRole("button", { name: /Ready for handoff/ }).click()
  await expect(page.getByRole("link", { name: "Open handoff" })).toBeVisible()
  await expect(page.getByRole("link", { name: "Continue review" })).toHaveCount(0)

  await page.getByRole("button", { name: /Failed/ }).click()
  const blocker = page.getByText("Advanced details — blocker").locator("..")
  await expect(blocker).toHaveAttribute("open", "")
  await expect(page.getByText("Last failure: Provider output failed validation")).toBeVisible()
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll")
})

function request(id: string, status: string, packStatus: string | null) {
  return {
    id: `${id}-request`,
    job_id: `${id}-job`,
    story_id: `${id}-story`,
    status,
    last_failure: null,
    created_at: "2026-07-26T08:00:00Z",
    updated_at: "2026-07-26T08:01:00Z",
    pack: packStatus
      ? {
          id: `${id}-pack`,
          story_id: `${id}-story`,
          story_revision_id: `${id}-story-revision`,
          brand_profile_id: "brand",
          status: packStatus,
          created_at: "2026-07-26T08:00:00Z",
          updated_at: "2026-07-26T08:01:00Z",
          variants: [],
        }
      : null,
  }
}
