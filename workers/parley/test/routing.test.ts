import { exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import { open, openWithCookie, pass } from "./support";

describe("agent routes", () => {
  it.each([
    "parley-sphere-agent",
    "parley-session-agent",
    "parley-event-agent",
    "parley-organizers-agent",
  ])(
    "accepts a socket on /agents/%s/",
    async (namespace) => {
      const response = await exports.default.fetch(`http://localhost:8787/agents/${namespace}/1`, {
        headers: { Origin: "http://localhost:8000", Upgrade: "websocket" },
      });

      expect(response.status).toBe(101);
      response.webSocket?.accept();
      response.webSocket?.close();
    },
    // NOTE: the first socket boots the Durable Object in workerd, which on a
    // cold run outlasts Vitest's default 5 s.
    20_000,
  );
});

// Closed as a server error, a socket is redialled with the same pass, and
// each try wakes its Durable Object; a pass close sends it for a new one.
describe("a socket its pass does not let in", () => {
  it.each([
    ["no pass", "theme=dark"],
    ["a pass that does not verify", "parley_capability=not.a.pass"],
  ])(
    "is sent for a new pass when it brings %s",
    async (_, cookie) => {
      for (const path of [
        "parley-sphere-agent/46",
        "parley-inbox-agent/46",
        "parley-event-agent/46:1",
      ]) {
        const socket = await openWithCookie(path, cookie);

        await expect(socket.closed).resolves.toBe(4401);
      }
    },
    20_000,
  );

  it("is sent for a new pass when the pass does not reach the room", async () => {
    const elsewhere = await pass("7", "41");
    for (const path of ["parley-sphere-agent/47", "parley-event-agent/47:1"]) {
      const socket = await open(path, elsewhere);

      await expect(socket.closed).resolves.toBe(4403);
    }
  }, 20_000);
});
