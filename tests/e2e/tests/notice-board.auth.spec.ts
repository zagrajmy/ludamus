import { expect, test } from "@playwright/test";

test.describe("Encounter detail — organizer share dialog", () => {
  test("reveals and dismisses the QR code from the share menu", async ({ page }) => {
    // Seeded encounter authored by the e2e-tester user; share code is fixed
    // to keep the URL deterministic across runs.
    await page.goto("/e/ENCQR1/");

    await expect(page.getByRole("heading", { name: "Backyard Tactics Night" })).toBeVisible();

    // The QR action lives behind the Share menu — open it first.
    await page.getByRole("button", { name: "Share" }).first().click();
    await page.getByRole("button", { name: "Show QR code" }).first().click();

    // Dialog has no accessible name; it carries an <img alt="QR Code">,
    // which is what the user actually sees and what we assert against.
    const qrImage = page.getByRole("img", { name: "QR Code" });
    await expect(qrImage).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(qrImage).toBeHidden();
  });
});
