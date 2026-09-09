import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// A dedicated user (e2e-notified, tests/e2e/scripts/bootstrap_data.py) with one
// destination notification (links to /events/) and one url-less content
// notification (read in the overlay). Isolated so opening/marking-read here never
// disturbs another spec's unread count. Mark-read semantics are covered by the
// Python integration tests; this spec covers the overlay + list wiring only.
//
// The overlay is deliberately not URL-addressable: the bell renders on every
// page, so a `?notification=` link would give one notification as many
// addresses as there are pages. It opens in place and leaves the URL alone.

const contentTitle = "Autumn Open: doors to hall B open at 9:00";
const destinationTitle = "You're in: a spot opened in Dragons & Dungeons";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-notified.json") });

test.describe("Notification overlay and list page", () => {
  test("the bell's View all link opens the full notification list", async ({ page }) => {
    await page.goto("/events/");

    await page.getByRole("button", { name: /Notifications/ }).click();
    await page.getByRole("link", { name: "View all" }).click();

    await expect(page).toHaveURL(/\/notifications\/$/);
    await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(contentTitle) })).toBeVisible();
    await expect(page.getByRole("link", { name: new RegExp(destinationTitle) })).toBeVisible();
  });

  test("a content notification opens in an overlay and closes on Escape", async ({ page }) => {
    await page.goto("/notifications/");

    await page.getByRole("link", { name: new RegExp(contentTitle) }).click();

    const dialog = page.getByRole("dialog", { name: contentTitle });
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText("Bring your badge");
    await expect(page).toHaveURL(/\/notifications\/$/);

    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(/\/notifications\/$/);
  });

  test("the overlay opens over whatever page the bell was clicked from", async ({ page }) => {
    await page.goto("/events/");

    await page.getByRole("button", { name: /Notifications/ }).click();
    await page.getByRole("link", { name: new RegExp(contentTitle) }).click();

    await expect(page.getByRole("dialog", { name: contentTitle })).toBeVisible();
    await expect(page).toHaveURL(/\/events\/$/);
  });

  test("a destination notification navigates to its target", async ({ page }) => {
    await page.goto("/notifications/");

    await page.getByRole("link", { name: new RegExp(destinationTitle) }).click();

    await expect(page).toHaveURL(/\/events\/$/);
  });
});
