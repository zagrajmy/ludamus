import { expect, test } from "./helpers/fixtures";

test.describe("Command menu", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/about/");
  });

  test("opens from the keyboard, lists what it can do, and closes on Escape", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");

    const menu = page.getByRole("dialog", { name: "Command menu" });
    await expect(menu.getByRole("combobox")).toBeFocused();
    await expect(menu.getByRole("group", { name: "Go to" }).getByRole("option")).toHaveText([
      "Events",
      "Log in",
    ]);
    await expect(menu.getByRole("group", { name: "Language" }).getByRole("option")).toHaveText([
      /Polski/,
      /English/,
    ]);
    await expect(menu.getByRole("option", { name: "English" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expect(menu.getByRole("option", { name: "Polski" })).not.toHaveAttribute("aria-current");

    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
  });

  test("the navbar button opens it and hands focus back on close", async ({ page }) => {
    const opener = page.getByRole("button", { name: "Open command menu" });
    await opener.click();
    await expect(page.getByRole("dialog", { name: "Command menu" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(opener).toBeFocused();
  });

  test("switches the language for a visitor, past the browser session", async ({
    context,
    page,
  }) => {
    // Found by its Polish name, typed without the diacritic, on an English page.
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("jezyk");
    await expect(page.getByRole("option")).toHaveText([/Polski/, /English/]);
    await page.keyboard.press("Enter");

    await expect(page.locator("html")).toHaveAttribute("lang", "pl");
    await expect(page).toHaveURL(/\/about\/$/);
    const cookie = (await context.cookies()).find(({ name }) => name === "django_language");
    // A session cookie reports -1: the choice would be gone on restart.
    expect(cookie?.expires).toBeGreaterThan(Date.now() / 1000);

    await page.getByRole("button", { name: "Otwórz menu poleceń" }).click();
    const menu = page.getByRole("dialog", { name: "Menu poleceń" });
    await menu.getByRole("combobox").fill("language");
    await expect(menu.getByRole("option")).toHaveText([/Polski/, /English/]);
    await expect(menu.getByRole("option", { name: "Polski" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  test("goes to the page picked with the arrow keys", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });
    await expect(menu.getByRole("option", { name: "Events" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.keyboard.press("ArrowDown");
    await expect(menu.getByRole("option", { name: "Log in" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page.keyboard.press("ArrowUp");
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/localhost:8000\/$/);
  });

  test("switches the theme and keeps the footer switcher in step", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("dark");
    await page.getByRole("option", { name: "Dark theme" }).click();

    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.locator("html")).toContainClass("dark");
    await expect(page.getByRole("radio", { name: "dark" })).toBeChecked();

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByRole("option", { name: "Dark theme" })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  test("says so when nothing matches", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("qqqq");

    const menu = page.getByRole("dialog", { name: "Command menu" });
    await expect(menu.getByText("No results found.")).toBeVisible();
    await expect(menu.getByRole("option")).toHaveCount(0);
  });
});
