import type { Locator } from "@playwright/test";

import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { bootstrap, FakeWorker, message, openRoom, routeBootstrap } from "./helpers/parley";

// The chromium-auth default user has no sphere role; the event chat in the
// room list needs the superuser, as parley-thread.auth.spec.ts does.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const { copy } = bootstrap;
const ROOM = "Zagrajmy";

const reopen = async (panel: Locator) => {
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await panel
    .getByRole("navigation", { name: copy.roomsLabel })
    .getByRole("button", { name: new RegExp(ROOM, "u") })
    .click();
};

test("A room waits on stand-ins, offers a retry, and reopens from what it last showed", async ({
  page,
}) => {
  await routeBootstrap(page);
  const first = [
    message({ body: "Who brings the dice?", id: 1 }),
    message({ authorId: bootstrap.user.id, body: "Me, two sets", id: 2 }),
  ];
  const worker = (await FakeWorker.install(page)).on("loadBefore", () => "silent");

  await page.goto("/");
  const panel = await openRoom(page, ROOM);
  const thread = panel.getByRole("region", { name: copy.messageListLabel });

  // Before the room answers, an empty list is no sign of an empty room.
  await expect(thread).toHaveAttribute("aria-busy", "true");
  await expect(panel.locator(".parley-skeleton")).toBeVisible();
  await expect(panel.getByText(copy.emptyEvent)).toHaveCount(0);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-thread-loading.png" });

  worker.on("loadBefore", () => ({ code: "rate_limited", ok: false }));
  await reopen(panel);
  await expect(panel.getByRole("alert")).toContainText(copy.historyFailed);
  await expect(panel.locator(".parley-skeleton")).toHaveCount(0);
  await expect(panel.getByText(copy.emptyEvent)).toHaveCount(0);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-thread-failed.png" });

  worker.on("loadBefore", () => ({ ok: true, value: first }));
  await panel.getByRole("button", { name: copy.retry }).click();
  await expect(panel.getByText("Me, two sets")).toBeVisible();
  await expect(thread).toHaveAttribute("aria-busy", "false");
  await expect(panel.getByRole("alert")).toHaveCount(0);

  // Reopened while the room is slow, the thread is already there.
  worker.on("loadBefore", () => "silent");
  await reopen(panel);
  await expect(panel.getByText("Who brings the dice?")).toBeVisible();
  await expect(panel.locator(".parley-skeleton")).toHaveCount(0);

  // Once the room answers, its word replaces the remembered one: a message
  // deleted meanwhile does not linger.
  worker.on("loadBefore", () => ({
    ok: true,
    value: [
      message({ body: "", deletedAt: Date.now(), id: 1 }),
      first[1],
      message({ body: "Bring snacks too", id: 3 }),
    ],
  }));
  await reopen(panel);
  await expect(panel.getByText("Bring snacks too")).toBeVisible();
  await expect(panel.getByText("Who brings the dice?")).toHaveCount(0);
  await expect(panel.getByText(copy.deletedMessage)).toHaveCount(1);
  await expect(panel.getByText("Me, two sets")).toHaveCount(1);
});

test("An empty room says so once it has answered", async ({ page }) => {
  await routeBootstrap(page);
  await FakeWorker.install(page);

  await page.goto("/");
  const panel = await openRoom(page, ROOM);

  await expect(panel.getByText(copy.emptyEvent)).toBeVisible();
  await expect(panel.getByRole("region", { name: copy.messageListLabel })).toHaveAttribute(
    "aria-busy",
    "false",
  );
  await expect(panel.locator(".parley-skeleton")).toHaveCount(0);
});
