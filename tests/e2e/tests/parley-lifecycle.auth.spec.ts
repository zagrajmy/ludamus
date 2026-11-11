import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";
import {
  bootstrap,
  FakeWorker,
  launcherOf,
  message,
  openRoom,
  panelOf,
  passExpiring,
  routeBootstrap,
  sphereRoom,
} from "./helpers/parley";

test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const { copy } = bootstrap;
const roomsOf = (panel: ReturnType<typeof panelOf>) =>
  panel.getByRole("navigation", { name: copy.roomsLabel });

test("A chat that cannot connect says so, and Try again recovers", async ({ page }) => {
  // The page connects on its own for the badge; that first failure stays
  // quiet, and opening the chat tries again rather than replaying it.
  const served = await routeBootstrap(page, [500, 500, { delayMs: 800 }]);
  await FakeWorker.install(page);
  await page.goto("/");
  await expect.poll(served.count).toBe(1);

  const launcher = launcherOf(page);
  await launcher.click();
  const panel = panelOf(page);
  await expect(panel.getByRole("alert")).toContainText(copy.connectionError);
  expect(served.count()).toBe(2);
  await analyzePageAccessibility(page);

  await panel.getByRole("button", { name: copy.retry }).click();
  await expect(panel.getByRole("status")).toHaveText(copy.loading);
  await expect(roomsOf(panel)).toBeVisible();
  await panel.getByRole("button", { name: copy.closeLabel }).click();
  await expect(panel).toBeHidden();
  await expect(launcher).toBeFocused();
});

test("The launcher closes a chat that is still loading", async ({ page }) => {
  await routeBootstrap(page, [{ delayMs: 3000 }]);
  await FakeWorker.install(page);
  await page.goto("/");
  const launcher = launcherOf(page);
  await launcher.click();
  await expect(panelOf(page).getByRole("status")).toHaveText(copy.loading);
  await launcher.click();
  await expect(panelOf(page)).toBeHidden();
});

test("A pass the Worker will not take shows the connection error", async ({ page }) => {
  await routeBootstrap(page, [{}], 500);
  await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();
  await expect(panelOf(page).getByRole("alert")).toContainText(copy.connectionError);
  await panelOf(page).getByRole("button", { name: copy.closeLabel }).click();
  await expect(panelOf(page)).toBeHidden();
});

test("Opening the chat mid-connect keeps only the newer connection", async ({ page }) => {
  const served = await routeBootstrap(page, [
    { delayMs: 1500, rooms: [{ ...sphereRoom, title: "Stale sphere" }] },
    { delayMs: 300 },
  ]);
  await FakeWorker.install(page);
  await page.goto("/");
  await expect.poll(served.count).toBe(1);
  await launcherOf(page).click();
  await expect(roomsOf(panelOf(page)).getByRole("button", { name: /Zagrajmy/u })).toBeVisible();
  await page.waitForTimeout(1500);
  await expect(panelOf(page).getByText("Stale sphere")).toHaveCount(0);
});

const hiddenTab = () => {
  let state: DocumentVisibilityState = "hidden";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  Object.assign(window, {
    showTab: () => {
      state = "visible";
      document.dispatchEvent(new Event("visibilitychange"));
    },
  });
};

test("A background tab waits until it is shown to connect", async ({ page }) => {
  await page.addInitScript(hiddenTab);
  const served = await routeBootstrap(page);
  await FakeWorker.install(page);
  await page.goto("/");
  await page.waitForTimeout(1500);
  expect(served.count()).toBe(0);
  await page.evaluate(() => (window as unknown as { showTab: () => void }).showTab());
  await expect.poll(served.count).toBe(1);
});

test("A chat opened in a background tab marks nothing read", async ({ page }) => {
  await page.addInitScript(hiddenTab);
  await routeBootstrap(page);
  const worker = (await FakeWorker.install(page)).on("loadBefore", () => ({
    ok: true,
    value: [message({ body: "Read me later", id: 7 })],
  }));
  await page.goto("/");
  await openRoom(page, "Zagrajmy", "Read me later");
  await page.waitForTimeout(500);
  expect(worker.called("markRead")).toHaveLength(0);
});

