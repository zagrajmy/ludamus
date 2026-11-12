import {
  Agent,
  callable,
  getAgentByName,
  getCurrentAgent,
  type AgentContext,
  type AgentNamespace,
  type Connection,
  type ConnectionContext,
} from "agents";

import type { ParleyConversationAgent } from "./conversation-agent";
import type { ParleyInboxAgent } from "./inbox-agent";
import type { ParleyEventAgent, ParleyOrganizersAgent, ParleySessionAgent } from "./session-agent";
import type { ParleySphereAgent } from "./sphere-agent";

import { canModerate, canRead, canWrite, parseRoom, type Room, type RoomKind } from "./access";
import { capabilityFromRequest } from "./auth";
import { isEmoji } from "./emoji";
import { DAY_MS, integer, MESSAGE_LIFETIME_MS, normalizeMessage, retentionCutoff } from "./limits";
import { closeRevokedIn, passOf, sendWhere } from "./passes";
import {
  NOT_A_MEMBER,
  PASS_REVOKED,
  type Capability,
  type ConnectionState,
  MAX_REACTION_KINDS,
  type Message,
  type ReactionChange,
  REACTIONS,
  type Reactions,
  type Reactors,
  type Reported,
  type Revocation,
  type RpcResult,
  type ServerEvent,
} from "./protocol";

export type Env = {
  JWT_AUDIENCE: string;
  JWT_ISSUER: string;
  PARLEY_PUBLIC_KEY: string;
  ROOT_DOMAIN: string;
  // NOTE: routeAgentRequest serves each namespace under its binding name,
  // kebab-cased, and the browser addresses rooms by class name.
  ParleyConversationAgent: AgentNamespace<ParleyConversationAgent>;
  ParleyEventAgent: AgentNamespace<ParleyEventAgent>;
  ParleyInboxAgent: AgentNamespace<ParleyInboxAgent>;
  ParleyOrganizersAgent: AgentNamespace<ParleyOrganizersAgent>;
  ParleySessionAgent: AgentNamespace<ParleySessionAgent>;
  ParleySphereAgent: AgentNamespace<ParleySphereAgent>;
};

// The Durable Object behind any room, by the room Django named.
export function roomAgent(env: Env, room: Room) {
  const namespaces = {
    conversation: env.ParleyConversationAgent,
    event: env.ParleyEventAgent,
    organizers: env.ParleyOrganizersAgent,
    session: env.ParleySessionAgent,
  };
  return getAgentByName<Env, RoomAgent>(
    namespaces[room.kind] as unknown as DurableObjectNamespace<RoomAgent>,
    room.id.slice(room.id.indexOf(":") + 1),
  );
}

export { NOT_A_MEMBER };

type MessageRow = {
  author_avatar_url: string;
  author_id: string;
  author_name: string;
  body: string;
  client_nonce: string;
  created_at: number;
  deleted_at: number | null;
  id: number;
};

type ReactionRow = { emoji: string; message_id: number; user_id: string; user_name: string };

const QUICK: readonly string[] = REACTIONS;

// The quick reactions first, in their order; then any other emoji in the
// order it was first given. Rows come oldest first.
function reactionsOf(rows: ReactionRow[]): { reactions: Reactions; reactors: Reactors } {
  const rank = (emoji: string) => (QUICK.includes(emoji) ? QUICK.indexOf(emoji) : QUICK.length);
  const order = [...new Set(rows.map((row) => row.emoji))].sort((a, b) => rank(a) - rank(b));
  const reactions: Reactions = {};
  for (const emoji of order) {
    reactions[emoji] = rows.filter((row) => row.emoji === emoji).map((row) => row.user_id);
  }
  return {
    reactions,
    reactors: Object.fromEntries(rows.map((row) => [row.user_id, row.user_name])),
  };
}

export abstract class RoomAgent extends Agent<Env> {
  protected readonly agentContext: AgentContext;
  protected readonly workerEnv: Env;
  protected abstract readonly roomPrefix: RoomKind;

  constructor(context: AgentContext, env: Env) {
    super(context, env);
    this.agentContext = context;
    this.workerEnv = env;
  }

  get roomId(): string {
    return `${this.roomPrefix}:${this.name}`;
  }

  protected get room(): Room | null {
    return parseRoom(this.roomPrefix, this.name);
  }

