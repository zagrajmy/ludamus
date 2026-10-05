import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// Mobile browser chrome (address/status bar) paints from <meta name="theme-color">,
// not from color-scheme, so the meta must track a manual theme choice too.
const themeColor = (page: Page) => page.locator('meta[name="theme-color"]');

test.describe("Theme color meta", () => {
  test("follows a stored manual theme from first paint and the switcher after", async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: "light" });
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/");

    await expect(themeColor(page)).toHaveAttribute("content", "#0a0a0a");

    await page.locator('label[for="theme-light"]').click();

    await expect(themeColor(page)).toHaveAttribute("content", "#f0f1f3");
  });

  test("follows the system preference when the theme is system", async ({ page }) => {
    // NOTE: Firefox ignores color-scheme emulation set before the first navigation.
    await page.goto("/");
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();

    await expect(themeColor(page)).toHaveAttribute("content", "#0a0a0a");

    await page.emulateMedia({ colorScheme: "light" });

    await expect(themeColor(page)).toHaveAttribute("content", "#f0f1f3");
  });
});
