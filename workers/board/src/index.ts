import { type Env, PASS_HEADER, type Refusal } from "./board-room";
import { parsePool } from "./dice";
import { type Pass, verifyDeletion, verifyPass } from "./pass";
import { aliasRedirect, serveSite, type SiteEnv } from "./site";

export { BoardRoom } from "./board-room";

// NOTE: the pass travels in the request itself, never in a cookie. The
// board app is served from this origin, so the rooms API needs no CORS:
// another origin's page can neither read an answer nor send a pass it has.
const REFUSAL_STATUS: Record<Refusal, number> = { full: 429, "link-reset": 403, "too-fast": 429 };

function answer(result: Refusal | object): Response {
  return typeof result === "string"
    ? new Response(result, { status: REFUSAL_STATUS[result] })
    : Response.json(result, { headers: { "Cache-Control": "no-store" } });
}

async function passFor(request: Request, env: Env, board: string): Promise<Pass | null> {
  const token =
    request.headers.get("Authorization")?.replace(/^Bearer /u, "") ??
    new URL(request.url).searchParams.get("pass");
  if (token === null) return null;
  try {
    const pass = await verifyPass(token, env);
    return pass.board === board ? pass : null;
  } catch {
    return null;
  }
}

async function mayDelete(request: Request, env: Env, board: string): Promise<boolean> {
  const token = request.headers.get("Authorization")?.replace(/^Bearer /u, "");
  if (token === undefined) return false;
  try {
    return (await verifyDeletion(token, env)) === board;
  } catch {
    return false;
  }
}

const ROOMS = /^\/rooms\//u;

export default {
  async fetch(request: Request, env: Env & SiteEnv): Promise<Response> {
    const moved = aliasRedirect(request, env);
    if (moved !== null) return moved;
    const url = new URL(request.url);
    if (!ROOMS.test(url.pathname)) return serveSite(request, env);
    const [, board, action] =
      /^\/rooms\/([\w-]{1,64})\/(connect|delete|rolls?)$/u.exec(url.pathname) ?? [];
    if (board === undefined) return new Response("Not found", { status: 404 });
    if (action === "delete") {
      if (request.method !== "POST") return new Response("Not found", { status: 404 });
      if (!(await mayDelete(request, env, board))) {
        return new Response("Forbidden", { status: 403 });
      }
      await env.BoardRoom.get(env.BoardRoom.idFromName(board)).destroy(board);
      return new Response(null, { status: 204 });
    }
    const pass = await passFor(request, env, board);
    if (pass === null) return new Response("Forbidden", { status: 403 });
    const room = env.BoardRoom.get(env.BoardRoom.idFromName(board));

    if (action === "connect" && request.headers.get("Upgrade") === "websocket") {
      const sessionId = url.searchParams.get("sessionId");
      if (sessionId === null) return new Response("Bad request", { status: 400 });
      const forwarded = new Request(request);
      forwarded.headers.set(PASS_HEADER, JSON.stringify(pass));
      return room.fetch(forwarded);
    }
    if (action === "rolls" && request.method === "GET") return answer(await room.rolls(pass));
    if (action === "roll" && request.method === "POST") {
      const pool = parsePool(await request.json().catch(() => null));
      if (pool === null) return new Response("Bad request", { status: 400 });
      return answer(await room.roll(pass, pool));
    }
    return new Response("Not found", { status: 404 });
  },
};
