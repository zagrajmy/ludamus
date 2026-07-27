import { expect, test } from "@playwright/test";

test.describe("Write-in answers", () => {
  test("carries a write-in alongside the picked options", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    await page.getByLabel(/contact email/i).fill("write-in@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await expect(wizard.getByText("comma separated")).toBeVisible();

    await page.getByLabel(/title/i).fill("Nocna sesja");
    await page.getByLabel(/description/i).fill("A one-shot with content to flag.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page.getByLabel(/duration/i).selectOption("PT1H");
    await page.getByRole("checkbox", { name: "Horror" }).check();
    await page.locator('input[name="session_triggers_custom"]').fill("krew, przemoc");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(page.getByText("Horror, krew, przemoc")).toBeVisible();
  });

  test("shows the write-in again when the proposer steps back", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    await page.getByLabel(/contact email/i).fill("write-in-back@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await page.getByLabel(/title/i).fill("Powrót");
    await page.getByLabel(/description/i).fill("Stepping back to the details.");
    await page.getByLabel(/max participants/i).fill("4");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page.getByLabel(/duration/i).selectOption("PT1H");
    await page.getByRole("checkbox", { name: "Horror" }).check();
    await page.locator('input[name="session_triggers_custom"]').fill("krew");
    await page.getByRole("button", { name: /Continue/ }).click();

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await page.getByRole("button", { name: /Back/ }).click();

    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await expect(page.locator('input[name="session_triggers_custom"]')).toHaveValue("krew");
    await expect(page.getByRole("checkbox", { name: "Horror" })).toBeChecked();
  });
});

test.describe("Session field toggles", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("keeps multi-value and custom-value settings on the edit page", async ({
    page,
  }, testInfo) => {
    const name = testInfo.retry === 0 ? "Content notes" : `Content notes ${testInfo.retry}`;

    await page.goto("/panel/event/frostfire-con/cfp/session-fields/create/");
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByLabel("Question").fill(`${name}?`);
    await page.getByLabel("Field Type").selectOption("select");
    await page.getByLabel("Options").fill("Horror\nViolence");

    await page.getByLabel("Allow multiple selections").check();
    await page.getByLabel("Allow custom values").check();
    await page.getByRole("button", { name: /Create/ }).click();

    await page
      .getByRole("row", { name: new RegExp(name) })
      .getByRole("link", { name: "Edit" })
      .click();

    await expect(page.getByLabel("Allow multiple selections")).toBeChecked();
    await expect(page.getByLabel("Allow custom values")).toBeChecked();
  });
});