test("A revoked or expired pass is swapped for a new one", async ({ page }) => {
  const served = await routeBootstrap(page);
  const worker = await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();
  const panel = panelOf(page);
  await expect(roomsOf(panel)).toBeVisible();
  await expect.poll(served.count).toBe(1);

  // Refused right after it was issued: the next would be refused too, so
  // the chat waits for the person instead of looping.
  await worker.close(4403, /sphere-agent/u);
  await expect(panel.getByRole("alert")).toContainText(copy.connectionError);
  await panel.getByRole("button", { name: copy.retry }).click();
  await expect(roomsOf(panel)).toBeVisible();
  await expect.poll(served.count).toBe(2);

  // An older pass that lapses is replaced quietly.
  await page.waitForTimeout(5200);
  await worker.close(4401, /sphere-agent/u);
  await expect.poll(served.count).toBe(3);
  await expect(roomsOf(panel)).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);

  // A room socket's revocation does the same.
  await roomsOf(panel)
    .getByRole("button", { name: /Mothership/u })
    .click();
  await expect(panel.getByText(copy.emptyReadOnly)).toBeVisible();
  await page.waitForTimeout(5200);
  await worker.close(4403, /session-agent/u);
  await expect.poll(served.count).toBe(4);
});

test("A pass is renewed before it expires", async ({ page }) => {
  const served = await routeBootstrap(page, [
    { capabilityToken: passExpiring(Math.floor(Date.now() / 1000) - 60) },
    {},
  ]);
  await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();
  await expect(roomsOf(panelOf(page))).toBeVisible();
  // Already inside the last 30 s, it is renewed a second after it arrives.
  await expect.poll(served.count, { timeout: 5000 }).toBe(2);
  await page.waitForTimeout(1500);
  expect(served.count()).toBe(2);
});

