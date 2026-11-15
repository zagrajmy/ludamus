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
  openRoom,
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
const zed: Person = { avatarUrl: "", id: "10", name: "Zed Blocked" };
const yan: Person = { avatarUrl: "", id: "11", name: "Yan Blocking" };

const crew: Conversation = {
  canWrite: true,
  id: "conversation:20",
  isAdmin: true,
  kind: "group",
  members: [me, ada, kuba, ola, zed, yan],
  name: "Friday crew",
  state: "active",
  title: "Friday crew",
};
const duo: Conversation = {
  ...crew,
  id: "conversation:21",
  members: [me, ola],
  name: "",
  title: ola.name,
};

function thread(): ReturnType<typeof message>[] {
  const now = Date.now();
  return [
    message({ body: "Before mentions, <@7> was just text", createdAt: now - 5 * 60_000, id: 1 }),
    message({
      authorId: kuba.id,
      body: "<@1> your move, then <@7>. <@12> left, and <@77> is no one",
      createdAt: now - 4 * 60_000,
      id: 2,
      mentions: [me.id, ada.id, "12"],
    }),
    message({
      authorId: me.id,
      authorName: me.name,
      body: "On it, <@8>",
      createdAt: now - 3 * 60_000,
      id: 3,
      mentions: [kuba.id],
    }),
  ];
}

async function shoot(page: Page, name: string): Promise<void> {
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    await page.evaluate(
      (dark) => document.documentElement.classList.toggle("dark", dark),
      theme === "dark",
    );
    await page.screenshot({
      animations: "disabled",
      path: `screenshots/parley-${name}-${theme}.png`,
    });
  }
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
}

const options = (panel: Locator) =>
  panel.getByRole("listbox", { name: copy.mentionPeople }).getByRole("option");
const named = (...people: Person[]) => people.map(({ name }) => new RegExp(`${name}$`, "u"));
const bubble = (panel: Locator, text: string) => panel.locator("p").filter({ hasText: text });

test("Typing @ offers everyone in the room but oneself, and the keyboard or a tap picks one", async ({
  page,
}) => {
  await routeBootstrap(page, [{ blocked: [zed], canMessage: true, conversations: [crew] }]);
  await routeApi(page, {});
  const worker = (await FakeWorker.install(page))
    .on("loadBefore", () => ({ ok: true, value: thread() }))
    .on("sendMessage", (input) => ({
      ok: true,
      value: message({
        authorId: me.id,
        authorName: me.name,
        body: String(input.body),
        id: 4,
        mentions: input.mentions as string[],
      }),
    }));

  await page.goto("/");
  const panel = await openRoom(page, crew.title, "your move");
  const said = bubble(panel, "your move");
  await expect(said).toContainText(`@${me.name} your move, then @${ada.name}.`);
  await expect(said).toContainText("@Someone left, and <@77> is no one");
  await expect(bubble(panel, "Before mentions")).toContainText("<@7> was just text");
  await expect(bubble(panel, "On it")).toContainText(`On it, @${kuba.name}`);

  const composer = panel.getByLabel(copy.messageLabel, { exact: true });
  await composer.pressSequentially("ada@");
  await expect(panel.getByRole("listbox")).toBeHidden();
  await composer.fill("");
  await composer.pressSequentially("Hi @");
  await expect(options(panel)).toHaveText(named(ada, kuba, ola, zed, yan));
  await expect(composer).toHaveAttribute("aria-autocomplete", "list");
  await expect(composer).toHaveAttribute("aria-activedescendant", `parley-mentions-${ada.id}`);
  await analyzePageAccessibility(page);
  await shoot(page, "mention-picker");

  await composer.press("ArrowDown");
  await expect(options(panel).nth(1)).toHaveAttribute("aria-selected", "true");
  await composer.press("ArrowUp");
  await composer.press("ArrowUp");
  await expect(composer).toHaveAttribute("aria-activedescendant", `parley-mentions-${yan.id}`);
  // A key an input method is still composing is its own, not the picker's.
  await composer.dispatchEvent("keydown", { bubbles: true, isComposing: true, key: "Enter" });
  await expect(composer).toHaveValue("Hi @");

  // A pick replaces the whole word the caret sits in.
  await composer.pressSequentially("Ol");
  await composer.press("ArrowLeft");
  await expect(options(panel)).toHaveText(named(ola));
  await composer.press("Enter");
  await expect(composer).toHaveValue(`Hi @${ola.name} `);
  await expect(panel.getByRole("listbox")).toBeHidden();

  await composer.pressSequentially("and @now");
  await expect(options(panel)).toHaveText(named(kuba));
  await options(panel).first().click();
  await expect(composer).toHaveValue(`Hi @${ola.name} and @${kuba.name} `);
  await expect(composer).toBeFocused();

  await composer.pressSequentially("@a");
  await expect(options(panel)).toHaveText(named(ada));
  await panel.getByRole("heading", { name: crew.title }).click();
  await expect(panel.getByRole("listbox")).toBeHidden();
  await composer.focus();
  await expect(options(panel)).toHaveText(named(ada));
  await composer.press("Escape");
  await expect(panel.getByRole("listbox")).toBeHidden();
  await expect(panel).toBeVisible();
  await composer.pressSequentially("d");
  await expect(panel.getByRole("listbox")).toBeHidden();

  await composer.press("Enter");
  await expect
    .poll(() => worker.called("sendMessage").at(-1)?.input)
    .toMatchObject({
      body: `Hi <@${ola.id}> and <@${kuba.id}> @ad`,
      mentions: [ola.id, kuba.id],
    });
  await expect(composer).toHaveValue("");
  await expect(bubble(panel, "Hi @")).toContainText(`Hi @${ola.name} and @${kuba.name} @ad`);
  await shoot(page, "mention-rendered");

  await composer.press("Escape");
  await expect(panelOf(page)).toBeHidden();
});

