import type { Locator } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { managerState } from "./helpers/auth";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  FakeWorker,
  launcherOf,
  message,
  onPageOf,
  panelOf,
  routeBootstrap,
} from "./helpers/parley";

const { copy } = bootstrap;
const CHATS_URL = "/multiverse/panel/chats/";

const organizers = {
  canModerate: true,
  canWrite: true,
  id: "organizers:1",
  kind: "organizers",
  moderating: false,
  sphere: 1,
  title: "Zagrajmy",
};
// The manager plays in this one: it is theirs, not only theirs to moderate.
const played = {
  canModerate: true,
  canWrite: true,
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
  id: "session:1:41",
  kind: "session",
  moderating: true,
  sphere: 1,
  title: "Wsiąść do pociągu",
};
const rooms = [organizers, watchedEvent, played, watched];
const moderation = { moderationUrl: CHATS_URL };

const ownList = (panel: Locator): Locator =>
  panel.getByRole("navigation", { name: copy.roomsLabel });

test.describe("The chat of a sphere's organizer", () => {
  test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

  test("keeps their own chats apart from the ones they only moderate", async ({ page }) => {
    await routeBootstrap(page, [{ ...moderation, rooms }]);
    const worker = await FakeWorker.install(page);
    await page.goto("/");
    // The snapshot first, so the live event lands on top of it.
    await expect
      .poll(() =>
        worker.called("getActivity").some(({ url }) => url.includes("parley-sphere-agent/1")),
      )
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
    await expect(ownList(panel).getByRole("button", { name: /Mothership/u })).toBeVisible();
    await expect(ownList(panel).getByRole("button", { name: /Wsiąść do pociągu/u })).toHaveCount(0);
    const entry = ownList(panel).getByRole("link", { name: new RegExp(copy.moderation, "u") });
    await expect(entry).toHaveAttribute("href", CHATS_URL);
    await expect(entry).toContainText("2 chats you moderate");
    await expect(entry).toContainText(copy.unread);
    await analyzePageAccessibility(page);
  });

  test("finds the chats they moderate even with none of their own", async ({ page }) => {
    await routeBootstrap(page, [{ ...moderation, rooms: [watchedEvent, watched] }]);
    await FakeWorker.install(page);
    await page.goto("/");
    await launcherOf(page).click();
    const panel = panelOf(page);

    await expect(ownList(panel).getByRole("button")).toHaveCount(0);
    const entry = ownList(panel).getByRole("link", { name: new RegExp(copy.moderation, "u") });
    await expect(entry).toBeFocused();
    await expect(entry).toContainText("2 chats you moderate");
  });

  test("writes where they only moderate only after a deliberate step", async ({ page }) => {
    await routeBootstrap(page, [{ ...moderation, rooms }]);
    const worker = (await FakeWorker.install(page))
      .on("loadBefore", (_input, url) => ({
        ok: true,
        value: url.includes("session-agent/1:41") ? [message({ id: 3 })] : [],
      }))
      .on("sendMessage", (input) => ({
        ok: true,
        value: message({ authorId: bootstrap.user.id, body: String(input.body), id: 9 }),
      }));
    // The moderation page links here, and the chat opens on the room.
    await page.goto(`/#parley:${watched.id}`);
    const panel = panelOf(page);
    await expect(panel.getByText("Message 3")).toBeVisible();
    await expect(panel.getByText(`${copy.sessionRoom} · ${copy.moderatorView}`)).toBeVisible();
    await expect(panel.getByText(copy.moderatorReading)).toBeVisible();
    await expect(panel.getByRole("textbox", { name: copy.messageLabel })).toHaveCount(0);
    await analyzePageAccessibility(page);

    await panel.getByRole("button", { name: copy.writeAsOrganizer }).click();
    const composer = panel.getByRole("textbox", { name: copy.messageLabel });
    await expect(composer).toBeFocused();
    await expect(composer).toHaveAttribute("placeholder", copy.organizerPlaceholder);
    await composer.fill("The table moved to room 2.");
    await composer.press("Enter");
    await expect.poll(() => worker.called("sendMessage").length).toBe(1);
    await expect(panel.getByText("The table moved to room 2.")).toBeVisible();

    // In a room of their own, the composer is there from the start.
    await panel.getByRole("button", { name: copy.backLabel }).click();
    await ownList(panel)
      .getByRole("button", { name: /Mothership/u })
      .click();
    await expect(panel.getByRole("textbox", { name: copy.messageLabel })).toHaveAttribute(
      "placeholder",
      copy.writePlaceholder,
    );
    await expect(panel.getByText(copy.moderatorReading)).toHaveCount(0);
  });

  test("waits on top of the list on the page of a chat they only moderate", async ({ page }) => {
    await routeBootstrap(page, [{ ...moderation, rooms }]);
    await FakeWorker.install(page);
    await onPageOf(page, watched.id);
    await page.goto("/");
    await launcherOf(page).click();
    const panel = panelOf(page);

    await expect(ownList(panel).getByRole("heading", { name: copy.onThisPage })).toBeVisible();
    await ownList(panel)
      .getByRole("button", { name: /Wsiąść do pociągu/u })
      .click();
    await expect(panel.getByText(copy.moderatorReading)).toBeVisible();
  });

  test("takes a page's own anchor for no chat link", async ({ page }) => {
    await routeBootstrap(page, [{ ...moderation, rooms }]);
    await FakeWorker.install(page);
    await page.goto("/#main");
    await launcherOf(page).click();
    const panel = panelOf(page);

    await expect(ownList(panel).getByRole("button", { name: /Mothership/u })).toBeVisible();
    await expect(panel.getByText(copy.linkUnavailable)).toHaveCount(0);
  });

  test("says when a link names a chat it cannot open, until another one opens", async ({
    page,
  }) => {
    await routeBootstrap(page, [{ ...moderation, rooms }]);
    await FakeWorker.install(page);
    await page.goto("/#parley:session:9:99");
    const panel = panelOf(page);

    await expect(panel.getByText(copy.linkUnavailable)).toBeVisible();
    await ownList(panel)
      .getByRole("button", { name: /Mothership/u })
      .click();
    await panel.getByRole("button", { name: copy.backLabel }).click();
    await expect(ownList(panel)).toBeVisible();
    await expect(panel.getByText(copy.linkUnavailable)).toHaveCount(0);
  });
});

