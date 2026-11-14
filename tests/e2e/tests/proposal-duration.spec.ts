import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";

test.describe("Proposal duration", () => {
  test.use({ storageState: managerState });

  test("reveals the hour and minute steppers only for a custom duration", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/proposals/create/");

    // The page defaults to the alphabetically first category, and panel.spec
    // adds more to this event as it runs — so name the seeded one that has a
    // configured duration. Changing it swaps the duration control over HTMX.
    // Changing the category swaps #proposal-session-fields over HTMX. Mark the
    // node we're replacing: waiting on the new markup alone is racy, because
    // the pre-swap category may already offer the same duration options.
    const fields = page.locator("#proposal-session-fields");
    await fields.evaluate((element: HTMLElement) => {
      element.dataset.stale = "1";
    });
    await page.getByLabel("Category").selectOption({ label: "RPG Proposals" });
    await expect(page.locator("#proposal-session-fields[data-stale]")).toHaveCount(0);

    const hours = page.getByLabel("Hours", { exact: true });
    const duration = page.getByLabel("Duration", { exact: true });
    await expect(duration.locator("option[value='PT1H']")).toBeAttached();
    await expect(hours).toBeHidden();

    // The reveal is CSS-only, keyed on "Custom" being the last option.
    await duration.selectOption("custom");
    await expect(hours).toBeVisible();

    await duration.selectOption("PT1H");
    await expect(hours).toBeHidden();
  });

  test("the hour stepper steps, stops at its bounds and posts a plain number", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/proposals/create/");
    // The stepper arrives in an HTMX swap here, so this also covers an
    // element that upgrades after the page loaded.
    const fields = page.locator("#proposal-session-fields");
    await fields.evaluate((element: HTMLElement) => {
      element.dataset.stale = "1";
    });
    await page.getByLabel("Category").selectOption({ label: "RPG Proposals" });
    await expect(page.locator("#proposal-session-fields[data-stale]")).toHaveCount(0);
    await page.getByLabel("Duration", { exact: true }).selectOption("custom");

    const hours = page.getByLabel("Hours", { exact: true });
    const less = page.getByRole("button", { name: "Decrease: Hours", exact: true });
    const more = page.getByRole("button", { name: "Increase: Hours", exact: true });
    const max = Number(await hours.getAttribute("max"));

    await hours.fill("0");
    await hours.press("Tab");
    await expect(less).toBeDisabled();
    await expect(more).toBeEnabled();
    // The input's own arrow keys step it, so the buttons are not tab stops.
    await expect(less).toHaveAttribute("tabindex", "-1");
    await expect(more).toHaveAttribute("tabindex", "-1");
    await expect(more).toHaveAttribute("aria-controls", (await hours.getAttribute("id")) ?? "");

    await more.click();
    await expect(hours).toHaveValue("1");
    await expect(less).toBeEnabled();
    await hours.press("ArrowUp");
    await expect(hours).toHaveValue("2");
    await hours.press("End");
    await expect(hours).toHaveValue(String(max));
    await expect(more).toBeDisabled();

    await hours.fill(String(max + 50));
    await hours.press("Tab");
    await expect(hours).toHaveValue(String(max));
    expect(
      await hours.evaluate((input: HTMLInputElement) =>
        new FormData(input.form ?? undefined).getAll(input.name),
      ),
    ).toEqual([String(max)]);
  });
});
