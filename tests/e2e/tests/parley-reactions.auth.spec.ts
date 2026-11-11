import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  FakeWorker,
  message,
  openRoom,
  type Person,
  type Reply,
  routeBootstrap,
} from "./helpers/parley";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const ME = bootstrap.user.id;
const { copy } = bootstrap;
const zed: Person = { avatarUrl: "", id: "9", name: "Zed Blocked" };

type Reactions = Record<string, string[]>;

const QUICK = ["👍", "❤️", "😂", "😮", "😢", "🎲"];

// Kuba's message with reactions, among them this person's dice; one of this
// person's own, from before reactions; a deleted one; and one from someone
// this person blocked.
function thread(): ReturnType<typeof message>[] {
  const now = Date.now();
  return [
    message({
      body: "Who brings snacks?",
      createdAt: now - 4 * 60_000,
      id: 1,
      reactions: { "👍": ["2", "3"], "🎲": [ME, zed.id] },
      reactors: { "2": "Kuba Nowak", "3": "Ola", [ME]: bootstrap.user.name, [zed.id]: zed.name },
    }),
    message({ authorId: ME, body: "I will", createdAt: now - 3 * 60_000, id: 2 }),
    message({
      body: "",
      createdAt: now - 2 * 60_000,
      deletedAt: now,
      id: 3,
      reactions: { "😢": ["3"] },
    }),
    message({
      authorId: zed.id,
      authorName: zed.name,
      body: "Hidden words",
      createdAt: now - 60_000,
      id: 4,
      reactions: { "❤️": ["2"] },
    }),
  ];
}

// The Worker's toggle: the same call adds a reaction and takes it back.
function toggling(): (input: Record<string, unknown>) => Reply {
  const held = new Map<number, Reactions>(
    thread().map((entry) => [entry.id, { ...entry.reactions }]),
  );
  return (input) => {
    const messageId = input.messageId as number;
    const emoji = input.emoji as string;
    const reactions = { ...held.get(messageId) };
    const users = reactions[emoji] ?? [];
    reactions[emoji] = users.includes(ME) ? users.filter((id) => id !== ME) : [...users, ME];
    if (reactions[emoji].length === 0) delete reactions[emoji];
    held.set(messageId, reactions);
    // The quick ones first, in their order, as the Worker sends them.
    const rank = (key: string) => {
      const at = QUICK.indexOf(key);
      return at === -1 ? QUICK.length : at;
    };
    const ordered = Object.fromEntries(
      Object.entries(reactions).toSorted(([a], [b]) => rank(a) - rank(b)),
    );
    const reactors = { ...thread().find((entry) => entry.id === messageId)?.reactors, [ME]: "Me" };
    return { ok: true, value: { messageId, reactions: ordered, reactors } };
  };
}

function bubbleOf(panel: Locator, body: string): Locator {
  // Above the bubble's row: the column holding it and its reactions.
  return panel.getByText(body).locator("xpath=../..");
}

const reactionsOf = (panel: Locator, body: string): Locator =>
  bubbleOf(panel, body).getByRole("group", { name: copy.reactionsLabel });

// The chips that toggle a reaction, not the one that opens the picker.
const chipsOf = (panel: Locator, body: string): Locator =>
  reactionsOf(panel, body).locator("button[aria-pressed]");

async function openActions(page: Page, panel: Locator, body: string): Promise<Locator> {
  await bubbleOf(panel, body).getByRole("button", { name: copy.messageActions }).click();
  return page.getByRole("menu", { name: copy.messageActions });
}

