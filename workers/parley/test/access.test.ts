import { describe, expect, it } from "vitest";

import type { Capability } from "../src/protocol";

import { canModerate, canRead, canSeeRoom, canWrite, lifecycleOf, parseRoom } from "../src/access";

const HOUR = 3_600;

function capability(overrides: Partial<Capability> = {}): Capability {
  return {
    aud: "parley",
    avatar: "",
    exp: 2_000_000_000,
    iat: 1_900_000_000,
    iss: "ludamus",
    jti: "token",
    name: "Ada",
    readOnlyAfter: 48 * HOUR,
    retainFor: 30 * 24 * HOUR,
    role: "member",
    sessions: { "101": { endsAt: 1_900_000_000, writable: true } },
    sphere: "3",
    sub: "7",
    ...overrides,
  };
}

const manager = capability({ role: "manager", sessions: {} });
const sphereRoom = parseRoom("sphere", "3")!;
const ownSession = parseRoom("session", "3:101")!;
const otherSession = parseRoom("session", "3:102")!;
const foreignSession = parseRoom("session", "4:101")!;

describe("parseRoom", () => {
  it("reads the sphere out of every room name", () => {
    expect(sphereRoom).toEqual({ id: "sphere:3", kind: "sphere", sphere: "3" });
    expect(ownSession).toEqual({
      id: "session:3:101",
      kind: "session",
      session: "101",
      sphere: "3",
    });
  });

  it("rejects names that do not say which sphere the room is in", () => {
    expect(parseRoom("session", "101")).toBeNull();
    expect(parseRoom("session", "3:101:9")).toBeNull();
    expect(parseRoom("sphere", "3:101")).toBeNull();
    expect(parseRoom("sphere", "")).toBeNull();
  });
});

describe("a manager", () => {
  it("reads, writes and moderates every room of their sphere without listing it", () => {
    for (const room of [sphereRoom, ownSession, otherSession]) {
      expect(canRead(manager, room)).toBe(true);
      expect(canWrite(manager, room)).toBe(true);
      expect(canModerate(manager, room)).toBe(true);
    }
  });

  it("gets nothing in another sphere", () => {
    expect(canRead(manager, foreignSession)).toBe(false);
    expect(canWrite(manager, foreignSession)).toBe(false);
    expect(canModerate(manager, foreignSession)).toBe(false);
    expect(canRead(manager, parseRoom("sphere", "4")!)).toBe(false);
  });
});

describe("a member", () => {
  const member = capability({
    sessions: {
      "101": { endsAt: 1_900_000_000, writable: true },
      "103": { endsAt: 1_900_000_000, writable: false },
    },
  });

  it("joins the sphere room and their own sessions only", () => {
    expect(canRead(member, sphereRoom)).toBe(true);
    expect(canRead(member, ownSession)).toBe(true);
    expect(canRead(member, otherSession)).toBe(false);
    expect(canRead(member, foreignSession)).toBe(false);
  });

  it("writes only where their grant allows and never moderates", () => {
    expect(canWrite(member, sphereRoom)).toBe(true);
    expect(canWrite(member, ownSession)).toBe(true);
    expect(canWrite(member, parseRoom("session", "3:103")!)).toBe(false);
    expect(canModerate(member, sphereRoom)).toBe(false);
    expect(canModerate(member, ownSession)).toBe(false);
  });

  it("does not inherit grants from an object prototype", () => {
    expect(parseRoom("session", "3:constructor")).toBeNull();
    expect(canSeeRoom(member, "session:3:constructor")).toBe(false);
  });

  it("sees activity only for rooms they can read", () => {
    expect(canSeeRoom(member, "sphere:3")).toBe(true);
    expect(canSeeRoom(member, "session:3:101")).toBe(true);
    expect(canSeeRoom(member, "session:3:102")).toBe(false);
    expect(canSeeRoom(member, "session:4:101")).toBe(false);
    expect(canSeeRoom(member, "nonsense")).toBe(false);
    expect(canSeeRoom(manager, "session:3:102")).toBe(true);
  });
});

describe("lifecycleOf", () => {
  it("derives both deadlines from the session's end", () => {
    expect(lifecycleOf(capability(), ownSession)).toEqual({
      deleteAt: 1_900_000_000 + 30 * 24 * HOUR,
      readOnlyAt: 1_900_000_000 + 48 * HOUR,
    });
  });

  it("knows nothing for rooms the token carries no grant for", () => {
    expect(lifecycleOf(manager, ownSession)).toBeNull();
    expect(lifecycleOf(capability(), sphereRoom)).toBeNull();
    expect(lifecycleOf(capability(), otherSession)).toBeNull();
  });
});
