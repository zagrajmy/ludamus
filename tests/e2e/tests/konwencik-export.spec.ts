import { expect, test } from "./helpers/fixtures";

// The integrations list renders per-row actions from data the row carries, so
// only an export integration gets "Export now" and "Configure". These assert
// the rendered controls; what the view puts in the context is asserted in
// tests/integration.
const EVENT = "frostfire-con";
const INTEGRATIONS_URL = `/panel/event/${EVENT}/settings/integrations/`;
const INTEGRATION = "Konwencik agenda";

test.describe("Konwencik export row actions", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("the export row offers both of its own actions", async ({ page }) => {
    await page.goto(INTEGRATIONS_URL);

    const row = page.getByRole("row", { name: new RegExp(INTEGRATION) });
    await expect(row.getByRole("button", { name: "Export now" })).toBeVisible();
    await expect(row.getByRole("link", { name: "Configure" })).toBeVisible();
  });

  test("Configure opens the export settings page", async ({ page }) => {
    await page.goto(INTEGRATIONS_URL);

    const row = page.getByRole("row", { name: new RegExp(INTEGRATION) });
    await row.getByRole("link", { name: "Configure" }).click();

    await page.waitForURL(/\/export\/\d+\/$/);
    await expect(page.getByRole("heading", { name: "Konwencik export" })).toBeVisible();
    await expect(page.getByText(INTEGRATION)).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeVisible();
  });
});
