import { expect, test } from "./helpers/fixtures";
import { DENSE_EVENT_URL } from "./helpers/urls";

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
    // Each setting is one row that names its current value.
    await expect(menu.getByRole("group", { name: "Settings" }).getByRole("option")).toHaveText([
      /Language\s*English/,
      /Theme\s*System theme/,
    ]);

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

  test("a setting opens its own list, and Escape or Backspace steps back out", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });
    await menu.getByRole("option", { name: "Language" }).click();

    const languages = menu.getByRole("listbox", { name: "Language" });
    await expect(languages.getByRole("option")).toHaveText([/Polski/, /English/]);
    await expect(languages.getByRole("option", { name: "English" })).toHaveAttribute(
      "aria-current",
      "true",
    );
    await expect(languages.getByRole("option", { name: "Polski" })).not.toHaveAttribute(
      "aria-current",
    );
    await expect(menu.getByRole("combobox")).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(menu.getByRole("option", { name: "Log in" })).toBeVisible();

    await menu.getByRole("option", { name: "Theme" }).click();
    await expect(menu.getByRole("option", { name: "Dark theme" })).toBeVisible();
    await page.keyboard.press("Backspace");
    await expect(menu.getByRole("option", { name: "Log in" })).toBeVisible();

    await menu.getByRole("option", { name: "Theme" }).click();
    await menu.getByRole("button", { name: "Back" }).click();
    await expect(menu.getByRole("option", { name: "Log in" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
  });

  test("switches the language for a visitor, past the browser session", async ({
    context,
    page,
  }) => {
    // Found by its Polish name, typed without the diacritic, on an English
    // page, and without opening the Language list first.
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("jezyk");
    await expect(page.getByRole("option")).toHaveText([/Language/, /Polski/, /English/]);
    await page.getByRole("option", { name: "Polski" }).click();

    await expect(page.locator("html")).toHaveAttribute("lang", "pl");
    await expect(page).toHaveURL(/\/about\/$/);
    const cookie = (await context.cookies()).find(({ name }) => name === "django_language");
    // A session cookie reports -1: the choice would be gone on restart.
    expect(cookie?.expires).toBeGreaterThan(Date.now() / 1000);

    await page.getByRole("button", { name: "Otwórz menu poleceń" }).click();
    const menu = page.getByRole("dialog", { name: "Menu poleceń" });
    await menu.getByRole("combobox").fill("language");
    await expect(menu.getByRole("option")).toHaveText([/Język\s*Polski/, /Polski/, /English/]);
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

  test("a modified click opens the page in another tab and leaves this one be", async ({
    context,
    page,
  }) => {
    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });
    const [opened] = await Promise.all([
      context.waitForEvent("page"),
      menu.getByRole("option", { name: "Events" }).click({ modifiers: ["ControlOrMeta"] }),
    ]);

    await expect(opened).toHaveURL(/localhost:8000\/$/);
    await expect(page).toHaveURL(/\/about\/$/);
    await expect(menu).toBeVisible();
  });

  test("switches the theme and keeps the footer switcher in step", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("option", { name: "Theme" }).click();
    await page.getByRole("option", { name: "Dark theme" }).click();

    await expect(page.getByRole("dialog")).toBeHidden();
    await expect(page.locator("html")).toContainClass("dark");
    await expect(page.getByRole("radio", { name: "dark" })).toBeChecked();

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByRole("option", { name: "Theme" })).toHaveText(/Dark theme/);
  });

  test("a failed download of the menu is tried again on the next press", async ({ page }) => {
    let failures = 0;
    await page.route(/\/assets\/menu-[^/]+\.js$/, (route) => {
      if (failures > 0) return route.fallback();
      failures += 1;
      return route.abort();
    });
    const menu = page.getByRole("dialog", { name: "Command menu" });

    await page.keyboard.press("ControlOrMeta+k");
    await expect.poll(() => failures).toBe(1);
    await expect(menu).toBeHidden();

    // The retry is a new press, so give each attempt its own.
    await expect(async () => {
      await page.keyboard.press("ControlOrMeta+k");
      await expect(menu.getByRole("combobox")).toBeFocused({ timeout: 2000 });
    }).toPass();
  });

  test("opens over a modal dialog and hands the page back to it", async ({ page }) => {
    await page.goto("/event/autumn-open/");
    await page.getByRole("link", { name: "Open details for Mega Strategy Lab" }).press("Enter");
    const session = page.getByRole("dialog", { name: "Mega Strategy Lab" });
    await expect(session).toBeVisible();

    await page.keyboard.press("ControlOrMeta+k");
    const menu = page.getByRole("dialog", { name: "Command menu" });
    await expect(menu.getByRole("combobox")).toBeFocused();
    await menu.getByRole("combobox").fill("theme");
    await expect(menu.getByRole("option", { name: "Dark theme" })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(session).toBeVisible();
    await session.getByRole("button", { name: "Close" }).click();
    await expect(session).toBeHidden();
  });

  // A browser Back over a schedule view switch makes htmx swap the whole body
  // in place, which drops everything a script appended to it.
  test("opens again after Back restores the page under it", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(DENSE_EVENT_URL);
    const menu = page.getByRole("dialog", { name: "Command menu" });
    await page.keyboard.press("ControlOrMeta+k");
    await expect(menu.getByRole("combobox")).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();

    await page.getByRole("tab", { name: "Rooms" }).click();
    await expect(page).toHaveURL(/view=rooms/);
    await page.goBack();
    await expect(page).not.toHaveURL(/view=rooms/);
    await expect(page.getByRole("tab", { name: "List" })).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("ControlOrMeta+k");
    await expect(menu.getByRole("combobox")).toBeFocused();
    expect(errors).toEqual([]);
  });

  test("says so when nothing matches", async ({ page }) => {
    await page.keyboard.press("ControlOrMeta+k");
    await page.getByRole("combobox").fill("qqqq");

    const menu = page.getByRole("dialog", { name: "Command menu" });
    await expect(menu.getByText("No results found.")).toBeVisible();
    await expect(menu.getByRole("option")).toHaveCount(0);
  });
});
