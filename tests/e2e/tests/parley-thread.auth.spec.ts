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
  routeBootstrap,
} from "./helpers/parley";

// The chromium-auth default user has no sphere role; the chat's manager
// copy and moderation need the superuser, as parley.auth.spec.ts does.
test.use({
  storageState: path.join(__dirname, "..", ".auth-state-superuser.json"),
  timezoneId: "UTC",
});

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
// A fixed afternoon, so "today", "yesterday" and "last week" never straddle
// midnight. Timers still run in real time.
const NOW = Date.parse("2026-11-10T15:00:00Z");
const ME = bootstrap.user.id;

test("A conversation reads back in runs with dates, links, avatars and history", async ({
  page,
}) => {
  await page.clock.setFixedTime(NOW);
  await routeBootstrap(page);
  const avatar =
    "data:image/svg+xml;base64," +
    Buffer.from('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>').toString(
      "base64",
    );
  const latest = [
    message({ body: "Ten days back", createdAt: NOW - 10 * DAY, id: 3 }),
    message({ authorId: ME, body: "Three days back from me", createdAt: NOW - 3 * DAY, id: 4 }),
    message({
      authorAvatarUrl: avatar,
      authorId: "3",
      authorName: "Ola",
      body: "Yesterday hello",
      createdAt: NOW - DAY,
      id: 5,
    }),
    message({
      authorAvatarUrl: avatar,
      authorId: "3",
      authorName: "Ola",
      body: "Rules at https://example.com/rules today",
      createdAt: NOW - DAY + 2 * MINUTE,
      id: 6,
    }),
    message({ body: "", createdAt: NOW - HOUR, deletedAt: NOW - HOUR, id: 7 }),
    ...Array.from({ length: 44 }, (_, index) =>
      message({
        authorId: ME,
        body: `Filler ${index + 8}`,
        createdAt: NOW - 40 * MINUTE + index * 10_000,
        id: index + 8,
      }),
    ),
    // Last, so it is on screen: its lazy picture only loads, and fails, there.
    message({
      authorAvatarUrl: "http://localhost:8000/static/missing-avatar.png",
      authorId: "4",
      authorName: "Broken Avatar",
      body: "My picture is gone",
      createdAt: NOW - MINUTE,
      id: 52,
    }),
  ];
  const worker = (await FakeWorker.install(page)).on("loadBefore", (input) =>
    input.beforeId === undefined
      ? { ok: true, value: latest }
      : {
          ok: true,
          value: [
            message({ body: "The very first word", createdAt: NOW - 20 * DAY, id: 1 }),
            message({ body: "And the second", createdAt: NOW - 20 * DAY + MINUTE, id: 2 }),
          ],
        },
  );

  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "My picture is gone");

  await expect(panel.getByRole("link", { name: "https://example.com/rules" })).toHaveAttribute(
    "href",
    "https://example.com/rules",
  );
  await expect(panel.getByText(bootstrap.copy.deletedMessage)).toHaveCount(1);
  // One run, one name: Ola's two messages sit under a single label.
  await expect(panel.getByText("Ola", { exact: true })).toHaveCount(1);
  // A picture that fails to load gives way to the initials.
  await expect(panel.locator('img[src*="missing-avatar"]')).toHaveCount(0);
  await expect(panel.locator(`img[src="${avatar}"]`)).toHaveCount(1);
  await expect
    .poll(() => worker.called("markRead").at(-1)?.input)
    .toEqual({
      messageId: 52,
      roomId: "sphere:1",
    });

  await expect(panel.getByText(bootstrap.copy.retentionNote)).toHaveCount(0);
  await panel.getByRole("button", { name: bootstrap.copy.loadEarlier }).click();
  await expect(panel.getByText("The very first word")).toBeVisible();
  // The second page came back short, so there is nothing further back, and
  // the start of history says why it ends there.
  await expect(panel.getByRole("button", { name: bootstrap.copy.loadEarlier })).toHaveCount(0);
  await expect(panel.getByText(bootstrap.copy.retentionNote)).toBeVisible();
  expect(worker.called("loadBefore").at(-1)?.input).toEqual({ beforeId: 3, limit: 50 });

  worker.push("presence.changed", { count: 1 }, /parley-sphere-agent/u);
  await expect(panel.getByText("Common room · 1 person here")).toBeVisible();
  worker.push("presence.changed", { count: 3 }, /parley-sphere-agent/u);
  await expect(panel.getByText("Common room · 3 people here")).toBeVisible();

  // A message the room already holds (an echo of one's own send) stays single.
  worker.push("message.created", latest.at(-1));
  worker.push("message.created", message({ body: "Fresh off the press", createdAt: NOW, id: 53 }));
  await expect(panel.getByText("Fresh off the press")).toBeVisible();
  await expect(panel.getByText("My picture is gone")).toHaveCount(1);
  worker.push("message.deleted", { id: 53 });
  await expect(panel.getByText(bootstrap.copy.deletedMessage)).toHaveCount(2);
  await analyzePageAccessibility(page);
});

