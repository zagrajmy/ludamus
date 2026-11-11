export type RoomKind = "conversation" | "session" | "sphere";

export type SessionGrant = { endsAt: number; writable: boolean };

// The token holds a role, not a list of rooms: a manager covers every room of
// the sphere, a member the sphere room plus the sessions they take part in.
export type Capability = {
  aud: "parley";
  avatar: string;
  // Whether direct and group conversations are open to this person at all.
  direct?: boolean;
  exp: number;
  iat: number;
  iss: "ludamus";
  jti: string;
  name: string;
  readOnlyAfter: number;
  retainFor: number;
  role: "manager" | "member";
  sessions: Record<string, SessionGrant>;
  sphere: string;
  sub: string;
};

export type MemberState = "active" | "request";

export type Member = { state: MemberState; user: string; writable: boolean };

// Who is in a conversation, as Django last saw it. A newer one replaces it whole.
export type Membership = {
  conversation: string;
  iat: number;
  kind: "direct" | "group";
  members: Member[];
};

// "Every pass this sphere issued to sub before revokedBefore is void"; sub
// "*" covers everyone in the sphere. It matters until those passes would
// have expired on their own, which is the revocation's own exp.
export type Reported = Pick<
  Message,
  "authorId" | "authorName" | "body" | "createdAt" | "deletedAt"
>;

// Django asking after one message, to keep a copy with a report of it.
export type Lookup = { messageId: number; room: string };

export type Revocation = {
  exp: number;
  revokedBefore: number;
  sphere: string;
  sub: string;
};

// NOTE: application close codes the browser reads as "fetch a new pass",
// never as a reason to retry the same one.
export const PASS_EXPIRED = 4401;
export const PASS_REVOKED = 4403;
// Not on the conversation's member list, or not yet: the socket redials, as
// it would after any drop, rather than fetching a new pass.
export const NOT_A_MEMBER = 4404;

// Admission waits on the sphere's deny-list; until it answers the socket
// holds a pass but hears nothing.
export type ConnectionState = {
  admitted: boolean;
  capability: Capability;
};

// The only reactions a room takes, in the order they are shown.
export const REACTIONS = ["👍", "❤️", "😂", "😮", "😢", "🎲"] as const;

export type Reaction = (typeof REACTIONS)[number];

// Who reacted with what; a reaction nobody holds is left out.
export type Reactions = Partial<Record<Reaction, string[]>>;

export type Message = {
  authorAvatarUrl: string;
  authorId: string;
  authorName: string;
  body: string;
  createdAt: number;
  deletedAt: number | null;
  id: number;
  nonce: string;
  reactions: Reactions;
};

export type ReactionChange = { messageId: number; reactions: Reactions };

export type ServerEvent =
  | { type: "message.created"; v: 1; payload: Message }
  | { type: "message.deleted"; v: 1; payload: { id: number } }
  | { type: "reaction.changed"; v: 1; payload: ReactionChange }
  | { type: "presence.changed"; v: 1; payload: { count: number } }
  | { type: "typing.changed"; v: 1; payload: { expiresAt: number; userId: string } }
  | { type: "restriction.changed"; v: 1; payload: { mutedUntil: number | null; userId: string } }
  | { type: "room.archived"; v: 1; payload: Record<string, never> }
  | {
      type: "room.activity";
      v: 1;
      payload: { at: number; latestMessageId: number; roomId: string };
    }
  | { type: "unread.changed"; v: 1; payload: { roomId: string; unread: boolean } };

export type RoomActivity = { at: number; unread: boolean };

export type RpcError = {
  // pending: a request not yet accepted takes one message, no more.
  code: "archived" | "forbidden" | "invalid" | "muted" | "pending" | "rate_limited";
  ok: false;
};

export type RpcResult<T> = { ok: true; value: T } | RpcError;