test("A sphere with one room opens it straight from the launcher", async ({ page }) => {
  await routeBootstrap(page, [{ delayMs: 600, rooms: [sphereRoom] }]);
  const worker = (await FakeWorker.install(page))
    .on("getActivity", () => ({ code: "forbidden", ok: false }))
    .on("loadBefore", () => ({ code: "invalid", ok: false }));
  await page.goto("/");
  const launcher = launcherOf(page);
  // Asked for before the bootstrap lands, the only room opens as it arrives.
  await launcher.click();
  const panel = panelOf(page);
  await expect(panel.getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
  await expect(panel.getByRole("button", { name: copy.backLabel })).toHaveCount(0);
  // A history that would not load leaves the room empty, not broken.
  await expect(panel.getByText(copy.emptySphere)).toBeVisible();
  expect(worker.called("getActivity").length).toBeGreaterThan(0);

  // Keys other than Escape leave the window open.
  await page.keyboard.press("a");
  await expect(panel).toBeVisible();
  await panel.getByRole("button", { name: copy.closeLabel }).click();
  await expect(panel).toBeHidden();
  await expect(launcher).toBeFocused();

  await launcher.click();
  await expect(panel.getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
  // The launcher only opens and closes; it reopens where the window was left.
  await page.setViewportSize({ height: 800, width: 1280 });
  await launcher.click();
  await expect(panel).toBeHidden();
  await launcher.click();
  await expect(panel.getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
  await expect(roomsOf(panel)).toHaveCount(0);
});

test("A one-room sphere loaded in the background opens that room", async ({ page }) => {
  const served = await routeBootstrap(page, [{ rooms: [sphereRoom] }]);
  await FakeWorker.install(page);
  await page.goto("/");
  await expect.poll(served.count).toBe(1);
  await expect(launcherOf(page)).toHaveAttribute("aria-expanded", "false");
  await launcherOf(page).click();
  await expect(panelOf(page).getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
});

test.describe("On a touch screen", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { height: 844, width: 390 } });

  test("an opened room keeps the keyboard down", async ({ page }) => {
    await routeBootstrap(page);
    await FakeWorker.install(page);
    await page.goto("/");
    const panel = await openRoom(page, "Zagrajmy", copy.emptySphere);
    await expect(panel.getByRole("button", { name: copy.closeLabel })).toBeFocused();
  });
});

test("The room list puts recent rooms first and counts the unread ones", async ({ page }) => {
  const now = Date.parse("2026-11-10T15:00:00Z");
  await page.clock.setFixedTime(now);
  const rooms = [
    sphereRoom,
    ...["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"].map((title, index) => ({
      canModerate: false,
      canWrite: index !== 0,
      id: `session:1:${index + 10}`,
      kind: "session",
      title,
    })),
  ];
  await routeBootstrap(page, [{ rooms }]);
  const worker = await FakeWorker.install(page, {
    "session:1:10": { at: now - 5 * 60_000, unread: true },
    "session:1:11": { at: now - 3 * 3_600_000, unread: true },
    "session:1:12": { at: now - 2 * 86_400_000, unread: true },
    "session:1:13": { at: now - 10 * 86_400_000, unread: true },
    "session:1:14": { at: now - 10 * 86_400_000, unread: true },
  });
  await page.goto("/");
  // An empty page language falls back to Polish plural rules.
  await page.evaluate(() => document.documentElement.setAttribute("lang", ""));
  // The snapshot first, so the live event lands on top of it.
  await expect.poll(() => worker.called("getActivity").length).toBe(1);
  worker.push("room.activity", { at: now - 60_000, latestMessageId: 3, roomId: "sphere:1" });
  const launcher = launcherOf(page);
  await expect(launcher).toHaveAccessibleDescription("6 unread conversations");

  await launcher.click();
  const panel = panelOf(page);
  const list = roomsOf(panel).getByRole("button");
  await expect(list).toHaveText([
    /Zagrajmy/u,
    /Alpha/u,
    /Bravo/u,
    /Charlie/u,
    /Delta/u,
    /Echo/u,
    /Foxtrot/u,
  ]);
  await expect(list.first()).toBeFocused();
  await expect(list.nth(1)).toContainText(copy.unread);

  // Reading a room elsewhere clears it here; a room with no activity yet
  // can turn unread without a time to show.
  for (const id of [12, 13, 14])
    worker.push("unread.changed", { roomId: `session:1:${id}`, unread: false });
  worker.push("unread.changed", { roomId: "session:1:15", unread: true });
  await expect(launcher).toHaveAccessibleDescription("4 unread conversations");
  await expect(list.last()).toHaveText(/Foxtrot\s*Programme point\s*Unread$/u);
  await page.evaluate(() => document.documentElement.setAttribute("lang", "en"));

  // The open room does not count as unread.
  await list.nth(1).click();
  await expect(panel.getByRole("heading", { name: "Alpha" })).toBeVisible();
  for (const id of ["sphere:1", "session:1:11"])
    worker.push("unread.changed", { roomId: id, unread: false });
  await expect(launcher).toHaveAccessibleDescription("1 unread conversation");
  await panel.getByRole("button", { name: copy.backLabel }).click();
  await expect(list.nth(1)).toHaveAttribute("aria-current", "true");
  await analyzePageAccessibility(page);
});

test("The chat loads on its own a moment after the page, or at once on a click", async ({
  page,
}) => {
  // Without requestIdleCallback the loader falls back to a timer.
  await page.addInitScript(() => {
    Reflect.deleteProperty(window, "requestIdleCallback");
  });
  const served = await routeBootstrap(page);
  await FakeWorker.install(page);
  await page.goto("/");
  await launcherOf(page).click();
  await expect(roomsOf(panelOf(page))).toBeVisible();
  await page.waitForTimeout(1500);
  expect(served.count()).toBe(1);
});

test("A bare chat root still starts, with default labels", async ({ page }) => {
  await page.addInitScript(() => {
    new MutationObserver((records, observer) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (!(node instanceof HTMLElement) || !node.matches("[data-parley-root]")) continue;
          for (const name of [
            "data-bootstrap-url",
            "data-close-label",
            "data-loading",
            "data-connection-error",
            "data-retry",
          ])
            node.removeAttribute(name);
          node.querySelector("[data-parley-launcher]")?.removeAttribute("aria-label");
          observer.disconnect();
        }
      }
    }).observe(document, { childList: true, subtree: true });
  });
  await routeBootstrap(page);
  await FakeWorker.install(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await expect(page.getByRole("dialog", { name: copy.title })).toBeVisible();
});

test.describe("A Worker on another host", () => {
  // The app's CSP only lets the page reach its own configured Worker host.
  test.use({ bypassCSP: true });

  for (const agentHost of [
    "http://localhost:8787",
    "parley.ludamus.localhost:8787",
    "127.0.0.1:8787",
    "parley.example.test",
  ]) {
    test(`is reached at ${agentHost}`, async ({ page }) => {
      await routeBootstrap(page, [{ agentHost }]);
      const worker = await FakeWorker.install(page);
      await page.goto("/");
      await openRoom(page, "Zagrajmy", copy.emptySphere);
      const secure = agentHost === "parley.example.test";
      expect(
        worker.sockets.every((socket) => socket.url().startsWith(secure ? "wss:" : "ws:")),
      ).toBe(true);
    });
  }
});