test("The room says who is typing and drops them when they go quiet", async ({ page }) => {
  await routeBootstrap(page);
  const now = Date.now();
  const worker = (await FakeWorker.install(page)).on("loadBefore", () => ({
    ok: true,
    value: [
      message({ body: "Kuba was here", createdAt: now - MINUTE, id: 1 }),
      message({ authorId: "3", authorName: "Ola", body: "So was Ola", id: 2 }),
    ],
  }));
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", "So was Ola");
  const typing = (userId: string, ms: number) =>
    worker.push("typing.changed", { expiresAt: Date.now() + ms, userId }, /sphere-agent/u);

  typing(ME, 5000);
  typing("2", 5000);
  await expect(panel.getByText("Kuba Nowak is typing…")).toBeVisible();
  typing("3", 5000);
  await expect(panel.getByText("Kuba Nowak and Ola are typing…")).toBeVisible();
  typing("9", 5000);
  await expect(panel.getByText(bootstrap.copy.typingMany)).toBeVisible();
  // Sending a message ends that person's typing. Two typists left, one of
  // them nobody in the thread: there is no pair of names to give.
  worker.push("message.created", message({ body: "Done typing", id: 3 }));
  await expect(panel.getByText("Done typing")).toBeVisible();
  await expect(panel.getByText(bootstrap.copy.typingMany)).toBeVisible();
  typing("3", -1);
  await expect(panel.getByText("Someone is typing…")).toBeVisible();
  typing("9", -1);
  await expect(panel.getByText(bootstrap.copy.typingMany)).toHaveCount(0);
  typing("9", 400);
  await expect(panel.getByText("Someone is typing…")).toBeVisible();
  await expect(panel.getByText("Someone is typing…")).toHaveCount(0);
});

test("The composer sends, counts, and says what went wrong", async ({ page }) => {
  await routeBootstrap(page);
  let reply: "ok" | "rate_limited" | "silent" | "weird" = "ok";
  const worker = await FakeWorker.install(page);
  let sentCount = 0;
  worker.on("sendMessage", (input) => {
    if (reply === "silent") return "silent";
    if (reply !== "ok") return { code: reply, ok: false };
    const sent = message({
      authorId: ME,
      body: String(input.body),
      id: 100 + sentCount,
      nonce: String(input.nonce),
    });
    // The first time, the Worker's broadcast beats the call's own answer back.
    if (sentCount === 0) worker.push("message.created", sent, /sphere-agent/u);
    sentCount += 1;
    return { ok: true, value: sent };
  });
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", bootstrap.copy.emptySphere);
  const composer = panel.getByLabel("Message", { exact: true });
  const send = panel.getByRole("button", { name: bootstrap.copy.sendLabel });

  await composer.pressSequentially("Hi");
  await expect.poll(() => worker.called("startTyping").length).toBe(1);
  await composer.fill("");
  await expect.poll(() => worker.called("stopTyping").length).toBe(1);
  // A blank draft that was never announced says nothing either.
  await composer.fill("   ");
  await composer.fill("");
  await composer.fill("Line one");
  await composer.press("Shift+Enter");
  await composer.pressSequentially("Line two");
  await composer.press("Enter");
  await expect(panel.getByText(/Line one\s+Line two/u)).toBeVisible();
  await expect(composer).toHaveValue("");
  await expect(composer).toBeFocused();
  // The Worker's echo of the same message does not double it.
  worker.push("message.created", message({ authorId: ME, body: "Line one\nLine two", id: 100 }));
  await expect(panel.getByText(/Line one\s+Line two/u)).toHaveCount(1);
  await composer.fill("Second thought");
  await composer.press("Enter");
  await expect(panel.getByText("Second thought")).toBeVisible();

  reply = "rate_limited";
  await composer.fill("Again");
  await send.click();
  await expect(panel.getByRole("alert")).toHaveText(bootstrap.copy.errorRateLimited);
  reply = "weird";
  await send.click();
  await expect(panel.getByRole("alert")).toHaveText(bootstrap.copy.errorUnknown);

  await composer.fill("y".repeat(950));
  await expect(panel.getByText("950/1,000")).toBeVisible();
  await composer.fill("y".repeat(1001));
  await expect(panel.getByRole("alert")).toHaveText(bootstrap.copy.messageTooLong);
  await expect(send).toBeDisabled();
  const sends = worker.called("sendMessage").length;
  await composer.press("Enter");
  expect(worker.called("sendMessage")).toHaveLength(sends);

  // A socket that never answers lets the composer go after 10 s.
  reply = "silent";
  await composer.fill("Into the void");
  await composer.press("Enter");
  await expect(panel.getByRole("button", { name: bootstrap.copy.sending })).toHaveAttribute(
    "aria-busy",
    "true",
  );
  await composer.press("Enter");
  expect(worker.called("sendMessage")).toHaveLength(sends + 1);
  await expect(panel.getByRole("alert")).toHaveText(bootstrap.copy.connectionError, {
    timeout: 15_000,
  });

  // Closing the chat with a draft still announced takes the "typing…" back.
  const stops = worker.called("stopTyping").length;
  await panel.getByRole("button", { name: bootstrap.copy.closeLabel }).click();
  await expect(panelOf(page)).toBeHidden();
  await expect.poll(() => worker.called("stopTyping").length).toBe(stops + 1);
});

