import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  type Conversation,
  eventRoom,
  FakeWorker,
  launcherOf,
  message,
  panelOf,
  type Person,
  routeApi,
  routeBootstrap,
} from "./helpers/parley";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const { copy } = bootstrap;
const me: Person = { avatarUrl: "", id: bootstrap.user.id, name: bootstrap.user.name };
const ada: Person = { avatarUrl: "", id: "7", name: "Ada Lovelace" };
const kuba: Person = { avatarUrl: "", id: "8", name: "Kuba Nowak" };

const organizers = {
  canModerate: true,
  canWrite: true,
  id: "organizers:1",
  kind: "organizers",
  title: "Zagrajmy",
};
const elsewhere = {
  canModerate: false,
  canWrite: true,
  id: "session:2:7",
  kind: "session",
  title: "Wsiąść do pociągu",
};
const party: Conversation = {
  canWrite: true,
  id: "conversation:30",
  isAdmin: false,
  kind: "party",
  members: [me, ada, kuba],
  name: "Drużyna Pierścienia",
  state: "active",
  title: "Drużyna Pierścienia",
};

const roomButton = (panel: Locator, name: string): Locator =>
  panel
    .getByRole("navigation", { name: copy.roomsLabel })
    .getByRole("button", { name: new RegExp(name, "u") });

const menuOf = (page: Page): Locator => page.getByRole("menu", { name: copy.messageActions });

test("Chats from every sphere and party sit in one list, each saying what it is", async ({
  page,
}) => {
  await routeBootstrap(page, [
    { canMessage: true, conversations: [party], rooms: [organizers, eventRoom, elsewhere] },
  ]);
  const worker = await FakeWorker.install(page);

  await page.goto("/");
  await expect
    .poll(() => worker.sockets.map((socket) => new URL(socket.url()).pathname).toSorted())
    .toEqual([
      "/agents/parley-inbox-agent/1",
      "/agents/parley-sphere-agent/1",
      "/agents/parley-sphere-agent/2",
    ]);
  worker.push(
    "room.activity",
    { at: Date.now(), latestMessageId: 4, roomId: elsewhere.id },
    /parley-sphere-agent\/2/u,
  );
  await expect(launcherOf(page)).toHaveAccessibleDescription(/1 unread conversation/u);

  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(roomButton(panel, organizers.title).first()).toContainText(copy.organizersRoom);
  await expect(roomButton(panel, "Drużyna")).toContainText(`${copy.partyRoom} · 3 members`);
  await expect(roomButton(panel, elsewhere.title)).toContainText(copy.sessionRoom);
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-room-kinds.png" });

  worker.on("loadBefore", () => ({ ok: true, value: [message({ id: 4 })] }));
  await roomButton(panel, elsewhere.title).click();
  await expect(panel.getByText("Message 4")).toBeVisible();
  await expect
    .poll(() => worker.called("markRead").map(({ url }) => new URL(url).pathname))
    .toContain("/agents/parley-sphere-agent/2");
  await expect(launcherOf(page)).not.toHaveAccessibleDescription(/unread/u);

  await panel.getByRole("button", { name: copy.backLabel }).click();
  await roomButton(panel, copy.organizersRoom).click();
  await expect(panel.getByText(copy.emptyOrganizers)).toBeVisible();
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await roomButton(panel, copy.eventRoom).click();
  await expect(panel.getByText(copy.emptyEvent)).toBeVisible();
});

test("A party's chat belongs to the party: nobody renames or leaves it there", async ({ page }) => {
  await routeBootstrap(page, [{ canMessage: true, conversations: [party], rooms: [] }]);
  await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await roomButton(panel, "Drużyna").click();

  await expect(panel.getByRole("heading", { name: party.title })).toBeVisible();
  await expect(panel.getByText(copy.emptyParty)).toBeVisible();
  await panel.getByRole("button", { name: copy.detailsLabel }).click();
  const details = panel.getByRole("region", { name: copy.detailsLabel });
  await expect(details.getByText(copy.partyHint)).toBeVisible();
  await expect(details.getByText("3 members")).toBeVisible();
  await expect(details.getByLabel(copy.nameLabel)).toHaveCount(0);
  await expect(details.getByRole("button", { name: copy.leaveGroup })).toHaveCount(0);
  await expect(details.getByRole("button", { name: copy.leaveConversation })).toHaveCount(0);
  await expect(details.getByRole("button", { name: /^Block/u })).toHaveCount(0);
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-party-details.png" });
});

test("Someone under 16 still talks in their party's chat, and can block there", async ({
  page,
}) => {
  await routeBootstrap(page, [
    { ageGate: "under_16", canMessage: false, conversations: [party], rooms: [eventRoom] },
  ]);
  const worker = (await FakeWorker.install(page)).on("loadBefore", (_input, url) =>
    url.includes("conversation")
      ? { ok: true, value: [message({ authorId: ada.id, authorName: ada.name, id: 1 })] }
      : { ok: true, value: [] },
  );
  const calls = await routeApi(page, { "blocks/": [{ status: 204 }] });
  await page.goto("/");
  await expect
    .poll(() => worker.sockets.some((socket) => socket.url().includes("parley-inbox-agent/1")))
    .toBe(true);

  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(panel.getByRole("button", { name: copy.newMessage })).toHaveCount(0);
  await roomButton(panel, "Drużyna").click();
  await expect(panel.getByText("Message 1")).toBeVisible();
  await panel
    .getByText("Message 1")
    .locator("xpath=..")
    .getByRole("button", { name: copy.messageActions })
    .click();
  await menuOf(page)
    .getByRole("menuitem", { name: `Block ${ada.name}` })
    .click();
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.block }).click();
  await expect(panel.getByText(`${ada.name} blocked.`)).toBeVisible();
  expect(calls.find(({ path: where }) => where === "blocks/")?.body).toEqual({ userId: ada.id });
});

test("On an event's page the chat opens on the event's own room", async ({ page }) => {
  await routeBootstrap(page, [{ rooms: [organizers, eventRoom] }]);
  await FakeWorker.install(page);
  // NOTE: stands in for the event page, whose template sets this.
  await page.addInitScript(() => {
    addEventListener("DOMContentLoaded", () => {
      document.querySelector<HTMLElement>("[data-parley-root]")!.dataset.pageRoom = "event:1:5";
    });
  });
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);

  await expect(panel.getByText(copy.emptyEvent)).toBeVisible();
  await expect(panel.getByText(`${copy.eventRoom}`).first()).toBeVisible();
});
