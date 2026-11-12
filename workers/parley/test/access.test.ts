import { describe, expect, it } from "vitest";

import type { Capability, EventGrant } from "../src/protocol";

import {
  canModerate,
  canRead,
  canSeeRoom,
  canWrite,
  inSphere,
  lifecycleOf,
  parseRoom,
  roomFromId,
} from "../src/access";

const HOUR = 3_600;
const ENDS = 1_900_000_000;

const event = (sessions: Record<string, boolean>, fields: Partial<EventGrant> = {}) => ({
  chat: true,
  endsAt: ENDS,
  sessions,
  writable: true,
  ...fields,
});

function capability(overrides: Partial<Capability> = {}): Capability {
  return {
    aud: "parley",
    avatar: "",
    events: { "3:9": event({ "101": true }) },
    exp: 2_000_000_000,
    iat: 1_900_000_000,
    iss: "ludamus",
    jti: "token",
    managed: {},
    name: "Ada",
    readOnlyAfter: 48 * HOUR,
    retainFor: 30 * 24 * HOUR,
    sub: "7",
    ...overrides,
  };
}

const manager = capability({
  events: { "3:9": event({}) },
  managed: { "3": { organizers: true } },
});
const organizers = parseRoom("organizers", "3")!;
const ownEvent = parseRoom("event", "3:9")!;
const otherEvent = parseRoom("event", "3:10")!;
const ownSession = parseRoom("session", "3:101")!;
const otherSession = parseRoom("session", "3:102")!;
const foreignSession = parseRoom("session", "4:101")!;
const conversation = parseRoom("conversation", "12")!;

describe("parseRoom", () => {
  it("reads the sphere out of every sphere room's name", () => {
    expect(organizers).toEqual({ id: "organizers:3", kind: "organizers", sphere: "3" });
    expect(ownSession).toEqual({
      id: "session:3:101",
      kind: "session",
      name: "3:101",
      pk: "101",
      sphere: "3",
    });
  });

  it("rejects names that do not say which sphere the room is in", () => {
    expect(parseRoom("session", "101")).toBeNull();
    expect(parseRoom("event", "3:9:1")).toBeNull();
    expect(parseRoom("organizers", "3:101")).toBeNull();
    expect(parseRoom("conversation", "3:4")).toBeNull();
  });

  it("finds any room by its full id, and nothing for the old common room", () => {
    expect(roomFromId("event:3:9")).toEqual(ownEvent);
    expect(roomFromId("conversation:12")).toEqual(conversation);
    expect(roomFromId("sphere:3")).toBeNull();
    expect(roomFromId("nonsense")).toBeNull();
  });
});

describe("a manager", () => {
  it("reads, writes and moderates every programme point of their sphere without listing it", () => {
    for (const room of [organizers, ownEvent, ownSession, otherSession]) {
      expect(canRead(manager, room)).toBe(true);
      expect(canWrite(manager, room)).toBe(true);
      expect(canModerate(manager, room)).toBe(true);
    }
  });

  it("enters an event's chat only on its grant, which says when it closes", () => {
    expect(canRead(manager, otherEvent)).toBe(false);
    const archived = capability({
      events: { "3:9": event({}, { writable: false }) },
      managed: { "3": { organizers: true } },
    });
    expect(canRead(archived, ownEvent)).toBe(true);
    expect(canWrite(archived, ownEvent)).toBe(false);
    expect(lifecycleOf(manager, ownEvent)).toEqual({
      deleteAt: ENDS + 30 * 24 * HOUR,
      readOnlyAt: ENDS + 48 * HOUR,
    });
  });

  it("is kept out of the organizers' room once the sphere closes it", () => {
    const closed = capability({ events: {}, managed: { "3": { organizers: false } } });
    expect(canRead(closed, organizers)).toBe(false);
    expect(canWrite(closed, organizers)).toBe(false);
    expect(canRead(closed, otherSession)).toBe(true);
  });

  it("gets nothing in another sphere", () => {
    expect(canRead(manager, foreignSession)).toBe(false);
    expect(canModerate(manager, foreignSession)).toBe(false);
    expect(canRead(manager, parseRoom("organizers", "4")!)).toBe(false);
  });
});

describe("a member", () => {
  const member = capability({
    events: {
      "3:9": event({ "101": true, "103": false }),
      "4:20": event({ "201": true }, { chat: false }),
    },
  });

  it("joins their own events and programme points, in every sphere, and nothing else", () => {
    expect(canRead(member, ownEvent)).toBe(true);
    expect(canRead(member, ownSession)).toBe(true);
    expect(canRead(member, parseRoom("session", "4:201")!)).toBe(true);
    expect(canRead(member, parseRoom("event", "4:20")!)).toBe(false);
    expect(canRead(member, otherEvent)).toBe(false);
    expect(canRead(member, otherSession)).toBe(false);
    expect(canRead(member, foreignSession)).toBe(false);
    expect(canRead(member, organizers)).toBe(false);
  });

  it("writes only where their grant allows and never moderates", () => {
    expect(canWrite(member, ownEvent)).toBe(true);
    expect(canWrite(member, ownSession)).toBe(true);
    expect(canWrite(member, parseRoom("session", "3:103")!)).toBe(false);
    expect(
      canWrite(capability({ events: { "3:9": event({}, { writable: false }) } }), ownEvent),
    ).toBe(false);
    expect(canModerate(member, ownEvent)).toBe(false);
  });

  it("does not inherit grants from an object prototype", () => {
    expect(parseRoom("session", "3:constructor")).toBeNull();
    expect(canSeeRoom(member, "session:3:constructor")).toBe(false);
    expect(canRead(capability({ events: {} }), parseRoom("event", "3:9")!)).toBe(false);
  });

  it("sees activity only for rooms they can read", () => {
    expect(canSeeRoom(member, "event:3:9")).toBe(true);
    expect(canSeeRoom(member, "session:3:101")).toBe(true);
    expect(canSeeRoom(member, "session:3:102")).toBe(false);
    expect(canSeeRoom(member, "organizers:3")).toBe(false);
    expect(canSeeRoom(member, "conversation:12")).toBe(false);
    expect(canSeeRoom(manager, "organizers:3")).toBe(true);
  });
});

describe("a sphere's feed", () => {
  it("reaches whoever has a room in the sphere", () => {
    expect(inSphere(capability(), "3")).toBe(true);
    expect(inSphere(manager, "3")).toBe(true);
    expect(inSphere(capability({ events: {} }), "3")).toBe(false);
    expect(inSphere(capability(), "4")).toBe(false);
  });
});

describe("a conversation", () => {
  it("is left to its own member list", () => {
    expect(canRead(capability(), conversation)).toBe(true);
    expect(canWrite(capability(), conversation)).toBe(true);
    expect(canModerate(manager, conversation)).toBe(false);
  });
});

describe("lifecycleOf", () => {
  it("derives both deadlines from the event's end", () => {
    for (const room of [ownSession, ownEvent]) {
      expect(lifecycleOf(capability(), room)).toEqual({
        deleteAt: ENDS + 30 * 24 * HOUR,
        readOnlyAt: ENDS + 48 * HOUR,
      });
    }
  });

  it("knows nothing for rooms the token carries no grant for", () => {
    expect(lifecycleOf(manager, ownSession)).toBeNull();
    expect(lifecycleOf(capability(), organizers)).toBeNull();
    expect(lifecycleOf(capability(), otherSession)).toBeNull();
  });
});
