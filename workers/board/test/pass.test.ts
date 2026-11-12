import { describe, expect, it } from "vitest";

import { call, now, open, pass, seat, until } from "./support";

describe("a pass", () => {
  it("opens the board it names", async () => {
    const { response } = await open("b1", await pass());
    expect(response.status).toBe(101);
  });

  it.each([
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
    const again = await open("reset", await pass({ board: "reset", sub: "g:1" }));
    expect(again.response.status).toBe(403);
    expect((await call("/rooms/reset/rolls", await pass({ board: "reset" }))).status).toBe(403);
  });
});
