import { expect, test } from "@playwright/test";

// User-centric tests (Kent C. Dodds style): drive the controls the way a person
// does — find them by their accessible role/name, act, and assert on the state
// the user can perceive (pressed/checked, persistence) — never on CSS classes,
// data-* hooks, or the Web Audio internals.

test.describe("interface sound toggle", () => {
  const toggle = (page: import("@playwright/test").Page) =>
    page.getByRole("button", { name: /interface sound/i });

  test("starts off and turns on when the user presses it", async ({ page }) => {
    await page.goto("/design/");

    await expect(toggle(page)).toHaveAttribute("aria-pressed", "false");

    await toggle(page).click();

    await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");
  });

  test("remembers the choice across a page reload", async ({ page }) => {
    await page.goto("/design/");

    await toggle(page).click();
    await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");

    await page.reload();

    await expect(toggle(page)).toHaveAttribute("aria-pressed", "true");
  });
});

test.describe("segmented switcher", () => {
  test("shows its configured choice and lets the user pick another", async ({
    page,
  }) => {
    await page.goto("/design/");

    // The design gallery configures the switcher with "Grid view" selected.
    await expect(page.getByRole("radio", { name: /grid view/i })).toBeChecked();
    await expect(
      page.getByRole("radio", { name: /list view/i }),
    ).not.toBeChecked();

    await page.getByRole("radio", { name: /list view/i }).check();

    await expect(page.getByRole("radio", { name: /list view/i })).toBeChecked();
    await expect(
      page.getByRole("radio", { name: /grid view/i }),
    ).not.toBeChecked();
  });
});
