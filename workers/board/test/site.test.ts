import { env, exports } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import board from "../src/index";

const worker = (exports as unknown as { default: { fetch: typeof fetch } }).default;
const testEnv = env as unknown as { ROOT_DOMAIN: string };

const get = (url: string, init: RequestInit = {}) =>
  worker.fetch(new Request(url, { redirect: "manual", ...init }));

function directives(response: Response): Map<string, string[]> {
  const policy = response.headers.get("Content-Security-Policy") ?? "";
  return new Map(
    policy.split(";").map((directive) => {
      const [name = "", ...sources] = directive.trim().split(/\s+/u);
      return [name, sources];
    }),
  );
}

describe("the board shell", () => {
  it.each(["/b/AbC123xyz789", "/b/AbC123xyz789/"])("is served at %s", async (path) => {
    const response = await get(`https://board.test${path}`);

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toMatch(/^text\/html/u);
    expect(await response.text()).toContain("data-board-root");
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("X-Robots-Tag")).toBe("noindex, nofollow");
  });

  it("carries a policy that allows the board and nothing else", async () => {
    const policy = directives(await get("https://board.test/b/AbC123xyz789"));

    expect(Object.fromEntries(policy)).toEqual({
      "base-uri": ["'none'"],
      "connect-src": ["'self'", "wss://board.test", "http://localhost:8000"],
      "default-src": ["'none'"],
      "font-src": ["'self'"],
      "form-action": ["'none'"],
      "frame-ancestors": ["'none'"],
      "img-src": ["'self'", "data:", "blob:"],
      "manifest-src": ["'self'"],
      "object-src": ["'none'"],
      "script-src": ["'self'"],
      "style-src": ["'self'", "'unsafe-inline'"],
    });
  });

  it("opens its socket in plain text where the page is plain text", async () => {
    const policy = directives(await get("http://localhost:8788/b/AbC123xyz789"));

    expect(policy.get("connect-src")).toContain("ws://localhost:8788");
  });

  it("leaves with the hardening headers", async () => {
    const { headers } = await get("https://board.test/b/AbC123xyz789");

    expect({
      coop: headers.get("Cross-Origin-Opener-Policy"),
      frame: headers.get("X-Frame-Options"),
      hsts: headers.get("Strict-Transport-Security"),
      permissions: headers.get("Permissions-Policy"),
      referrer: headers.get("Referrer-Policy"),
      sniff: headers.get("X-Content-Type-Options"),
    }).toEqual({
      coop: "same-origin",
      frame: "DENY",
      hsts: "max-age=31536000; includeSubDomains",
      permissions:
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), display-capture=()",
      // The address holds the share code, which opens the board.
      referrer: "no-referrer",
      sniff: "nosniff",
    });
  });

  it.each(["/b/", "/b/not-a-code!", "/b/AbC/extra", "/elsewhere"])(
    "is not served at %s",
    async (path) => {
      expect((await get(`https://board.test${path}`)).status).toBe(404);
    },
  );

  it("refuses anything but reading", async () => {
    const response = await get("https://board.test/b/AbC123xyz789", { method: "POST" });

    expect(response.status).toBe(405);
  });

  it("sends a person at the bare name to their boards on the app", async () => {
    const response = await get("https://board.test/");

    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toBe("http://localhost:8000/boards/");
  });
});

describe("the built files", () => {
  it("are cached for good when their names carry a hash", async () => {
    const response = await get("https://board.test/assets/app-fixture.js");

    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("public, max-age=31536000, immutable");
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
  });

  it("include the manifest, under the same policy", async () => {
    const response = await get("https://board.test/manifest.webmanifest");

    expect(response.status).toBe(200);
    expect(directives(response).get("default-src")).toEqual(["'none'"]);
  });

  it("put the policy on index.html fetched by its own name", async () => {
    const response = await get("https://board.test/index.html");

    expect(directives(response).get("script-src")).toEqual(["'self'"]);
  });
});

describe("the board's other names", () => {
  // The module's own handler, called with an env whose root domain is set.
  const withRoot = (rootDomain: string, url: string) =>
    board.fetch(new Request(url, { redirect: "manual" }), {
      ...(env as unknown as Parameters<typeof board.fetch>[1]),
      ROOT_DOMAIN: rootDomain,
    });

  it.each(["vtt", "tabletop", "tablica"])(
    "%s moves to the board's own host, path and query kept",
    async (label) => {
      const response = await withRoot(
        "example.org",
        `https://${label}.example.org/b/AbC123xyz789?lang=pl`,
      );

      expect(response.status).toBe(308);
      expect(response.headers.get("Location")).toBe(
        "https://board.example.org/b/AbC123xyz789?lang=pl",
      );
    },
  );

  it("serves no API on an alias", async () => {
    const response = await withRoot("example.org", "https://vtt.example.org/rooms/b1/rolls");

    expect(response.status).toBe(308);
    expect(response.headers.get("Location")).toBe("https://board.example.org/rooms/b1/rolls");
  });

  it("does not move the board's own host", async () => {
    const response = await withRoot("example.org", "https://board.example.org/b/AbC123xyz789");

    expect(response.status).toBe(200);
  });

  it("serves an unknown host as it is, as on a workers.dev preview", async () => {
    const response = await withRoot(
      "example.org",
      "https://ludamus-board-pr-7.example.workers.dev/b/AbC123xyz789",
    );

    expect(response.status).toBe(200);
  });

  it("moves nothing without a root domain", async () => {
    expect(testEnv.ROOT_DOMAIN).toBe("");
    const response = await get("https://vtt.example.org/b/AbC123xyz789");

    expect(response.status).toBe(200);
  });
});
