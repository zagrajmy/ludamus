import { importSPKI, jwtVerify } from "jose";

import type { Capability, Revocation } from "./protocol";

const COOKIE_NAME = "parley_capability";
// Its own audience, so neither kind of token can be passed off as the other.
export const REVOCATION_AUDIENCE = "parley-revocation";

type AuthEnv = {
  ALLOWED_ORIGINS: string;
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
  PARLEY_PUBLIC_KEY: string;
};

function allowedOrigins(env: AuthEnv): Set<string> {
  return new Set(env.ALLOWED_ORIGINS.split(",").map((origin) => origin.trim()));
}

export function originIsAllowed(request: Request, env: AuthEnv): boolean {
  const origin = request.headers.get("Origin");
  return origin !== null && allowedOrigins(env).has(origin);
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

function isSessionGrants(value: unknown): value is Capability["sessions"] {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  return Object.entries(value).every(
    ([session, grant]) =>
      /^\d+$/u.test(session) &&
      typeof grant === "object" &&
      grant !== null &&
      isSeconds((grant as { endsAt?: unknown }).endsAt) &&
      typeof (grant as { writable?: unknown }).writable === "boolean",
  );
}

async function verified(token: string, env: AuthEnv, audience: string) {
  const publicKey = await importSPKI(env.PARLEY_PUBLIC_KEY.replaceAll("\\n", "\n"), "RS256");
  const { payload } = await jwtVerify(token, publicKey, {
    algorithms: ["RS256"],
    audience,
    issuer: env.JWT_ISSUER,
    requiredClaims: ["exp", "iat", "sub"],
  });
  return payload;
}

export async function verifyCapability(token: string, env: AuthEnv): Promise<Capability> {
  const payload = await verified(token, env, env.JWT_AUDIENCE);
  if (
    typeof payload.sub !== "string" ||
    typeof payload.sphere !== "string" ||
    typeof payload.name !== "string" ||
    typeof payload.avatar !== "string" ||
    typeof payload.jti !== "string" ||
    (payload.role !== "manager" && payload.role !== "member") ||
    !isSeconds(payload.readOnlyAfter) ||
    !isSeconds(payload.retainFor) ||
    !isSessionGrants(payload.sessions)
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
    const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
    return corsResponse(
      request,
      env,
      new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "no-store",
          "Set-Cookie": `${COOKIE_NAME}=${token}; HttpOnly; SameSite=Strict; Path=/agents; Max-Age=${maxAge}${secure}`,
        },
      }),
    );
  } catch {
    return new Response("Invalid capability", { status: 401 });
  }
}

export function corsResponse(request: Request, env: AuthEnv, response: Response): Response {
  const origin = request.headers.get("Origin");
  if (origin === null || !allowedOrigins(env).has(origin)) return response;
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