  async onStart(): Promise<void> {
    void this.sql`CREATE TABLE IF NOT EXISTS messages (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      author_id TEXT NOT NULL,
      author_name TEXT NOT NULL,
      author_avatar_url TEXT NOT NULL DEFAULT '',
      body TEXT NOT NULL,
      client_nonce TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      deleted_at INTEGER,
      deleted_by TEXT,
      deletion_reason TEXT,
      UNIQUE(author_id, client_nonce)
    )`;
    void this.sql`CREATE INDEX IF NOT EXISTS messages_created_at ON messages (created_at)`;
    void this.sql`CREATE TABLE IF NOT EXISTS restrictions (
      user_id TEXT PRIMARY KEY,
      muted_until INTEGER,
      actor_id TEXT NOT NULL,
      updated_at INTEGER NOT NULL
    )`;
    void this.sql`CREATE TABLE IF NOT EXISTS reactions (
      message_id INTEGER NOT NULL,
      user_id TEXT NOT NULL,
      emoji TEXT NOT NULL,
      user_name TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY (message_id, user_id, emoji)
    )`;
    void this.sql`CREATE TABLE IF NOT EXISTS rate_events (
      user_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      created_at INTEGER NOT NULL
    )`;
    await this.scheduleSweep({ earliest: Date.now(), idempotent: true });
  }

  async onConnect(
    connection: Connection<ConnectionState>,
    context: ConnectionContext,
  ): Promise<void> {
    const capability = await capabilityFromRequest(context.request, this.workerEnv);
    const room = this.room;
    if (room === null || !canRead(capability, room)) throw new Error("Forbidden room");
    // SAFETY: state goes on before the deny-list is asked, so a revocation
    // landing while it answers still finds this socket to close.
    connection.setState({ admitted: false, capability });
    if (!(await this.admits(capability))) {
      connection.close(this.refusal(), "Access revoked");
      return;
    }
    if (connection.readyState !== WebSocket.OPEN) return;
    connection.setState({ admitted: true, capability });
    this.emit({ type: "presence.changed", v: 1, payload: { count: this.presentUsers() } });
  }

  protected abstract admits(capability: Capability): Promise<boolean>;

  // How a refused admission closes; a pass close, unless a room says otherwise.
  protected refusal(): number {
    return PASS_REVOKED;
  }

  closeRevoked(revocation: Pick<Revocation, "revokedBefore" | "sub">): void {
    closeRevokedIn(this.getConnections<ConnectionState>(), revocation);
  }

  onClose(): void {
    this.emit({ type: "presence.changed", v: 1, payload: { count: this.presentUsers() } });
  }

  @callable()
  sendMessage(input: { body?: unknown; nonce?: unknown }): RpcResult<Message> {
    const capability = this.currentCapability();
    const writeError = this.writeError(capability);
    if (writeError !== null) return writeError;
    const body = normalizeMessage(input?.body);
    if (
      body === null ||
      typeof input?.nonce !== "string" ||
      input.nonce.length === 0 ||
      input.nonce.length > 100
    ) {
      return { ok: false, code: "invalid" };
    }
    this.purgeExpiredMessages();
    const existing = this
      .sql<MessageRow>`SELECT * FROM messages WHERE author_id = ${capability.sub} AND client_nonce = ${input.nonce}`[0];
    if (existing !== undefined)
      return { ok: true, value: this.message(existing, this.reactionsFor(existing.id)) };
    if (
      !this.consumeRate(capability.sub, "message", 5, 10_000) ||
      !this.consumeRate(capability.sub, "message-minute", 30, 60_000)
    ) {
      return { ok: false, code: "rate_limited" };
    }
    const now = Date.now();
    void this
      .sql`INSERT INTO messages (author_id, author_name, author_avatar_url, body, client_nonce, created_at)
      VALUES (${capability.sub}, ${capability.name}, ${capability.avatar}, ${body}, ${input.nonce}, ${now})`;
    const row = this
      .sql<MessageRow>`SELECT * FROM messages WHERE author_id = ${capability.sub} AND client_nonce = ${input.nonce}`[0];
    const message = this.message(row, { reactions: {}, reactors: {} });
    this.emit({ type: "message.created", v: 1, payload: message });
    void this.scheduleSweep({ earliest: now, idempotent: true });
    this.afterMessage(message);
    return { ok: true, value: message };
  }

