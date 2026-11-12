import { importSPKI, jwtVerify } from "jose";

import type {
  Capability,
  Lookup,
  Member,
  Membership,
  Revocation,
  ThreadPost,
  ThreadSource,
} from "./protocol";

const COOKIE_NAME = "parley_capability";
// Its own audience, so neither kind of token can be passed off as the other.
export const REVOCATION_AUDIENCE = "parley-revocation";
export const MEMBERSHIP_AUDIENCE = "parley-membership";
export const LOOKUP_AUDIENCE = "parley-message";
export const POST_AUDIENCE = "parley-post";
export const POSTED_MESSAGE_MAX = 4_000;
const THREAD_SOURCES: readonly string[] = [
  "case_opened",
  "decision",
  "email_in",
  "email_out",
  "note",
] satisfies ThreadSource[];

type AuthEnv = {
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
  PARLEY_PUBLIC_KEY: string;
  ROOT_DOMAIN: string;
};

function isLocal(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "[::1]" ||
    hostname.endsWith(".localhost")
  );
}

// A Worker answering on a local host is a dev server, where the app and the
// Worker often sit on different local sites (ludamus.localhost:1355 and
// localhost:8787, or whatever ports an agent picked). There any local page
// may open it, and its cookie crosses sites. Cloudflare routes by Host, so a
// deployed Worker never sees a local one.
function servedLocally(request: Request): boolean {
  return isLocal(new URL(request.url).hostname);
}

function originOf(request: Request): URL | null {
  const origin = request.headers.get("Origin");
  if (origin === null) return null;
  try {
    return new URL(origin);
  } catch {
    return null;
  }
}

// The app and every sphere on a subdomain of it; a sphere on a custom domain
// of its own could not send the SameSite=Strict cookie anyway.
export function originIsAllowed(request: Request, env: AuthEnv): boolean {
  const origin = originOf(request);
  if (origin === null) return false;
  if (servedLocally(request)) return isLocal(origin.hostname);
  return (
    origin.protocol === "https:" &&
    (origin.host === env.ROOT_DOMAIN || origin.host.endsWith(`.${env.ROOT_DOMAIN}`))
  );
}

export function cookieAttributes(request: Request): string {
  // NOTE: SameSite=None needs Secure, which browsers accept from a local
  // host over plain http; Partitioned keeps it working where third-party
  // cookies are blocked.
  return servedLocally(request) ? "SameSite=None; Secure; Partitioned" : "SameSite=Strict; Secure";
}

export function capabilityCookie(request: Request): string | null {
  const cookies = request.headers.get("Cookie") ?? "";
  for (const cookie of cookies.split(";")) {
    const [name, ...value] = cookie.trim().split("=");
    if (name === COOKIE_NAME) return value.join("=");
  }
  return null;
}

function isSeconds(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 0;
}

function isGrants(value: unknown): value is Capability["sessions"] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  return Object.entries(value).every(
    ([room, grant]) =>
      /^\d+:\d+$/u.test(room) &&
      typeof grant === "object" &&
      grant !== null &&
      isSeconds((grant as { endsAt?: unknown }).endsAt) &&
      typeof (grant as { writable?: unknown }).writable === "boolean",
  );
}

async function verified(
  token: string,
  env: AuthEnv,
  audience: string,
  requiredClaims = ["exp", "iat", "sub"],
) {
  const publicKey = await importSPKI(env.PARLEY_PUBLIC_KEY.replaceAll("\\n", "\n"), "RS256");
  const { payload } = await jwtVerify(token, publicKey, {
    algorithms: ["RS256"],
    audience,
    issuer: env.JWT_ISSUER,
    requiredClaims,
  });
  return payload;
}

export async function verifyCapability(token: string, env: AuthEnv): Promise<Capability> {
  const payload = await verified(token, env, env.JWT_AUDIENCE);
  if (
    typeof payload.sub !== "string" ||
    typeof payload.name !== "string" ||
    typeof payload.avatar !== "string" ||
    typeof payload.jti !== "string" ||
    !Array.isArray(payload.managed) ||
    !payload.managed.every((sphere) => typeof sphere === "string" && /^\d+$/u.test(sphere)) ||
    !isSeconds(payload.readOnlyAfter) ||
    !isSeconds(payload.retainFor) ||
    !isGrants(payload.sessions) ||
    !isGrants(payload.events) ||
    (payload.direct !== undefined && typeof payload.direct !== "boolean")
  ) {
    throw new Error("Invalid capability");
  }
  return payload as Capability;
}

export async function verifyRevocation(token: string, env: AuthEnv): Promise<Revocation> {
  const payload = await verified(token, env, REVOCATION_AUDIENCE);
  if (
    typeof payload.sphere !== "string" ||
    !/^\d+$/u.test(payload.sphere) ||
    typeof payload.sub !== "string" ||
    !/^(?:\d+|\*)$/u.test(payload.sub) ||
    !isSeconds(payload.revokedBefore) ||
    !isSeconds(payload.exp)
  ) {
    throw new Error("Invalid revocation");
  }
  return {
    exp: payload.exp,
    revokedBefore: payload.revokedBefore,
    sphere: payload.sphere,
    sub: payload.sub,
  };
}

function isMember(value: unknown): value is Member {
  if (typeof value !== "object" || value === null) return false;
  const { state, user, writable } = value as Record<string, unknown>;
  return (
    typeof user === "string" &&
    /^\d+$/u.test(user) &&
    (state === "active" || state === "request") &&
    typeof writable === "boolean"
  );
}

