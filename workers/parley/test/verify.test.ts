import { exportSPKI, generateKeyPair, SignJWT } from "jose";
import { beforeAll, describe, expect, it } from "vitest";

import { verifyCapability } from "../src/auth";

let env: {
  ALLOWED_ORIGINS: string;
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
  PARLEY_PUBLIC_KEY: string;
};
let sign: (claims: Record<string, unknown>) => Promise<string>;

const valid = {
  avatar: "",
  jti: "token",
  name: "Ada",
  readOnlyAfter: 172_800,
  retainFor: 2_592_000,
  role: "member",
  sessions: { "101": { endsAt: 1_900_000_000, writable: true } },
  sphere: "3",
  sub: "7",
};

beforeAll(async () => {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  env = {
    ALLOWED_ORIGINS: "https://ludamus.test",
    JWT_AUDIENCE: "parley",
    JWT_ISSUER: "ludamus",
    PARLEY_PUBLIC_KEY: await exportSPKI(publicKey),
  };
  sign = (claims) =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: "RS256", typ: "JWT" })
      .setAudience("parley")
      .setIssuer("ludamus")
      .setIssuedAt()
      .setExpirationTime("15m")
      .sign(privateKey);
});

describe("verifyCapability", () => {
  it("accepts a member and a manager token", async () => {
    await expect(verifyCapability(await sign(valid), env)).resolves.toMatchObject({
      role: "member",
      sphere: "3",
    });
    await expect(
      verifyCapability(await sign({ ...valid, role: "manager", sessions: {} }), env),
    ).resolves.toMatchObject({ role: "manager" });
  });

  it.each([
    ["an unknown role", { role: "admin" }],
    ["sessions as a list", { sessions: ["101"] }],
    ["a grant without an end", { sessions: { "101": { writable: true } } }],
    ["a grant with a string flag", { sessions: { "101": { endsAt: 1, writable: "yes" } } }],
    ["a non-numeric session key", { sessions: { abc: { endsAt: 1, writable: true } } }],
    ["no retention", { retainFor: undefined }],
    ["the old per-room lists", { readOnlyAfter: undefined, rooms: ["sphere:3"] }],
  ])("rejects %s", async (_label, overrides) => {
    const token = await sign({ ...valid, ...overrides });
    await expect(verifyCapability(token, env)).rejects.toThrow();
  });
});
