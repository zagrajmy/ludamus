import { getAgentByName, routeAgentRequest } from "agents";

import type { ParleyConversationAgent } from "./conversation-agent";
import type { Env } from "./room-agent";
import type { ParleySphereAgent } from "./sphere-agent";

import { roomFromId } from "./access";
import {
  corsResponse,
  exchangeCapability,
  lookupFromRequest,
  membershipFromRequest,
  MODERATION_AUDIENCE,
  originIsAllowed,
  revocationFromRequest,
  threadPostFromRequest,
} from "./auth";
import { roomAgent } from "./room-agent";

export { ParleyConversationAgent } from "./conversation-agent";
export { ParleyInboxAgent } from "./inbox-agent";
export { ParleyEventAgent, ParleyOrganizersAgent, ParleySessionAgent } from "./session-agent";
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
    if (url.pathname === "/conversations/messages" && request.method === "POST") {
      const post = await threadPostFromRequest(request, env);
      if (post instanceof Response) return post;
      const room = await getAgentByName<Env, ParleyConversationAgent>(
        env.ParleyConversationAgent,
        post.conversation,
      );
      // A thread whose member list is still on its way is asked again.
      return (await room.post(post))
        ? new Response(null, { status: 204 })
        : new Response("Not a case thread yet", { status: 503 });
    }
    if (url.pathname === "/messages" && request.method === "POST") {
      const lookup = await lookupFromRequest(request, env);
      if (lookup instanceof Response) return lookup;
      const room = roomFromId(lookup.room);
      if (room === null) return new Response("Not found", { status: 404 });
      const message = await (await roomAgent(env, room)).readMessage(lookup.messageId);
      return message === null
        ? new Response("Not found", { status: 404 })
        : Response.json(message, { headers: { "Cache-Control": "no-store" } });
    }
    if (url.pathname === "/moderation" && request.method === "POST") {
      const order = await lookupFromRequest(request, env, MODERATION_AUDIENCE);
      if (order instanceof Response) return order;
      const room = roomFromId(order.room);
      if (room === null) return new Response("Unknown room", { status: 400 });
      const deleted = await (await roomAgent(env, room)).deleteAsStaff(order.messageId);
      return new Response(null, { status: deleted ? 204 : 404 });
    }
    if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
    return (await routeAgentRequest(request, env)) ?? new Response("Not found", { status: 404 });
  },
};
