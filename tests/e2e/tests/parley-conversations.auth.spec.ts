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

const direct = (fields: Partial<Conversation> = {}): Conversation => ({
  canWrite: true,
  id: "conversation:12",
  isAdmin: false,
  kind: "direct",
  members: [me, ada],
  name: "",
  state: "active",
  title: ada.name,
  ...fields,
});

const group = (fields: Partial<Conversation> = {}): Conversation => ({
  canWrite: true,
  id: "conversation:20",
  isAdmin: true,
  kind: "group",
  members: [me, ada, kuba],
  name: "Friday crew",
  state: "active",
  title: "Friday crew",
  ...fields,
});

async function openList(page: Page): Promise<Locator> {
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(panel.getByRole("navigation", { name: copy.roomsLabel })).toBeVisible();
  return panel;
}

const roomButton = (panel: Locator, name: string): Locator =>
  panel
    .getByRole("navigation", { name: copy.roomsLabel })
    .getByRole("button", { name: new RegExp(name, "u") });

test("A person conversations are open to finds someone and writes to them first", async ({
  page,
}) => {
  await routeBootstrap(page, [{ canMessage: true }]);
  let sent = 0;
  const worker = (await FakeWorker.install(page)).on("sendMessage", (input) => {
    sent += 1;
    return sent === 1
      ? { ok: true, value: message({ authorId: me.id, body: String(input.body), id: 1 }) }
      : { code: "pending", ok: false };
  });
  const calls = await routeApi(page, {
    "conversations/direct/": [
      { json: { error: "not_found" }, status: 404 },
      "abort",
      { json: direct(), status: 201 },
    ],
    "people/": (_body, url) => {
      const query = url.searchParams.get("q");
      if (query === "fa") return { json: {}, status: 500 };
      return { json: { people: query === "ad" ? [ada] : [] }, status: 200 };
    },
  });

  const panel = await openList(page);
  await panel.getByRole("button", { name: copy.newMessage }).click();
  await expect(panel.getByRole("heading", { name: copy.newMessage })).toBeVisible();
  const search = panel.getByLabel(copy.searchPeople);
  await expect(search).toBeFocused();
  await expect(panel.getByText(copy.searchHint)).toBeVisible();

  await search.fill("zz");
  await expect(panel.getByText(copy.nobodyFound)).toBeVisible();
  await search.fill("fa");
  await expect(panel.getByText(copy.errorUnknown)).toBeVisible();
  await search.fill("ad");
  const found = panel.getByRole("button", { name: ada.name });
  await expect(found).toBeVisible();
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-new-message.png" });

  // Escape empties the search before it would close the chat.
  await search.press("Escape");
  await expect(search).toHaveValue("");
  await expect(panel).toBeVisible();
  await search.fill("ad");

  await found.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorNotFound);
  await found.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.connectionError);
  await found.click();
  await expect(panel.getByRole("heading", { name: ada.name })).toBeVisible();
  expect(calls.filter(({ path: where }) => where === "conversations/direct/").at(-1)?.body).toEqual(
    { userId: ada.id },
  );
  await expect(panel.getByText(copy.directMessage)).toBeVisible();
  await expect(panel.getByText(copy.emptyDirect)).toBeVisible();
  expect(worker.sockets.some((socket) => /parley-inbox-agent\/1\b/u.test(socket.url()))).toBe(true);

  const composer = panel.getByLabel(copy.messageLabel, { exact: true });
  await composer.fill("Fancy a game on Friday?");
  await composer.press("Enter");
  await expect(panel.getByText("Fancy a game on Friday?")).toBeVisible();
  expect(worker.called("sendMessage")[0]?.url).toMatch(/parley-conversation-agent\/12\b/u);
  await composer.fill("Hello?");
  await composer.press("Enter");
  await expect(panel.getByRole("alert")).toHaveText(copy.errorPending);
});

