import type { Page, WebSocketRoute } from "@playwright/test";

import path from "node:path";

import { analyzePageAccessibility } from "./helpers/a11y";
import { expect, test } from "./helpers/fixtures";

// The chromium-auth project's default storage state (e2e-tester) is a plain
// user with no sphere role, so it can't reach /multiverse/panel/ to flip
// the setting this spec exercises. Every other panel-touching .auth.spec.ts
// (modal-surfaces, promotion) swaps in the superuser state for the same
// reason.
test.use({ storageState: path.join(__dirname, "..", ".auth-state-superuser.json") });

const bootstrap = {
  agentHost: "localhost:8787",
  capabilityToken: "mock-token",
  copy: {
    backLabel: "Back to conversations",
    cancelLabel: "Cancel",
    closeLabel: "Close chat",
    connectionError: "Could not connect to the chat.",
    copyLink: "Copy message link",
    deletedMessage: "Message deleted",
    deleteConfirm: "Delete this message for everyone?",
    emptyReadOnly: "Nobody has written here yet.",
    muteConfirm: "Mute this person indefinitely? They can still read.",
    muted: "Writing access limited.",
    mutedUntil: "Your writing access is muted until %(time)s.",
    deleteLabel: "Delete message",
    emptySession: "You found the table first. Leave a note for the others.",
    emptySphere: "Quiet in here. Say hello before someone starts a rules debate.",
    errorArchived: "This conversation is archived.",
    errorForbidden: "You do not have permission to do that.",
    errorInvalid: "That message could not be sent.",
    errorMuted: "Your writing access is currently muted.",
    errorRateLimited: "Too many messages. Wait a moment and try again.",
    errorUnknown: "Something went wrong. Try again.",
    loadEarlier: "Load earlier messages",
    linkCopied: "Link copied.",
    loading: "Gathering conversations…",
    messageActions: "Message actions",
    messageLabel: "Message",
    messageListLabel: "Messages",
    messageTooLong: "Messages can be up to 1,000 characters.",
    moderatorDelete: "Delete as moderator",
    muteIndefinitely: "Mute indefinitely",
    muteLabel: "Change writing access",
    muteOneDay: "Mute for 24 hours",
    muteOneHour: "Mute for 1 hour",
    muteSevenDays: "Mute for 7 days",
    offline: "Connection lost. Reconnecting…",
    presenceFew: "%(count)s people here",
    presenceMany: "%(count)s people here",
    presenceOne: "%(count)s person here",
    readOnly: "You can read this conversation, but not write in it.",
    reported: "Message reported.",
    reportMessage: "Report message",
    retry: "Try again",
    restoreWriting: "Restore writing access",
    roomsLabel: "Conversations",
    scrollLatest: "Jump to the latest messages",
    sending: "Sending…",
    sendLabel: "Send message",
    sessionRoom: "Programme point",
    sphereRoom: "Common room",
    title: "Chat",
    typingMany: "Several people are typing…",
    typingOne: "%(name)s is typing…",
    typingSomeone: "Someone",
    typingTwo: "%(first)s and %(second)s are typing…",
    unread: "Unread",
    unreadCountFew: "%(count)s unread conversations",
    unreadCountMany: "%(count)s unread conversations",
    unreadCountOne: "%(count)s unread conversation",
    writePlaceholder: "Write a message…",
    writingRestored: "Writing access restored.",
  },
  csrfToken: "mock-csrf",
  rooms: [
    { canModerate: true, canWrite: true, id: "sphere:1", kind: "sphere", title: "Zagrajmy" },
    {
      canModerate: true,
      canWrite: false,
      id: "session:1:42",
      kind: "session",
      title: "Mothership",
    },
  ],
  sphere: { id: "1", name: "Zagrajmy" },
  user: { avatarUrl: "", id: "1", name: "E2E Manager" },
};

test.describe.configure({ mode: "serial" });

// The chat is on by default; an organizer turns it off in sphere settings.
async function setChat(page: Page, enabled: boolean): Promise<void> {
  await page.goto("/multiverse/panel/");
  await page.getByLabel("Enable chat").setChecked(enabled);
  await page.getByRole("button", { name: "Save Settings" }).click();
  await expect(page.getByText("Sphere settings saved successfully.")).toBeVisible();
}

async function routeBootstrap(page: Page): Promise<void> {
  await page.route("**/parley/bootstrap/", (route) =>
    route.fulfill({ contentType: "application/json", json: bootstrap }),
  );
  await page.route("http://localhost:8787/auth/exchange", (route) =>
    route.fulfill({
      headers: {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Origin": "http://localhost:8000",
      },
      status: 204,
    }),
  );
}

