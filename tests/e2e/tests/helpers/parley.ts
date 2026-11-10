import type { Locator, Page, WebSocketRoute } from "@playwright/test";

import { expect } from "./fixtures";

// What /parley/bootstrap/ returns for the superuser e2e state: a manager of
// sphere 1 with its common room and one read-only programme point.
export const bootstrap = {
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
    deleteLabel: "Delete message",
    emptyReadOnly: "Nobody has written here yet.",
    emptySession: "You found the table first. Leave a note for the others.",
    emptySphere: "Quiet in here. Say hello before someone starts a rules debate.",
    errorArchived: "This conversation is archived.",
    errorForbidden: "You do not have permission to do that.",
    errorInvalid: "That message could not be sent.",
    errorMuted: "Your writing access is currently muted.",
    errorRateLimited: "Too many messages. Wait a moment and try again.",
    errorUnknown: "Something went wrong. Try again.",
    linkCopied: "Link copied.",
    loadEarlier: "Load earlier messages",
    loading: "Gathering conversations…",
    messageActions: "Message actions",
    messageLabel: "Message",
    messageListLabel: "Messages",
    messageTooLong: "Messages can be up to 1,000 characters.",
    moderatorDelete: "Delete as moderator",
    muteConfirm: "Mute this person indefinitely? They can still read.",
    muted: "Writing access limited.",
    mutedUntil: "Your writing access is muted until %(time)s.",
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
    restoreWriting: "Restore writing access",
    retry: "Try again",
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

export type Bootstrap = typeof bootstrap;
type Room = Bootstrap["rooms"][number];

export const sphereRoom: Room = bootstrap.rooms[0];
export const sessionRoom: Room = bootstrap.rooms[1];

// A pass the client can read its expiry from; the signature is never checked
// in the browser, so any third segment does.
export function passExpiring(exp: number): string {
  const encode = (value: object) =>
    Buffer.from(JSON.stringify(value)).toString("base64url").replaceAll("=", "");
  return `${encode({ alg: "RS256", typ: "JWT" })}.${encode({ exp, sub: "1" })}.signature`;
}

export type BootstrapReply = (Partial<Bootstrap> & { delayMs?: number }) | number;

// Serves /parley/bootstrap/ and the Worker's /auth/exchange. Each reply in
// the list answers one request, the last one repeating; a number is an
// error status, and delayMs holds a reply back. Returns how many bootstraps
// were asked for.
export async function routeBootstrap(
  page: Page,
  replies: BootstrapReply[] = [{}],
  exchangeStatus = 204,
): Promise<{ count: () => number }> {
  let served = 0;
  await page.route("**/parley/bootstrap/", async (route) => {
    const reply = replies[Math.min(served, replies.length - 1)];
    served += 1;
    if (typeof reply === "number") return route.fulfill({ status: reply });
    const { delayMs = 0, ...fields } = reply;
    if (delayMs > 0) await new Promise((resolve) => setTimeout(resolve, delayMs));
    return route.fulfill({ contentType: "application/json", json: { ...bootstrap, ...fields } });
  });
  await page.route(/\/auth\/exchange$/u, (route) =>
    route.fulfill({
      headers: {
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Origin": new URL(page.url() || "http://localhost:8000").origin,
      },
      status: exchangeStatus,
    }),
  );
  return { count: () => served };
}

export type Reply =
  | { code: string; ok: false }
  | { ok: true; value: unknown }
  | "reject"
  | "silent";
type Handler = (input: Record<string, unknown>, url: string) => Reply;

// Stands in for the chat Worker's Durable Object sockets. Every call
// succeeds unless a handler says otherwise: getActivity returns the given
// activity, loadBefore an empty room. "silent" never answers; "reject"
// fails the call itself, as a broken socket would.
export class FakeWorker {
  readonly calls: { input: Record<string, unknown>; method: string; url: string }[] = [];
  readonly sockets: WebSocketRoute[] = [];
  private readonly handlers = new Map<string, Handler>();

  constructor(private readonly activity: Record<string, { at: number; unread: boolean }> = {}) {}

  static async install(
    page: Page,
    activity: Record<string, { at: number; unread: boolean }> = {},
  ): Promise<FakeWorker> {
    const worker = new FakeWorker(activity);
    await page.routeWebSocket(/^wss?:\/\/[^/]+\/agents\//u, (socket) => worker.accept(socket));
    return worker;
  }

  on(method: string, handler: Handler): this {
    this.handlers.set(method, handler);
    return this;
  }

  // Server events go to every open socket whose URL matches.
  push(type: string, payload: unknown, path: RegExp = /./u): void {
    for (const socket of this.sockets) {
      if (path.test(socket.url())) socket.send(JSON.stringify({ payload, type, v: 1 }));
    }
  }

  async close(code: number, path: RegExp = /./u): Promise<void> {
    const closing = this.sockets.filter((socket) => path.test(socket.url()));
    this.sockets.splice(
      0,
      this.sockets.length,
      ...this.sockets.filter((s) => !closing.includes(s)),
    );
    await Promise.all(closing.map((socket) => socket.close({ code, reason: "test" })));
  }

  called(method: string): { input: Record<string, unknown>; method: string; url: string }[] {
    return this.calls.filter((call) => call.method === method);
  }

  private accept(socket: WebSocketRoute): void {
    this.sockets.push(socket);
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw)) as {
        args?: Record<string, unknown>[];
        id: string;
        method: string;
        type: string;
      };
      if (message.type !== "rpc") return;
      const input = message.args?.[0] ?? {};
      this.calls.push({ input, method: message.method, url: socket.url() });
      const reply = this.reply(message.method, input, socket.url());
      if (reply === "silent") return;
      socket.send(
        JSON.stringify(
          reply === "reject"
            ? { error: "boom", id: message.id, success: false, type: "rpc" }
            : { done: true, id: message.id, result: reply, success: true, type: "rpc" },
        ),
      );
    });
  }

  private reply(method: string, input: Record<string, unknown>, url: string): Reply {
    const handler = this.handlers.get(method);
    if (handler !== undefined) return handler(input, url);
    if (method === "getActivity") return { ok: true, value: this.activity };
    if (method === "loadBefore") return { ok: true, value: [] };
    return { ok: true, value: {} };
  }
}

export type Message = {
  authorAvatarUrl: string;
  authorId: string;
  authorName: string;
  body: string;
  createdAt: number;
  deletedAt: number | null;
  id: number;
  nonce: string;
};

export function message(fields: Partial<Message> & Pick<Message, "id">): Message {
  return {
    authorAvatarUrl: "",
    authorId: "2",
    authorName: "Kuba Nowak",
    body: `Message ${fields.id}`,
    createdAt: Date.now(),
    deletedAt: null,
    nonce: `n${fields.id}`,
    ...fields,
  };
}

export const launcherOf = (page: Page): Locator => page.getByRole("button", { name: "Open chat" });
export const panelOf = (page: Page): Locator => page.getByRole("dialog", { name: "Chat" });

// Opens the chat and the named room; resolves once the room's history is in.
export async function openRoom(page: Page, title: string, ready?: string): Promise<Locator> {
  await launcherOf(page).click();
  const panel = panelOf(page);
  await panel
    .getByRole("navigation", { name: "Conversations" })
    .getByRole("button", { name: new RegExp(title, "u") })
    .click();
  await expect(panel.getByRole("heading", { name: title })).toBeVisible();
  if (ready !== undefined) await expect(panel.getByText(ready).first()).toBeVisible();
  return panel;
}
