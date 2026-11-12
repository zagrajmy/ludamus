import { describe, expect, it } from "vitest";

import { MEMBERSHIP_AUDIENCE, verifyCapability, verifyMembership } from "../src/auth";
import { now, open, pass, post, settle, sign } from "./support";

type Result = { code?: string; ok: boolean; value?: unknown };

let next = 500;
// A fresh conversation per test, so no room's history leaks into another.
const conversationId = () => String((next += 1));

const sync = (
  conversation: string,
  members: { state: string; user: string; writable: boolean }[],
  kind = "group",
  issuedAt = now(),
) =>
  post(
    "/conversations",
    { conversation, iat: issuedAt, kind, members, needsDirect: kind !== "party" },
    MEMBERSHIP_AUDIENCE,
  );

const direct = (sub: string) => pass(sub, "3", now(), { direct: true });
const say = (socket: Awaited<ReturnType<typeof open>>, body: string) =>
  socket.call<Result>("sendMessage", { body, nonce: crypto.randomUUID() });

describe("a member list", () => {
  it("is its own kind of token", async () => {
    const env = {
      JWT_AUDIENCE: "parley",
      JWT_ISSUER: "ludamus",
      PARLEY_PUBLIC_KEY: (
        (await import("cloudflare:workers")).env as unknown as { PARLEY_PUBLIC_KEY: string }
      ).PARLEY_PUBLIC_KEY,
      ROOT_DOMAIN: "localhost:8000",
    };
    const members = [{ state: "active", user: "7", writable: true }];
    const membership = await sign(
      { conversation: "1", kind: "group", members },
      MEMBERSHIP_AUDIENCE,
    );

    await expect(verifyMembership(membership, env)).resolves.toMatchObject({ conversation: "1" });
    await expect(verifyCapability(membership, env)).rejects.toThrow();
    for (const bad of [
      { conversation: "x", kind: "group", members },
      { conversation: "1", kind: "sphere", members },
      { conversation: "1", kind: "group", members: [{ state: "left", user: "7", writable: true }] },
      { conversation: "1", kind: "group", members: "7" },
    ]) {
      await expect(verifyMembership(await sign(bad, MEMBERSHIP_AUDIENCE), env)).rejects.toThrow();
    }
    // A pass posted as a member list is refused at the door.
    const response = await post(
      "/conversations",
      { conversation: "1", kind: "group", members },
      "parley",
    );
    expect(response.status).toBe(401);
  });
});

