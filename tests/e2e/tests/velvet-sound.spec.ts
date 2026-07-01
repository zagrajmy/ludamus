import { expect, test } from "@playwright/test";

test.describe("Content activity log", () => {
  test("panel shows content log with recorded changes", async ({ page }) => {
    await page.goto("/panel/event/frostfire-con/settings/");

    const nameInput = page.locator("#id_name");
    await nameInput.fill("Frostfire Game Convention Log Test");
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Event settings saved successfully.")).toBeVisible();

    await nameInput.fill("Frostfire Game Convention");
    await page.getByRole("button", { name: "Save Settings" }).click();
    await expect(page.getByText("Event settings saved successfully.")).toBeVisible();

    await page.goto("/panel/event/frostfire-con/content-log/");

    await expect(page.getByRole("heading", { name: "Content Activity Log" })).toBeVisible();
    await expect(page.getByText("Frostfire Game Convention Log Test")).toBeVisible();
  });
});
