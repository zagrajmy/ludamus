import { expect, test } from "@playwright/test";

// User-centric tests (Kent C. Dodds style): drive the controls the way a person
// does — find them by their accessible role/name, act, and assert on the state
// the user can perceive (pressed/checked, persistence) — never on CSS classes,
// data-* hooks, or the Web Audio internals.

test.describe("interface sound toggle", () => {
  const toggle = (page: import("@playwright/test").Page) =>
    page.getByRole("checkbox", { name: /interface sound/i });
  const pressToggle = async (page: import("@playwright/test").Page): Promise<void> => {
    await toggle(page).locator("xpath=ancestor::label[1]").click();
  };

  test("starts on and turns off when the user presses it", async ({ page }) => {
    await page.goto("/design/");

    await expect(toggle(page)).toBeChecked();

    await pressToggle(page);

    await expect(toggle(page)).not.toBeChecked();
  });

  test("remembers the choice across a page reload", async ({ page }) => {
    await page.goto("/design/");

    await expect(toggle(page)).toBeChecked();
    await pressToggle(page);
    await expect(toggle(page)).not.toBeChecked();

    await page.reload();

    await expect(toggle(page)).not.toBeChecked();
  });
});

test.describe("segmented switcher", () => {
  test("shows its configured choice and lets the user pick another", async ({ page }) => {
    await page.goto("/design/");

    // The design gallery configures the switcher with "Grid view" selected.
    await expect(page.getByRole("radio", { name: /grid view/i })).toBeChecked();
    await expect(page.getByRole("radio", { name: /list view/i })).not.toBeChecked();

    // Activate "List view" the way a person does: click the visible segment.
    // The radio itself is sr-only, so we find it by its accessible name and
    // click its enclosing label (the visible control).
    await page
      .getByRole("radio", { name: /list view/i })
      .locator("xpath=ancestor::label[1]")
      .click();

    await expect(page.getByRole("radio", { name: /list view/i })).toBeChecked();
    await expect(page.getByRole("radio", { name: /grid view/i })).not.toBeChecked();
  });
});
