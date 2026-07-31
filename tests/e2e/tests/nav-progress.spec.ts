import { expect, test } from "./helpers/fixtures";

// The panel shows a thin top-edge progress bar while a request is in flight
// (nav-progress.ts). Real navigations finish too fast to observe reliably, so
// the specs drive the same htmx events the bar listens to and assert on what
// the user perceives: a bar that appears during a slow request and goes away
// when the response lands.

const BAR_SELECTOR = 'div[aria-hidden="true"][style*="position: fixed"]';

test.describe("panel navigation progress bar", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
    await page.goto("/panel/");
    await expect(page).toHaveURL(/\/panel\/event\/[\w-]+\//);
  });

  test("appears while a request is pending and hides when it completes", async ({ page }) => {
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:beforeRequest", { detail: {} }));
    });

    // Becomes visible only after the anti-flicker delay (180ms).
    await expect(page.locator(BAR_SELECTOR)).toBeVisible();

    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:afterRequest", { detail: {} }));
    });

    await expect(page.locator(BAR_SELECTOR)).toHaveCount(0);
  });

  test("never shows for a request that finishes quickly", async ({ page }) => {
    await page.evaluate(() => {
      document.dispatchEvent(new CustomEvent("htmx:beforeRequest", { detail: {} }));
      document.dispatchEvent(new CustomEvent("htmx:afterRequest", { detail: {} }));
    });

    // Give the show-delay a chance to (wrongly) fire before asserting.
    await page.waitForTimeout(400);
    await expect(page.locator(BAR_SELECTOR)).toHaveCount(0);
  });
});