test("A mute replaces the composer, says until when, and lifts on its own", async ({ page }) => {
  await routeBootstrap(page);
  // How the Worker refuses: "plain" says muted; "announced" first sends the
  // restriction with its end, as a mute landing mid-call would.
  let refusal: "announced" | "none" | "plain" = "plain";
  const worker = await FakeWorker.install(page);
  const refuse = () => {
    if (refusal === "none") return { ok: true, value: {} } as const;
    if (refusal === "announced")
      worker.push("restriction.changed", { mutedUntil: Date.now() + 1500, userId: ME });
    return { code: "muted", ok: false } as const;
  };
  worker.on("startTyping", refuse).on("sendMessage", refuse);
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", bootstrap.copy.emptySphere);
  const composer = panel.getByLabel("Message", { exact: true });
  const restore = async () => {
    worker.push("restriction.changed", { mutedUntil: 0, userId: ME });
    await expect(panel.getByText(bootstrap.copy.writingRestored)).toBeVisible();
    await expect(composer).toBeVisible();
  };

  // The first typing ping is refused for a mute nobody announced yet.
  await composer.pressSequentially("x");
  await expect(panel.getByText(bootstrap.copy.errorMuted)).toBeVisible();
  await expect(composer).toHaveCount(0);
  await restore();

  // So is a send; with the end already known, the notice keeps it.
  refusal = "announced";
  await composer.fill("Can I talk?");
  await panel.getByRole("button", { name: bootstrap.copy.sendLabel }).click();
  await expect(panel.getByText(/Your writing access is muted until /u)).toBeVisible();
  // The mute ends on its own when its time is up.
  await expect(composer).toBeVisible({ timeout: 5000 });
  await expect(panel.getByText(bootstrap.copy.writingRestored)).toBeVisible();

  refusal = "plain";
  await panel.getByRole("button", { name: bootstrap.copy.sendLabel }).click();
  await expect(panel.getByText(bootstrap.copy.errorMuted)).toBeVisible();
  await restore();

  // A typing ping goes out at most every 3 s.
  refusal = "announced";
  await page.waitForTimeout(3100);
  await composer.pressSequentially("y");
  await expect(panel.getByText(/Your writing access is muted until /u)).toBeVisible();
  await expect(composer).toBeVisible({ timeout: 5000 });

  refusal = "none";
  // Someone else's mute is not this person's business; a mute already over
  // when it arrives changes nothing.
  worker.push("restriction.changed", { mutedUntil: null, userId: "2" });
  worker.push("restriction.changed", { mutedUntil: Date.now() - 1000, userId: ME });
  await expect(composer).toBeVisible();
  worker.push("restriction.changed", { mutedUntil: Date.now() + 3 * DAY, userId: ME });
  await expect(panel.getByText(/Your writing access is muted until /u)).toBeVisible();
  await analyzePageAccessibility(page);
});

test("A dropped connection says so and clears once the socket is back", async ({ page }) => {
  await routeBootstrap(page);
  const worker = await FakeWorker.install(page);
  await page.goto("/");
  const panel = await openRoom(page, "Zagrajmy", bootstrap.copy.emptySphere);
  worker.push("presence.changed", { count: 2 }, /sphere-agent/u);
  worker.push("typing.changed", { expiresAt: Date.now() + 60_000, userId: "2" }, /sphere-agent/u);
  await expect(panel.getByText("Common room · 2 people here")).toBeVisible();
  await expect(panel.getByText("Someone is typing…")).toBeVisible();

  await worker.close(1011);
  await expect(panel.getByRole("status").filter({ hasText: bootstrap.copy.offline })).toBeVisible();
  await expect(panel.getByText("2 people here")).toHaveCount(0);
  await expect(panel.getByText("Someone is typing…")).toHaveCount(0);
  // Nobody hears a typing ping while the socket is down.
  await panel.getByLabel("Message", { exact: true }).pressSequentially("hello?");
  expect(worker.called("startTyping")).toHaveLength(0);
  // The socket redials on its own; the strip goes once it is open again.
  await expect(panel.getByText(bootstrap.copy.offline)).toHaveCount(0, { timeout: 15_000 });
  await expect(launcherOf(page)).toBeVisible();
});

test("A programme point's thread, gone within the month, promises no year", async ({ page }) => {
  await routeBootstrap(page);
  await (
    await FakeWorker.install(page)
  ).on("loadBefore", () => ({
    ok: true,
    value: [message({ body: "See you at the table", createdAt: Date.now(), id: 1 })],
  }));
  await page.goto("/");

  const panel = await openRoom(page, "Mothership", "See you at the table");

  await expect(panel.getByText(bootstrap.copy.retentionNote)).toHaveCount(0);
});
