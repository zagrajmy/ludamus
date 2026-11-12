import type { Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import { bootstrap, FakeWorker, launcherOf, routeBootstrap } from "./helpers/parley";

// The chromium-auth project's default storage state (e2e-tester) is a plain
// user with no sphere role, so it can't reach /multiverse/panel/ to flip
// the setting this spec exercises. Every other panel-touching .auth.spec.ts
// (modal-surfaces, promotion) swaps in the superuser state for the same
// reason.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

// The chat setting is shared state, so the tests that flip it run in order.
test.describe.configure({ mode: "serial" });

// The chat is on by default; an organizer turns it off in sphere settings.
async function setChat(page: Page, enabled: boolean): Promise<void> {
  await page.goto("/multiverse/panel/");
  await page.getByLabel("Enable chat").setChecked(enabled);
  await page.getByRole("button", { name: "Save Settings" }).click();
  await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();
}

test("The launcher counts unread conversations before the chat is ever opened", async ({
  page,
}) => {
  await routeBootstrap(page);
  await FakeWorker.install(page, { "sphere:1": { at: Date.now(), unread: true } });

  await page.goto("/");
  const launcher = launcherOf(page);
  await expect(launcher).toHaveAttribute("aria-expanded", "false");
  await expect(launcher).toHaveAccessibleDescription(/1 unread conversation/u);
});

test("The chat launcher opens an accessible chat window from its room list", async ({ page }) => {
  await routeBootstrap(page);
  await FakeWorker.install(page);

  await page.goto("/");
  const launcher = launcherOf(page);
  await expect(launcher).toHaveAttribute("aria-expanded", "false");
  await launcher.click();

  const panel = page.getByRole("dialog", { name: "Chat" });
  const rooms = panel.getByRole("navigation", { name: "Conversations" });
  await expect(rooms).toBeVisible();
  await expect(launcher).toHaveAttribute("aria-expanded", "true");
  await analyzePageAccessibility(page);

  await rooms.getByRole("button", { name: /Zagrajmy/u }).click();
  await expect(panel.getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
  await expect(panel.getByLabel("Message", { exact: true })).toBeFocused();
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-desktop.png" });

  await panel.getByRole("button", { name: "Back to conversations" }).click();
  await rooms.getByRole("button", { name: /Mothership/u }).click();
  await expect(panel.getByText(bootstrap.copy.readOnly)).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(panel).toBeHidden();
  await expect(launcher).toBeFocused();

  await page.setViewportSize({ height: 844, width: 390 });
  await launcher.click();
  await page
    .getByRole("navigation", { name: "Conversations" })
    .getByRole("button", { name: /Zagrajmy/u })
    .click();
  await expect(page.getByPlaceholder("Write a message…")).toBeVisible();
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-mobile.png" });
});

test("An organizer who turns the chat off removes its launcher", async ({ page }) => {
  try {
    await setChat(page, false);
    await page.goto("/");
    await expect(launcherOf(page)).toHaveCount(0);
  } finally {
    await setChat(page, true);
  }
});
