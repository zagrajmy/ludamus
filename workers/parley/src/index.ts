import { getAgentByName, routeAgentRequest } from "agents";

import type { ParleyConversationAgent } from "./conversation-agent";
import type { Env, RoomAgent } from "./room-agent";
import type { ParleySphereAgent } from "./sphere-agent";

import { roomFromId } from "./access";
import {
  corsResponse,
  exchangeCapability,
  lookupFromRequest,
  membershipFromRequest,
  originIsAllowed,
  revocationFromRequest,
} from "./auth";

export { ParleyConversationAgent } from "./conversation-agent";
export { ParleyInboxAgent } from "./inbox-agent";
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
    if (url.pathname === "/conversations" && request.method === "POST") {
      const membership = await membershipFromRequest(request, env);
      if (membership instanceof Response) return membership;
      const room = await getAgentByName<Env, ParleyConversationAgent>(
        env.ParleyConversationAgent,
        membership.conversation,
      );
      await room.sync(membership);
      return new Response(null, { status: 204 });
    }
    if (url.pathname === "/messages" && request.method === "POST") {
      const lookup = await lookupFromRequest(request, env);
      if (lookup instanceof Response) return lookup;
      const room = roomFromId(lookup.room);
      if (room === null) return new Response("Not found", { status: 404 });
      const namespaces = {
        conversation: env.ParleyConversationAgent,
        session: env.ParleySessionAgent,
        sphere: env.ParleySphereAgent,
      };
      const agent = await getAgentByName<Env, RoomAgent>(
        namespaces[room.kind] as unknown as DurableObjectNamespace<RoomAgent>,
        lookup.room.slice(lookup.room.indexOf(":") + 1),
      );
      const message = await agent.readMessage(lookup.messageId);
      return message === null
        ? new Response("Not found", { status: 404 })
        : Response.json(message, { headers: { "Cache-Control": "no-store" } });
    }
    if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
    return (await routeAgentRequest(request, env)) ?? new Response("Not found", { status: 404 });
  },
};