test("Someone reacts from a message's actions and toggles a reaction from its chip", async ({
  page,
}) => {
  await routeBootstrap(page, [{ blocked: [zed] }]);
  const worker = (await FakeWorker.install(page))
    .on("loadBefore", () => ({ ok: true, value: thread() }))
    .on("toggleReaction", toggling());
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "Who brings snacks?");

  // Counted and marked where the viewer holds one, and nobody named; a
  // deleted message and a blocked person's show none.
  const chips = chipsOf(panel, "Who brings snacks?");
  await expect(chips).toHaveText(["👍2", "🎲2"]);
  await expect(chips.first()).toHaveAccessibleName("Thumbs up: 2 people");
  await expect(chips.first()).toHaveAttribute("aria-pressed", "false");
  await expect(chips.last()).toHaveAccessibleName("Dice: 2 people");
  await expect(chips.last()).toHaveAttribute("aria-pressed", "true");
  await expect(panel.getByRole("group", { name: copy.reactionsLabel })).toHaveCount(1);
  await expect(panel.getByText(zed.name)).toHaveCount(0);
  await analyzePageAccessibility(page);

  await chips.last().click();
  await expect(chips.last()).toHaveAccessibleName("Dice: 1 person");
  await expect(chips.last()).toHaveAttribute("aria-pressed", "false");
  expect(worker.called("toggleReaction").at(-1)?.input).toEqual({ emoji: "🎲", messageId: 1 });

  // The actions menu leads with the palette, checking what the viewer holds.
  let menu = await openActions(page, panel, "Who brings snacks?");
  const palette = menu.getByRole("group", { name: copy.react });
  const options = palette.getByRole("menuitemcheckbox");
  await expect(options).toHaveCount(6);
  for (const [index, name] of [
    copy.reactionThumbsUp,
    copy.reactionHeart,
    copy.reactionLaugh,
    copy.reactionSurprised,
    copy.reactionSad,
    copy.reactionDice,
  ].entries()) {
    await expect(options.nth(index)).toHaveAccessibleName(name);
  }
  await expect(palette.getByRole("menuitemcheckbox", { checked: true })).toHaveCount(0);
  await expect(palette.getByRole("menuitemcheckbox").first()).toBeFocused();
  await analyzePageAccessibility(page);
  await palette.getByRole("menuitemcheckbox", { name: copy.reactionHeart }).click();
  await expect(menu).toBeHidden();
  await expect(chips).toHaveText(["👍2", "❤️1", "🎲1"]);
  await expect(chips.nth(1)).toHaveAttribute("aria-pressed", "true");

  // Choosing a held reaction again takes it back, its chip with it.
  menu = await openActions(page, panel, "Who brings snacks?");
  await expect(
    menu.getByRole("menuitemcheckbox", { checked: true, name: copy.reactionHeart }),
  ).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(chips).toHaveText(["👍2", "🎲1"]);

  // One's own message takes reactions too.
  menu = await openActions(page, panel, "I will");
  await menu.getByRole("menuitemcheckbox", { name: copy.reactionDice }).click();
  await expect(chipsOf(panel, "I will")).toHaveAccessibleName("Dice: 1 person");

  // Taking back the last of a reaction from the keyboard hands focus to the
  // chip in its place, and once none is left, to the message's actions.
  menu = await openActions(page, panel, "I will");
  await menu.getByRole("menuitemcheckbox", { name: copy.reactionSurprised }).click();
  const own = chipsOf(panel, "I will");
  await expect(own).toHaveText(["😮1", "🎲1"]);
  await own.first().focus();
  await page.keyboard.press("Enter");
  await expect(own).toHaveText(["🎲1"]);
  await expect(own.first()).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(own).toHaveCount(0);
  await expect(
    bubbleOf(panel, "I will").getByRole("button", { name: copy.messageActions }),
  ).toBeFocused();

  // Others' reactions arrive as they happen; one for a message not loaded is
  // nobody's business here.
  worker.push("reaction.changed", { messageId: 1, reactions: { "😂": ["2", "3", "4", "5"] } });
  worker.push("reaction.changed", { messageId: 99, reactions: { "😂": ["2"] } });
  await expect(chips).toHaveText(["😂4"]);
  await expect(chips).toHaveAccessibleName("Laughing: 4 people");

  // A message deleted under its reactions takes them with it.
  const groups = panel.getByRole("group", { name: copy.reactionsLabel });
  await expect(groups).toHaveCount(1);
  worker.push("message.deleted", { id: 1 });
  await expect(panel.getByText("Who brings snacks?")).toHaveCount(0);
  await expect(groups).toHaveCount(0);
});

test("A refused reaction says why, and muting puts the chips out of reach", async ({ page }) => {
  await routeBootstrap(page);
  const replies: Reply[] = [
    { code: "rate_limited", ok: false },
    { code: "full", ok: false },
    { code: "invalid", ok: false },
    { code: "forbidden", ok: false },
    "reject",
    { code: "muted", ok: false },
  ];
  const worker = (await FakeWorker.install(page))
    .on("loadBefore", () => ({ ok: true, value: thread() }))
    .on("toggleReaction", () => replies.shift()!);
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "Who brings snacks?");
  const thumbs = chipsOf(panel, "Who brings snacks?").first();

  for (const problem of [
    copy.errorReactionRateLimited,
    copy.errorReactionFull,
    copy.errorReactionGone,
    copy.errorForbidden,
    copy.connectionError,
  ]) {
    await thumbs.click();
    await expect(panel.getByRole("alert")).toHaveText(problem);
  }
  await expect(thumbs).toHaveAccessibleName("Thumbs up: 2 people");

  // Refused for a mute, the composer gives way to the notice and the
  // reactions can only be read.
  await thumbs.click();
  await expect(panel.getByRole("status").filter({ hasText: copy.errorMuted })).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(thumbs).toBeDisabled();
  const menu = await openActions(page, panel, "Who brings snacks?");
  await expect(menu.getByRole("menuitemcheckbox")).toHaveCount(0);
  expect(worker.called("toggleReaction")).toHaveLength(6);
});

