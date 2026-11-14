import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  type Conversation,
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
const ola: Person = { avatarUrl: "", id: "9", name: "Ola Wiśniewska" };

const crew: Conversation = {
  canWrite: true,
  id: "conversation:20",
  isAdmin: false,
  kind: "group",
  members: [me, ada, kuba],
  name: "",
  state: "active",
  title: "Friday crew",
};

const withKuba = (fields: Partial<Conversation> = {}): Conversation => ({
  canWrite: true,
  id: "conversation:12",
  isAdmin: false,
  kind: "direct",
  members: [me, kuba],
  name: "",
  state: "active",
  title: kuba.name,
  ...fields,
});

const roomButton = (panel: Locator, name: string): Locator =>
  panel
    .getByRole("navigation", { name: copy.roomsLabel })
    .getByRole("button", { name: new RegExp(name, "u") });

function actionsOf(panel: Locator, body: string): Locator {
  return panel
    .getByText(body)
    .locator("xpath=..")
    .getByRole("button", { name: copy.messageActions });
}

const menuOf = (page: Page): Locator => page.getByRole("menu", { name: copy.messageActions });

test("Someone blocked stays out of sight in a group and in an event chat", async ({ page }) => {
  await routeBootstrap(page, [{ blocked: [kuba], canMessage: true, conversations: [crew] }]);
  const now = Date.now();
  const worker = (await FakeWorker.install(page)).on("loadBefore", () => ({
    ok: true,
    value: [
      message({
        authorId: kuba.id,
        authorName: kuba.name,
        body: "Words nobody wants",
        createdAt: now - 60_000,
        id: 1,
      }),
      message({
        authorId: ada.id,
        authorName: ada.name,
        body: "Ada says hi",
        createdAt: now,
        id: 2,
      }),
    ],
  }));
  const calls = await routeApi(page, {
    "blocks/": [{ json: {}, status: 500 }, { status: 204 }],
    "conversations/": () => ({ json: { conversations: [crew] }, status: 200 }),
  });
  const reports: string[] = [];
  await page.route("**/parley/reports/", (route) => {
    reports.push(route.request().postData() ?? "");
    return route.fulfill({ json: {}, status: 201 });
  });

  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await roomButton(panel, "Friday crew").click();
  await expect(panel.getByText("Ada says hi")).toBeVisible();
  await expect(panel.getByText(copy.blockedMessage)).toBeVisible();
  await expect(panel.getByText("Words nobody wants")).toHaveCount(0);
  await expect(panel.getByText(kuba.name)).toHaveCount(0);
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-blocked-message.png" });

  // A conversation's messages are reported like any room's.
  await actionsOf(panel, "Ada says hi").click();
  await menuOf(page).getByRole("menuitem", { name: copy.reportMessage }).click();
  await panel
    .getByRole("alertdialog", { name: copy.reportMessage })
    .getByRole("button", { name: copy.reportMessage })
    .click();
  await expect(panel.getByText(copy.reported)).toBeVisible();
  expect(reports[0]).toContain("conversation:20");

  // In an event chat too, and a blocked typist is never announced.
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await roomButton(panel, "Zagrajmy").click();
  await expect(panel.getByText("Ada says hi")).toBeVisible();
  worker.push(
    "typing.changed",
    { expiresAt: now + 60_000, userId: kuba.id },
    /parley-event-agent/u,
  );
  worker.push("typing.changed", { expiresAt: now + 60_000, userId: ada.id }, /parley-event-agent/u);
  await expect(panel.getByText(`${ada.name} is typing…`)).toBeVisible();

  await actionsOf(panel, "Ada says hi").click();
  await menuOf(page)
    .getByRole("menuitem", { name: `Block ${ada.name}` })
    .click();
  const sheet = panel.getByRole("alertdialog");
  await expect(sheet).toContainText(`Block ${ada.name}? Their messages will be hidden`);
  await sheet.getByRole("button", { name: copy.block }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);
  await actionsOf(panel, "Ada says hi").click();
  await menuOf(page)
    .getByRole("menuitem", { name: `Block ${ada.name}` })
    .click();
  await sheet.getByRole("button", { name: copy.block }).click();
  await expect(panel.getByText(`${ada.name} blocked.`)).toBeVisible();
  await expect(panel.getByText("Ada says hi")).toHaveCount(0);
  await expect(panel.getByText(copy.blockedMessage)).toHaveCount(2);
  await expect(panel.getByText(`${ada.name} is typing…`)).toHaveCount(0);
  expect(calls.filter(({ path: where }) => where === "blocks/").at(-1)?.body).toEqual({
    userId: ada.id,
  });
});

