import { importSPKI, jwtVerify } from "jose";

import type { Capability } from "./protocol";

const COOKIE_NAME = "parley_capability";

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

export async function verifyCapability(token: string, env: AuthEnv): Promise<Capability> {
  const publicKey = await importSPKI(env.PARLEY_PUBLIC_KEY.replaceAll("\\n", "\n"), "RS256");
  const { payload } = await jwtVerify(token, publicKey, {
    algorithms: ["RS256"],
    audience: env.JWT_AUDIENCE,
    issuer: env.JWT_ISSUER,
  });
  if (
    typeof payload.sub !== "string" ||
    typeof payload.sphere !== "string" ||
    typeof payload.name !== "string" ||
    typeof payload.avatar !== "string" ||
    typeof payload.jti !== "string" ||
    !Array.isArray(payload.rooms) ||
    !Array.isArray(payload.writes) ||
    !Array.isArray(payload.moderates)
  ) {
    throw new Error("Invalid capability");
  }
  return payload as Capability;
}

export async function capabilityFromRequest(request: Request, env: AuthEnv): Promise<Capability> {
  const token = capabilityCookie(request);
  if (token === null) throw new Error("Missing capability");
  return verifyCapability(token, env);
}

export async function exchangeCapability(request: Request, env: AuthEnv): Promise<Response> {
  if (!originIsAllowed(request, env)) return new Response("Forbidden", { status: 403 });
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return new Response("Invalid request", { status: 400 });
  }
  if (
    typeof body !== "object" ||
    body === null ||
    !("token" in body) ||
    typeof body.token !== "string"
  ) {
    return new Response("Invalid request", { status: 400 });
  }
  try {
    const capability = await verifyCapability(body.token, env);
    const maxAge = Math.max(0, capability.exp - Math.floor(Date.now() / 1000));
    const secure = new URL(request.url).protocol === "https:" ? "; Secure" : "";
    return corsResponse(
      request,
      env,
      new Response(null, {
        status: 204,
        headers: {
          "Cache-Control": "no-store",
          "Set-Cookie": `${COOKIE_NAME}=${body.token}; HttpOnly; SameSite=Strict; Path=/agents; Max-Age=${maxAge}${secure}`,
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
