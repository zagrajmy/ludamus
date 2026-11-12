import type { Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import { bootstrap, FakeWorker, launcherOf, panelOf, routeBootstrap } from "./helpers/parley";

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

  // The window does not trap the page: Escape out there is the page's own.
  const pageLink = page.getByRole("main").getByRole("link").first();
  await pageLink.focus();
  await page.keyboard.press("Escape");
  await expect(rooms).toBeVisible();
  await expect(pageLink).toBeFocused();

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

  // Reopened, it is back where it was left; the back button reaches the rest.
  await page.setViewportSize({ height: 844, width: 390 });
  await launcher.click();
  await expect(panel.getByText(bootstrap.copy.readOnly)).toBeVisible();
  await panel.getByRole("button", { name: "Back to conversations" }).click();
  await rooms.getByRole("button", { name: /Zagrajmy/u }).click();
  await expect(page.getByPlaceholder("Write a message…")).toBeVisible();
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-mobile.png" });
});

test("The chat window floats where it is dragged, and stays there", async ({ page }) => {
  // Measured mid-opening, it would still be growing.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await routeBootstrap(page);
  await FakeWorker.install(page);
  await page.goto("/");
  const launcher = launcherOf(page);
  await launcher.click();
  const panel = panelOf(page);
  const header = panel.locator("header").first();
  await expect(header).toBeVisible();
  const corner = async () => {
    const { x, y } = (await panel.boundingBox())!;
    return [Math.round(x), Math.round(y)];
  };
  const before = (await panel.boundingBox())!;
  expect(before.x).toBeGreaterThan(16);

  // A press without a move leaves it where it is.
  const grip = (await header.boundingBox())!;
  await page.mouse.click(grip.x + 120, grip.y + 20);
  expect(await panel.boundingBox()).toEqual(before);

  // Dragged by its header, it follows the pointer; far past an edge, it
  // stops 16px inside the viewport.
  await page.mouse.move(grip.x + 120, grip.y + 20);
  await page.mouse.down();
  await page.mouse.move(grip.x - 2000, grip.y - 2000, { steps: 6 });
  await page.mouse.up();
  await expect.poll(corner).toEqual([16, 16]);

  // A press on a button in the header is a press, not a drag.
  await panel.getByRole("button", { name: bootstrap.copy.closeLabel }).click();
  await expect(panel).toBeHidden();

  // Reopened, it comes back where it was left.
  await launcher.click();
  await expect(panel).toBeVisible();
  await expect.poll(corner).toEqual([16, 16]);

  // Left in the far corner, a smaller browser window pushes it back inside.
  await page.mouse.move(grip.x + 120 - before.x + 16, grip.y + 20 - before.y + 16);
  await page.mouse.down();
  await page.mouse.move(4000, 4000, { steps: 6 });
  await page.mouse.up();
  await page.setViewportSize({ height: 600, width: 900 });
  await expect
    .poll(async () => {
      const box = (await panel.boundingBox())!;
      return [Math.round(box.x + box.width), Math.round(box.y + box.height)];
    })
    .toEqual([900 - 16, 600 - 16]);

  // A phone gets it full screen, whatever spot was saved, and no drag.
  await page.setViewportSize({ height: 844, width: 390 });
  await expect
    .poll(async () => await panel.boundingBox())
    .toEqual({ height: 844, width: 390, x: 0, y: 0 });
  await page.mouse.move(120, 20);
  await page.mouse.down();
  await page.mouse.move(200, 300, { steps: 4 });
  await page.mouse.up();
  expect(await panel.boundingBox()).toEqual({ height: 844, width: 390, x: 0, y: 0 });
});

test("With storage refused, the chat window still opens and moves", async ({ page }) => {
  await routeBootstrap(page);
  await FakeWorker.install(page);
  await page.addInitScript(() => {
    const { getItem } = Storage.prototype;
    Storage.prototype.getItem = function (key) {
      if (key === "parley.window") throw new DOMException("Storage is off.", "SecurityError");
      return getItem.call(this, key);
    };
  });
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  const grip = (await panel.locator("header").first().boundingBox())!;
  await page.mouse.move(grip.x + 120, grip.y + 20);
  await page.mouse.down();
  await page.mouse.move(grip.x - 2000, grip.y - 2000, { steps: 6 });
  await page.mouse.up();
  await expect
    .poll(async () => {
      const { x, y } = (await panel.boundingBox())!;
      return [Math.round(x), Math.round(y)];
    })
    .toEqual([16, 16]);
});

test("On a programme point's page the chat opens on its room, kept on top of the list", async ({
  page,
}) => {
  await routeBootstrap(page, [{ ageGate: "unconfirmed" }]);
  await FakeWorker.install(page);
  // NOTE: stands in for an enrolment page, whose template sets this.
  await page.addInitScript(() => {
    addEventListener("DOMContentLoaded", () => {
      document.querySelector<HTMLElement>("[data-parley-root]")!.dataset.pageSession = "42";
    });
  });
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(panel.getByRole("heading", { name: "Mothership" })).toBeVisible();

  await panel.getByRole("button", { name: "Back to conversations" }).click();
  const rooms = panel.getByRole("navigation", { name: "Conversations" });
  await expect(rooms.getByRole("heading")).toHaveText([
    bootstrap.copy.onThisPage,
    bootstrap.copy.allChats,
  ]);
  await expect(rooms.getByRole("button").first()).toContainText("Mothership");
  // Someone who has not said they are 16 or older learns why they cannot
  // start a conversation, and where to change that.
  await expect(rooms.getByRole("link", { name: bootstrap.copy.confirmAge })).toHaveAttribute(
    "href",
    bootstrap.ageUrl,
  );
});

test("Someone under 16 learns when direct messages open for them", async ({ page }) => {
  await routeBootstrap(page, [{ ageGate: "under_16" }]);
  await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();

  const rooms = panelOf(page).getByRole("navigation", { name: "Conversations" });
  await expect(rooms.getByText(bootstrap.copy.messagingUnder16)).toBeVisible();
  await expect(rooms.getByRole("link")).toHaveCount(0);
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