test("Blocked people are unblocked from a conversation's details or their own list", async ({
  page,
}) => {
  await routeBootstrap(page, [
    { blocked: [kuba, ola], canMessage: true, conversations: [withKuba({ canWrite: false })] },
  ]);
  await FakeWorker.install(page);
  const calls = await routeApi(page, {
    "blocks/8/remove/": [{ status: 204 }],
    "blocks/9/remove/": [{ json: {}, status: 500 }, { status: 204 }],
    "conversations/": () => ({ json: { conversations: [withKuba()] }, status: 200 }),
  });

  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await roomButton(panel, kuba.name).click();
  await expect(panel.getByText(copy.readOnly)).toBeVisible();
  await panel.getByRole("button", { name: copy.detailsLabel }).click();
  const details = panel.getByRole("region", { name: copy.detailsLabel });
  await details.getByRole("button", { name: `Unblock ${kuba.name}` }).click();
  await expect(details.getByRole("status")).toHaveText(`${kuba.name} unblocked.`);
  await expect(details.getByRole("button", { name: `Block ${kuba.name}` })).toBeVisible();
  expect(calls.some(({ path: where }) => where === "blocks/8/remove/")).toBe(true);
  await details.getByRole("button", { name: copy.backToConversation }).click();
  // Unblocked, the conversation can be written in again.
  await expect(panel.getByLabel(copy.messageLabel, { exact: true })).toBeVisible();

  await panel.getByRole("button", { name: copy.backLabel }).click();
  await panel.getByRole("button", { name: copy.newMessage }).click();
  const list = panel.getByRole("button", { name: copy.blockedPeople });
  await expect(list).toContainText("1");
  await list.click();
  const back = panel.getByRole("button", { name: copy.backToNewMessage });
  await expect(back).toBeFocused();
  await back.click();
  await expect(panel.getByRole("heading", { name: copy.newMessage })).toBeVisible();
  await list.click();
  await expect(panel.getByRole("heading", { name: copy.blockedPeople })).toBeVisible();
  await expect(panel.getByText(copy.blockedHint)).toBeVisible();
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-blocked-people.png" });

  const unblock = panel.getByRole("button", { name: `Unblock ${ola.name}` });
  await unblock.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);
  await unblock.click();
  await expect(panel.getByRole("status")).toHaveText(`${ola.name} unblocked.`);
  await expect(panel.getByText(copy.nobodyBlocked)).toBeVisible();
  await expect(back).toBeFocused();

  await launcherOf(page).click();
  await expect(panel).toBeHidden();
  await launcherOf(page).click();
  await panel.getByRole("button", { name: copy.newMessage }).click();
  await expect(panel.getByRole("button", { name: copy.blockedPeople })).toHaveCount(0);
});

test("Someone who cannot message still finds the people they blocked in a room", async ({
  page,
}) => {
  await routeBootstrap(page, [{ blocked: [], canMessage: false }]);
  (await FakeWorker.install(page)).on("loadBefore", () => ({
    ok: true,
    value: [
      message({
        authorId: ada.id,
        authorName: ada.name,
        body: "Ada says hi",
        createdAt: Date.now(),
        id: 1,
      }),
    ],
  }));
  await routeApi(page, {
    "blocks/": [{ status: 204 }],
    "blocks/7/remove/": [{ status: 204 }],
  });

  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(panel.getByRole("button", { name: copy.blockedPeople })).toHaveCount(0);
  await roomButton(panel, "Zagrajmy").click();
  await actionsOf(panel, "Ada says hi").click();
  await menuOf(page)
    .getByRole("menuitem", { name: `Block ${ada.name}` })
    .click();
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.block }).click();
  await expect(panel.getByText(copy.blockedMessage)).toBeVisible();

  await panel.getByRole("button", { name: copy.backLabel }).click();
  await panel.getByRole("button", { name: copy.blockedPeople }).click();
  await panel.getByRole("button", { name: `Unblock ${ada.name}` }).click();
  await expect(panel.getByRole("status")).toHaveText(`${ada.name} unblocked.`);
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await expect(panel.getByRole("navigation", { name: copy.roomsLabel })).toBeVisible();
  await expect(panel.getByRole("button", { name: copy.blockedPeople })).toHaveCount(0);
});
