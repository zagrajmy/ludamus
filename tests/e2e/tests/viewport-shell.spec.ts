import { expect, test } from "./helpers/fixtures";

const shellHeight = (page: import("@playwright/test").Page): Promise<number> =>
  page.evaluate(() => Math.round(document.body.getBoundingClientRect().height));

const appVh = (page: import("@playwright/test").Page): Promise<string> =>
  page.evaluate(() => document.documentElement.style.getPropertyValue("--app-vh"));

test.describe("App shell viewport height", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("the shell is exactly the height the viewport is showing", async ({ page }) => {
    await expect.poll(() => appVh(page)).toMatch(/^\d+px$/);

    const visible = await page.evaluate(() => Math.round(visualViewport!.height));
    expect(await shellHeight(page)).toBe(visible);

    // The scroller fills the shell, so the end of the page is reachable rather
    // than sitting past a clip edge — the defect this variable exists to fix.
    await page.evaluate(() => {
      document.getElementById("app-scroll")!.scrollTop = 1e6;
    });
    const reachedEnd = await page.evaluate(() => {
      const scroller = document.getElementById("app-scroll")!;
      return Math.abs(scroller.scrollTop + scroller.clientHeight - scroller.scrollHeight) < 2;
    });
    expect(reachedEnd).toBe(true);
  });

  test("the shell follows the viewport when it changes size", async ({ page }) => {
    const before = await shellHeight(page);
    await page.setViewportSize({ width: 390, height: before - 140 });

    await expect.poll(() => shellHeight(page)).toBe(before - 140);
  });

  test("pinch-zoom magnifies without resizing the shell", async ({ browserName, page }) => {
    // Emulation.setPageScaleFactor is the only way to drive a real pinch, and
    // it is Chromium-only. The regression it guards is engine-independent:
    // visualViewport.height is the zoomed height, so publishing it unscaled
    // shrank the whole app for as long as someone magnified a card.
    test.skip(browserName !== "chromium", "needs CDP page-scale emulation");

    const before = await appVh(page);
    const cdp = await page.context().newCDPSession(page);

    for (const pageScaleFactor of [1.5, 2, 3]) {
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor });
      expect(await page.evaluate(() => Math.round(visualViewport!.scale))).toBeGreaterThan(1);
      expect(await appVh(page)).toBe(before);
    }

    await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    expect(await appVh(page)).toBe(before);
  });
});
