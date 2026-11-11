import { exportSPKI, generateKeyPair, SignJWT } from "jose";
import { beforeAll, describe, expect, it } from "vitest";

import type { Capability } from "../src/protocol";

import { REVOCATION_AUDIENCE, verifyCapability, verifyRevocation } from "../src/auth";
import { revokes } from "../src/room-agent";

let env: {
  ROOT_DOMAIN: string;
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
  PARLEY_PUBLIC_KEY: string;
};
let sign: (claims: Record<string, unknown>, audience?: string) => Promise<string>;

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
    ROOT_DOMAIN: "ludamus.test",
    JWT_AUDIENCE: "parley",
    JWT_ISSUER: "ludamus",
    PARLEY_PUBLIC_KEY: await exportSPKI(publicKey),
  };
  sign = (claims, audience = "parley") =>
    new SignJWT(claims)
      .setProtectedHeader({ alg: "RS256", typ: "JWT" })
      .setAudience(audience)
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

const revocation = { revokedBefore: 1_900_000_000, sphere: "3", sub: "7" };

describe("verifyRevocation", () => {
  it("accepts one person or everyone in a sphere", async () => {
    await expect(
      verifyRevocation(await sign(revocation, REVOCATION_AUDIENCE), env),
    ).resolves.toMatchObject({ revokedBefore: 1_900_000_000, sphere: "3", sub: "7" });
    await expect(
      verifyRevocation(await sign({ ...revocation, sub: "*" }, REVOCATION_AUDIENCE), env),
    ).resolves.toMatchObject({ sub: "*" });
  });

  it("keeps passes and revocations from standing in for each other", async () => {
    await expect(verifyRevocation(await sign(revocation), env)).rejects.toThrow();
    await expect(verifyCapability(await sign(valid, REVOCATION_AUDIENCE), env)).rejects.toThrow();
  });

  it("rejects one signed by another key", async () => {
    const { privateKey } = await generateKeyPair("RS256");
    const forged = await new SignJWT(revocation)
      .setProtectedHeader({ alg: "RS256", typ: "JWT" })
      .setAudience(REVOCATION_AUDIENCE)
      .setIssuer("ludamus")
      .setIssuedAt()
      .setExpirationTime("12h")
      .sign(privateKey);
    await expect(verifyRevocation(forged, env)).rejects.toThrow();
  });

  it.each([
    ["a sphere that is not an id", { sphere: "3:101" }],
    ["a subject that is not an id", { sub: "ada" }],
    ["a fractional cutoff", { revokedBefore: 1.5 }],
    ["no cutoff", { revokedBefore: undefined }],
  ])("rejects %s", async (_label, overrides) => {
    const token = await sign({ ...revocation, ...overrides }, REVOCATION_AUDIENCE);
    await expect(verifyRevocation(token, env)).rejects.toThrow();
  });
});

describe("revokes", () => {
  const pass = (iat: number, sub = "7"): Capability => ({
    ...valid,
    aud: "parley",
    exp: iat + 1,
    iat,
    iss: "ludamus",
    role: "member",
    sub,
  });

  it("voids passes issued before the cutoff and spares the one fetched after it", () => {
    expect(revokes(revocation, pass(1_899_999_999))).toBe(true);
    // A pass fetched in the same second as the cutoff is the re-fetch the
    // revocation asked for.
    expect(revokes(revocation, pass(1_900_000_000))).toBe(false);
  });

  it("reaches only its subject, or everyone for *", () => {
    expect(revokes(revocation, pass(1, "8"))).toBe(false);
    expect(revokes({ ...revocation, sub: "*" }, pass(1, "8"))).toBe(true);
  });
});
