import { env, exports } from "cloudflare:workers";
import { importPKCS8, SignJWT } from "jose";

// Real sockets against the Worker under test, signed with the committed dev
// key the test config binds.
const testEnv = env as unknown as { TEST_SIGNING_KEY: string };

export const now = () => Math.floor(Date.now() / 1_000);

export async function sign(claims: Record<string, unknown>, audience: string, issuedAt = now()) {
  return new SignJWT(claims)
    .setProtectedHeader({ alg: "RS256", typ: "JWT" })
    .setAudience(audience)
    .setIssuer("ludamus")
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + 3_600)
    .sign(await importPKCS8(testEnv.TEST_SIGNING_KEY, "RS256"));
}

export function pass(
  sub: string,
  sphere: string,
  issuedAt = now(),
  extra: Record<string, unknown> = {},
) {
  return sign(
    {
      avatar: "",
      jti: crypto.randomUUID(),
      name: `Person ${sub}`,
      readOnlyAfter: 172_800,
      retainFor: 2_592_000,
      events: {},
      managed: [],
      sessions: { [`${sphere}:101`]: { endsAt: now() + 3_600, writable: true } },
      sub,
      ...extra,
    },
    "parley",
    issuedAt,
  );
}

export const manager = (sub: string, sphere: string, issuedAt = now()) =>
  pass(sub, sphere, issuedAt, { managed: [sphere], sessions: {} });

export type Socket = {
  call: <T = unknown>(method: string, input?: Record<string, unknown>) => Promise<T>;
  closed: Promise<number>;
  events: { payload: unknown; type: string }[];
  socket: WebSocket;
};

// Resolves once the room has admitted the socket (its first message) or
// closed it.
export async function open(path: string, token: string): Promise<Socket> {
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
  const events: Socket["events"] = [];
  const pending = new Map<string, (result: unknown) => void>();
  socket.addEventListener("message", (event) => {
    const frame = JSON.parse(String(event.data)) as {
      error?: string;
      id?: string;
      payload?: unknown;
      result?: unknown;
      success?: boolean;
      type: string;
    };
    if (frame.type === "rpc" && frame.id !== undefined) {
      pending.get(frame.id)?.(frame.success === false ? { error: frame.error } : frame.result);
    } else events.push({ payload: frame.payload, type: frame.type });
  });
  socket.accept();
  await Promise.race([admitted, closed]);
  const call = <T>(method: string, input: Record<string, unknown> = {}) =>
    new Promise<T>((resolve) => {
      const id = crypto.randomUUID();
      pending.set(id, (result) => resolve(result as T));
      socket.send(JSON.stringify({ args: [input], id, method, type: "rpc" }));
    });
  return { call, closed, events, socket };
}

export async function post(path: string, claims: Record<string, unknown>, audience: string) {
  return exports.default.fetch(`http://localhost:8787${path}`, {
    body: JSON.stringify({
      token: await sign(claims, audience, typeof claims.iat === "number" ? claims.iat : now()),
    }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
}

export const settle = (ms = 150) => new Promise((resolve) => setTimeout(resolve, ms));