export async function verifyMembership(token: string, env: AuthEnv): Promise<Membership> {
  // A member list names a room, not a person.
  const payload = await verified(token, env, MEMBERSHIP_AUDIENCE, ["exp", "iat"]);
  if (
    typeof payload.conversation !== "string" ||
    !/^\d+$/u.test(payload.conversation) ||
    (payload.kind !== "direct" &&
      payload.kind !== "group" &&
      payload.kind !== "party" &&
      payload.kind !== "staff") ||
    !Array.isArray(payload.members) ||
    !payload.members.every(isMember)
  ) {
    throw new Error("Invalid membership");
  }
  return {
    conversation: payload.conversation,
    iat: payload.iat!,
    kind: payload.kind,
    members: payload.members,
  };
}

export async function verifyLookup(token: string, env: AuthEnv): Promise<Lookup> {
  // A lookup names a message, not a person.
  const payload = await verified(token, env, LOOKUP_AUDIENCE, ["exp", "iat"]);
  if (
    typeof payload.room !== "string" ||
    typeof payload.message !== "number" ||
    !Number.isSafeInteger(payload.message) ||
    payload.message < 1
  ) {
    throw new Error("Invalid lookup");
  }
  return { messageId: payload.message, room: payload.room };
}

export async function verifyThreadPost(token: string, env: AuthEnv): Promise<ThreadPost> {
  const payload = await verified(token, env, POST_AUDIENCE, ["exp", "iat"]);
  if (
    typeof payload.conversation !== "string" ||
    !/^\d+$/u.test(payload.conversation) ||
    typeof payload.author !== "string" ||
    !/^(?:\d+|system|email)$/u.test(payload.author) ||
    typeof payload.name !== "string" ||
    typeof payload.body !== "string" ||
    payload.body.trim().length === 0 ||
    [...payload.body].length > POSTED_MESSAGE_MAX ||
    typeof payload.source !== "string" ||
    !THREAD_SOURCES.includes(payload.source) ||
    typeof payload.nonce !== "string" ||
    payload.nonce.length === 0 ||
    payload.nonce.length > 100 ||
    !isSeconds(payload.retainFor)
  ) {
    throw new Error("Invalid thread post");
  }
  return {
    authorId: payload.author,
    authorName: payload.name,
    body: payload.body,
    conversation: payload.conversation,
    nonce: payload.nonce,
    retainFor: payload.retainFor,
    source: payload.source as ThreadSource,
  };
}

async function tokenFromBody(request: Request): Promise<string | null> {
  try {
    const body: unknown = await request.json();
    return typeof body === "object" &&
      body !== null &&
      "token" in body &&
      typeof body.token === "string"
      ? body.token
      : null;
  } catch {
    return null;
  }
}

// Django calls this server to server, so there is no Origin to check: the
// signature is the authority, and replaying one only repeats the same cutoff.
export async function revocationFromRequest(
  request: Request,
  env: AuthEnv,
): Promise<Revocation | Response> {
  const token = await tokenFromBody(request);
  if (token === null) return new Response("Invalid request", { status: 400 });
  try {
    return await verifyRevocation(token, env);
  } catch {
    return new Response("Invalid revocation", { status: 401 });
  }
}

// Django's push of a conversation's member list, server to server like a
// revocation.
export async function membershipFromRequest(
  request: Request,
  env: AuthEnv,
): Promise<Membership | Response> {
  const token = await tokenFromBody(request);
  if (token === null) return new Response("Invalid request", { status: 400 });
  try {
    return await verifyMembership(token, env);
  } catch {
    return new Response("Invalid membership", { status: 401 });
  }
}

// Django asking for a reported message, server to server like a revocation.
export async function lookupFromRequest(
  request: Request,
  env: AuthEnv,
): Promise<Lookup | Response> {
  const token = await tokenFromBody(request);
  if (token === null) return new Response("Invalid request", { status: 400 });
  try {
    return await verifyLookup(token, env);
  } catch {
    return new Response("Invalid lookup", { status: 401 });
  }
}

export async function threadPostFromRequest(
  request: Request,
  env: AuthEnv,
): Promise<ThreadPost | Response> {
  const token = await tokenFromBody(request);
  if (token === null) return new Response("Invalid request", { status: 400 });
  try {
    return await verifyThreadPost(token, env);
  } catch {
    return new Response("Invalid thread post", { status: 401 });
  }
}

export async function capabilityFromRequest(request: Request, env: AuthEnv): Promise<Capability> {
  const token = capabilityCookie(request);
  if (token === null) throw new Error("Missing capability");
  return verifyCapability(token, env);
}

export async function exchangeCapability(request: Request, env: AuthEnv): Promise<Response> {
  if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
  const token = await tokenFromBody(request);
  if (token === null) return new Response("Invalid request", { status: 400 });
  try {
    const capability = await verifyCapability(token, env);
    const maxAge = Math.max(0, capability.exp - Math.floor(Date.now() / 1000));
    return corsResponse(
      request,
      env,
      new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "no-store",
          "Set-Cookie": `${COOKIE_NAME}=${token}; HttpOnly; ${cookieAttributes(request)}; Path=/agents; Max-Age=${maxAge}`,
        },
      }),
    );
  } catch {
    return new Response("Invalid capability", { status: 401 });
  }
}

export function corsResponse(request: Request, env: AuthEnv, response: Response): Response {
  const origin = request.headers.get("Origin");
  if (origin === null || !originIsAllowed(request, env)) return response;
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Credentials", "true");
  headers.set("Access-Control-Allow-Origin", origin);
  headers.append("Vary", "Origin");
  return new Response(response.body, {
    headers,
    status: response.status,
    statusText: response.statusText,
  });
}
