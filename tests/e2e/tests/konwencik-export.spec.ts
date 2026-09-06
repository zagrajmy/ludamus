import { expect, test } from "./helpers/fixtures";

// The export is its own panel section, reached from the sidebar like the
// Google Docs import — not from a row action on the integrations list. These
// assert the rendered chrome; what the view puts in the context is asserted in
// tests/integration.
const EVENT = "frostfire-con";
const TIMETABLE_URL = `/panel/event/${EVENT}/timetable/`;
const INTEGRATION = "Konwencik agenda";

test.describe("Konwencik export", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/admin/login/", { waitUntil: "domcontentloaded" });
    await page.getByLabel("Username:").fill("e2e-manager");
    await page.getByLabel("Password:").fill("e2e-manager-123");
    await page.getByRole("button", { name: /Log in/i }).click();
  });

  test("a manager reaches the export from the sidebar", async ({ page }) => {
    await page.goto(TIMETABLE_URL);

    // The site navbar is a <nav> too, so the sidebar is picked by its label.
    const sidebar = page.getByRole("navigation", { name: "Panel sections" });
    const link = sidebar.getByRole("link", { name: "Konwencik export", exact: true });

    await link.click();

    await expect(page).toHaveURL(new RegExp(`/panel/event/${EVENT}/export/$`));
    await expect(page.getByRole("heading", { name: "Konwencik export" })).toBeVisible();
    await expect(page.getByText(INTEGRATION)).toBeVisible();
    await expect(link).toHaveAttribute("aria-current", "page");
  });

  test("the export page offers its own run and save controls", async ({ page }) => {
    await page.goto(`/panel/event/${EVENT}/export/`);

    await expect(page.getByRole("button", { name: "Export now" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toBeVisible();
  });
});
