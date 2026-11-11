import { describe, expect, it } from "vitest";

import type { Message, ReactionChange } from "../src/protocol";

import { MEMBERSHIP_AUDIENCE } from "../src/auth";
import { now, open, pass, post, settle, type Socket } from "./support";

type Result<T = unknown> = { code?: string; ok: boolean; value?: T };

let next = 60;
// A fresh sphere per test, so no room's history leaks into another.
const sphereId = () => String((next += 1));

const say = async (socket: Socket, body: string) =>
  (
    await socket.call<Result<Message>>("sendMessage", {
      body,
      nonce: crypto.randomUUID(),
    })
  ).value!;
const react = (socket: Socket, messageId: unknown, emoji: unknown) =>
  socket.call<Result<ReactionChange>>("toggleReaction", { emoji, messageId });
const history = async (socket: Socket) =>
  (await socket.call<Result<Message[]>>("loadBefore", {})).value!;

describe("a reaction", () => {
  it("toggles once per person and emoji, and every open socket hears of it", async () => {
    const sphere = sphereId();
    const ada = await open(`parley-sphere-agent/${sphere}`, await pass("7", sphere));
    const bea = await open(`parley-sphere-agent/${sphere}`, await pass("8", sphere));
    const sent = await say(ada, "Who brings the dice?");
    expect(sent.reactions).toEqual({});

    expect(await react(bea, sent.id, "🎲")).toEqual({
      ok: true,
      value: { messageId: sent.id, reactions: { "🎲": ["8"] } },
    });
    await react(ada, sent.id, "❤️");
    // Shown in the palette's order, whatever order they came in.
    expect((await react(ada, sent.id, "🎲")).value!.reactions).toEqual({
      "❤️": ["7"],
      "🎲": ["8", "7"],
    });
    expect(Object.keys((await history(bea))[0]!.reactions)).toEqual(["❤️", "🎲"]);

    // The same call again takes it back.
    expect((await react(bea, sent.id, "🎲")).value!.reactions).toEqual({
      "❤️": ["7"],
      "🎲": ["7"],
    });
    await settle();
    expect(ada.events.filter((event) => event.type === "reaction.changed").at(-1)).toEqual({
      payload: { messageId: sent.id, reactions: { "❤️": ["7"], "🎲": ["7"] } },
      type: "reaction.changed",
    });
    expect((await history(bea))[0]!.reactions).toEqual({ "❤️": ["7"], "🎲": ["7"] });
    ada.socket.close();
    bea.socket.close();
  }, 20_000);

  it("takes only the palette, and only on a message still standing", async () => {
    const sphere = sphereId();
    const ada = await open(`parley-sphere-agent/${sphere}`, await pass("7", sphere));
    const kept = await say(ada, "Keep me");
    const gone = await say(ada, "Delete me");
    await react(ada, gone.id, "👍");

    for (const emoji of ["🙂", "👍🏻", "❤", "", 1, undefined]) {
      expect(await react(ada, kept.id, emoji)).toEqual({ code: "invalid", ok: false });
    }
    for (const messageId of [0, "1", undefined, gone.id + 1]) {
      expect(await react(ada, messageId, "👍")).toEqual({ code: "invalid", ok: false });
    }

    await ada.call("deleteOwnMessage", { messageId: gone.id });
    expect(await react(ada, gone.id, "😢")).toEqual({ code: "invalid", ok: false });
    // A deleted message's reactions go with its words.
    expect((await history(ada)).map((message) => message.reactions)).toEqual([{}, {}]);
    ada.socket.close();
  }, 20_000);

  it("is limited to ten in ten seconds", async () => {
    const sphere = sphereId();
    const ada = await open(`parley-sphere-agent/${sphere}`, await pass("7", sphere));
    const sent = await say(ada, "Click me");
    for (let count = 0; count < 10; count += 1) {
      expect(await react(ada, sent.id, "😂")).toMatchObject({ ok: true });
    }
    expect(await react(ada, sent.id, "😂")).toEqual({ code: "rate_limited", ok: false });
    ada.socket.close();
  }, 20_000);
});

describe("who may react", () => {
  it("is nobody muted, and nobody reading a room they cannot write in", async () => {
    const sphere = sphereId();
    const manager = await open(
      `parley-sphere-agent/${sphere}`,
      await pass("1", sphere, now(), { role: "manager", sessions: {} }),
    );
    const muted = await open(`parley-sphere-agent/${sphere}`, await pass("8", sphere));
    const sent = await say(manager, "House rules");
    await manager.call("muteUser", { durationMs: 3_600_000, userId: "8" });
    expect(await react(muted, sent.id, "👍")).toEqual({ code: "muted", ok: false });

    const reader = await open(
      `parley-session-agent/${sphere}:101`,
      await pass("8", sphere, now(), {
        sessions: { "101": { endsAt: now() + 3_600, writable: false } },
      }),
    );
    expect(await react(reader, 1, "👍")).toEqual({ code: "forbidden", ok: false });
    const late = await open(
      `parley-session-agent/${sphere}:102`,
      await pass("9", sphere, now(), {
        sessions: { "102": { endsAt: now() - 3 * 86_400, writable: true } },
      }),
    );
    expect(await react(late, 1, "👍")).toEqual({ code: "archived", ok: false });
    for (const socket of [manager, muted, reader, late]) socket.socket.close();
  }, 20_000);

  it("is nobody in a direct request until it is accepted", async () => {
    const conversation = "800";
    await post(
      "/conversations",
      {
        conversation,
        iat: now(),
        kind: "direct",
        members: [
          { state: "active", user: "7", writable: true },
          { state: "request", user: "8", writable: false },
        ],
      },
      MEMBERSHIP_AUDIENCE,
    );
    const direct = (sub: string) => pass(sub, "3", now(), { direct: true });
    const sender = await open(`parley-conversation-agent/${conversation}`, await direct("7"));
    const recipient = await open(`parley-conversation-agent/${conversation}`, await direct("8"));
    const sent = await say(sender, "Fancy a game?");

    expect(await react(recipient, sent.id, "👍")).toEqual({ code: "forbidden", ok: false });
    // The sender's one message is spent; until an answer, nothing more.
    expect(await react(sender, sent.id, "👍")).toEqual({ code: "pending", ok: false });
    sender.socket.close();
    recipient.socket.close();
  }, 20_000);
});
