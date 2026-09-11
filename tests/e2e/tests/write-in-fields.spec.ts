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
    await expect(wizard.getByText("Type a value and press Enter to add it.")).toBeVisible();

    await page.getByLabel(/title/i).fill("Nocna sesja");
    await page.getByLabel(/description/i).fill("A one-shot with content to flag.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
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

  test("keeps plain write-in usable when enhancement fails to load", async ({ page }) => {
    await page.route("**/write-in-chips*", (route) => route.abort());
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("write-in-fallback@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await page.getByLabel(/title/i).fill("Plain input");
    await page.getByLabel(/description/i).fill("Semicolons work without the chip enhancement.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page
      .getByRole("group", { name: /What tone should players expect\?/ })
      .getByRole("checkbox", { name: "Comedy" })
      .check();
    await systemInput(page).fill("Fate");
    await expect(page.getByText("semicolon separated")).toBeVisible();
    await customValue(page, "Any trigger warnings?").fill("krew; przemoc");
    await expect(customValue(page, "Any trigger warnings?")).toHaveValue("krew; przemoc");
    await page.getByRole("button", { name: /Continue/ }).click();

    await expect(page.getByRole("heading", { name: "Review & Submit" })).toBeVisible();
    await expect(page.getByText("krew, przemoc", { exact: true })).toBeVisible();
  });

  test("shows the write-in again when the proposer steps back", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");

    await page.getByLabel(/contact email/i).fill("write-in-back@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await page.getByLabel(/title/i).fill("Powrót");
    await page.getByLabel(/description/i).fill("Stepping back to the details.");
    await page.getByLabel(/max participants/i).fill("4");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
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

  test("keeps overflowing text and clears validation after removing a chip", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("write-in-limit@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    const writeIn = customValue(page, "Any trigger warnings?");
    const first = "a".repeat(45);
    await writeIn.fill(first);
    await writeIn.press("Enter");
    await writeIn.fill("violence");

    await expect(writeIn).toHaveValue("violence");
    await expect(writeIn).toHaveAttribute("aria-invalid", "true");
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(writeIn).not.toHaveJSProperty("validationMessage", "");
    await writeIn.press("Enter");
    await expect(writeIn).toHaveValue("violence");

    await page.getByRole("button", { name: `Remove: ${first}` }).click();
    await expect(page.getByRole("alert")).toBeHidden();
    await expect(writeIn).toHaveJSProperty("validationMessage", "");
    await writeIn.press("Enter");
    await expect(page.getByRole("button", { name: "Remove: violence" })).toBeVisible();
  });

  test("keeps keyboard focus when blur commits a draft beside existing chips", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("write-in-focus@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();

    const writeIn = customValue(page, "Any trigger warnings?");
    await writeIn.fill("krew;");
    await expect(page.getByRole("button", { name: "Remove: krew" })).toBeVisible();
    await writeIn.fill("przemoc");
    await writeIn.press("Shift+Tab");

    const firstChip = page.getByRole("button", { name: "Remove: krew" });
    await expect(firstChip).toBeFocused();
    await expect(page.getByRole("button", { name: "Remove: przemoc" })).toBeVisible();
    await firstChip.press("Enter");
    await expect(firstChip).toBeHidden();
    await expect(writeIn).toBeFocused();
    await writeIn.fill("przemoc;");
    await expect(page.getByRole("button", { name: "Remove: przemoc" })).toHaveCount(1);
    await writeIn.press("Backspace");
    await expect(page.getByRole("button", { name: "Remove: przemoc" })).toBeHidden();
  });

  test("keeps server validation attached to the visible write-in", async ({ page }) => {
    await page.goto("/event/open-mic/session/propose/");
    await page.getByLabel(/contact email/i).fill("write-in-errors@example.com");
    await page.getByRole("button", { name: /Continue/ }).click();
    await page.getByLabel(/title/i).fill("Server validation");
    await page.getByLabel(/description/i).fill("An answer rejected by the server.");
    await page.getByLabel(/max participants/i).fill("5");
    await page.getByLabel(/presenter name/i).fill("Mystery GM");
    await page
      .getByRole("group", { name: /What tone should players expect\?/ })
      .getByRole("checkbox", { name: "Comedy" })
      .check();
    await systemInput(page).fill("Fate");
    await page.route("**/event/open-mic/session/propose/parts/details", async (route) => {
      const body = route.request().postData() ?? "";
      await route.continue({
        postData: body.replace(
          /(name="session_triggers_custom"\r\n\r\n)[^\r\n]*/,
          `$1${"a".repeat(51)}`,
        ),
      });
    });
    await page.getByRole("button", { name: /Continue/ }).click();

    const writeIn = customValue(page, "Any trigger warnings?");
    await expect(writeIn).toBeVisible();
    await expect(writeIn).toHaveAttribute("aria-invalid", "true");
    await expect(writeIn).toHaveAccessibleDescription(
      /Ensure this value has at most 50 characters/,
    );
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

  test("keeps multi-value and custom-value settings on the edit page", async ({ page }) => {
    const name = `Content notes ${Date.now()}`;

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