test("Nobody is offered in a room without a member list", async ({ page }) => {
  await routeBootstrap(page);
  await FakeWorker.install(page);

  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy");
  const composer = panel.getByLabel(copy.messageLabel, { exact: true });
  await composer.pressSequentially("@");
  await expect(panel.getByRole("listbox")).toBeHidden();
  await expect(composer).not.toHaveAttribute("aria-autocomplete", /./u);
});

test("Being mentioned marks the room until it is read, unless a blocked person did it", async ({
  page,
}) => {
  await routeBootstrap(page, [
    {
      blocked: [zed],
      canMessage: true,
      conversations: [crew, duo, { ...duo, id: "conversation:22", title: "Zed's table" }],
    },
  ]);
  await routeApi(page, {});
  const worker = (
    await FakeWorker.install(page, {
      [crew.id]: { at: Date.now() - 60_000, mentionedBy: [kuba.id], unread: true },
      "conversation:22": { at: Date.now() - 120_000, mentionedBy: [zed.id], unread: true },
    })
  ).on("loadBefore", (_input, url) => ({
    ok: true,
    value: /parley-conversation-agent\/20\b/u.test(url) ? thread() : [],
  }));

  await page.goto("/");
  await expect(launcherOf(page)).toHaveAccessibleDescription(/2 unread conversations/u);
  await launcherOf(page).click();
  const list = panelOf(page).getByRole("navigation", { name: copy.roomsLabel });
  const row = (title: string) => list.getByRole("button", { name: new RegExp(title, "u") });
  await expect(row(crew.title)).toContainText(copy.mentionedYou);
  await expect(row(crew.title)).toContainText(copy.unread);
  await expect(row("Zed's table")).not.toContainText(copy.mentionedYou);
  await expect(row(duo.title)).not.toContainText(copy.mentionedYou);

  worker.push(
    "room.activity",
    { at: Date.now(), latestMessageId: 5, mentionedBy: [ola.id], roomId: duo.id },
    /parley-inbox-agent/u,
  );
  await expect(row(duo.title)).toContainText(copy.mentionedYou);
  await expect(launcherOf(page)).toHaveAccessibleDescription(/3 unread conversations/u);
  await analyzePageAccessibility(page);
  await shoot(page, "mentioned-you");
  // A deleted message takes its mention along; one from a room unheard of is ignored.
  worker.push("mentions.changed", { mentionedBy: [], roomId: "conversation:99" }, /inbox/u);
  worker.push("mentions.changed", { mentionedBy: [], roomId: duo.id }, /inbox/u);
  await expect(row(duo.title)).not.toContainText(copy.mentionedYou);

  await row(crew.title).click();
  await expect
    .poll(() => worker.called("markRead").at(-1)?.input)
    .toEqual({
      messageId: 3,
      roomId: crew.id,
    });
  await panelOf(page).getByRole("button", { name: copy.backLabel }).click();
  await expect(row(crew.title)).not.toContainText(copy.mentionedYou);
});

