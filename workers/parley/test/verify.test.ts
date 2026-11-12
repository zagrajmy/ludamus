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
  events: { "3:9": { endsAt: 1_900_000_000, writable: true } },
  managed: [],
  organizers: [],
  sessions: { "3:101": { endsAt: 1_900_000_000, writable: true } },
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
      events: { "3:9": { endsAt: 1_900_000_000, writable: true } },
      managed: [],
    });
    await expect(
      verifyCapability(await sign({ ...valid, managed: ["3", "4"], sessions: {} }), env),
    ).resolves.toMatchObject({ managed: ["3", "4"] });
  });

  it.each([
    ["a managed sphere that is not an id", { managed: ["3:101"] }],
    ["managed spheres as a string", { managed: "3" }],
    ["no organizers' rooms", { organizers: undefined }],
    ["no events", { events: undefined }],
    ["sessions as a list", { sessions: ["3:101"] }],
    ["a grant without an end", { sessions: { "3:101": { writable: true } } }],
    ["a grant with a string flag", { sessions: { "3:101": { endsAt: 1, writable: "yes" } } }],
    ["a session key without its sphere", { sessions: { "101": { endsAt: 1, writable: true } } }],
    ["a non-numeric event key", { events: { "3:abc": { endsAt: 1, writable: true } } }],
    ["no retention", { retainFor: undefined }],
    ["the one-sphere pass", { managed: undefined, role: "member", sphere: "3" }],
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
