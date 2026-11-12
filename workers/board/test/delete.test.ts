import { describe, expect, it } from "vitest";

import type { Roll } from "../src/dice";

import { call, deletion, destroy, now, open, pass, roll, seat, until } from "./support";

const extraPage = {
  id: "page:extra",
  index: "a2",
  meta: {},
  name: "Extra",
  typeName: "page",
};

async function drawOnto(board: string) {
  const person = await seat(board, await pass({ board }));
  person.send({ clientClock: 1, diff: { [extraPage.id]: ["put", extraPage] }, type: "push" });
  await until(() =>
    person.received.some(
      (message) =>
        message.type === "data" &&
        (message.data as { type: string }[]).some((part) => part.type === "push_result"),
    ),
  );
  return person;
}

async function documentSeenBy(board: string) {
  const person = await seat(board, await pass({ board }));
  const connect = person.received.find((message) => message.type === "connect")!;
  return Object.keys((connect as unknown as { diff: object }).diff);
}

describe("deleting a board", () => {
  it("clears the document and the roll log and puts everyone out", async () => {
    const person = await drawOnto("bye");
    await roll("bye", await pass({ board: "bye" }), [6]);
    expect(await documentSeenBy("bye")).toContain(extraPage.id);

    const response = await destroy("bye", await deletion({ board: "bye" }));

    expect(response.status).toBe(204);
    expect(await person.closure).toEqual({ code: 4099, reason: "NOT_FOUND" });
    const log = await call("/rooms/bye/rolls", await pass({ board: "bye" }));
    expect(await log.json()).toEqual([]);
    expect(await documentSeenBy("bye")).not.toContain(extraPage.id);
  });

  it("lets the board start again at a lower link version than it had", async () => {
    await roll("again", await pass({ board: "again", link: 3 }), [6]);
    await destroy("again", await deletion({ board: "again" }));

    const rolled = await roll("again", await pass({ board: "again", link: 0 }), [20]);

    expect(rolled.status).toBe(200);
    const log = await call("/rooms/again/rolls", await pass({ board: "again" }));
    expect(((await log.json()) as Roll[]).map((entry) => entry.dice.length)).toEqual([1]);
    expect((await open("again", await pass({ board: "again" }))).response.status).toBe(101);
  });

  it("is the same the second time", async () => {
    const token = await deletion({ board: "twice" });
    expect((await destroy("twice", token)).status).toBe(204);
    expect((await destroy("twice", token)).status).toBe(204);
  });

  it.each([
    ["a pass", () => pass({ board: "keep" })],
    ["a token for another board", () => deletion({ board: "other" })],
    ["a token that expired", () => deletion({ board: "keep", issuedAt: now() - 3_600 })],
    ["a token for Parley", () => deletion({ audience: "parley", board: "keep" })],
    ["no token", async () => null],
  ])("is refused with %s and changes nothing", async (_label, token) => {
    const person = await drawOnto("keep");

    const response = await destroy("keep", await token());

    expect(response.status).toBe(403);
    expect(person.isClosed()).toBe(false);
    expect(await documentSeenBy("keep")).toContain(extraPage.id);
  });

  it("gives a deletion token no say in the board itself", async () => {
    const token = await deletion({ board: "b1" });

    expect((await open("b1", token)).response.status).toBe(403);
    expect((await roll("b1", token, [6])).status).toBe(403);
    expect((await call("/rooms/b1/rolls", token)).status).toBe(403);
  });
});
