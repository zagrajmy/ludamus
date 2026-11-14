import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  FakeWorker,
  launcherOf,
  message,
  panelOf,
  routeBootstrap,
} from "./helpers/parley";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const { copy } = bootstrap;

const organizers = {
  canModerate: true,
  canWrite: true,
  id: "organizers:1",
  kind: "organizers",
  sphere: 1,
  title: "Zagrajmy",
};
// The manager plays in this one: it is theirs, not only theirs to moderate.
const played = {
  canModerate: true,
  canWrite: true,
  eventTitle: "Bachanalia",
  id: "session:1:40",
  kind: "session",
  moderating: false,
  sphere: 1,
  title: "Mothership",
};
const watchedEvent = {
  canModerate: true,
  canWrite: true,
  id: "event:1:5",
  kind: "event",
  moderating: true,
  sphere: 1,
  title: "Bachanalia",
};
const watched = {
  canModerate: true,
  canWrite: true,
  eventTitle: "Bachanalia",
  id: "session:1:41",
  kind: "session",
  moderating: true,
  sphere: 1,
  title: "Wsiąść do pociągu",
};
const rooms = [organizers, watchedEvent, played, watched];

const listOf = (panel: Locator, name: string): Locator => panel.getByRole("navigation", { name });

// Stands in for a page whose template names its room.
async function onPageOf(page: Page, roomId: string): Promise<void> {
  await page.route(
    (url) => url.pathname === "/",
    async (route) => {
      const response = await route.fetch();
      const body = (await response.text()).replace(
        'data-page-room=""',
        `data-page-room="${roomId}"`,
      );
      await route.fulfill({ body, response });
    },
  );
}

test("A manager's own chats stay apart from the ones they only moderate", async ({ page }) => {
  await routeBootstrap(page, [{ rooms }]);
  const worker = await FakeWorker.install(page);
  await page.goto("/");
  await expect
    .poll(() => worker.sockets.some((socket) => socket.url().includes("parley-sphere-agent/1")))
    .toBe(true);
  worker.push(
    "room.activity",
    { at: Date.now(), latestMessageId: 3, mentionedBy: [], roomId: watched.id },
    /parley-sphere-agent\/1/u,
  );

  // News in a chat they only moderate does not call them to the chat.
  await expect(launcherOf(page)).not.toHaveAccessibleDescription(/unread/u);
  await launcherOf(page).click();
  const panel = panelOf(page);
  const own = listOf(panel, copy.roomsLabel);
  await expect(own.getByRole("button", { name: /Mothership/u })).toBeVisible();
  await expect(own.getByRole("button", { name: /Wsiąść do pociągu/u })).toHaveCount(0);
  const entry = own.getByRole("button", { name: new RegExp(copy.moderation, "u") });
  await expect(entry).toContainText("2 chats you moderate");
  await expect(entry).toContainText(copy.unread);
  await analyzePageAccessibility(page);
  await page.screenshot({
    animations: "disabled",
    path: "screenshots/parley-moderation-entry.png",
  });

  await entry.click();
  const moderation = listOf(panel, copy.moderation);
  await expect(moderation.getByText(copy.moderationHint)).toBeVisible();
  await expect(moderation.getByRole("heading", { name: "Bachanalia" })).toBeVisible();
  await expect(moderation.getByRole("button", { name: /Mothership/u })).toHaveCount(0);
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-moderation-list.png" });

  worker.on("loadBefore", (_input, url) => ({
    ok: true,
    value: url.includes("session-agent/1:41") ? [message({ id: 3 })] : [],
  }));
  await moderation.getByRole("button", { name: /Wsiąść do pociągu/u }).click();
  await expect(panel.getByText("Message 3")).toBeVisible();
  await expect(panel.getByText(`${copy.sessionRoom} · ${copy.moderatorView}`)).toBeVisible();
  await expect(panel.getByText(copy.moderatorReading)).toBeVisible();
  await expect(panel.getByLabel(copy.messageLabel)).toHaveCount(0);
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-moderation-room.png" });

  await panel.getByRole("button", { name: copy.backToModeration }).click();
  await expect(listOf(panel, copy.moderation)).toBeVisible();
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await expect(own).toBeVisible();
});

test("Writing where they only moderate takes a deliberate step", async ({ page }) => {
  await routeBootstrap(page, [{ rooms }]);
  const worker = (await FakeWorker.install(page)).on("sendMessage", (input) => ({
    ok: true,
    value: message({ authorId: bootstrap.user.id, body: String(input.body), id: 9 }),
  }));
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await listOf(panel, copy.roomsLabel)
    .getByRole("button", { name: new RegExp(copy.moderation, "u") })
    .click();
  await listOf(panel, copy.moderation)
    .getByRole("button", { name: /Wsiąść do pociągu/u })
    .click();

  await page.keyboard.type("Hello");
  expect(worker.called("sendMessage")).toHaveLength(0);

  await panel.getByRole("button", { name: copy.writeAsOrganizer }).click();
  const composer = panel.getByLabel(copy.messageLabel);
  await expect(composer).toBeFocused();
  await expect(composer).toHaveAttribute("placeholder", copy.organizerPlaceholder);
  await page.screenshot({
    animations: "disabled",
    path: "screenshots/parley-moderation-writing.png",
  });
  await composer.fill("The table moved to room 2.");
  await composer.press("Enter");
  await expect.poll(() => worker.called("sendMessage").length).toBe(1);
  await expect(panel.getByText("The table moved to room 2.")).toBeVisible();

  // Back in a room of their own, the composer is there from the start.
  await panel.getByRole("button", { name: copy.backToModeration }).click();
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await listOf(panel, copy.roomsLabel)
    .getByRole("button", { name: /Mothership/u })
    .click();
  await expect(panel.getByLabel(copy.messageLabel)).toHaveAttribute(
    "placeholder",
    copy.writePlaceholder,
  );
  await expect(panel.getByText(copy.moderatorReading)).toHaveCount(0);
});

test("On the page of a programme point they only moderate, its chat waits on top", async ({
  page,
}) => {
  await routeBootstrap(page, [{ rooms }]);
  await FakeWorker.install(page);
  await onPageOf(page, watched.id);
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);

  const own = listOf(panel, copy.roomsLabel);
  await expect(own.getByRole("heading", { name: copy.onThisPage })).toBeVisible();
  await expect(own.getByRole("button", { name: /Wsiąść do pociągu/u })).toBeVisible();
  await own.getByRole("button", { name: /Wsiąść do pociągu/u }).click();
  await expect(panel.getByText(copy.moderatorReading)).toBeVisible();
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await expect(own).toBeVisible();
});
