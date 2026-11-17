import type { Locator } from "@playwright/test";

import path from "node:path";

import { expect, test } from "./helpers/fixtures";
import { bootstrap, FakeWorker, message, openRoom, routeBootstrap } from "./helpers/parley";

// The chromium-auth default user has no sphere role; the event chat in the
// room list needs the superuser, as parley-thread.auth.spec.ts does.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const { copy } = bootstrap;
const ROOM = "Zagrajmy";
const REFUSED = { code: "rate_limited", ok: false };

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
  // A full page, so there is history further back.
  const latest = [
    ...Array.from({ length: 48 }, (_, index) =>
      message({ body: `Line ${index + 101}`, id: index + 101 }),
    ),
    message({ body: "Who brings the dice?", id: 149 }),
    message({ authorId: bootstrap.user.id, body: "Me, two sets", id: 150 }),
  ];
  const worker = (await FakeWorker.install(page)).on("loadBefore", () => "silent");

  await page.goto("/");
  const panel = await openRoom(page, ROOM);
  const thread = panel.getByRole("region", { name: copy.messageListLabel });
  const alert = panel.getByRole("alert");

  // Before the room answers, an empty list is no sign of an empty room.
  await expect(thread).toHaveAttribute("aria-busy", "true");
  await expect(panel.getByText(copy.emptyEvent)).toHaveCount(0);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-thread-loading.png" });

  worker.on("loadBefore", () => REFUSED);
  await reopen(panel);
  await expect(alert).toContainText(copy.historyFailed);
  await expect(thread).toHaveAttribute("aria-busy", "false");
  await expect(panel.getByText(copy.emptyEvent)).toHaveCount(0);
  await page.screenshot({ animations: "disabled", path: "screenshots/parley-thread-failed.png" });

  // Earlier history that will not load says so too, above the thread.
  worker.on("loadBefore", (input) =>
    input.beforeId === undefined ? { ok: true, value: latest } : REFUSED,
  );
  await panel.getByRole("button", { name: copy.retry }).click();
  await expect(panel.getByText("Me, two sets")).toBeVisible();
  await expect(alert).toHaveCount(0);
  await panel.getByRole("button", { name: copy.loadEarlier }).click();
  await expect(alert).toContainText(copy.historyFailed);
  await expect(panel.getByText("Me, two sets")).toBeVisible();

  worker.on("loadBefore", (input) =>
    input.beforeId === undefined
      ? { ok: true, value: latest }
      : { ok: true, value: [message({ body: "The very first word", id: 100 })] },
  );
  await panel.getByRole("button", { name: copy.retry }).click();
  await expect(panel.getByText("The very first word")).toBeVisible();
  await expect(alert).toHaveCount(0);
  expect(worker.called("loadBefore").at(-1)?.input).toEqual({ beforeId: 101, limit: 50 });

  // Reopened while the room is slow, the thread is already there.
  worker.on("loadBefore", () => "silent");
  await reopen(panel);
  await expect(thread).toHaveAttribute("aria-busy", "true");
  await expect(panel.getByText("Who brings the dice?")).toBeVisible();

  // Once the room answers, its word replaces the remembered one: a message
  // deleted meanwhile does not linger.
  worker.on("loadBefore", () => ({
    ok: true,
    value: [
      ...latest.slice(0, 48),
      message({ body: "", deletedAt: Date.now(), id: 149 }),
      latest[49],
      message({ body: "Bring snacks too", id: 151 }),
    ],
  }));
  await reopen(panel);
  await expect(panel.getByText("Bring snacks too")).toBeVisible();
  await expect(thread).toHaveAttribute("aria-busy", "false");
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
});
