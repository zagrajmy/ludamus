import { expect, test } from "./helpers/fixtures";

test.describe("Anonymous proposals", () => {
  test("redirects to login when anonymous proposals are disabled", async ({ page }) => {
    await page.goto("/event/autumn-open/session/propose/");

    await expect(page).toHaveURL(/\/crowd\/login-required\/\?next=/);
  });

  test("lets an anonymous visitor submit a proposal when enabled", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Your Information" })).toBeVisible();
    await page.getByLabel(/contact email/i).fill("anon@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await page.getByLabel(/title/i).fill("Anonymous One-Shot");
    await page.getByLabel(/description/i).fill("A drop-in adventure pitched without an account.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page.getByLabel(/duration/i).selectOption("PT1H");
    // The open-mic category asks for two organizer-defined fields, both required.
    await page.getByRole("checkbox", { name: "Comedy" }).check();
    await page.locator("#id_session_system").fill("Dungeon World");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(page.getByText("anon@example.com")).toBeVisible();
    await expect(page.getByText("Anonymous One-Shot")).toBeVisible();
    await page.getByRole("button", { name: "Submit Proposal" }).click();

    await expect(page.getByText("Anonymous One-Shot")).toBeVisible();
  });
});
