import { expect, test } from "@playwright/test";

test.describe("Proposal duration", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("reveals the hour and minute steppers only for a custom duration", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/proposals/create/");

    const hours = page.getByLabel("Hours");
    const duration = page.getByLabel("Duration", { exact: true });
    await expect(hours).toBeHidden();

    // The reveal is CSS-only, keyed on "Custom" being the last option.
    await duration.selectOption("custom");
    await expect(hours).toBeVisible();

    await duration.selectOption("PT1H");
    await expect(hours).toBeHidden();
  });
});
