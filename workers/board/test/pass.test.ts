import { TLSyncErrorCloseEventCode, TLSyncErrorCloseEventReason } from "@tldraw/sync-core";
import { describe, expect, it } from "vitest";

import { MAX_NAME_LENGTH, MAX_PEOPLE } from "../src/limits";
import { call, now, open, pass, seat, until } from "./support";

describe("a pass", () => {
  it("opens the board it names", async () => {
    const { response } = await open("b1", await pass());
    expect(response.status).toBe(101);
  });

  it("counts a name in characters, as Django does", async () => {
    const { response } = await open("b1", await pass({ name: "🎲".repeat(MAX_NAME_LENGTH) }));
    expect(response.status).toBe(101);
  });

  it.each([
    ["with a name one character too long", () => pass({ name: "🎲".repeat(MAX_NAME_LENGTH + 1) })],
    ["for another board", () => pass({ board: "b2" })],
    ["for Parley", () => pass({ audience: "parley" })],
    ["that expired", () => pass({ issuedAt: now() - 3_600 })],
    ["that is not a token", async () => "nonsense"],
  ])("%s is refused", async (_label, token) => {
    const { response } = await open("b1", await token());
    expect(response.status).toBe(403);
  });

  it("is required", async () => {
    expect((await call("/rooms/b1/rolls", null)).status).toBe(403);
  });
});

describe("resetting the link", () => {
  it("puts out everyone who came in by the old link and keeps them out", async () => {
    const guest = await seat("reset", await pass({ board: "reset", sub: "g:1" }));
    const owner = await seat("reset", await pass({ board: "reset", link: 1, owner: true }));

    await until(guest.isClosed);
    expect(owner.isClosed()).toBe(false);
    expect((await call("/rooms/reset/rolls", await pass({ board: "reset" }))).status).toBe(403);
  });
});

describe("a refusal on the socket", () => {
  it("tells a person from a reset link why, in a way the browser can read", async () => {
    await seat("gone", await pass({ board: "gone", link: 1, owner: true }));
    const { closure, response } = await open("gone", await pass({ board: "gone", sub: "g:1" }));

    expect(response.status).toBe(101);
    expect(await closure).toEqual({
      code: TLSyncErrorCloseEventCode,
      reason: TLSyncErrorCloseEventReason.FORBIDDEN,
    });
  });

  it("tells the newcomer the board is full and leaves the seats alone", async () => {
    const seated = [];
    for (let person = 0; person < MAX_PEOPLE; person++) {
      seated.push(await seat("full", await pass({ board: "full", sub: `u:${person}` })));
    }

    const late = await open("full", await pass({ board: "full", sub: "u:late" }));

    expect(late.response.status).toBe(101);
    expect(await late.closure).toEqual({
      code: TLSyncErrorCloseEventCode,
      reason: TLSyncErrorCloseEventReason.ROOM_FULL,
    });
    expect(seated.some((person) => person.isClosed())).toBe(false);
    const free = seated[0]!;
    free.send({ type: "ping" });
    await until(() => free.received.some((message) => message.type === "pong"));
  });

  it("lets a seated person back into a full board, and nobody else in their seat", async () => {
    const sessionId = crypto.randomUUID();
    await seat("rejoin", await pass({ board: "rejoin", sub: "u:0" }), sessionId);
    for (let person = 1; person < MAX_PEOPLE; person++) {
      await seat("rejoin", await pass({ board: "rejoin", sub: `u:${person}` }));
    }

    const back = await seat("rejoin", await pass({ board: "rejoin", sub: "u:0" }), sessionId);
    const impostor = await open(
      "rejoin",
      await pass({ board: "rejoin", sub: "u:late" }),
      sessionId,
    );

    expect(back.isClosed()).toBe(false);
    expect(await impostor.closure).toEqual({
      code: TLSyncErrorCloseEventCode,
      reason: TLSyncErrorCloseEventReason.ROOM_FULL,
    });
  });
});
