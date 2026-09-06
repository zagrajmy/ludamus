import { expect, test } from "./helpers/fixtures";

// NOTE: no project here has browser chrome, so how much room mobile Safari
// gives the page is a device question (scripts/ios-regressions). What this can
// check is scroll ownership: the document must not scroll, #app-scroll must,
// and the end of the page has to be reachable through it.
test.describe("App shell scrolling on a phone", () => {
  test("the document does not scroll, and #app-scroll reaches the end of the page", async ({
    page,
  }) => {
    await page.goto("/");

    const documentScrolls = await page.evaluate(
      () => document.documentElement.scrollHeight > document.documentElement.clientHeight,
    );
    expect(documentScrolls).toBe(false);

    // Measured, not just looked at: toBeInViewport passes on any intersection,
    // so a footer already peeking into a short page would satisfy it with an
    // inert scroller.
    const scrolled = await page.evaluate(() => {
      const root = document.getElementById("app-scroll")!;
      const range = root.scrollHeight - root.clientHeight;
      root.scrollTop = root.scrollHeight;
      return { range, top: root.scrollTop, overflowY: getComputedStyle(root).overflowY };
    });
    expect(scrolled.range).toBeGreaterThan(0);
    expect(scrolled.top).toBeGreaterThan(0);
    // A person has to be able to do what the line above did programmatically.
    expect(["auto", "scroll"]).toContain(scrolled.overflowY);

    await expect(page.getByRole("contentinfo")).toBeInViewport();
  });
});
