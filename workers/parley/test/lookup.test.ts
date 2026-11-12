import { describe, expect, it } from "vitest";

import { LOOKUP_AUDIENCE, MEMBERSHIP_AUDIENCE } from "../src/auth";
import { now, open, pass, post } from "./support";

type Result = { ok: boolean; value?: { id: number } };

const lookup = (room: string, message: unknown, audience = LOOKUP_AUDIENCE) =>
  post("/messages", { message, room }, audience);

describe("a reported message", () => {
  it("is read back whole by Django, words and all, even once deleted", async () => {
    const conversation = "900";
    await post(
      "/conversations",
      {
        conversation,
        iat: now(),
        kind: "group",
        members: [{ state: "active", user: "7", writable: true }],
      },
      MEMBERSHIP_AUDIENCE,
    );
    const author = await open(
      `parley-conversation-agent/${conversation}`,
      await pass("7", "3", now(), { direct: true }),
    );
    const sent = await author.call<Result>("sendMessage", {
      body: "Something to report",
      nonce: crypto.randomUUID(),
    });
    await author.call("deleteOwnMessage", { messageId: sent.value!.id });

    const response = await lookup(`conversation:${conversation}`, sent.value!.id);

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      authorId: "7",
      authorName: "Person 7",
      body: "Something to report",
      deletedAt: expect.any(Number),
    });
    author.socket.close();
  }, 20_000);

  it("is found in a sphere's room too, and missing where there is none", async () => {
    const member = await open("parley-sphere-agent/31", await pass("7", "31"));
    const sent = await member.call<Result>("sendMessage", {
      body: "In the common room",
      nonce: crypto.randomUUID(),
    });

    expect(await (await lookup("sphere:31", sent.value!.id)).json()).toMatchObject({
      body: "In the common room",
    });
    expect((await lookup("sphere:31", sent.value!.id + 1)).status).toBe(404);
    expect((await lookup("party:31", 1)).status).toBe(404);
    member.socket.close();
  }, 20_000);

  it("is told only to a lookup Django signed for it", async () => {
    expect((await lookup("sphere:31", 1, "parley")).status).toBe(401);
    expect((await lookup("sphere:31", 0)).status).toBe(401);
    expect((await lookup("sphere:31", "1")).status).toBe(401);
    const response = await post("/messages", { message: 1 }, LOOKUP_AUDIENCE);
    expect(response.status).toBe(401);
    const unsigned = await (
      await import("cloudflare:workers")
    ).exports.default.fetch("http://localhost:8787/messages", { body: "{}", method: "POST" });
    expect(unsigned.status).toBe(400);
  });
});
