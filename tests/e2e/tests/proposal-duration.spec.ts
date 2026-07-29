import { expect, test } from "./helpers/fixtures";

test.describe("Proposal duration", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

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

    const hours = page.getByLabel("Hours");
    const duration = page.getByLabel("Duration", { exact: true });
    await expect(duration.locator("option[value='PT1H']")).toBeAttached();
    await expect(hours).toBeHidden();

    // The reveal is CSS-only, keyed on "Custom" being the last option.
    await duration.selectOption("custom");
    await expect(hours).toBeVisible();

    await duration.selectOption("PT1H");
    await expect(hours).toBeHidden();
  });
});
