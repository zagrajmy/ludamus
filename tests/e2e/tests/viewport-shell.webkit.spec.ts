import { expect, test } from "./helpers/fixtures";

type Page = import("@playwright/test").Page;

const shellHeight = (page: Page): Promise<number> =>
  page.evaluate(() => Math.round(document.body.getBoundingClientRect().height));

const appVh = (page: Page): Promise<string> =>
  page.evaluate(() => document.documentElement.style.getPropertyValue("--app-vh"));

// NOTE: the suffix asks for WebKit at an iPhone's width; the desktop projects
// match every spec, so this runs there too. In none of them is there browser
// chrome, so visualViewport.height is just the window height and the shell is
// sized from it — the equality below is close to self-evident. It is worth
// keeping only as a wiring check: it fails if the publisher stops running.
// Whether the page actually fills an iPhone's screen is a question no headless
// engine can be asked.
test.describe("App shell viewport height on a phone", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("the shell is the height the viewport is showing", async ({ page }) => {
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
    await expect(page.getByRole("contentinfo")).toBeInViewport();
  });
});