test.describe("The sphere's chat moderation page", () => {
  test.use({ storageState: managerState });

  test("lists the chats an organizer is not in and opens the chat on one", async ({ page }) => {
    await page.goto(CHATS_URL);
    await expect(page.getByRole("heading", { name: "Chat moderation" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Chat moderation" })).toHaveAttribute(
      "href",
      CHATS_URL,
    );
    const list = page.getByRole("navigation", { name: "Chats to moderate" });
    const first = list
      .getByRole("link")
      .filter({ hasNotText: "Event chat" })
      .filter({ hasNotText: "Read only" })
      .first();
    const title = (await first.innerText()).trim();
    const href = (await first.getAttribute("href")) ?? "";
    const roomId = href.split("#parley:")[1] ?? "";
    expect(roomId).toMatch(/^session:\d+:\d+$/u);
    await analyzePageAccessibility(page);

    await routeBootstrap(page, [
      {
        moderationUrl: CHATS_URL,
        rooms: [
          {
            canModerate: true,
            canWrite: true,
            id: roomId,
            kind: "session",
            moderating: true,
            sphere: Number(roomId.split(":")[1]),
            title: "Programme point",
          },
        ],
      },
    ]);
    await FakeWorker.install(page);
    await first.click();

    await expect(page).toHaveURL(/\/multiverse\/panel\/chats\/session\/\d+\/#parley:/u);
    await expect(first).toHaveAttribute("aria-current", "page");
    const opened = page.getByRole("article", { name: title });
    await expect(opened.getByRole("heading", { level: 2, name: title })).toBeVisible();
    const panel = panelOf(page);
    await expect(panel.getByText(copy.moderatorReading)).toBeVisible();
    await analyzePageAccessibility(page);
  });
});