test("In a room one may only read, reactions show but do not toggle", async ({ page }) => {
  await routeBootstrap(page);
  await (await FakeWorker.install(page)).on("loadBefore", () => ({ ok: true, value: thread() }));
  await page.goto("/");
  const panel = await openRoom(page, "Mothership", "Who brings snacks?");

  const chips = chipsOf(panel, "Who brings snacks?");
  await expect(chips).toHaveCount(2);
  for (const chip of await chips.all()) await expect(chip).toBeDisabled();
  const menu = await openActions(page, panel, "Who brings snacks?");
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await expect(menu.getByRole("menuitemcheckbox")).toHaveCount(0);
});

test("A reaction names who gave it, and + opens every emoji there is", async ({ page }) => {
  await routeBootstrap(page, [{ blocked: [zed] }]);
  const fans = Array.from({ length: 12 }, (_, index) => String(20 + index));
  const worker = (await FakeWorker.install(page))
    .on("loadBefore", () => ({
      ok: true,
      value: [
        ...thread(),
        message({
          body: "Crowd pleaser",
          id: 5,
          reactions: { "😂": fans },
          reactors: Object.fromEntries(fans.map((id) => [id, `Fan ${id}`])),
        }),
      ],
    }))
    .on("toggleReaction", toggling());
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "Crowd pleaser");
  const tooltip = page.locator("[role=tooltip]");

  // Hovered or focused, a chip names its people: the viewer first, anyone
  // blocked unnamed, and past ten only a count.
  const [thumbs, dice] = [0, 1].map((index) => chipsOf(panel, "Who brings snacks?").nth(index));
  await dice!.hover();
  await expect(tooltip).toHaveText(`You and ${copy.reactorBlocked}`);
  await expect(dice!).toHaveAccessibleDescription(`You and ${copy.reactorBlocked}`);
  await panel.getByRole("heading", { name: "Zagrajmy" }).hover();
  await expect(tooltip).toHaveCount(0);
  await thumbs!.focus();
  await expect(tooltip).toHaveText("Kuba Nowak and Ola");
  await thumbs!.blur();
  await expect(tooltip).toHaveCount(0);
  await expect(chipsOf(panel, "Crowd pleaser")).toHaveAccessibleDescription(
    /^Fan 20, Fan 21, .*Fan 29,? and \+2$/u,
  );
  // Someone the room never named is still counted.
  worker.push("reaction.changed", { messageId: 5, reactions: { "😂": ["77"] }, reactors: {} });
  await expect(chipsOf(panel, "Crowd pleaser")).toHaveAccessibleDescription(copy.typingSomeone);

  // The last chip opens every emoji, found by searching, in the page's own
  // language.
  await page.evaluate(() => {
    document.documentElement.lang = "pl";
  });
  const more = reactionsOf(panel, "Who brings snacks?").getByRole("button", {
    name: copy.addReaction,
  });
  await more.click();
  const picker = page.getByRole("dialog", { name: copy.reactionPicker });
  const search = picker.getByPlaceholder(copy.searchEmoji);
  await expect(search).toBeFocused();
  // NOTE: Frimousse numbers its grid's rows and cells from 0, where ARIA
  // counts from 1, and finds rows by that number itself, so the rows are
  // left out until it is fixed upstream.
  await analyzePageAccessibility(page, { exclude: "[frimousse-row]" });
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-emoji-picker.png" });
  await search.fill("ocean");
  await picker.getByText("🐙", { exact: true }).click();
  await expect(picker).toBeHidden();
  await expect(more).toBeFocused();
  await expect(chipsOf(panel, "Who brings snacks?").last()).toHaveAccessibleName("🐙: 1 person");
  expect(worker.called("toggleReaction").at(-1)?.input).toEqual({ emoji: "🐙", messageId: 1 });

  // From a message's actions too, in English this time; Escape puts it away
  // and focus back.
  await page.evaluate(() => {
    document.documentElement.lang = "en";
  });
  const menu = await openActions(page, panel, "Crowd pleaser");
  await menu.getByRole("menuitem", { name: copy.addReaction }).click();
  await expect(picker).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(picker).toBeHidden();
  await expect(panel).toBeVisible();
  await expect(
    bubbleOf(panel, "Crowd pleaser").getByRole("button", { name: copy.messageActions }),
  ).toBeFocused();

  // A press elsewhere, or the thread moving under it, puts it away too.
  await more.click();
  await expect(picker).toBeVisible();
  await panel.getByRole("heading", { name: "Zagrajmy" }).click();
  await expect(picker).toBeHidden();
  await more.click();
  await expect(picker).toBeVisible();
  const scroller = panel.locator("[data-menu-scroller]");
  // A scroll that leaves the + where it was, as the thread keeping its place
  // does, keeps it open.
  await scroller.dispatchEvent("scroll");
  await expect(picker).toBeVisible();
  await scroller.evaluate((viewport) => viewport.scrollTo(0, 0));
  await expect(picker).toBeHidden();
});
