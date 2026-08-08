import { expect, test } from "./helpers/fixtures";

/**
 * The tab title is what the browser shows and what a shared link previews as.
 * Both come from one captured value, so these assert the rendered result:
 * Titles name the current page and its event or sphere, using bullets only.
 */
test.describe("Page titles", () => {
  test("names the page, then the sphere, and shares under the same title", async ({ page }) => {
    await page.goto("/event/autumn-open/");

    await expect(page).toHaveTitle(/^Autumn Open Playtest • /);
    await expect(page).not.toHaveTitle(/[-—]/);

    const ogTitle = page.locator('meta[property="og:title"]');
    const twitterTitle = page.locator('meta[name="twitter:title"]');
    await expect(ogTitle).toHaveAttribute("content", await page.title());
    await expect(twitterTitle).toHaveAttribute("content", await page.title());
  });

  test("names an organizer's event in panel and print titles", async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();

    await page.goto("/panel/event/frostfire-con/proposals/");

    await expect(page).toHaveTitle(/^Proposals • Frostfire Game Convention/);

    await page.goto("/event/frostfire-con/print/?material=door-cards");

    await expect(page).toHaveTitle("Frostfire Game Convention • Print • Root Domain Sphere");
  });
});
