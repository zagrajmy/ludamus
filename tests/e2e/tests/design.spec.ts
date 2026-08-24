import { type Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

test.describe("Design system page", () => {
  /** The upgraded combobox input — waits out the enhancement, which a native
   * <select> would otherwise satisfy, since it carries the combobox role too. */
  const upgradedCombobox = async (page: Page, name: string) => {
    const combobox = page.getByRole("combobox", { name });
    await expect(combobox).toHaveAttribute("aria-autocomplete", "list");
    return combobox;
  };

  test("renders design showcase with component sections", async ({ page }) => {
    await page.goto("/design/");

    // Page should load (design.html extends base)
    await expect(page).toHaveTitle(/tessera/i);

    // Should contain component examples — buttons, cards, alerts, etc.
    await expect(page.getByRole("button").first()).toBeVisible();

    await page.screenshot({
      path: "test-results/design-page.png",
      fullPage: true,
    });
  });

  test("lets people exercise toast stacking and dismissal", async ({ page }) => {
    await page.goto("/design/");

    const playground = page.getByRole("group", { name: "Toast playground" });
    await playground.getByRole("button", { name: "Show success" }).click();
    await playground.getByRole("button", { name: "Show sticky error" }).click();

    const toasts = page.getByRole("region", { name: "Notifications" }).locator("[data-flash]");
    await expect(toasts).toHaveCount(2);
    await expect(toasts.first()).toHaveAttribute("data-flash-mounted", "true");
    await expect
      .poll(() =>
        toasts.evaluateAll((elements) => {
          const [front, back] = elements.map((element) => element.getBoundingClientRect());
          return back.top - front.top < front.height;
        }),
      )
      .toBe(true);

    await playground.getByRole("button", { name: "Dismiss all" }).click();
    await expect(toasts).toHaveCount(0);
  });

  test("upgrades the combobox and filters its options", async ({ page }) => {
    await page.goto("/design/");

    const combobox = await upgradedCombobox(page, "Fruit");
    // The upgrade swaps the control: the select steps aside for the input.
    await expect(page.locator("#t-combobox")).toBeHidden();

    await combobox.fill("ap");
    await expect(page.getByRole("listbox", { name: "Fruit" }).getByRole("option")).toHaveText([
      "Apple",
      "Apricot",
    ]);

    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    await combobox.press("Enter");
    await expect(combobox).toHaveValue("Apricot");
    // The select is still the value — a form would post this.
    await expect(page.locator("#t-combobox")).toHaveValue("apricot");
  });

  test("keeps the native select when scripts do not run", async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto("/design/");

    // The markup ships a working select; the shell only appears once the
    // script has something to upgrade it to.
    await expect(page.locator("#t-combobox")).toBeVisible();
    await expect(page.locator("#t-combobox-input")).toBeHidden();

    await context.close();
  });

  test("follows the combobox keyboard contract", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    const value = page.locator("#t-combobox");

    // Alt+Down opens without moving the active option, per the pattern.
    await combobox.focus();
    await combobox.press("Alt+ArrowDown");
    await expect(combobox).toHaveAttribute("aria-expanded", "true");
    await expect(combobox).not.toHaveAttribute("aria-activedescendant", /./);

    // Up from there wraps to the last option rather than clamping.
    await combobox.press("ArrowUp");
    await expect(page.getByRole("option", { name: "Cherry" })).toHaveAttribute("data-active", "");

    // Alt+Up commits the active option and closes.
    await combobox.press("Alt+ArrowUp");
    await expect(value).toHaveValue("cherry");
    await expect(combobox).toHaveAttribute("aria-expanded", "false");

    // Tab commits the active option on the way out.
    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    await combobox.press("Tab");
    await expect(value).toHaveValue("apple");
    await expect(combobox).toHaveAttribute("aria-expanded", "false");
  });

  test("navigating the list does not change the value until it is committed", async ({ page }) => {
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    const value = page.locator("#t-combobox");

    await combobox.click();
    await combobox.press("ArrowDown");
    await combobox.press("ArrowDown");
    // Moving the active option is not a pick — the select still holds nothing.
    await expect(value).toHaveValue("");

    await combobox.press("Escape");
    await expect(value).toHaveValue("");
  });

  test("keeps the list inside the part of the screen a keyboard leaves", async ({ browser }) => {
    const context = await browser.newContext({
      viewport: { width: 390, height: 700 },
      isMobile: true,
      hasTouch: true,
    });
    const page = await context.newPage();
    await page.goto("/design/");
    const combobox = await upgradedCombobox(page, "Fruit");
    await combobox.scrollIntoViewIfNeeded();
    await combobox.click();

    // Stand in for the on-screen keyboard: it shrinks and offsets the visual
    // viewport and leaves the layout viewport — and so window.innerHeight —
    // untouched, which is exactly the case the placement has to read.
    const band = await page.evaluate(() => {
      const viewport = window.visualViewport!;
      Object.defineProperty(viewport, "height", { configurable: true, value: 320 });
      Object.defineProperty(viewport, "offsetTop", { configurable: true, value: 180 });
      viewport.dispatchEvent(new Event("resize"));
      return { bottom: 180 + 320, innerHeight: window.innerHeight, top: 180 };
    });
    // The stub has to be the interesting case: a layout viewport that still
    // claims the room the keyboard took.
    expect(band.innerHeight).toBeGreaterThan(band.bottom);

    const popup = page.locator("[data-combobox-popup]");
    await expect
      .poll(async () => {
        const box = await popup.boundingBox();
        return box ? Math.round(box.y + box.height) : null;
      })
      .toBeLessThanOrEqual(band.bottom + 1);

    const box = await popup.boundingBox();
    expect(box!.y).toBeGreaterThanOrEqual(band.top - 1);
    // Still worth showing: a list squeezed to nothing would pass the bounds
    // check above while being useless.
    expect(box!.height).toBeGreaterThan(80);

    await context.close();
  });
});
