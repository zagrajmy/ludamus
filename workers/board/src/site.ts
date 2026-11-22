// The board app's pages and files: the names it answers to, the SPA shell
// at /b/<share code>, and the headers every page and file leaves with.

export type SiteEnv = {
  // Where Django runs, scheme included: the app asks it for passes.
  APP_ORIGIN: string;
  ASSETS: Fetcher;
  // The app's root domain. Empty on a laptop, in tests and on workers.dev
  // previews, where the board answers to whatever host it is reached by.
  ROOT_DOMAIN: string;
};

// The board's own name, and the names that lead to it. The root domain comes
// from configuration (staging and production differ); the labels do not.
export const PRIMARY_LABEL = "board";
export const ALIAS_LABELS = ["vtt", "tabletop", "tablica"] as const;

// A request to an alias moves to the same path on the board's own host,
// before anything else runs: no page, file, API or socket is served there.
export function aliasRedirect(request: Request, env: SiteEnv): Response | null {
  if (env.ROOT_DOMAIN === "") return null;
  const url = new URL(request.url);
  const isAlias = ALIAS_LABELS.some((label) => url.hostname === `${label}.${env.ROOT_DOMAIN}`);
  if (!isAlias) return null;
  url.hostname = `${PRIMARY_LABEL}.${env.ROOT_DOMAIN}`;
  return Response.redirect(url.toString(), 308);
}

// NOTE: the dice draw with three.js on a plain canvas today. Physics in
// WebAssembly would need "'wasm-unsafe-eval'" here, and nowhere else.
const SCRIPT_SRC = ["'self'"];

// The shell's Content-Security-Policy. It starts from the site's own policy
// (src/ludamus/edges/settings.py, CSP_POLICY) and allows what the board
// needs: its own scripts, fonts and tldraw's self-hosted assets, the rooms
// socket on this host, and Django's origin for the pass request.
export function contentSecurityPolicy(request: Request, env: SiteEnv): string {
  const { host, protocol } = new URL(request.url);
  const socket = `${protocol === "https:" ? "wss" : "ws"}://${host}`;
  const directives: Record<string, string[]> = {
    "default-src": ["'none'"],
    "script-src": SCRIPT_SRC,
    // NOTE: tldraw positions every shape with inline style attributes.
    "style-src": ["'self'", "'unsafe-inline'"],
    // Uploaded images will come from this Worker's own /assets route.
    "img-src": ["'self'", "data:", "blob:"],
    "font-src": ["'self'"],
    "connect-src": ["'self'", socket, env.APP_ORIGIN],
    "manifest-src": ["'self'"],
    "object-src": ["'none'"],
    "base-uri": ["'none'"],
    "form-action": ["'none'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, sources]) => `${name} ${sources.join(" ")}`)
    .join("; ");
}

// What every response of the app carries, page or file. The policy goes on
// files too, so that index.html fetched by its own name is no way around it.
function harden(response: Response, request: Request, env: SiteEnv): Response {
  const hardened = new Response(response.body, response);
  const { headers } = hardened;
  headers.set("Content-Security-Policy", contentSecurityPolicy(request, env));
  headers.set("X-Content-Type-Options", "nosniff");
  // The address holds the board's share code, which opens the board.
  headers.set("Referrer-Policy", "no-referrer");
  headers.set("X-Frame-Options", "DENY");
  headers.set("Cross-Origin-Opener-Policy", "same-origin");
  headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
  );
  if (new URL(request.url).protocol === "https:") {
    headers.set("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
  }
  return hardened;
}

const SHELL = /^\/b\/[A-Za-z0-9]{1,64}\/?$/u;
// Vite names every built script, style and font after its content.
const HASHED = /^\/assets\//u;

export async function serveSite(request: Request, env: SiteEnv): Promise<Response> {
  const url = new URL(request.url);
  if (request.method !== "GET" && request.method !== "HEAD") {
    return harden(new Response("Method not allowed", { status: 405 }), request, env);
  }
  if (url.pathname === "/") {
    // Nothing lives at the root: a person who types the name gets their boards.
    return harden(Response.redirect(`${env.APP_ORIGIN}/boards/`, 302), request, env);
  }
  if (SHELL.test(url.pathname)) {
    const shell = await env.ASSETS.fetch(new URL("/index.html", url));
    const page = harden(shell, request, env);
    page.headers.set("Cache-Control", "no-cache");
    page.headers.set("X-Robots-Tag", "noindex, nofollow");
    return page;
  }
  const file = harden(await env.ASSETS.fetch(request), request, env);
  if (file.ok && HASHED.test(url.pathname)) {
    file.headers.set("Cache-Control", "public, max-age=31536000, immutable");
  }
  return file;
}
