import type { Page } from "@playwright/test";

import { expect, test } from "./helpers/fixtures";

// A page can offer several write-ins, so each is named after its own question.
const customValue = (page: Page, question: string) =>
  page.getByLabel(`Custom value for: ${question}`, { exact: true });

// By role, not by label: a required field's label carries "(required)" and a
// non-public one "organizers only", and getByLabel does not normalize the
// markup's whitespace for a regex. The accessible name is normalized, and
// anchoring keeps the companion's "Custom value for: …" out.
const systemInput = (page: Page) => page.getByRole("textbox", { name: /^Which system\?/ });

test.describe("Write-in answers", () => {
  test("carries a write-in alongside the picked options", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    await page.getByLabel(/contact email/i).fill("write-in@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await expect(wizard.getByText("semicolon separated")).toBeVisible();

    await page.getByLabel(/title/i).fill("Nocna sesja");
    await page.getByLabel(/description/i).fill("A one-shot with content to flag.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page.getByLabel(/duration/i).selectOption("PT1H");
    await page
      .getByRole("group", { name: /What tone should players expect\?/ })
      .getByRole("checkbox", { name: "Comedy" })
      .check();
    await systemInput(page).fill("Fate");
    await page
      .getByRole("group", { name: /Any trigger warnings\?/ })
      .getByRole("checkbox", { name: "Horror" })
      .check();
    await customValue(page, "Any trigger warnings?").fill("krew; przemoc");
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
    await page
      .getByRole("group", { name: /What tone should players expect\?/ })
      .getByRole("checkbox", { name: "Comedy" })
      .check();
    await systemInput(page).fill("Fate");
    await page
      .getByRole("group", { name: /Any trigger warnings\?/ })
      .getByRole("checkbox", { name: "Horror" })
      .check();
    await customValue(page, "Any trigger warnings?").fill("krew");
    await page.getByRole("button", { name: /Continue/ }).click();

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await page.getByRole("button", { name: /Back/ }).click();

    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    // The saved write-in comes back as a removable chip; the input is empty.
    await expect(page.getByRole("button", { name: "Remove: krew" })).toBeVisible();
    await expect(customValue(page, "Any trigger warnings?")).toHaveValue("");
    await expect(
      page
        .getByRole("group", { name: /Any trigger warnings\?/ })
        .getByRole("checkbox", { name: "Horror" }),
    ).toBeChecked();
  });

  test("commits chips on Enter, removes them, and submits the joined value", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    await page.getByLabel(/contact email/i).fill("write-in-chips@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    const wizard = page.locator('[id="wizard-content"]');
    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();

    const writeIn = customValue(page, "Any trigger warnings?");
    await writeIn.fill("krew");
    await writeIn.press("Enter");
    // Enter committed a chip instead of submitting the step.
    await expect(wizard.getByRole("heading", { name: "Session Details" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Remove: krew" })).toBeVisible();
    await expect(writeIn).toHaveValue("");

    await writeIn.fill("przemoc");
    await writeIn.press("Enter");
    await page.getByRole("button", { name: "Remove: przemoc" }).click();
    await expect(page.getByRole("button", { name: "Remove: przemoc" })).toBeHidden();

    await page.getByLabel(/title/i).fill("Sesja z chipsami");
    await page.getByLabel(/description/i).fill("Chips keep the stored value canonical.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page.getByLabel(/duration/i).selectOption("PT1H");
    await page
      .getByRole("group", { name: /What tone should players expect\?/ })
      .getByRole("checkbox", { name: "Comedy" })
      .check();
    await systemInput(page).fill("Fate");
    await page
      .getByRole("group", { name: /Any trigger warnings\?/ })
      .getByRole("checkbox", { name: "Horror" })
      .check();
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(wizard.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(page.getByText("Horror, krew")).toBeVisible();
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
