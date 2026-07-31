import { expect, test } from "./helpers/fixtures";

// The panel shows a thin top-edge progress bar while a request is in flight
// (nav-progress.ts). The link-click test slows the next navigation down with
// a routed delay so the bar's appearance is deterministic; the htmx tests
// drive the events the bar listens to directly. Assertions are on what the
// user perceives: a loading progressbar during a slow request, none once the
// response lands.

// No name filter: the accessible label is localized, and the panel has only
// one progressbar.
const bar = (page: import("@playwright/test").Page) => page.getByRole("progressbar");

test.describe("panel navigation progress bar", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await page.goto("/panel/");
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);
  });

  test("appears while a full-page navigation is pending", async ({ page }) => {
    // Locator assertions wait out an in-flight navigation before they query
    // the page, so the bar cannot be observed mid-flight. Cancel the
    // navigation instead: the old document — and the bar the click started —
    // survives a cancelled navigation, and only the 30s failsafe clears it.
    await page.route("**/proposals/", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 800));
      await route.abort("aborted");
    });

    const navigation = page
      .getByRole("link", { name: "Proposals", exact: true })
      .click()
      .catch(() => {
        // The click's navigation wait may reject when the request aborts.
      });
    await expect(bar(page)).toBeVisible();
    await navigation;

    // A navigation that lands replaces the document, bar included.
    await page.unroute("**/proposals/");
    await page.getByRole("link", { name: "Proposals", exact: true }).click();
    await expect(page).toHaveURL(/\/proposals\//);
    await expect(bar(page)).toHaveCount(0);
  });

  test("appears while an htmx request is pending and hides when it completes", async ({ page }) => {
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:beforeRequest", { detail: {} }));
    });

    // Becomes visible only after the anti-flicker delay (180ms).
    await expect(bar(page)).toBeVisible();

    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:afterRequest", { detail: {} }));
    });

    await expect(bar(page)).toHaveCount(0);
  });

  test("never shows for a request that finishes quickly", async ({ page }) => {
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:beforeRequest", { detail: {} }));
      document.dispatchEvent(new CustomEvent("htmx:afterRequest", { detail: {} }));
    });

    // Give the show-delay a chance to (wrongly) fire before asserting.
    await page.waitForTimeout(400);
    await expect(bar(page)).toHaveCount(0);
  });
});
