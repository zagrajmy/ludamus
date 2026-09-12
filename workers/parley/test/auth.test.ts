import { describe, expect, it } from "vitest";

import { originIsAllowed } from "../src/auth";

const env = {
  ALLOWED_ORIGINS: "https://ludamus.test, https://event.ludamus.test",
  JWT_AUDIENCE: "parley",
  JWT_ISSUER: "ludamus",
  PARLEY_PUBLIC_KEY: "unused",
};

describe("originIsAllowed", () => {
  it("requires an exact configured origin", () => {
    expect(
      originIsAllowed(
        new Request("https://worker.test", { headers: { Origin: "https://event.ludamus.test" } }),
        env,
      ),
    ).toBe(true);
    expect(
      originIsAllowed(
        new Request("https://worker.test", { headers: { Origin: "https://evil.test" } }),
        env,
      ),
    ).toBe(false);
    expect(originIsAllowed(new Request("https://worker.test"), env)).toBe(false);
  });
});
