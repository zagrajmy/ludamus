import { expect, test } from "./helpers/fixtures";

type Page = import("@playwright/test").Page;

const shellHeight = (page: Page): Promise<number> =>
  page.evaluate(() => Math.round(document.body.getBoundingClientRect().height));

const appVh = (page: Page): Promise<string> =>
  page.evaluate(() => document.documentElement.style.getPropertyValue("--app-vh"));

// Two frames, so a publish deferred to a frame callback would still have landed
// by the time we assert. Without it a broken implementation reads green here
// simply by being late.
const settle = (page: Page): Promise<void> =>
  page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  );

test.describe("App shell viewport height", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("the shell is the height the viewport is showing", { tag: "@ios" }, async ({ page }) => {
    await expect.poll(() => appVh(page)).toMatch(/^\d+px$/);

    const visible = await page.evaluate(() => Math.round(visualViewport!.height));
    expect(await shellHeight(page)).toBe(visible);

    // The shell clips what overflows it, so the page end is only reachable if
    // the document itself never scrolls and #app-scroll owns the whole range.
    const documentScrolls = await page.evaluate(
      () => document.documentElement.scrollHeight > document.documentElement.clientHeight,
    );
    expect(documentScrolls).toBe(false);

    await page.evaluate(() => {
      document.getElementById("app-scroll")!.scrollTop = 1e6;
    });
    await expect(page.locator("footer").first()).toBeInViewport();
  });

  test("the published height follows the viewport", async ({ page }) => {
    const before = await shellHeight(page);
    await page.setViewportSize({ width: 390, height: before - 140 });
    await settle(page);

    // The published value, not the shell's height: 100dvh tracks a viewport
    // resize on its own, so asserting the height alone passes with the module
    // deleted.
    expect(await appVh(page)).toBe(`${before - 140}px`);
    expect(await shellHeight(page)).toBe(before - 140);
  });

  test("pinch-zoom magnifies without resizing the shell", async ({ browserName, page }) => {
    // Emulation.setPageScaleFactor is the only way to drive a real pinch, and it
    // is Chromium-only. The regression it guards is engine-independent:
    // visualViewport.height is the zoomed height, so publishing it unscaled
    // shrank the whole app for as long as someone magnified a card.
    test.skip(browserName !== "chromium", "needs CDP page-scale emulation");

    await expect.poll(() => appVh(page)).toMatch(/^\d+px$/);
    const before = await appVh(page);
    const cdp = await page.context().newCDPSession(page);

    for (const pageScaleFactor of [1.5, 2, 3]) {
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor });
      await settle(page);
      expect(await page.evaluate(() => visualViewport!.scale)).toBeGreaterThan(1);
      expect(await appVh(page)).toBe(before);
    }

    await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
    await settle(page);
    expect(await appVh(page)).toBe(before);
  });
});
