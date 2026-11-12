import { type Env, PASS_HEADER, type Refusal } from "./board-room";
import { parsePool } from "./dice";
import { type Pass, verifyPass } from "./pass";

export { BoardRoom } from "./board-room";

// NOTE: the pass travels in the request itself, never in a cookie, so a
// page on any origin can only act with a pass the app gave it. That is what
// lets a sphere on a custom domain of its own use a board.
const CORS = {
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Allow-Methods": "GET, POST",
  "Access-Control-Allow-Origin": "*",
};

const REFUSAL_STATUS: Record<Refusal, number> = { full: 429, "link-reset": 403, "too-fast": 429 };

function answer(result: Refusal | object): Response {
  return typeof result === "string"
    ? new Response(result, { headers: CORS, status: REFUSAL_STATUS[result] })
    : Response.json(result, { headers: { ...CORS, "Cache-Control": "no-store" } });
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS, status: 204 });
    const url = new URL(request.url);
    const [, board, action] =
      /^\/rooms\/([\w-]{1,64})\/(connect|rolls?)$/u.exec(url.pathname) ?? [];
    if (board === undefined) return new Response("Not found", { headers: CORS, status: 404 });
    const pass = await passFor(request, env, board);
    if (pass === null) return new Response("Forbidden", { headers: CORS, status: 403 });
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
      if (pool === null) return new Response("Bad request", { headers: CORS, status: 400 });
      return answer(await room.roll(pass, pool));
    }
    return new Response("Not found", { headers: CORS, status: 404 });
  },
};