// Stands in for the chat Worker's sockets: every RPC succeeds (getActivity
// with the given activity, loadBefore with an empty room), and the returned
// list lets a test push server events to every open socket.
async function routeAgents(
  page: Page,
  activity: Record<string, { at: number; unread: boolean }>,
): Promise<WebSocketRoute[]> {
  const sockets: WebSocketRoute[] = [];
  await page.routeWebSocket(/^ws:\/\/localhost:8787\//, (socket) => {
    sockets.push(socket);
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw)) as { id: string; method: string; type: string };
      if (message.type !== "rpc") return;
      const value =
        message.method === "getActivity" ? activity : message.method === "loadBefore" ? [] : {};
      socket.send(
        JSON.stringify({
          done: true,
          id: message.id,
          result: { ok: true, value },
          success: true,
          type: "rpc",
        }),
      );
    });
  });
  return sockets;
}

function push(sockets: WebSocketRoute[], type: string, payload: unknown): void {
  for (const socket of sockets) socket.send(JSON.stringify({ payload, type, v: 1 }));
}

test("The launcher counts unread conversations before the chat is ever opened", async ({
  page,
}) => {
  await routeBootstrap(page);
  await routeAgents(page, { "sphere:1": { at: Date.now(), unread: true } });

  await page.goto("/");
  const launcher = page.getByRole("button", { name: "Open chat" });
  await expect(launcher).toHaveAttribute("aria-expanded", "false");
  await expect(launcher).toHaveAccessibleDescription(/1 unread conversation/);
});

test("The composer shows who is typing, the length limit, and a mute", async ({ page }) => {
  await routeBootstrap(page);
  const sockets = await routeAgents(page, {});

  await page.goto("/");
  await page.getByRole("button", { name: "Open chat" }).click();
  const panel = page.getByRole("dialog", { name: "Chat" });
  await panel.getByRole("button", { name: /Zagrajmy/ }).click();
  const composer = panel.getByLabel("Message", { exact: true });
  await expect(composer).toBeFocused();
  // The empty state means loadBefore came back, so the room's socket is open.
  await expect(panel.getByText(bootstrap.copy.emptySphere)).toBeVisible();

  push(sockets, "message.created", {
    authorAvatarUrl: "",
    authorId: "2",
    authorName: "Kuba Nowak",
    body: "Anyone at table 7?",
    createdAt: Date.now(),
    deletedAt: null,
    id: 1,
    nonce: "n1",
  });
  push(sockets, "typing.changed", { expiresAt: Date.now() + 5000, userId: "2" });
  await expect(panel.getByText("Kuba Nowak is typing…")).toBeVisible();

  await composer.fill("x".repeat(1001));
  await expect(panel.getByRole("alert")).toHaveText(bootstrap.copy.messageTooLong);
  await expect(panel.getByRole("button", { name: "Send message" })).toBeDisabled();

  push(sockets, "restriction.changed", { mutedUntil: null, userId: bootstrap.user.id });
  await expect(panel.getByText(bootstrap.copy.errorMuted)).toBeVisible();
  await expect(composer).toBeHidden();
  await analyzePageAccessibility(page);

  push(sockets, "restriction.changed", { mutedUntil: 0, userId: bootstrap.user.id });
  await expect(composer).toBeVisible();
  await expect(panel.getByText(bootstrap.copy.writingRestored)).toBeVisible();
});

test("The chat launcher opens an accessible chat window from its room list", async ({ page }) => {
  await routeBootstrap(page);

  try {
    await page.goto("/");
    const launcher = page.getByRole("button", { name: "Open chat" });
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    await launcher.click();

    const panel = page.getByRole("dialog", { name: "Chat" });
    const rooms = panel.getByRole("navigation", { name: "Conversations" });
    await expect(rooms).toBeVisible();
    await expect(launcher).toHaveAttribute("aria-expanded", "true");
    await analyzePageAccessibility(page);

    await rooms.getByRole("button", { name: /Zagrajmy/ }).click();
    await expect(panel.getByRole("heading", { name: "Zagrajmy" })).toBeVisible();
    await expect(panel.getByLabel("Message", { exact: true })).toBeFocused();
    await analyzePageAccessibility(page);
    await page.screenshot({ animations: "disabled", path: "screenshots/parley-desktop.png" });

    await panel.getByRole("button", { name: "Back to conversations" }).click();
    await rooms.getByRole("button", { name: /Mothership/ }).click();
    await expect(panel.getByText(bootstrap.copy.readOnly)).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(panel).toBeHidden();
    await expect(launcher).toBeFocused();

    await page.setViewportSize({ height: 844, width: 390 });
    await launcher.click();
    await page
      .getByRole("navigation", { name: "Conversations" })
      .getByRole("button", { name: /Zagrajmy/ })
      .click();
    await expect(page.getByPlaceholder("Write a message…")).toBeVisible();
    await page.screenshot({ animations: "disabled", path: "screenshots/parley-mobile.png" });

    await setChat(page, false);
    await page.goto("/");
    await expect(page.getByRole("button", { name: "Open chat" })).toHaveCount(0);
  } finally {
    await setChat(page, true);
  }
});