describe("a conversation", () => {
  it("lets in only its members, and only people conversations are open to", async () => {
    const id = conversationId();
    expect((await sync(id, [{ state: "active", user: "7", writable: true }])).status).toBe(204);

    const member = await open(`parley-conversation-agent/${id}`, await direct("7"));
    const stranger = await open(`parley-conversation-agent/${id}`, await direct("8"));
    const minor = await open(`parley-conversation-agent/${id}`, await pass("7", "3"));

    expect(member.socket.readyState).toBe(WebSocket.OPEN);
    // Not on the list: the socket may redial, for the list may be on its way.
    await expect(stranger.closed).resolves.toBe(4404);
    await expect(minor.closed).resolves.not.toBe(4404);
    member.socket.close();
  }, 20_000);

  it("of a party lets its members in whether or not direct messages are open to them", async () => {
    const id = conversationId();
    await sync(id, [{ state: "active", user: "7", writable: true }], "party");

    const member = await open(`parley-conversation-agent/${id}`, await pass("7", "3"));
    const stranger = await open(`parley-conversation-agent/${id}`, await pass("8", "3"));

    expect(member.socket.readyState).toBe(WebSocket.OPEN);
    expect(await say(member, "Who brings the dice?")).toMatchObject({ ok: true });
    await expect(stranger.closed).resolves.toBe(4404);
    member.socket.close();
  }, 20_000);

  it("drops someone the newest list leaves out, and never takes an older list", async () => {
    const id = conversationId();
    const both = [
      { state: "active", user: "7", writable: true },
      { state: "active", user: "8", writable: true },
    ];
    await sync(id, both, "group", now());
    const leaving = await open(`parley-conversation-agent/${id}`, await direct("8"));
    expect(leaving.socket.readyState).toBe(WebSocket.OPEN);

    await sync(id, [both[0]!], "group", now() + 5);
    await expect(leaving.closed).resolves.toBe(4404);
    // A delivery that crossed with the newer one changes nothing.
    await sync(id, both, "group", now());
    const back = await open(`parley-conversation-agent/${id}`, await direct("8"));
    await expect(back.closed).resolves.toBe(4404);
  }, 20_000);

  it("takes one message on a request until it is accepted, and none from a reader", async () => {
    const id = conversationId();
    await sync(
      id,
      [
        { state: "active", user: "7", writable: true },
        { state: "request", user: "8", writable: false },
      ],
      "direct",
    );
    const sender = await open(`parley-conversation-agent/${id}`, await direct("7"));
    const recipient = await open(`parley-conversation-agent/${id}`, await direct("8"));

    expect(await say(sender, "Hi, fancy a game?")).toMatchObject({ ok: true });
    expect(await say(sender, "Hello?")).toEqual({ code: "pending", ok: false });
    expect(await say(recipient, "Who is this?")).toEqual({ code: "forbidden", ok: false });
    // Nobody moderates a conversation.
    expect(await sender.call<Result>("deleteMessage", { messageId: 1 })).toEqual({
      code: "forbidden",
      ok: false,
    });

    await sync(
      id,
      [
        { state: "active", user: "7", writable: true },
        { state: "active", user: "8", writable: true },
      ],
      "direct",
      now() + 5,
    );
    expect(await say(sender, "Thanks for accepting")).toMatchObject({ ok: true });
    expect(await say(recipient, "Sure")).toMatchObject({ ok: true });
    sender.socket.close();
    recipient.socket.close();
  }, 20_000);
});

describe("an inbox", () => {
  it("is its owner's alone, whatever their age", async () => {
    const someone = await open("parley-inbox-agent/7", await direct("8"));
    const minor = await open("parley-inbox-agent/7", await pass("7", "3"));

    await expect(someone.closed).resolves.toBe(4403);
    expect(minor.socket.readyState).toBe(WebSocket.OPEN);
    minor.socket.close();
  });

  it("hears of news in every conversation its owner is in, until read", async () => {
    const id = conversationId();
    await sync(id, [
      { state: "active", user: "17", writable: true },
      { state: "active", user: "18", writable: true },
    ]);
    const author = await open(`parley-conversation-agent/${id}`, await direct("17"));
    const inbox = await open("parley-inbox-agent/18", await direct("18"));
    const ownInbox = await open("parley-inbox-agent/17", await direct("17"));

    await say(author, "News for you");
    await settle(300);
    expect(inbox.events.some((event) => event.type === "room.activity")).toBe(true);
    const unread = await inbox.call<{ value: Record<string, { unread: boolean }> }>("getActivity");
    expect(unread.value[`conversation:${id}`]?.unread).toBe(true);
    // One's own message is read already.
    const own = await ownInbox.call<{ value: Record<string, { unread: boolean }> }>("getActivity");
    expect(own.value[`conversation:${id}`]?.unread).toBe(false);

    expect(await inbox.call<Result>("markRead", { roomId: `conversation:${id}` })).toEqual({
      code: "invalid",
      ok: false,
    });
    await inbox.call("markRead", { messageId: 1, roomId: `conversation:${id}` });
    const read = await inbox.call<{ value: Record<string, { unread: boolean }> }>("getActivity");
    expect(read.value[`conversation:${id}`]?.unread).toBe(false);
    for (const socket of [author, inbox, ownInbox]) socket.socket.close();
  }, 20_000);
});
