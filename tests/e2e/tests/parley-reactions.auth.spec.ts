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
    return { ok: true, value: { messageId, reactions } };
  };
}

function bubbleOf(panel: Locator, body: string): Locator {
  // Above the bubble's row: the column holding it and its reactions.
  return panel.getByText(body).locator("xpath=../..");
}

const reactionsOf = (panel: Locator, body: string): Locator =>
  bubbleOf(panel, body).getByRole("group", { name: copy.reactionsLabel });

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
  const chips = reactionsOf(panel, "Who brings snacks?").getByRole("button");
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
  await expect(reactionsOf(panel, "I will").getByRole("button")).toHaveAccessibleName(
    "Dice: 1 person",
  );

  // Others' reactions arrive as they happen; one for a message not loaded is
  // nobody's business here.
  worker.push("reaction.changed", { messageId: 1, reactions: { "😂": ["2", "3", "4", "5"] } });
  worker.push("reaction.changed", { messageId: 99, reactions: { "😂": ["2"] } });
  await expect(chips).toHaveText(["😂4"]);
  await expect(chips).toHaveAccessibleName("Laughing: 4 people");

  // A message deleted under its reactions takes them with it.
  worker.push("message.deleted", { id: 1 });
  await expect(panel.getByText("Who brings snacks?")).toHaveCount(0);
  await expect(panel.getByRole("group", { name: copy.reactionsLabel })).toHaveCount(1);
});

test("A refused reaction says why, and muting puts the chips out of reach", async ({ page }) => {
  await routeBootstrap(page);
  const replies: Reply[] = [
    { code: "rate_limited", ok: false },
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
  const thumbs = reactionsOf(panel, "Who brings snacks?").getByRole("button").first();

  for (const problem of [
    copy.errorReactionRateLimited,
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
  expect(worker.called("toggleReaction")).toHaveLength(5);
});

test("In a room one may only read, reactions show but do not toggle", async ({ page }) => {
  await routeBootstrap(page);
  await (await FakeWorker.install(page)).on("loadBefore", () => ({ ok: true, value: thread() }));
  await page.goto("/");
  const panel = await openRoom(page, "Mothership", "Who brings snacks?");

  const chips = reactionsOf(panel, "Who brings snacks?").getByRole("button");
  await expect(chips).toHaveCount(2);
  for (const chip of await chips.all()) await expect(chip).toBeDisabled();
  const menu = await openActions(page, panel, "Who brings snacks?");
  await expect(menu.getByRole("menuitem").first()).toBeFocused();
  await expect(menu.getByRole("menuitemcheckbox")).toHaveCount(0);
});
