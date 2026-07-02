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

test.describe("Encounter detail — copy share link", () => {
  test.use({ permissions: ["clipboard-read", "clipboard-write"] });

  test("copies the link and confirms with a popover, without resizing", async ({ page }) => {
    await page.goto("/e/ENCQR1/");

    await page.getByRole("button", { name: "Share" }).first().click();
    const copyLink = page.getByRole("button", { name: "Copy link" }).first();
    const before = await copyLink.boundingBox();

    await copyLink.click();

    // The confirmation popover is a live region inside the button; the button
    // itself must not change size (the bug this component was built to fix).
    await expect(copyLink.getByRole("status")).toHaveText("Copied!");
    expect(await copyLink.boundingBox()).toEqual(before);

    const clipboard = await page.evaluate(() => navigator.clipboard.readText());
    expect(clipboard).toContain("/e/ENCQR1/");
  });
});
