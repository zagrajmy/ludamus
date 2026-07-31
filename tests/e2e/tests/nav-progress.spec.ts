import { expect, test } from "./helpers/fixtures";

// The panel shows a thin top-edge progress bar while a request is in flight
// (nav-progress.ts). The link-click test slows the next navigation down with
// a routed delay so the bar's appearance is deterministic; the htmx tests
// drive the events the bar listens to directly. Assertions are on what the
// user perceives: a loading progressbar during a slow request, none once the
// response lands.

const bar = (page: import("@playwright/test").Page) =>
  page.getByRole("progressbar", { name: /loading/i });

test.describe("panel navigation progress bar", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await page.goto("/panel/");
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);
  });

  test("appears while a slow full-page navigation is pending", async ({ page }) => {
    // Hold the proposals page response long enough for the bar to pass its
    // anti-flicker delay while the old page is still on screen.
    await page.route("**/proposals/", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.continue();
    });

    // click() auto-waits for the navigation it triggers, and the bar lives
    // only in the old document while that navigation is pending — so assert
    // mid-flight and await the click after.
    const navigation = page.getByRole("link", { name: "Proposals", exact: true }).click();
    await expect(bar(page)).toBeVisible();
    await navigation;

    // The new document replaces the old one, bar included.
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
