import { describe, expect, it } from "vitest";

import { REVOCATION_AUDIENCE } from "../src/auth";
import { manager, now, open, pass, post } from "./support";

const revoke = (claims: Record<string, unknown>, audience = REVOCATION_AUDIENCE) =>
  post("/revoke", claims, audience);

describe("revocation", () => {
  it("closes the person's sockets in every room of the sphere", async () => {
    const issued = now() - 10;
    const member = await pass("7", "3", issued, {
      events: { "3:9": { endsAt: now() + 3_600, writable: true } },
    });
    const sphere = await open("parley-sphere-agent/3", member);
    const session = await open("parley-session-agent/3:101", member);
    const event = await open("parley-event-agent/3:9", member);
    const organizer = await open("parley-organizers-agent/3", await manager("6", "3", issued));
    const bystander = await open("parley-sphere-agent/3", await pass("8", "3", issued));

    const response = await revoke({ revokedBefore: now(), sphere: "3", sub: "7" });

    expect(response.status).toBe(204);
    await expect(sphere.closed).resolves.toBe(4403);
    await expect(session.closed).resolves.toBe(4403);
    await expect(event.closed).resolves.toBe(4403);
    await revoke({ revokedBefore: now(), sphere: "3", sub: "*" });
    await expect(organizer.closed).resolves.toBe(4403);
    await expect(bystander.closed).resolves.toBe(4403);
  }, 20_000);

  it("leaves everyone else's sockets open", async () => {
    const issued = now() - 10;
    const bystander = await open("parley-sphere-agent/4", await pass("8", "4", issued));

    await revoke({ revokedBefore: now(), sphere: "4", sub: "7" });

    const stillOpen = await Promise.race([
      bystander.closed,
      new Promise((resolve) => setTimeout(() => resolve("open"), 200)),
    ]);
    expect(stillOpen).toBe("open");
    bystander.socket.close();
  }, 20_000);

  it("refuses the old pass and admits the one fetched after the cutoff", async () => {
    const cutoff = now();
    await revoke({ revokedBefore: cutoff, sphere: "5", sub: "7" });

    const stale = await open("parley-session-agent/5:101", await pass("7", "5", cutoff - 10));
    await expect(stale.closed).resolves.toBe(4403);
    const fresh = await open("parley-session-agent/5:101", await pass("7", "5", cutoff));
    expect(fresh.socket.readyState).toBe(WebSocket.OPEN);
    fresh.socket.close();
  }, 20_000);

  it("rejects a pass posted as a revocation", async () => {
    const response = await revoke({ revokedBefore: now(), sphere: "3", sub: "7" }, "parley");

    expect(response.status).toBe(401);
  });
});
