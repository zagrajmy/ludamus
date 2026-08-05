import { expect, test } from "./helpers/fixtures";

// The form used to be a CSS multi-column masonry, and the tall column painted
// over the footer. Read the layout mode itself, not how many cards the event's
// data happens to render: multicol computes grid-template-columns: none, grid
// computes one px track per column.
//
// Only the column contract is pinned. The overlap it caused is not: measuring
// the lowest card's bottom against the footer passes on the pre-fix markup too
// (Chromium expands the multicol box to its tallest column), so an assertion
// about it would read as coverage without ever failing.
const columnCount = async (page: import("@playwright/test").Page) =>
  page.locator("#proposal-form").evaluate((form) => {
    const { display, gridTemplateColumns } = getComputedStyle(form);
    return display === "grid" ? gridTemplateColumns.split(" ").length : 0;
  });

test.describe("Proposal form layout", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("keeps three columns wide, two medium, one narrow", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/panel/event/frostfire-con/proposals/create/");
    await expect(page.locator("#proposal-form")).toBeVisible();

    expect(await columnCount(page)).toBe(3);

    await page.setViewportSize({ width: 1100, height: 900 });
    expect(await columnCount(page)).toBe(2);

    await page.setViewportSize({ width: 480, height: 900 });
    expect(await columnCount(page)).toBe(1);
  });

  // The organizer's own form is unbounded. A `max` attribute here is what
  // produced a bare browser tooltip ("Wartość nie może być większa niż 255.")
  // on a ceiling the category carried for submitters — assert the rendered
  // attribute, since that, not the field's Python state, is what blocked them.
  test("leaves the participants limit uncapped", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/proposals/create/");

    const limit = page.locator("#id_participants_limit");
    await expect(limit).toBeVisible();
    await expect(limit).not.toHaveAttribute("max", /./);

    await limit.fill("500");
    expect(await limit.evaluate((input: HTMLInputElement) => input.checkValidity())).toBe(true);
    await expect(page.getByText(/Empty or 0 = no limit/)).toBeVisible();
  });
});
