import { expect, test } from "./helpers/fixtures";

// The form used to be a CSS multi-column masonry. Cards carrying
// break-inside-avoid overflowed the balanced column box, so the tall column
// painted over the footer and the page ended mid-content.
const columnLefts = async (page: import("@playwright/test").Page) =>
  page
    .locator("#proposal-form .card")
    .evaluateAll((cards) => [
      ...new Set(cards.map((card) => Math.round(card.getBoundingClientRect().left))),
    ]);

test.describe("Proposal form layout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("keeps three columns wide, one narrow, and never covers the footer", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/panel/event/frostfire-con/proposals/create/");
    await expect(page.locator("#proposal-form")).toBeVisible();

    expect(await columnLefts(page)).toHaveLength(3);

    const form = await page.locator("#proposal-form").boundingBox();
    const footer = await page.locator("footer").boundingBox();
    expect(form).not.toBeNull();
    expect(footer).not.toBeNull();
    expect(form!.y + form!.height).toBeLessThanOrEqual(footer!.y + 1);

    await page.setViewportSize({ width: 480, height: 900 });
    expect(await columnLefts(page)).toHaveLength(1);
  });
});
