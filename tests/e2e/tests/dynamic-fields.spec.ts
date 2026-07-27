import { expect, test } from "@playwright/test";

// Every organizer-defined field on the site renders through the `dynamic_field`
// tag, so these markup checks cover the panel and the wizard at once.
test.describe("Organizer-defined fields", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("anon@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await expect(
      page.locator('[id="wizard-content"]').getByRole("heading", { name: "Session Details" }),
    ).toBeVisible();
  });

  test("names a multi-select group with a legend instead of an orphan label", async ({ page }) => {
    const group = page.getByRole("group", { name: /What tone should players expect\?/ });

    await expect(group).toBeVisible();
    await expect(group.locator('input[type="checkbox"]')).toHaveCount(2);
    await expect(group.locator('input[type="radio"]')).toHaveCount(0);
  });

  test("marks a required text field and caps its length", async ({ page }) => {
    const input = page.locator("#id_session_system");

    await expect(input).toHaveAttribute("required", "");
    await expect(input).toHaveAttribute("maxlength", "40");
  });

  test("points the input at its help text", async ({ page }) => {
    const input = page.locator("#id_session_system");

    await expect(input).toHaveAttribute("aria-describedby", "id_session_system_help");
    await expect(page.locator("#id_session_system_help")).toContainText("Any edition is fine.");
  });

  test("gives the custom-value companion a name and the same length cap", async ({ page }) => {
    const companion = page.locator("#id_session_system_custom");

    await expect(companion).toHaveAttribute("aria-label", /custom value/i);
    await expect(companion).toHaveAttribute("maxlength", "40");
  });
});