  @callable()
  loadBefore(input: { beforeId?: unknown; limit?: unknown }): RpcResult<Message[]> {
    const capability = this.currentCapability();
    if (!this.consumeRate(capability.sub, "history", 5, 1_000))
      return { ok: false, code: "rate_limited" };
    const beforeId =
      input?.beforeId === undefined ? Number.MAX_SAFE_INTEGER : integer(input.beforeId);
    if (beforeId === null) return { ok: false, code: "invalid" };
    const limit = input?.limit === undefined ? 50 : integer(input.limit);
    if (limit === null) return { ok: false, code: "invalid" };
    this.purgeExpiredMessages();
    const rows = this
      .sql<MessageRow>`SELECT * FROM messages WHERE id < ${beforeId} ORDER BY id DESC LIMIT ${Math.min(limit, 50)}`;
    return { ok: true, value: this.messages(rows.reverse()) };
  }

  @callable()
  deleteOwnMessage(input: { messageId?: unknown }): RpcResult<{ id: number }> {
    const capability = this.currentCapability();
    const messageId = integer(input?.messageId);
    if (messageId === null) return { ok: false, code: "invalid" };
    this.purgeExpiredMessages();
    const row = this.sql<{
      author_id: string;
      deleted_at: number | null;
    }>`SELECT author_id, deleted_at FROM messages WHERE id = ${messageId}`[0];
    if (row === undefined || row.author_id !== capability.sub)
      return { ok: false, code: "forbidden" };
    if (row.deleted_at === null) {
      void this
        .sql`UPDATE messages SET deleted_at = ${Date.now()}, deleted_by = ${capability.sub}, deletion_reason = 'author' WHERE id = ${messageId}`;
      void this.sql`DELETE FROM reactions WHERE message_id = ${messageId}`;
      this.emit({ type: "message.deleted", v: 1, payload: { id: messageId } });
    }
    return { ok: true, value: { id: messageId } };
  }

  @callable()
  deleteMessage(input: { messageId?: unknown }): RpcResult<{ id: number }> {
    const capability = this.currentCapability();
    if (!this.moderates(capability)) return { ok: false, code: "forbidden" };
    const messageId = integer(input?.messageId);
    if (messageId === null) return { ok: false, code: "invalid" };
    this.purgeExpiredMessages();
    const row = this.sql<{
      deleted_at: number | null;
    }>`SELECT deleted_at FROM messages WHERE id = ${messageId}`[0];
    if (row === undefined) return { ok: false, code: "invalid" };
    if (row.deleted_at === null) {
      void this
        .sql`UPDATE messages SET deleted_at = ${Date.now()}, deleted_by = ${capability.sub}, deletion_reason = 'moderator' WHERE id = ${messageId}`;
      void this.sql`DELETE FROM reactions WHERE message_id = ${messageId}`;
      this.emit({ type: "message.deleted", v: 1, payload: { id: messageId } });
    }
    return { ok: true, value: { id: messageId } };
  }

  // Whoever may write here may react: the same call adds a reaction and,
  // once held, takes it back.
  @callable()
  toggleReaction(input: { emoji?: unknown; messageId?: unknown }): RpcResult<ReactionChange> {
    const capability = this.currentCapability();
    const writeError = this.writeError(capability);
    if (writeError !== null) return writeError;
    const messageId = integer(input?.messageId);
    if (messageId === null || !isEmoji(input?.emoji)) return { ok: false, code: "invalid" };
    const emoji = input.emoji;
    this.purgeExpiredMessages();
    const row = this.sql<{
      deleted_at: number | null;
    }>`SELECT deleted_at FROM messages WHERE id = ${messageId}`[0];
    if (row === undefined || row.deleted_at !== null) return { ok: false, code: "invalid" };
    if (
      !this.consumeRate(capability.sub, "reaction", 10, 10_000) ||
      !this.consumeRate(capability.sub, "reaction-minute", 60, 60_000)
    ) {
      return { ok: false, code: "rate_limited" };
    }
    const held = this.sql<{ held: number }>`SELECT COUNT(*) AS held FROM reactions
      WHERE message_id = ${messageId} AND user_id = ${capability.sub} AND emoji = ${emoji}`[0]!;
    if (held.held > 0) {
      void this.sql`DELETE FROM reactions
        WHERE message_id = ${messageId} AND user_id = ${capability.sub} AND emoji = ${emoji}`;
    } else {
      const kinds = this.sql<{ emoji: string }>`SELECT DISTINCT emoji FROM reactions
        WHERE message_id = ${messageId}`.map((kind) => kind.emoji);
      if (!kinds.includes(emoji) && kinds.length >= MAX_REACTION_KINDS)
        return { ok: false, code: "full" };
      void this.sql`INSERT INTO reactions (message_id, user_id, emoji, user_name, created_at)
        VALUES (${messageId}, ${capability.sub}, ${emoji}, ${capability.name}, ${Date.now()})`;
    }
    const change = { messageId, ...this.reactionsFor(messageId) };
    this.emit({ type: "reaction.changed", v: 1, payload: change });
    return { ok: true, value: change };
  }

