import { expect, test } from "./helpers/fixtures";

/**
 * The tab title is what the browser shows and what a shared link previews as.
 * Both come from one captured value, so these assert the rendered result:
 * "{page} • {sphere or event} • {brand}", bullets only, never a dash.
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

  test("names the event an organizer manages, not their sphere", async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();

    await page.goto("/panel/event/frostfire-con/proposals/");

    await expect(page).toHaveTitle(/^Proposals • Frostfire Game Convention/);

    await page.goto("/panel/event/frostfire-con/timetable/print/door-cards/");

    await expect(page).toHaveTitle(/^Door cards • Frostfire Game Convention/);
  });
});
