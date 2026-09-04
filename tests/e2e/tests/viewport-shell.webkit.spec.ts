import { expect, test } from "./helpers/fixtures";

// NOTE: the suffix asks for WebKit at an iPhone's width; the desktop projects
// match every spec, so this runs there too. None of them has browser chrome,
// so nothing here can speak to how much room mobile Safari gives the page —
// that question belongs to scripts/ios-regressions, on a real device.
//
// What this can check is the shell's scroll ownership, which survived the
// revert of #1030 and is the mechanism the device measurement turned on: the
// document must not scroll, because #app-scroll owns the whole range, and the
// end of the page has to stay reachable through it. An earlier revision also
// asserted the shell's height against visualViewport.height, which was
// self-evident here (no chrome, so they are the same number) and is now moot
// besides — app-viewport.ts and --app-vh went with the revert.
test.describe("App shell scrolling on a phone", () => {
  test("the document does not scroll, and #app-scroll reaches the end of the page", async ({
    page,
  }) => {
    await page.goto("/");

    // The shell clips what overflows it, so the page end is only reachable if
    // the document itself never scrolls and #app-scroll owns the whole range.
    const documentScrolls = await page.evaluate(
      () => document.documentElement.scrollHeight > document.documentElement.clientHeight,
    );
    expect(documentScrolls).toBe(false);

    // Measured, not just looked at. toBeInViewport passes on any intersection,
    // so a footer already peeking into a short page satisfies it without the
    // scroller having moved at all — the assertion would hold even if
    // #app-scroll were inert, which is the whole thing under test.
    const scrolled = await page.evaluate(() => {
      const root = document.getElementById("app-scroll")!;
      const range = root.scrollHeight - root.clientHeight;
      root.scrollTop = root.scrollHeight;
      return {
        range,
        top: root.scrollTop,
        clientHeight: root.clientHeight,
        height: root.scrollHeight,
      };
    });
    // A page with nothing to scroll cannot demonstrate who owns the scrolling.
    expect(scrolled.range).toBeGreaterThan(0);
    expect(scrolled.top).toBeGreaterThan(0);
    expect(scrolled.top + scrolled.clientHeight).toBeCloseTo(scrolled.height, 0);

    await expect(page.getByRole("contentinfo")).toBeInViewport();
  });
});
