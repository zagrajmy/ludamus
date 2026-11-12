import type { Locator, Page } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import { bootstrap, FakeWorker, message, openRoom, routeBootstrap } from "./helpers/parley";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const ME = bootstrap.user.id;
const { copy } = bootstrap;

// Kuba's message to moderate, one of this person's own, a deleted one, and
// enough of the room after them that the first two can sit high or low.
function thread(): ReturnType<typeof message>[] {
  const now = Date.now();
  return [
    message({ body: "Please moderate me", createdAt: now - 20 * 60_000, id: 1 }),
    message({ authorId: ME, body: "My own words", createdAt: now - 19 * 60_000, id: 2 }),
    message({ body: "", createdAt: now - 18 * 60_000, deletedAt: now, id: 3 }),
    ...Array.from({ length: 12 }, (_, index) =>
      message({
        authorId: index % 2 === 0 ? "3" : ME,
        authorName: "Ola",
        body: `Chatter ${index + 4}`,
        createdAt: now - 17 * 60_000 + index * 60_000,
        id: index + 4,
      }),
    ),
    message({ body: "The latest from Kuba", createdAt: now, id: 16 }),
  ];
}

function actionsFor(panel: Locator, body: string): Locator {
  // The bubble's parent holds the bubble and its actions button.
  return panel
    .getByText(body)
    .locator("xpath=..")
    .getByRole("button", { name: copy.messageActions });
}

const menuOf = (page: Page): Locator => page.getByRole("menu", { name: copy.messageActions });

async function open(page: Page, panel: Locator, body: string): Promise<Locator> {
  await actionsFor(panel, body).scrollIntoViewIfNeeded();
  await actionsFor(panel, body).click();
  const menu = menuOf(page);
  // Where this person may react, the reactions come first.
  await expect(
    menu.getByRole("menuitemcheckbox").or(menu.getByRole("menuitem")).first(),
  ).toBeFocused();
  return menu;
}

async function chat(
  page: Page,
  worker?: FakeWorker,
): Promise<{ panel: Locator; worker: FakeWorker }> {
  const installed =
    worker ??
    (await FakeWorker.install(page)).on("loadBefore", () => ({ ok: true, value: thread() }));
  if (worker !== undefined) worker.on("loadBefore", () => ({ ok: true, value: thread() }));
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "The latest from Kuba");
  return { panel, worker: installed };
}