  @callable()
  muteUser(input: { durationMs?: unknown; userId?: unknown }): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    if (!this.moderates(capability) || typeof input?.userId !== "string") {
      return { ok: false, code: "forbidden" };
    }
    const allowedDurations = new Set([3_600_000, 86_400_000, 604_800_000]);
    if (
      input.durationMs !== null &&
      (typeof input.durationMs !== "number" || !allowedDurations.has(input.durationMs))
    ) {
      return { ok: false, code: "invalid" };
    }
    const mutedUntil = input.durationMs === null ? null : Date.now() + input.durationMs;
    void this.sql`INSERT INTO restrictions (user_id, muted_until, actor_id, updated_at)
      VALUES (${input.userId}, ${mutedUntil}, ${capability.sub}, ${Date.now()})
      ON CONFLICT(user_id) DO UPDATE SET muted_until = excluded.muted_until, actor_id = excluded.actor_id, updated_at = excluded.updated_at`;
    this.emit({ type: "restriction.changed", v: 1, payload: { mutedUntil, userId: input.userId } });
    return { ok: true, value: {} };
  }

  @callable()
  restoreWriting(input: { userId?: unknown }): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    if (!this.moderates(capability) || typeof input?.userId !== "string") {
      return { ok: false, code: "forbidden" };
    }
    void this.sql`DELETE FROM restrictions WHERE user_id = ${input.userId}`;
    this.emit({
      type: "restriction.changed",
      v: 1,
      payload: { mutedUntil: 0, userId: input.userId },
    });
    return { ok: true, value: {} };
  }

  @callable()
  loadAround(input: { messageId?: unknown }): RpcResult<Message[]> {
    const capability = this.currentCapability();
    const messageId = integer(input?.messageId);
    if (!this.moderates(capability) || messageId === null) return { ok: false, code: "forbidden" };
    this.purgeExpiredMessages();
    const rows = this
      .sql<MessageRow>`SELECT * FROM messages WHERE id BETWEEN ${Math.max(1, messageId - 10)} AND ${messageId + 10} ORDER BY id`;
    return { ok: true, value: this.messages(rows) };
  }

  @callable()
  startTyping(): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    const error = this.writeError(capability);
    if (error !== null) return error;
    this.emit({
      type: "typing.changed",
      v: 1,
      payload: { expiresAt: Date.now() + 5_000, userId: capability.sub },
    });
    return { ok: true, value: {} };
  }

  @callable()
  stopTyping(): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    this.emit({
      type: "typing.changed",
      v: 1,
      payload: { expiresAt: Date.now(), userId: capability.sub },
    });
    return { ok: true, value: {} };
  }

  protected afterMessage(_message: Message): void {}

  protected currentCapability(): Capability {
    return passOf(
      getCurrentAgent<RoomAgent>().connection as Connection<ConnectionState> | undefined,
    );
  }

  protected moderates(capability: Capability): boolean {
    const room = this.room;
    return room !== null && canModerate(capability, room);
  }

  protected emit(event: ServerEvent): void {
    sendWhere(this.getConnections<ConnectionState>(), event);
  }

  protected emitTo(userId: string, event: ServerEvent): void {
    sendWhere(
      this.getConnections<ConnectionState>(),
      event,
      (capability) => capability.sub === userId,
    );
  }

  protected writeError(capability: Capability): Extract<RpcResult<never>, { ok: false }> | null {
    const room = this.room;
    if (room === null || !canWrite(capability, room)) return { ok: false, code: "forbidden" };
    const restriction = this.sql<{
      muted_until: number | null;
    }>`SELECT muted_until FROM restrictions WHERE user_id = ${capability.sub}`[0];
    if (
      restriction !== undefined &&
      (restriction.muted_until === null || restriction.muted_until > Date.now())
    ) {
      return { ok: false, code: "muted" };
    }
    return null;
  }

  // People, not sockets: one person holds several, a tab each and the
  // sphere feed beside its room.
  private presentUsers(): number {
    const users = new Set<string>();
    for (const connection of this.getConnections<ConnectionState>()) {
      if (connection.state?.admitted) users.add(connection.state.capability.sub);
    }
    return users.size;
  }

  private consumeRate(userId: string, kind: string, maximum: number, windowMs: number): boolean {
    const now = Date.now();
    void this.sql`DELETE FROM rate_events WHERE created_at <= ${now - 60_000}`;
    const count =
      this.sql<{ count: number }>`SELECT COUNT(*) AS count FROM rate_events
      WHERE user_id = ${userId} AND kind = ${kind} AND created_at > ${now - windowMs}`[0]?.count ??
      0;
    if (count >= maximum) return false;
    void this
      .sql`INSERT INTO rate_events (user_id, kind, created_at) VALUES (${userId}, ${kind}, ${now})`;
    return true;
  }

  // Not @callable: staff, acting on a report from a room nobody moderates,
  // delete over the Worker's own fetch. Answers whether the room has it.
  deleteAsStaff(id: number): boolean {
    this.purgeExpiredMessages();
    const row = this.sql<{
      deleted_at: number | null;
    }>`SELECT deleted_at FROM messages WHERE id = ${id}`[0];
    if (row === undefined) return false;
    if (row.deleted_at === null) {
      void this
        .sql`UPDATE messages SET deleted_at = ${Date.now()}, deleted_by = 'staff', deletion_reason = 'staff' WHERE id = ${id}`;
      void this.sql`DELETE FROM reactions WHERE message_id = ${id}`;
      this.emit({ type: "message.deleted", v: 1, payload: { id } });
    }
    return true;
  }

  // Not @callable: Django asks, over the Worker's own fetch, to keep a copy
  // of a reported message. A deleted one keeps its words for that.
  readMessage(id: number): Reported | null {
    this.purgeExpiredMessages();
    const row = this.sql<MessageRow>`SELECT * FROM messages WHERE id = ${id}`[0];
    if (row === undefined) return null;
    return {
      authorId: row.author_id,
      authorName: row.author_name,
      body: row.body,
      createdAt: row.created_at,
      deletedAt: row.deleted_at,
    };
  }

  private messages(rows: MessageRow[]): Message[] {
    if (rows.length === 0) return [];
    const ids = rows.map((row) => row.id);
    const held = this.sql<ReactionRow>`SELECT emoji, message_id, user_id, user_name FROM reactions
      WHERE message_id BETWEEN ${Math.min(...ids)} AND ${Math.max(...ids)}
      ORDER BY created_at, rowid`;
    return rows.map((row) =>
      this.message(row, reactionsOf(held.filter((reaction) => reaction.message_id === row.id))),
    );
  }

  private reactionsFor(messageId: number): { reactions: Reactions; reactors: Reactors } {
    return reactionsOf(
      this.sql<ReactionRow>`SELECT emoji, message_id, user_id, user_name FROM reactions
        WHERE message_id = ${messageId} ORDER BY created_at, rowid`,
    );
  }

  // The one place a message is deleted for good. Every read purges first,
  // so a late alarm never lets a message outlive its year.
  // NOTE: a table keyed by message id deletes its rows here, before the
  // messages that name them.
  protected purgeExpiredMessages(): void {
    const cutoff = retentionCutoff();
    void this.sql`DELETE FROM reactions
      WHERE message_id IN (SELECT id FROM messages WHERE created_at <= ${cutoff})`;
    void this.sql`DELETE FROM messages WHERE created_at <= ${cutoff}`;
  }

  // Not @callable: the room's own alarm runs it.
  async sweepExpiredMessages(): Promise<void> {
    this.purgeExpiredMessages();
    await this.scheduleSweep({ earliest: Date.now() + DAY_MS, idempotent: false });
  }

  // One sweep pending at a time, due once the oldest message turns a year
  // old, and never before `earliest`. A room with no messages sets none.
  // NOTE: a one-shot schedule stays listed until its callback returns, so
  // the sweep's own reschedule skips the dedup, which would find itself.
  private async scheduleSweep(options: { earliest: number; idempotent: boolean }): Promise<void> {
    const oldest = this.sql<{
      created_at: number;
    }>`SELECT created_at FROM messages ORDER BY created_at LIMIT 1`[0];
    if (oldest === undefined) return;
    await this.schedule(
      new Date(Math.max(oldest.created_at + MESSAGE_LIFETIME_MS, options.earliest)),
      "sweepExpiredMessages",
      undefined,
      { idempotent: options.idempotent },
    );
  }

  private message(
    row: MessageRow,
    { reactions, reactors }: { reactions: Reactions; reactors: Reactors },
  ): Message {
    return {
      authorAvatarUrl: row.author_avatar_url,
      authorId: row.author_id,
      authorName: row.author_name,
      body: row.deleted_at === null ? row.body : "",
      createdAt: row.created_at,
      deletedAt: row.deleted_at,
      id: row.id,
      nonce: row.client_nonce,
      reactions,
      reactors,
    };
  }
}
