import { expect, test } from "./helpers/fixtures";

type Page = import("@playwright/test").Page;

declare global {
  interface Window {
    appVhWrites?: string[];
  }
}

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

  test("the published height follows the viewport", async ({ page }) => {
    const before = await shellHeight(page);
    await page.setViewportSize({ width: 390, height: before - 140 });

    // Polled, not flushed over two frames: the write may be held back for up to
    // one throttle gap, which no number of frames is guaranteed to span.
    //
    // The published value, not the shell's height: 100dvh tracks a viewport
    // resize on its own, so asserting the height alone passes with the module
    // deleted.
    await expect.poll(() => appVh(page)).toBe(`${before - 140}px`);
    expect(await shellHeight(page)).toBe(before - 140);
  });

  test("the shell keeps tracking through a drag and settles on the last height", async ({
    page,
  }) => {
    // The mechanism this guards is the throttle, and the bug it guards against
    // is a debounce: publish once as the drag starts, then nothing until it
    // ends. That leaves the shell taller than the viewport for the whole drag,
    // so the *root* scrolls — the one thing the shell exists to prevent. A
    // single resize cannot tell the two apart, because a debounce publishes
    // immediately for that too. Only a burst longer than one gap can.
    await expect.poll(() => appVh(page)).toMatch(/^\d+px$/);

    await page.evaluate(() => {
      const writes: string[] = [];
      window.appVhWrites = writes;
      new MutationObserver(() => {
        writes.push(document.documentElement.style.getPropertyValue("--app-vh"));
      }).observe(document.documentElement, { attributeFilter: ["style"] });
    });

    const start = await shellHeight(page);
    const steps = 11;
    const stepMs = 60;
    for (let step = 1; step <= steps; step += 1) {
      // Every step but the last is spaced out; the last follows immediately, so
      // it necessarily lands inside a throttle window. Only a trailing write can
      // publish that one.
      if (step > 1 && step < steps) await page.waitForTimeout(stepMs);
      await page.setViewportSize({ width: 390, height: start - step * 20 });
    }
    const settled = `${start - steps * 20}px`;

    // Over a drag of ~600ms a 120ms throttle writes five times or more, where a
    // debounce writes twice however long the drag runs: once at the start and
    // once at the end.
    const writes = await page.evaluate(() => window.appVhWrites ?? []);
    expect(writes.length).toBeGreaterThanOrEqual(4);

    // And the trailing write is what makes the last one exact. A throttle with
    // no trailing edge tracks the drag and then stops short of where it ended.
    await expect.poll(() => appVh(page)).toBe(settled);
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