test("A group gets a name and people, and its admin shapes who is in it", async ({ page }) => {
  await routeBootstrap(page, [{ canMessage: true }]);
  await FakeWorker.install(page);
  const calls = await routeApi(page, {
    "conversations/20/leave/": [{ status: 204 }],
    "conversations/20/name/": [
      { json: { error: "invalid_title" }, status: 422 },
      { json: group({ name: "Saturday crew", title: "Saturday crew" }), status: 200 },
    ],
    "conversations/20/members/": [
      { json: { error: "too_many" }, status: 422 },
      { json: group({ members: [me, ada, kuba] }), status: 200 },
    ],
    "conversations/20/members/8/remove/": [
      { json: { error: "forbidden" }, status: 403 },
      { status: 204 },
    ],
    "conversations/groups/": [
      { json: { error: "too_many" }, status: 422 },
      { json: { error: "invalid_title" }, status: 422 },
      { json: group(), status: 201 },
    ],
    "people/": () => ({ json: { people: [ada, kuba] }, status: 200 }),
  });

  const panel = await openList(page);
  await panel.getByRole("button", { name: copy.newMessage }).click();
  await panel.getByRole("button", { name: copy.newGroup }).click();
  await expect(panel.getByRole("heading", { name: copy.newGroup })).toBeVisible();
  await panel.getByRole("button", { name: copy.backToNewMessage }).click();
  await expect(panel.getByRole("heading", { name: copy.newMessage })).toBeVisible();
  await panel.getByRole("button", { name: copy.newGroup }).click();

  // People come first; a name is optional.
  const search = panel.getByRole("searchbox", { name: copy.groupPeople });
  await expect(search).toBeFocused();
  const create = panel.getByRole("button", { name: copy.createGroup });
  await create.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.groupNeedsPeople);
  await panel.getByLabel(copy.groupName).fill("Friday crew");

  await search.fill("a");
  await expect(panel.getByText(copy.searchHint)).toBeVisible();
  // Enter in the search does not send the form half-filled.
  await search.press("Enter");
  await search.fill("ad");
  await panel.getByRole("button", { name: ada.name }).click();
  await panel.getByRole("button", { name: kuba.name }).click();
  const chosen = panel.getByRole("list", { name: copy.groupPeople });
  await chosen.getByRole("button", { exact: true, name: `Remove ${kuba.name}` }).click();
  await expect(chosen.getByText(kuba.name)).toBeHidden();
  await panel.getByRole("button", { name: kuba.name }).click();
  await expect(chosen.getByText(kuba.name)).toBeVisible();
  await analyzePageAccessibility(page);

  await create.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorTooMany);
  await create.click();
  await expect(panel.getByRole("alert")).toHaveText(copy.groupTitleTooLong);
  await create.click();
  await expect(panel.getByRole("heading", { name: "Friday crew" })).toBeVisible();
  expect(calls.find(({ path: where }) => where === "conversations/groups/")?.body).toEqual({
    memberIds: [ada.id, kuba.id],
    title: "Friday crew",
  });
  await expect(panel.getByText("3 members")).toBeVisible();
  await expect(panel.getByText(copy.emptyGroup)).toBeVisible();

  const opener = panel.getByRole("button", { name: copy.detailsLabel });
  await opener.click();
  const details = panel.getByRole("region", { name: copy.detailsLabel });
  await expect(details.getByRole("button", { name: copy.backToConversation })).toBeFocused();
  await expect(details.getByText(copy.you)).toBeVisible();
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-group-details.png" });

  // Anyone in it names it; an unchanged name has nothing to save.
  const name = details.getByLabel(copy.nameLabel);
  const save = details.getByRole("button", { name: copy.saveName });
  await expect(name).toHaveValue("Friday crew");
  await expect(save).toBeDisabled();
  await name.fill("Saturday crew");
  await save.click();
  await expect(details.getByRole("alert")).toHaveText(copy.groupTitleTooLong);
  await save.click();
  await expect(details.getByRole("status").filter({ hasText: copy.nameSaved })).toBeVisible();
  await expect(save).toBeDisabled();
  expect(
    calls.filter(({ path: where }) => where === "conversations/20/name/").at(-1)?.body,
  ).toEqual({ name: "Saturday crew" });

  const remove = details.getByRole("button", { name: `Remove ${kuba.name} from the group` });
  await remove.click();
  const sheet = details.getByRole("alertdialog");
  await expect(sheet).toContainText(`Remove ${kuba.name} from the group?`);
  await sheet.getByRole("button", { name: copy.cancelLabel }).click();
  await expect(remove).toBeFocused();
  await remove.click();
  await sheet.getByRole("button", { name: copy.removeLabel }).click();
  await expect(details.getByRole("alert")).toHaveText(copy.errorForbidden);
  await remove.click();
  await sheet.getByRole("button", { name: copy.removeLabel }).click();
  await expect(details.getByText(kuba.name)).toBeHidden();
  await expect(details.getByRole("heading", { name: "2 members" })).toBeVisible();

  await details.getByRole("button", { name: copy.addPeople }).click();
  const add = details.getByLabel(copy.addPeople);
  await expect(add).toBeFocused();
  await add.fill("ku");
  await expect(details.getByRole("button", { exact: true, name: ada.name })).toBeHidden();
  await details.getByRole("button", { name: kuba.name }).click();
  await expect(details.getByRole("alert")).toHaveText(copy.errorTooMany);
  await details.getByRole("button", { name: kuba.name }).click();
  await expect(
    details.getByRole("status").filter({ hasText: `${kuba.name} added.` }),
  ).toBeVisible();
  expect(calls.find(({ path: where }) => where === "conversations/20/members/")?.body).toEqual({
    memberIds: [kuba.id],
  });

  await details.getByRole("button", { name: copy.backToConversation }).click();
  await expect(opener).toBeFocused();
  await opener.click();
  await details.getByRole("button", { name: copy.leaveGroup }).click();
  await details.getByRole("alertdialog").getByRole("button", { name: copy.leaveGroup }).click();
  await expect(panel.getByRole("navigation", { name: copy.roomsLabel })).toBeVisible();
  await expect(roomButton(panel, "Friday crew")).toBeHidden();
});

