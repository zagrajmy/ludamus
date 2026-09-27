import { routeAgentRequest } from "agents";

import type { Env } from "./room-agent";

import { corsResponse, exchangeCapability, originIsAllowed } from "./auth";

export { ParleySessionAgent } from "./session-agent";
export { ParleySphereAgent } from "./sphere-agent";

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "OPTIONS" && originIsAllowed(request, env)) {
      return corsResponse(
        request,
        env,
        new Response(null, {
          status: 204,
          headers: {
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST",
          },
        }),
      );
    }
    if (url.pathname === "/auth/exchange" && request.method === "POST") {
      return exchangeCapability(request, env);
    }
    if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
    return (await routeAgentRequest(request, env)) ?? new Response("Not found", { status: 404 });
  },
};