test("People of one name keep apart, and only an @ at a word's start mentions", async ({
  page,
}) => {
  const anna: Person = { avatarUrl: "", id: "31", name: "Anna Kowalska" };
  const otherAnna: Person = { avatarUrl: "", id: "32", name: "Anna Kowalska" };
  const bo: Person = { avatarUrl: "", id: "123456789012", name: "Bo" };
  const annas = { ...crew, members: [me, anna, otherAnna, ola, bo] };
  await routeBootstrap(page, [{ canMessage: true, conversations: [annas] }]);
  await routeApi(page, {});
  const worker = (await FakeWorker.install(page)).on("sendMessage", (input) => ({
    ok: true,
    value: message({ authorId: me.id, body: String(input.body), id: 1 }),
  }));

  await page.goto("/");
  const panel = await openRoom(page, crew.title);
  const composer = panel.getByLabel(copy.messageLabel, { exact: true });
  await composer.pressSequentially("@Anna");
  await expect(options(panel)).toHaveText(named(anna, otherAnna));
  await composer.press("ArrowDown");
  await composer.press("Enter");
  await composer.pressSequentially("i @Anna");
  await composer.press("Enter");
  await composer.pressSequentially("@ol");
  await composer.press("Enter");
  await composer.pressSequentially(`mail:x@${ola.name}`);
  await expect(panel.getByRole("listbox")).toBeHidden();
  await composer.press("Enter");

  await expect
    .poll(() => worker.called("sendMessage").at(-1)?.input)
    .toMatchObject({
      body: `<@${otherAnna.id}> i <@${anna.id}> <@${ola.id}> mail:x@${ola.name}`,
      mentions: [otherAnna.id, anna.id, ola.id],
    });

  // The counter counts what the person sees; the Worker, the "<@id>" it keeps.
  await composer.pressSequentially("@Bo");
  await composer.press("Enter");
  await composer.fill(`@Bo ${"x".repeat(993)}`);
  await expect(panel.locator("#parley-count")).toContainText("997");
  await expect(panel.getByRole("alert")).toHaveText(copy.messageTooLong);
  await expect(panel.getByRole("button", { name: copy.sendLabel })).toBeDisabled();
});

test("Someone new in the room is asked for, and offered once known", async ({ page }) => {
  const nina: Person = { avatarUrl: "", id: "40", name: "Nina Zielińska" };
  await routeBootstrap(page, [{ canMessage: true, conversations: [crew] }]);
  const calls = await routeApi(page, {
    "conversations/": [
      { json: { conversations: [{ ...crew, members: [...crew.members, nina] }] }, status: 200 },
    ],
  });
  const worker = await FakeWorker.install(page);

  await page.goto("/");
  const panel = await openRoom(page, crew.title);
  worker.push(
    "message.created",
    message({ authorId: nina.id, authorName: nina.name, body: "Hi all", id: 9 }),
    /parley-conversation-agent/u,
  );
  await expect(bubble(panel, "Hi all")).toBeVisible();
  await expect.poll(() => calls.filter(({ path: at }) => at === "conversations/").length).toBe(1);

  const composer = panel.getByLabel(copy.messageLabel, { exact: true });
  await composer.pressSequentially("@ni");
  await expect(options(panel)).toHaveText(named(nina));
});

test("A link to a chat opens it", async ({ page }) => {
  await routeBootstrap(page, [{ canMessage: true, conversations: [crew, duo] }]);
  await routeApi(page, {});
  await FakeWorker.install(page);

  await page.goto(`/#parley:${duo.id}`);

  await expect(panelOf(page).getByRole("heading", { name: duo.title })).toBeVisible();
});
