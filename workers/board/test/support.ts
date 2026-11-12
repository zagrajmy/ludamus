import { createTLSchema } from "@tldraw/tlschema";
import { env, exports } from "cloudflare:workers";
import { importPKCS8, SignJWT } from "jose";

// NOTE: sync-core keeps its protocol version internal. A room answers a
// wrong one with an incompatibility error, which fails every seat() here.
const TLSYNC_PROTOCOL_VERSION = 8;

const testEnv = env as unknown as { TEST_SIGNING_KEY: string };

export const now = () => Math.floor(Date.now() / 1_000);

type Claims = {
  audience?: string;
  board?: string;
  issuedAt?: number;
  link?: number;
  name?: string;
  owner?: boolean;
  sub?: string;
};

export async function pass({
  audience = "board",
  board = "b1",
  issuedAt = now(),
  link = 0,
  name = "Ania",
  owner = false,
  sub = "u:1",
}: Claims = {}) {
  return new SignJWT({ board, link, name, owner, sub })
    .setProtectedHeader({ alg: "RS256", typ: "JWT" })
    .setAudience(audience)
    .setIssuer("ludamus")
    .setIssuedAt(issuedAt)
    .setExpirationTime(issuedAt + 300)
    .sign(await importPKCS8(testEnv.TEST_SIGNING_KEY, "RS256"));
}

const worker = (exports as unknown as { default: { fetch: typeof fetch } }).default;

export function call(path: string, token: string | null, init: RequestInit = {}) {
  return worker.fetch(
    new Request(`https://board.test${path}`, {
      ...init,
      headers: token === null ? {} : { Authorization: `Bearer ${token}` },
    }),
  );
}

export function roll(board: string, token: string, dice: unknown) {
  return call(`/rooms/${board}/roll`, token, { body: JSON.stringify({ dice }), method: "POST" });
}

export async function open(board: string, token: string, sessionId = crypto.randomUUID()) {
  const response = await worker.fetch(
    new Request(`https://board.test/rooms/${board}/connect?sessionId=${sessionId}&pass=${token}`, {
      headers: { Upgrade: "websocket" },
    }),
  );
  const socket = (response as unknown as { webSocket: WebSocket | null }).webSocket;
  socket?.accept();
  return { response, socket };
}

type SyncMessage = { data?: unknown; type: string };

// Speaks just enough of the tldraw sync protocol to become a connected
// session, then collects what the room sends.
export async function seat(board: string, token: string) {
  const { response, socket } = await open(board, token);
  if (socket === null) throw new Error(`refused: ${response.status}`);
  const received: SyncMessage[] = [];
  let closed = false;
  socket.addEventListener("message", (event) => {
    const message = JSON.parse(String(event.data));
    received.push(...(Array.isArray(message) ? message : [message]));
  });
  socket.addEventListener("close", () => (closed = true));
  socket.send(
    JSON.stringify({
      connectRequestId: crypto.randomUUID(),
      lastServerClock: 0,
      protocolVersion: TLSYNC_PROTOCOL_VERSION,
      schema: createTLSchema().serialize(),
      type: "connect",
    }),
  );
  await until(() => received.some((message) => message.type === "connect"));
  return { isClosed: () => closed, received };
}

export async function until(condition: () => boolean) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("timed out");
}
