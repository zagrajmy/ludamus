import { describe, expect, it } from "vitest";

import { cookieAttributes, originIsAllowed } from "../src/auth";

const env = {
  JWT_AUDIENCE: "parley",
  JWT_ISSUER: "ludamus",
  PARLEY_PUBLIC_KEY: "unused",
  ROOT_DOMAIN: "zagrajmy.test",
};

const deployed = "https://parley.zagrajmy.test/agents";
const local = "http://localhost:8787/agents";

function allowed(worker: string, origin?: string): boolean {
  const headers: Record<string, string> = origin === undefined ? {} : { Origin: origin };
  return originIsAllowed(new Request(worker, { headers }), env);
}

describe("originIsAllowed on a deployed Worker", () => {
  it("admits the app and its sphere subdomains over https", () => {
    expect(allowed(deployed, "https://zagrajmy.test")).toBe(true);
    expect(allowed(deployed, "https://konwent.zagrajmy.test")).toBe(true);
  });

  it.each([
    ["no origin", undefined],
    ["an unparsable origin", "null"],
    ["a lookalike domain", "https://evilzagrajmy.test"],
    ["plain http", "http://zagrajmy.test"],
    ["a local page", "http://localhost:8000"],
    ["another site", "https://evil.test"],
  ])("refuses %s", (_label, origin) => {
    expect(allowed(deployed, origin)).toBe(false);
  });
});

describe("originIsAllowed on a local Worker", () => {
  it("admits a local page on any port or hostname", () => {
    expect(allowed(local, "http://localhost:8123")).toBe(true);
    expect(allowed(local, "http://ludamus.localhost:1355")).toBe(true);
    expect(allowed("http://parley.ludamus.localhost:1355/agents", "http://127.0.0.1:8000")).toBe(
      true,
    );
  });

  it("still refuses a page from the internet", () => {
    expect(allowed(local, "https://zagrajmy.test")).toBe(false);
    expect(allowed(local, "http://localhost.evil.test")).toBe(false);
  });
});

describe("cookieAttributes", () => {
  it("keeps the deployed cookie on the app's own site", () => {
    expect(cookieAttributes(new Request(deployed))).toBe("SameSite=Strict; Secure");
  });

  it("lets a local cookie cross local sites", () => {
    expect(cookieAttributes(new Request(local))).toBe("SameSite=None; Secure; Partitioned");
  });
});
