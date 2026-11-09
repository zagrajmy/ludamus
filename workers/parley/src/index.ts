import { getAgentByName, routeAgentRequest } from "agents";

import type { Env } from "./room-agent";
import type { ParleySphereAgent } from "./sphere-agent";

import { corsResponse, exchangeCapability, originIsAllowed, revocationFromRequest } from "./auth";

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
    if (url.pathname === "/revoke" && request.method === "POST") {
      const revocation = await revocationFromRequest(request, env);
      if (revocation instanceof Response) return revocation;
      const sphere = await getAgentByName<Env, ParleySphereAgent>(
        env.ParleySphereAgent,
        revocation.sphere,
      );
      await sphere.revoke(revocation);
      return new Response(null, { status: 204 });
    }
    if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
    return (await routeAgentRequest(request, env)) ?? new Response("Not found", { status: 404 });
  },
};