test("A request waits on top until it is accepted, declined or blocked", async ({ page }) => {
  const asking = (person: Person, id: string): Conversation =>
    direct({ canWrite: false, id, members: [person, me], state: "request", title: person.name });
  // Someone who asked and has since gone, name and all.
  const gone = direct({
    canWrite: false,
    id: "conversation:15",
    members: [me],
    state: "request",
    title: "",
  });
  // What the list says once a block has it asked again.
  let listed = [direct(), gone];
  await routeBootstrap(page, [
    {
      canMessage: true,
      conversations: [
        asking(ada, "conversation:12"),
        asking(kuba, "conversation:13"),
        asking(ola, "conversation:14"),
        gone,
      ],
    },
  ]);
  await FakeWorker.install(page).then((worker) =>
    worker.on("getActivity", (_input, url) => ({
      ok: true,
      value: /parley-inbox-agent/u.test(url)
        ? { "conversation:12": { at: Date.now(), unread: true } }
        : {},
    })),
  );
  const calls = await routeApi(page, {
    "blocks/": [{ json: {}, status: 500 }, { status: 204 }],
    "conversations/": () => ({ json: { conversations: listed }, status: 200 }),
    "conversations/12/accept/": [
      { json: {}, status: 500 },
      { json: direct(), status: 200 },
    ],
    "conversations/12/leave/": () => {
      listed = listed.filter(({ id }) => id !== "conversation:12");
      return { status: 204 };
    },
    "conversations/13/decline/": [{ json: {}, status: 500 }, { status: 204 }],
    "conversations/14/decline/": [{ status: 204 }],
    "conversations/15/decline/": [{ status: 204 }],
  });

  await page.goto("/");
  await expect(launcherOf(page)).toHaveAccessibleDescription(/1 unread conversation/u);
  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(panel.getByRole("heading", { name: copy.requests })).toBeVisible();
  await expect(roomButton(panel, ada.name)).toBeFocused();
  await expect(roomButton(panel, ada.name)).toContainText(copy.requestFrom);
  await expect(roomButton(panel, copy.typingSomeone)).toContainText(copy.requestFrom);

  await roomButton(panel, ada.name).click();
  const question = panel.getByText(`${ada.name} wants to message you.`);
  await expect(question).toBeVisible();
  await expect(panel.getByLabel(copy.messageLabel, { exact: true })).toBeHidden();
  await analyzePageAccessibility(page);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-request.png" });
  await panel.getByRole("button", { exact: true, name: copy.accept }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);
  await panel.getByRole("button", { exact: true, name: copy.accept }).click();
  await expect(panel.getByLabel(copy.messageLabel, { exact: true })).toBeVisible();
  await expect(question).toBeHidden();

  await panel.getByRole("button", { name: copy.backLabel }).click();
  await roomButton(panel, kuba.name).click();
  await panel.getByRole("button", { exact: true, name: copy.decline }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);
  await panel.getByRole("button", { exact: true, name: copy.decline }).click();
  await expect(roomButton(panel, kuba.name)).toBeHidden();

  await roomButton(panel, ola.name).click();
  const block = panel.getByRole("button", { exact: true, name: copy.block });
  await block.click();
  const sheet = panel.getByRole("alertdialog");
  await expect(sheet).toContainText(`Block ${ola.name}?`);
  await sheet.getByRole("button", { name: copy.cancelLabel }).click();
  await block.click();
  await sheet.getByRole("button", { name: copy.block }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);
  await block.click();
  await sheet.getByRole("button", { name: copy.block }).click();
  await expect(roomButton(panel, ola.name)).toBeHidden();
  // With nobody left to block, blocking only declines.
  await roomButton(panel, copy.typingSomeone).click();
  await block.click();
  await sheet.getByRole("button", { name: copy.block }).click();
  await expect(roomButton(panel, copy.typingSomeone)).toBeHidden();
  expect(calls.filter(({ path: where }) => where === "blocks/").map(({ body }) => body)).toEqual([
    { userId: ola.id },
    { userId: ola.id },
  ]);

  // Blocked from a conversation already under way, it stays, closed.
  listed = [direct({ canWrite: false })];
  await roomButton(panel, ada.name).click();
  await panel.getByRole("button", { name: copy.detailsLabel }).click();
  const details = panel.getByRole("region", { name: copy.detailsLabel });
  await expect(details.getByRole("heading", { name: copy.membersLabel })).toBeVisible();
  await details.getByRole("button", { name: `Block ${ada.name}` }).click();
  await details.getByRole("alertdialog").getByRole("button", { name: copy.block }).click();
  await expect(panel.getByText(copy.readOnly)).toBeVisible();

  await panel.getByRole("button", { name: copy.detailsLabel }).click();
  const listings = () => calls.filter(({ path: where }) => where === "conversations/").length;
  const before = listings();
  await details.getByRole("button", { name: copy.leaveConversation }).click();
  await expect(details.getByRole("alertdialog")).toContainText(copy.leaveConversationConfirm);
  await details
    .getByRole("alertdialog")
    .getByRole("button", { name: copy.leaveConversation })
    .click();
  // Its news still in the inbox, the list is asked again, and leaves it out.
  await expect.poll(listings).toBeGreaterThan(before);
  await expect(roomButton(panel, ada.name)).toBeHidden();
});

