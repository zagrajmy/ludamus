import { getAgentByName } from "agents";
import { runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import type { Env } from "../src/room-agent";
import type { ParleySphereAgent } from "../src/sphere-agent";

import { REVOCATION_AUDIENCE } from "../src/auth";
import { eventGrant, now, open, pass, post, settle } from "./support";

type Activity = { value: Record<string, { at: number; unread: boolean }> };

const workerEnv = env as unknown as Env;
const feedOf = (sphere: string) =>
  getAgentByName<Env, ParleySphereAgent>(workerEnv.ParleySphereAgent, sphere);

describe("a sphere's feed", () => {
  it("hears of news in the sphere's rooms, unread until read, for those who may see them", async () => {
    const member = await pass("7", "41", now(), {
      events: { "41:5": eventGrant({ "101": true }, { chat: true }) },
    });
    const room = await open("parley-event-agent/41:5", member);
    const feed = await open("parley-sphere-agent/41", member);
    const organizer = await open(
      "parley-sphere-agent/41",
      await pass("6", "41", now(), {
        events: { "41:5": eventGrant({}, { chat: true }) },
        managed: { "41": { organizers: true } },
      }),
    );
    const outsider = await open("parley-sphere-agent/41", await pass("8", "41"));

    await room.call("sendMessage", { body: "Who brings snacks?", nonce: crypto.randomUUID() });
    await expect.poll(() => feed.events.some((event) => event.type === "room.activity")).toBe(true);

    const seen = await feed.call<Activity>("getActivity");
    expect(seen.value["event:41:5"]?.unread).toBe(true);
    expect((await organizer.call<Activity>("getActivity")).value["event:41:5"]?.unread).toBe(true);
    expect((await outsider.call<Activity>("getActivity")).value).toEqual({});

    expect(await feed.call("markRead", { roomId: "event:41:5" })).toEqual({
      code: "invalid",
      ok: false,
    });
    expect(await outsider.call("markRead", { messageId: 1, roomId: "event:41:5" })).toEqual({
      code: "invalid",
      ok: false,
    });
    expect(await feed.call("markRead", { messageId: 1, roomId: "event:41:5" })).toEqual({
      ok: true,
      value: {},
    });
    expect(feed.events.some((event) => event.type === "unread.changed")).toBe(true);
    expect(organizer.events.some((event) => event.type === "unread.changed")).toBe(false);
    expect((await feed.call<Activity>("getActivity")).value["event:41:5"]?.unread).toBe(false);
    for (const socket of [room, feed, organizer, outsider]) socket.socket.close();
  }, 20_000);

  it("turns away a pass revoked before it was issued, and takes no forged news", async () => {
    await post("/revoke", { revokedBefore: now(), sphere: "42", sub: "7" }, REVOCATION_AUDIENCE);

    const revoked = await open("parley-sphere-agent/42", await pass("7", "42", now() - 10));
    await expect(revoked.closed).resolves.toBe(4403);

    const stub = await feedOf("42");
    await runInDurableObject(stub, (instance) => {
      const feed = instance as unknown as ParleySphereAgent;
      expect(() => feed.recordActivity({ latestMessageId: 1, roomId: "event:43:1" })).toThrow();
      expect(() => feed.recordActivity({ latestMessageId: 1, roomId: "conversation:1" })).toThrow();
      expect(feed.admit({ exp: now() + 60, iat: now(), roomId: "session:43:1", sub: "9" })).toBe(
        false,
      );
    });
  }, 20_000);

  it("lets go of the messages of the room a sphere used to hold", async () => {
    const stub = await feedOf("45");
    await runInDurableObject(stub, async (instance) => {
      const feed = instance as unknown as ParleySphereAgent;
      void feed.sql`CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT)`;
      void feed.sql`INSERT INTO messages (body) VALUES (${"Who brings snacks?"})`;

      await feed.onStart();

      const tables = feed.sql<{
        name: string;
      }>`SELECT name FROM sqlite_master WHERE type = ${"table"} AND name = ${"messages"}`;
      expect(tables).toEqual([]);
    });
  });

  it("closes a socket whose pass has run out", async () => {
    const shortLived = await pass("7", "44", now() - 3_598);
    const feed = await open("parley-sphere-agent/44", shortLived);

    await settle(2_500);
    void feed.call("getActivity");

    await expect(feed.closed).resolves.toBe(4401);
  }, 20_000);
});
