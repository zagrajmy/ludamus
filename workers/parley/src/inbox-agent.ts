import { Agent, callable, getCurrentAgent, type Connection, type ConnectionContext } from "agents";

import type { Env } from "./room-agent";

import { capabilityFromRequest } from "./auth";
import { retentionCutoff } from "./limits";
import { passOf, sendWhere } from "./passes";
import {
  PASS_REVOKED,
  type Capability,
  type ConnectionState,
  type RoomActivity,
  type RpcResult,
  type ServerEvent,
} from "./protocol";

type ActivityRow = {
  latest_message_id: number;
  last_read_message_id: number | null;
  room_id: string;
  updated_at: number;
};

// One person's view across their conversations: which have news, and what
// they have read. Named by user id; nobody else opens it.
export class ParleyInboxAgent extends Agent<Env> {
  async onStart(): Promise<void> {
    void this.sql`CREATE TABLE IF NOT EXISTS room_activity (
      room_id TEXT PRIMARY KEY,
      latest_message_id INTEGER NOT NULL,
      last_read_message_id INTEGER,
      updated_at INTEGER NOT NULL
    )`;
    void this.sql`CREATE TABLE IF NOT EXISTS unread_mentions (
      room_id TEXT NOT NULL,
      message_id INTEGER NOT NULL,
      author_id TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      PRIMARY KEY (room_id, message_id)
    )`;
  }

  async onConnect(
    connection: Connection<ConnectionState>,
    context: ConnectionContext,
  ): Promise<void> {
    const capability = await capabilityFromRequest(context.request, this.env);
    if (capability.sub !== this.name) {
      connection.close(PASS_REVOKED, "Not this person's inbox");
      return;
    }
    connection.setState({ admitted: true, capability });
  }

  @callable()
  getActivity(): RpcResult<Record<string, RoomActivity>> {
    this.currentCapability();
    this.purgeExpiredActivity();
    const rows = this.sql<ActivityRow>`SELECT * FROM room_activity`;
    return {
      ok: true,
      value: Object.fromEntries(
        rows.map((row) => [
          row.room_id,
          {
            at: row.updated_at,
            mentionedBy: this.mentionedBy(row.room_id),
            unread: row.latest_message_id > (row.last_read_message_id ?? 0),
          },
        ]),
      ),
    };
  }

  @callable()
  markRead(input: { messageId?: unknown; roomId?: unknown }): RpcResult<Record<string, never>> {
    this.currentCapability();
    if (typeof input?.roomId !== "string" || typeof input.messageId !== "number") {
      return { code: "invalid", ok: false };
    }
    this.read(input.roomId, input.messageId);
    return { ok: true, value: {} };
  }

  // Not @callable: only a conversation room reaches this, over Durable
  // Object RPC, so a browser cannot forge activity.
  recordActivity(input: {
    authorId: string;
    latestMessageId: number;
    mentions: string[];
    roomId: string;
  }): void {
    this.purgeExpiredActivity();
    const now = Date.now();
    if (input.authorId !== this.name && input.mentions.includes(this.name)) {
      void this.sql`INSERT INTO unread_mentions (room_id, message_id, author_id, created_at)
        VALUES (${input.roomId}, ${input.latestMessageId}, ${input.authorId}, ${now})
        ON CONFLICT(room_id, message_id) DO NOTHING`;
    }
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${input.roomId}, ${input.latestMessageId}, ${now})
      ON CONFLICT(room_id) DO UPDATE SET
        latest_message_id = MAX(latest_message_id, excluded.latest_message_id),
        updated_at = excluded.updated_at`;
    this.emit({
      payload: {
        at: now,
        latestMessageId: input.latestMessageId,
        mentionedBy: this.mentionedBy(input.roomId),
        roomId: input.roomId,
      },
      type: "room.activity",
      v: 1,
    });
    // One's own message is read by definition.
    if (input.authorId === this.name) this.read(input.roomId, input.latestMessageId);
  }

  // Activity a year old points only at messages its room has deleted, so an
  // unread flag for one never lingers.
  private purgeExpiredActivity(): void {
    const cutoff = retentionCutoff();
    void this.sql`DELETE FROM room_activity WHERE updated_at <= ${cutoff}`;
    void this.sql`DELETE FROM unread_mentions WHERE created_at <= ${cutoff}`;
  }

  private mentionedBy(roomId: string): string[] {
    return [
      ...new Set(
        this.sql<{ author_id: string }>`SELECT author_id FROM unread_mentions
          WHERE room_id = ${roomId} ORDER BY message_id`.map((row) => row.author_id),
      ),
    ];
  }

  private read(roomId: string, messageId: number): void {
    void this.sql`UPDATE room_activity
      SET last_read_message_id = MAX(COALESCE(last_read_message_id, 0), ${messageId})
      WHERE room_id = ${roomId}`;
    void this
      .sql`DELETE FROM unread_mentions WHERE room_id = ${roomId} AND message_id <= ${messageId}`;
    this.emit({ payload: { roomId, unread: false }, type: "unread.changed", v: 1 });
  }

  private currentCapability(): Capability {
    return passOf(getCurrentAgent<ParleyInboxAgent>().connection as Connection<ConnectionState>);
  }

  private emit(event: ServerEvent): void {
    sendWhere(this.getConnections<ConnectionState>(), event);
  }
}
