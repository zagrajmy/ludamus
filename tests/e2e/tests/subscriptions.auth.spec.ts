import path from "node:path";

import { expect, test } from "./helpers/fixtures";

// The profile Notifications tab lists the spheres the user follows. No
// bootstrap seeding needed: visiting any page signed in is exactly
// what creates the sphere subscription (the visit middleware), so the first
// navigation here doubles as the auto-subscribe end-to-end check. Uses the
// isolated e2e-notified user so mute toggles never disturb other specs.
// Mute semantics (never unmuted by revisits, fanout skips muted) are covered
// by the Python integration tests; this spec covers the tab + toggle wiring.

test.use({ storageState: path.join(__dirname, "..", ".auth-state-notified.json") });

test.describe("Profile notification subscriptions", () => {
  test("visiting signed in subscribes and the tab lists the sphere", async ({ page }) => {
    await page.goto("/crowd/profile/notifications/");

    await expect(page.getByRole("tab", { name: "Notifications" })).toBeVisible();
    // The request that opened the tab subscribed the visitor to this sphere.
    await expect(page.getByRole("button", { name: /Mute|Unmute/ }).first()).toBeVisible();
  });

  test("mute and unmute round-trip with a visible badge", async ({ page }) => {
    await page.goto("/crowd/profile/notifications/");

    // Self-healing across retries: a leftover muted row starts with Unmute.
    const mute = page.getByRole("button", { name: "Mute", exact: true }).first();
    if (!(await mute.isVisible().catch(() => false))) {
      await page.getByRole("button", { name: "Unmute" }).first().click();
    }

    await page.getByRole("button", { name: "Mute", exact: true }).first().click();
    await expect(page.getByText("Subscription muted.")).toBeVisible();
    await expect(page.getByText("Muted", { exact: true }).first()).toBeVisible();

    await page.getByRole("button", { name: "Unmute" }).first().click();
    await expect(page.getByText("Subscription unmuted.")).toBeVisible();
    await expect(page.getByText("Muted", { exact: true })).toHaveCount(0);
  });
});
