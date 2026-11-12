import type { Capability, RoomGrant } from "./protocol";

// A sphere's rooms are named after the sphere first, so the sphere a
// manager's token covers can be checked against the room itself.
export type SphereRoom =
  | { id: string; kind: "event" | "session"; name: string; sphere: string }
  | { id: string; kind: "organizers" | "sphere"; sphere: string };

export type Room = { conversation: string; id: string; kind: "conversation" } | SphereRoom;

export type RoomKind = Room["kind"];

export type Lifecycle = { deleteAt: number; readOnlyAt: number };

const SPHERE_NAME = /^(\d+)$/u;
const ROOM_NAME = /^(\d+):(\d+)$/u;
const KINDS: readonly string[] = ["conversation", "event", "organizers", "session", "sphere"];

export function parseRoom(kind: RoomKind, name: string): Room | null {
  const id = `${kind}:${name}`;
  if (kind === "conversation") {
    return SPHERE_NAME.test(name) ? { conversation: name, id, kind } : null;
  }
  if (kind === "organizers" || kind === "sphere") {
    const match = SPHERE_NAME.exec(name);
    return match === null ? null : { id, kind, sphere: match[1] };
  }
  const match = ROOM_NAME.exec(name);
  return match === null ? null : { id, kind, name, sphere: match[1] };
}

// Any room by its full id, as Django names it.
export function roomFromId(roomId: string): Room | null {
  const separator = roomId.indexOf(":");
  const kind = roomId.slice(0, separator);
  if (separator < 0 || !KINDS.includes(kind)) return null;
  return parseRoom(kind as RoomKind, roomId.slice(separator + 1));
}

function manages(capability: Capability, sphere: string): boolean {
  return capability.managed.includes(sphere);
}

function grant(capability: Capability, room: Room): RoomGrant | undefined {
  if (room.kind !== "event" && room.kind !== "session") return undefined;
  const grants = room.kind === "event" ? capability.events : capability.sessions;
  return Object.hasOwn(grants, room.name) ? grants[room.name] : undefined;
}

function inSphere(capability: Capability, sphere: string): boolean {
  return (
    manages(capability, sphere) ||
    [...Object.keys(capability.events), ...Object.keys(capability.sessions)].some((name) =>
      name.startsWith(`${sphere}:`),
    )
  );
}

// A conversation's own member list decides who is in it.
export function canRead(capability: Capability, room: Room): boolean {
  if (room.kind === "conversation") return true;
  if (room.kind === "sphere") return inSphere(capability, room.sphere);
  return manages(capability, room.sphere) || grant(capability, room) !== undefined;
}

export function canWrite(capability: Capability, room: Room): boolean {
  if (room.kind === "sphere" || !canRead(capability, room)) return false;
  if (room.kind === "conversation" || room.kind === "organizers") return true;
  return manages(capability, room.sphere) || grant(capability, room)?.writable === true;
}

export function canModerate(capability: Capability, room: Room): boolean {
  return room.kind !== "conversation" && room.kind !== "sphere" && manages(capability, room.sphere);
}

export function canSeeRoom(capability: Capability, roomId: string): boolean {
  const room = roomFromId(roomId);
  return (
    room !== null &&
    room.kind !== "conversation" &&
    room.kind !== "sphere" &&
    canRead(capability, room)
  );
}

export function lifecycleOf(capability: Capability, room: Room): Lifecycle | null {
  const held = grant(capability, room);
  if (held === undefined) return null;
  return {
    deleteAt: held.endsAt + capability.retainFor,
    readOnlyAt: held.endsAt + capability.readOnlyAfter,
  };
}