test("The actions menu runs from the keyboard and closes when its message moves", async ({
  page,
}) => {
  await routeBootstrap(page);
  const { panel } = await chat(page);
  const trigger = actionsFor(panel, "The latest from Kuba");
  const menu = await open(page, panel, "The latest from Kuba");
  const reactions = menu.getByRole("menuitemcheckbox");
  const items = menu.getByRole("menuitem");
  await analyzePageAccessibility(page);

  // The reactions' row walks sideways or down, and so does the rest.
  await page.keyboard.press("ArrowRight");
  await expect(reactions.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(reactions.first()).toBeFocused();
  await page.keyboard.press("End");
  await page.keyboard.press("ArrowDown");
  await expect(reactions.first()).toBeFocused();
  await reactions.last().focus();
  await page.keyboard.press("ArrowDown");
  await expect(items.first()).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(items.nth(1)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(items.first()).toBeFocused();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowUp");
  await expect(items.last()).toHaveText(copy.restoreWriting);
  await expect(items.last()).toBeFocused();
  await page.keyboard.press("Home");
  await expect(reactions.first()).toBeFocused();
  await page.keyboard.press("End");
  await expect(items.last()).toBeFocused();
  // A key the menu has no use for does nothing.
  await page.keyboard.press("a");
  await expect(items.last()).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(menu).toBeHidden();

  // Escape closes the menu and gives focus back, but leaves the chat open.
  await open(page, panel, "The latest from Kuba");
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(panel).toBeVisible();

  // The trigger toggles; a press inside the menu keeps it, one outside closes it.
  await open(page, panel, "The latest from Kuba");
  await trigger.click();
  await expect(menu).toBeHidden();
  await open(page, panel, "The latest from Kuba");
  await menu.getByText(copy.muteLabel).click();
  await expect(menu).toBeVisible();
  await panel.getByRole("heading", { name: "Zagrajmy" }).click();
  await expect(menu).toBeHidden();

  await open(page, panel, "The latest from Kuba");
  const thread = panel.getByLabel(copy.messageListLabel, { exact: true });
  // A scroll that leaves the message where it was keeps the menu.
  await thread.dispatchEvent("scroll");
  await expect(menu).toBeVisible();
  await thread.evaluate((viewport) => viewport.scrollBy(0, -200));
  await expect(menu).toBeHidden();

  await open(page, panel, "The latest from Kuba");
  await page.setViewportSize({ height: 800, width: 1200 });
  await expect(menu).toBeHidden();
});

test("The actions menu opens on whichever side of its message has room", async ({ page }) => {
  await routeBootstrap(page);
  const { panel } = await chat(page);
  const box = async (locator: Locator) => {
    // The menu eases in; measure where it lands, not where it starts.
    await locator.evaluate((node) => {
      for (const animation of node.getAnimations()) animation.finish();
    });
    const rect = await locator.boundingBox();
    if (rect === null) throw new Error("not on screen");
    return rect;
  };

  // The last message sits at the bottom of the thread: the menu goes above.
  const low = await open(page, panel, "The latest from Kuba");
  const lowTrigger = await box(actionsFor(panel, "The latest from Kuba"));
  expect((await box(low)).y + (await box(low)).height).toBeLessThanOrEqual(lowTrigger.y);
  // Someone else's message: the menu lines up with the trigger's right edge.
  expect(Math.round((await box(low)).x + (await box(low)).width)).toBe(
    Math.round(lowTrigger.x + lowTrigger.width),
  );
  await page.keyboard.press("Escape");

  // Scrolled to the top, the first message has room below it.
  await panel
    .getByLabel(copy.messageListLabel, { exact: true })
    .evaluate((viewport) => viewport.scrollTo(0, 0));
  const high = await open(page, panel, "Please moderate me");
  const highTrigger = await box(actionsFor(panel, "Please moderate me"));
  expect((await box(high)).y).toBeGreaterThanOrEqual(highTrigger.y + highTrigger.height);
  await page.keyboard.press("Escape");

  // One's own message: the menu starts at the trigger and stays inside the thread.
  const own = await open(page, panel, "My own words");
  const thread = await box(panel.getByLabel(copy.messageListLabel, { exact: true }));
  expect((await box(own)).x).toBeGreaterThanOrEqual(thread.x);
  expect((await box(own)).x + (await box(own)).width).toBeLessThanOrEqual(thread.x + thread.width);
  await page.keyboard.press("Escape");

  // On a short phone screen the tall moderator menu fits neither side, so it
  // takes the roomier one and scrolls.
  await page.setViewportSize({ height: 420, width: 390 });
  await expect(panel.getByLabel(copy.messageListLabel, { exact: true })).toBeVisible();
  for (const body of ["Chatter 6", "Chatter 12"]) {
    await panel.getByLabel(copy.messageListLabel, { exact: true }).evaluate((viewport, text) => {
      const target = [...viewport.querySelectorAll("p")].find((p) => p.textContent?.includes(text));
      target?.scrollIntoView({ block: "center" });
    }, body);
    const menu = await open(page, panel, body);
    const shown = await box(menu);
    const area = await box(panel.getByLabel(copy.messageListLabel, { exact: true }));
    expect(shown.y).toBeGreaterThanOrEqual(area.y);
    expect(shown.y + shown.height).toBeLessThanOrEqual(area.y + area.height + 1);
    expect(await menu.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
    await page.keyboard.press("Escape");
  }
});

test("Deleting one's own message asks first and says when it fails", async ({ context, page }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await routeBootstrap(page);
  let deletion: "forbidden" | "ok" = "forbidden";
  const worker = (await FakeWorker.install(page)).on("deleteOwnMessage", () =>
    deletion === "ok" ? { ok: true, value: { id: 2 } } : { code: "forbidden", ok: false },
  );
  const { panel } = await chat(page, worker);
  const trigger = actionsFor(panel, "My own words");

  let menu = await open(page, panel, "My own words");
  await expect(menu.getByRole("menuitem")).toHaveText(["+", copy.copyLink, copy.deleteLabel]);
  await menu.getByRole("menuitem", { name: copy.copyLink }).click();
  await expect(panel.getByRole("status").filter({ hasText: copy.linkCopied })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toMatch(
    /#parley:event:1:5:2$/u,
  );

  // A clipboard the browser refuses is its call, not a lost connection.
  await page.evaluate(() => {
    navigator.clipboard.writeText = () => Promise.reject(new Error("refused"));
  });
  menu = await open(page, panel, "My own words");
  await menu.getByRole("menuitem", { name: copy.copyLink }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);

  menu = await open(page, panel, "My own words");
  await menu.getByRole("menuitem", { name: copy.deleteLabel }).click();
  const sheet = panel.getByRole("alertdialog", { name: copy.deleteLabel });
  await expect(sheet).toHaveAccessibleDescription(copy.deleteConfirm);
  await expect(sheet.getByRole("button", { name: copy.cancelLabel })).toBeFocused();
  await analyzePageAccessibility(page);
  // Escape answers the question, not the chat window.
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(panel).toBeVisible();
  await expect(trigger).toBeFocused();
  // Other keys leave the question standing.
  menu = await open(page, panel, "My own words");
  await menu.getByRole("menuitem", { name: copy.deleteLabel }).click();
  await page.keyboard.press("a");
  await expect(sheet).toBeVisible();

  await sheet.getByRole("button", { name: copy.deleteLabel }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.errorForbidden);
  await expect(panel.getByText("My own words")).toBeVisible();

  deletion = "ok";
  menu = await open(page, panel, "My own words");
  await menu.getByRole("menuitem", { name: copy.deleteLabel }).click();
  await sheet.getByRole("button", { name: copy.deleteLabel }).click();
  await expect(panel.getByText("My own words")).toHaveCount(0);
  await expect(panel.getByText(copy.deletedMessage)).toHaveCount(2);
  // A deleted message offers nothing more to do with it.
  await expect(
    panel.getByText(copy.deletedMessage).first().locator("xpath=..").getByRole("button"),
  ).toHaveCount(0);
});

test("A moderator reports, deletes and mutes someone else's message", async ({ page }) => {
  await routeBootstrap(page);
  const reports: number[] = [];
  await page.route("**/parley/reports/", (route) => {
    reports.push(1);
    return route.fulfill({ status: reports.length === 1 ? 201 : 500 });
  });
  let muting: "forbidden" | "ok" = "forbidden";
  let deleting: "ok" | "reject" = "reject";
  const worker = (await FakeWorker.install(page))
    .on("muteUser", () =>
      muting === "ok" ? { ok: true, value: {} } : { code: "forbidden", ok: false },
    )
    .on("deleteMessage", () => (deleting === "ok" ? { ok: true, value: { id: 1 } } : "reject"));
  const { panel } = await chat(page, worker);
  const choose = async (label: string, body = "Please moderate me") => {
    const menu = await open(page, panel, body);
    await menu.getByRole("menuitem", { name: label }).click();
  };

  const menu = await open(page, panel, "Please moderate me");
  await expect(menu.getByRole("menuitem")).toHaveText([
    "+",
    copy.copyLink,
    copy.reportMessage,
    "Block Kuba Nowak",
    copy.moderatorDelete,
    copy.muteOneHour,
    copy.muteOneDay,
    copy.muteSevenDays,
    copy.muteIndefinitely,
    copy.restoreWriting,
  ]);
  await page.keyboard.press("Escape");

  await choose(copy.reportMessage);
  await expect(panel.getByRole("status").filter({ hasText: copy.reported })).toBeVisible();
  await choose(copy.reportMessage);
  await expect(panel.getByRole("alert")).toHaveText(copy.errorUnknown);

  await choose(copy.muteOneHour);
  await expect(panel.getByRole("alert")).toHaveText(copy.errorForbidden);
  muting = "ok";
  await choose(copy.muteOneDay);
  await expect(panel.getByRole("status").filter({ hasText: copy.muted })).toBeVisible();
  await choose(copy.muteSevenDays);
  await choose(copy.muteIndefinitely);
  const sheet = panel.getByRole("alertdialog", { name: copy.muteIndefinitely });
  await expect(sheet).toHaveAccessibleDescription(copy.muteConfirm);
  await sheet.getByRole("button", { name: copy.muteIndefinitely }).click();
  await expect
    .poll(() => worker.called("muteUser").map((call) => call.input.durationMs))
    .toEqual([3_600_000, 86_400_000, 604_800_000, null]);
  await choose(copy.restoreWriting);
  await expect(panel.getByRole("status").filter({ hasText: copy.writingRestored })).toBeVisible();
  expect(worker.called("restoreWriting").at(-1)?.input).toEqual({ userId: "2" });

  // A call the socket drops says the connection is the problem.
  await choose(copy.moderatorDelete);
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.moderatorDelete }).click();
  await expect(panel.getByRole("alert")).toHaveText(copy.connectionError);
  deleting = "ok";
  await choose(copy.moderatorDelete, "The latest from Kuba");
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.moderatorDelete }).click();
  await expect(panel.getByText("The latest from Kuba")).toHaveCount(0);
  expect(worker.called("deleteMessage").at(-1)?.input).toEqual({ messageId: 16 });

  // The message vanishes while the question is open: focus lands on the composer.
  await choose(copy.moderatorDelete);
  worker.push("message.deleted", { id: 1 });
  await expect(panel.getByText("Please moderate me")).toHaveCount(0);
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.cancelLabel }).click();
  await expect(panel.getByLabel("Message", { exact: true })).toBeFocused();

  // In a room nobody writes in, focus falls back to the close button.
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await panel
    .getByRole("navigation", { name: copy.roomsLabel })
    .getByRole("button", { name: /Mothership/u })
    .click();
  await choose(copy.moderatorDelete);
  worker.push("message.deleted", { id: 1 }, /session-agent/u);
  await expect(panel.getByText("Please moderate me")).toHaveCount(0);
  await panel.getByRole("alertdialog").getByRole("button", { name: copy.cancelLabel }).click();
  await expect(panel.getByRole("button", { name: copy.closeLabel })).toBeFocused();
});

test("Someone without moderation rights can only copy, report and block", async ({ page }) => {
  await routeBootstrap(page, [
    { rooms: bootstrap.rooms.map((room) => ({ ...room, canModerate: false })) },
  ]);
  const { panel } = await chat(page);
  const menu = await open(page, panel, "Please moderate me");
  await expect(menu.getByRole("menuitem")).toHaveText([
    "+",
    copy.copyLink,
    copy.reportMessage,
    "Block Kuba Nowak",
  ]);
});
