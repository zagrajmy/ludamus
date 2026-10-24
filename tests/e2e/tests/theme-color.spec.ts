import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Mobile browser chrome (address/status bar) paints from <meta name="theme-color">,
// not from color-scheme, so the meta must track a manual theme choice too. The
// bar sits flush against the page's top edge, so it must match the surface
// there; comparing against the rendered surface, not a hex, catches the meta
// drifting from the CSS tokens it mirrors.
const barAndTopEdge = (page: Page) =>
  page.evaluate(() => {
    const transparent = "rgba(0, 0, 0, 0)";
    let surface: Element | null = document.elementFromPoint(innerWidth / 2, 0);
    while (surface && getComputedStyle(surface).backgroundColor === transparent) {
      surface = surface.parentElement;
    }

    const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    const probe = document.createElement("div");
    probe.style.color = meta?.content ?? "";
    document.body.append(probe);
    const bar = getComputedStyle(probe).color;
    probe.remove();

    return { bar, topEdge: surface ? getComputedStyle(surface).backgroundColor : transparent };
  });

const expectBarToMatchTopEdge = async (page: Page) => {
  await expect(async () => {
    const { bar, topEdge } = await barAndTopEdge(page);
    expect(bar).toBe(topEdge);
  }).toPass({ timeout: 10_000 });
};

test.describe("Theme color meta", () => {
  test("follows a stored manual theme from first paint and the switcher after", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/");

    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expectBarToMatchTopEdge(page);

    await page.getByTitle("Light theme", { exact: true }).click();

    await expect(page.locator("html")).toHaveClass(/\blight\b/);
    await expectBarToMatchTopEdge(page);
  });

  test("follows the system preference when the theme is system", async ({ page }) => {
    // NOTE: Firefox ignores color-scheme emulation set before the first navigation.
    await page.goto("/");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();

    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await expectBarToMatchTopEdge(page);

    await page.emulateMedia({ colorScheme: "light" });

    await expect(page.locator("html")).toHaveClass(/\blight\b/);
    await expectBarToMatchTopEdge(page);
  });
});
