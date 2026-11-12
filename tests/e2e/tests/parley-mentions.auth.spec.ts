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
  mentionable: [ada.id, kuba.id, ola.id, zed.id],
  name: "Friday crew",
  state: "active",
  title: "Friday crew",
};
const duo: Conversation = {
  ...crew,
  id: "conversation:21",
  members: [me, ola],
  mentionable: [ola.id],
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

test("Typing @ offers the people one may mention, and the keyboard or a tap picks one", async ({
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
  await expect(options(panel)).toHaveText(named(ada, kuba, ola));
  await expect(composer).toHaveAttribute("aria-autocomplete", "list");
  await expect(composer).toHaveAttribute("aria-activedescendant", `parley-mentions-${ada.id}`);
  await analyzePageAccessibility(page);
  await shoot(page, "mention-picker");

  await composer.press("ArrowDown");
  await expect(options(panel).nth(1)).toHaveAttribute("aria-selected", "true");
  await composer.press("ArrowUp");
  await composer.press("ArrowUp");
  await expect(composer).toHaveAttribute("aria-activedescendant", `parley-mentions-${ola.id}`);
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

  await row(crew.title).click();
  await expect
    .poll(() => worker.called("markRead").at(-1)?.input)
    .toEqual({
      messageId: 3,
      roomId: crew.id,
    });
  await panelOf(page).getByRole("button", { name: copy.backLabel }).click();
  await expect(row(crew.title)).not.toContainText(copy.mentionedYou);
  await expect(row(duo.title)).toContainText(copy.mentionedYou);
});
