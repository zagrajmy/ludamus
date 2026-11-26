import { describe, expect, it } from "vitest";

import type { Roll } from "../src/dice";

import { rollDie } from "../src/dice";
import { call, pass, roll, seat, until } from "./support";

describe("rolling", () => {
  it("shows every seat the same dice and keeps them in the log", async () => {
    const ania = await seat("dice", await pass({ board: "dice" }));
    const guest = await seat("dice", await pass({ board: "dice", name: "Guest", sub: "g:1" }));

    const response = await roll("dice", await pass({ board: "dice" }), [6, 6, 20]);
    const rolled: Roll = await response.json();

    expect(rolled.dice.map((die) => die.sides)).toEqual([6, 6, 20]);
    expect(rolled.name).toBe("Ania");
    for (const person of [ania, guest]) {
      await until(() => person.received.some((message) => message.type === "custom"));
      expect(person.received.find((message) => message.type === "custom")?.data).toEqual({
        roll: rolled,
        type: "roll",
      });
    }
    const log = await call("/rooms/dice/rolls", await pass({ board: "dice", sub: "g:1" }));
    expect(await log.json()).toEqual([rolled]);
  });

  it.each([
    ["no dice", []],
    ["too many dice", Array.from({ length: 21 }, () => 6)],
    ["a die that does not exist", [7]],
    ["something that is not a pool", "2d6"],
  ])("refuses %s", async (_label, dice) => {
    const response = await roll("bad", await pass({ board: "bad" }), dice);
    expect(response.status).toBe(400);
    const log = await call("/rooms/bad/rolls", await pass({ board: "bad" }));
    expect(await log.json()).toEqual([]);
  });

  it("refuses a second roll from the same person in the same instant", async () => {
    const token = await pass({ board: "fast" });
    expect((await roll("fast", token, [6])).status).toBe(200);
    expect((await roll("fast", token, [6])).status).toBe(429);
  });

  it("keeps only the latest fifty rolls", async () => {
    for (let person = 0; person < 52; person++) {
      await roll("long", await pass({ board: "long", sub: `u:${person}` }), [4]);
    }
    const log = await call("/rooms/long/rolls", await pass({ board: "long" }));
    const rolls: Roll[] = await log.json();
    expect(rolls.map((entry) => entry.sub)).toEqual(
      Array.from({ length: 50 }, (_, index) => `u:${index + 2}`),
    );
  });
});

describe("a die", () => {
  it.each([4, 6, 8, 10, 12, 20, 100])("with %i sides shows each face and no other", (sides) => {
    const faces = new Set(Array.from({ length: sides * 200 }, () => rollDie(sides)));
    expect([...faces].sort((a, b) => a - b)).toEqual(
      Array.from({ length: sides }, (_, index) => index + 1),
    );
  });
});
