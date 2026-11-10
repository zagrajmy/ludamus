import { env, exports } from "cloudflare:workers";
import { importPKCS8, SignJWT } from "jose";
import { describe, expect, it } from "vitest";

import { REVOCATION_AUDIENCE } from "../src/auth";

const testEnv = env as unknown as { TEST_SIGNING_KEY: string };
const now = () => Math.floor(Date.now() / 1_000);

async function sign(claims: Record<string, unknown>, audience: string, issuedAt: number) {
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "RS256", typ: "JWT" })
    .setAudience(audience)
    .setIssuer("ludamus")
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + 3_600)
    .sign(await importPKCS8(testEnv.TEST_SIGNING_KEY, "RS256"));
}

function pass(sub: string, sphere: string, issuedAt: number) {
  return sign(
    {
      avatar: "",
      jti: crypto.randomUUID(),
      name: "Ada",
      readOnlyAfter: 172_800,
      retainFor: 2_592_000,
      role: "member",
      sessions: { "101": { endsAt: now() + 3_600, writable: true } },
      sphere,
      sub,
    },
    "parley",
    issuedAt,
  );
}

type Socket = { closed: Promise<number>; socket: WebSocket };

// Resolves once the room has admitted the socket: admission is what sends
// the first presence count.
async function open(path: string, token: string): Promise<Socket> {
  const response = await exports.default.fetch(`http://localhost:8787/agents/${path}`, {
    headers: {
      Cookie: `parley_capability=${token}`,
      Origin: "http://localhost:8000",
      Upgrade: "websocket",
    },
  });
  const socket = response.webSocket;
  if (socket === null) throw new Error(`No socket for ${path}`);
  const closed = new Promise<number>((resolve) =>
    socket.addEventListener("close", (event) => resolve(event.code)),
  );
  const admitted = new Promise<void>((resolve) =>
    socket.addEventListener("message", () => resolve(), { once: true }),
  );
  socket.accept();
  await Promise.race([admitted, closed]);
  return { closed, socket };
}

async function revoke(claims: Record<string, unknown>, audience = REVOCATION_AUDIENCE) {
  return exports.default.fetch("http://localhost:8787/revoke", {
    body: JSON.stringify({ token: await sign(claims, audience, now()) }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
}

describe("revocation", () => {
  it("closes the person's sockets in the sphere and its session rooms", async () => {
    const sphere = await open("parley-sphere-agent/3", await pass("7", "3", now() - 10));
    const session = await open("parley-session-agent/3:101", await pass("7", "3", now() - 10));
    const bystander = await open("parley-sphere-agent/3", await pass("8", "3", now() - 10));

    const response = await revoke({ revokedBefore: now(), sphere: "3", sub: "7" });

    expect(response.status).toBe(204);
    await expect(sphere.closed).resolves.toBe(4403);
    await expect(session.closed).resolves.toBe(4403);
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
