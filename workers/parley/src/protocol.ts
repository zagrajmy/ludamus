export type RoomKind = "sphere" | "session";

export type Capability = {
  aud: "parley";
  avatar: string;
  exp: number;
  iat: number;
  iss: "ludamus";
  jti: string;
  lifecycle?: Record<string, { deleteAt: number; readOnlyAt: number }>;
  moderates: string[];
  name: string;
  rooms: string[];
  sphere: string;
  sub: string;
  writes: string[];
};

export type ConnectionState = {
  capability: Capability;
};

export type Message = {
  authorAvatarUrl: string;
  authorId: string;
  authorName: string;
  body: string;
  createdAt: number;
  deletedAt: number | null;
  id: number;
  nonce: string;
};

export type ServerEvent =
  | { type: "message.created"; v: 1; payload: Message }
  | { type: "message.deleted"; v: 1; payload: { id: number } }
  | { type: "presence.changed"; v: 1; payload: { count: number } }
  | { type: "typing.changed"; v: 1; payload: { expiresAt: number; userId: string } }
  | { type: "restriction.changed"; v: 1; payload: { mutedUntil: number | null; userId: string } }
  | { type: "room.archived"; v: 1; payload: Record<string, never> }
  | { type: "room.activity"; v: 1; payload: { latestMessageId: number; roomId: string } }
  | { type: "unread.changed"; v: 1; payload: { roomId: string; unread: boolean } };

export type RpcError = {
  code: "archived" | "expired" | "forbidden" | "invalid" | "muted" | "rate_limited";
  ok: false;
};

export type RpcResult<T> = { ok: true; value: T } | RpcError;
