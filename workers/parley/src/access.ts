import type { Capability } from "./protocol";

export type Room =
  | { id: string; kind: "conversation"; conversation: string }
  | { id: string; kind: "session"; session: string; sphere: string }
  | { id: string; kind: "sphere"; sphere: string };

export type Lifecycle = { deleteAt: number; readOnlyAt: number };

const SPHERE_NAME = /^(\d+)$/u;
const SESSION_NAME = /^(\d+):(\d+)$/u;

// A session room is named "<sphere>:<session>" so the sphere a manager's
// token covers can be checked against the room itself.
export function parseRoom(kind: Room["kind"], name: string): Room | null {
  if (kind === "conversation") {
    return SPHERE_NAME.test(name) ? { conversation: name, id: `conversation:${name}`, kind } : null;
  }
  if (kind === "sphere") {
    const match = SPHERE_NAME.exec(name);
    return match === null ? null : { id: `sphere:${name}`, kind, sphere: match[1] };
  }
  const match = SESSION_NAME.exec(name);
  return match === null
    ? null
    : { id: `session:${name}`, kind, session: match[2], sphere: match[1] };
}

function parseRoomId(roomId: string): Room | null {
  const separator = roomId.indexOf(":");
  const kind = roomId.slice(0, separator);
  if (separator < 0 || (kind !== "sphere" && kind !== "session")) return null;
  return parseRoom(kind, roomId.slice(separator + 1));
}

function grant(capability: Capability, room: Room) {
  return room.kind === "session" && Object.hasOwn(capability.sessions, room.session)
    ? capability.sessions[room.session]
    : undefined;
}

// A conversation's own member list decides who is in it; the pass only says
// whether conversations are open to this person at all.
export function canRead(capability: Capability, room: Room): boolean {
  if (room.kind === "conversation") return capability.direct === true;
  if (room.sphere !== capability.sphere) return false;
  return (
    room.kind === "sphere" || capability.role === "manager" || grant(capability, room) !== undefined
  );
}

export function canWrite(capability: Capability, room: Room): boolean {
  if (!canRead(capability, room)) return false;
  // The member list says who may write in a conversation, and when.
  if (room.kind === "conversation") return true;
  return (
    room.kind === "sphere" ||
    capability.role === "manager" ||
    grant(capability, room)?.writable === true
  );
}

export function canModerate(capability: Capability, room: Room): boolean {
  return room.kind !== "conversation" && capability.role === "manager" && canRead(capability, room);
}

export function canSeeRoom(capability: Capability, roomId: string): boolean {
  const room = parseRoomId(roomId);
  return room !== null && canRead(capability, room);
}

export function lifecycleOf(capability: Capability, room: Room): Lifecycle | null {
  const session = grant(capability, room);
  if (session === undefined) return null;
  return {
    deleteAt: session.endsAt + capability.retainFor,
    readOnlyAt: session.endsAt + capability.readOnlyAfter,
  };
}