test("News from a conversation the list never had brings it in; one that shuts the door goes", async ({
  page,
}) => {
  await routeBootstrap(page, [{ canMessage: true, conversations: [direct()] }]);
  const worker = (await FakeWorker.install(page))
    .on("getActivity", () => ({ ok: true, value: {} }))
    .on("loadBefore", (_input, url) => ({
      ok: true,
      value: /parley-conversation-agent/u.test(url)
        ? [message({ authorId: ada.id, authorName: ada.name, body: "Are you coming?", id: 4 })]
        : [],
    }));
  let lists = 0;
  let delayMs = 0;
  const gone = new Set<string>();
  const surprise = group({ id: "conversation:30", isAdmin: false, title: "Surprise party" });
  const calls = await routeApi(page, {
    "conversations/": () => {
      lists += 1;
      // The list itself failing once leaves the room to redial.
      if (lists === 2) return { json: {}, status: 500 };
      const conversations = [direct(), surprise].filter(({ id }) => !gone.has(id));
      return { delayMs, json: { conversations }, status: 200 };
    },
  });

  const panel = await openList(page);
  await expect
    .poll(() => worker.sockets.some((socket) => /parley-inbox-agent/u.test(socket.url())))
    .toBe(true);
  worker.push(
    "room.activity",
    { at: Date.now(), latestMessageId: 1, roomId: surprise.id },
    /parley-inbox-agent/u,
  );
  await expect(roomButton(panel, "Surprise party")).toBeVisible();
  await expect(roomButton(panel, "Surprise party")).toContainText(copy.unread);
  await expect(launcherOf(page)).toHaveAccessibleDescription(/1 unread conversation/u);

  await roomButton(panel, ada.name).click();
  await expect(panel.getByText("Are you coming?")).toBeVisible();
  await expect
    .poll(() => worker.called("markRead").map(({ input, url }) => [input, /inbox/u.test(url)]))
    .toEqual([[{ messageId: 4, roomId: "conversation:12" }, true]]);

  // Shut out while the list still has it, or cannot say: the room stays and
  // redials.
  const redialled = () =>
    worker.sockets.some((socket) => /parley-conversation-agent\/12\b/u.test(socket.url()));
  await worker.close(4404, /parley-conversation-agent\/12\b/u);
  await expect.poll(redialled, { timeout: 15_000 }).toBe(true);
  await worker.close(4404, /parley-conversation-agent\/12\b/u);
  await expect(panel.getByRole("heading", { name: ada.name })).toBeVisible();
  await expect.poll(redialled, { timeout: 15_000 }).toBe(true);

  // Dropped from a room already left behind: the list says so, and stays.
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await roomButton(panel, "Surprise party").click();
  await expect(panel.getByRole("heading", { name: "Surprise party" })).toBeVisible();
  await expect
    .poll(() =>
      worker.sockets.some((socket) => /parley-conversation-agent\/30\b/u.test(socket.url())),
    )
    .toBe(true);
  gone.add(surprise.id);
  delayMs = 1000;
  const asked = calls.length;
  await worker.close(4404, /parley-conversation-agent\/30\b/u);
  await expect.poll(() => calls.length).toBeGreaterThan(asked);
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await expect(roomButton(panel, "Surprise party")).toBeHidden();
  await expect(panel.getByRole("navigation", { name: copy.roomsLabel })).toBeVisible();
  delayMs = 0;

  await roomButton(panel, ada.name).click();
  await expect.poll(redialled).toBe(true);
  gone.add("conversation:12");
  await worker.close(4404, /parley-conversation-agent\/12\b/u);
  await expect(panel.getByRole("navigation", { name: copy.roomsLabel })).toBeVisible();
  await expect(roomButton(panel, ada.name)).toBeHidden();
});
