import { Agent, callable, getCurrentAgent, type Connection, type ConnectionContext } from "agents";

import type { Env } from "./room-agent";

import { capabilityFromRequest } from "./auth";
import { retentionCutoff } from "./limits";
import {
  askToMail,
  MAIL_AFTER_MS,
  MAIL_UNTIL_MS,
  MAX_LISTED,
  RETRY_MS,
  snippet,
  type UnreadMention,
} from "./mention-mail";
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

type MentionRow = {
  author_id: string;
  author_name: string;
  body: string;
  created_at: number;
  message_id: number;
  room_id: string;
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
      author_name TEXT NOT NULL,
      body TEXT NOT NULL,
      created_at INTEGER NOT NULL,
      mailed_at INTEGER,
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
    const mentioned = this.mentionedBy();
    return {
      ok: true,
      value: Object.fromEntries(
        rows.map((row) => [
          row.room_id,
          {
            at: row.updated_at,
            mentionedBy: mentioned.get(row.room_id) ?? [],
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
  async recordActivity(input: {
    authorId: string;
    authorName: string;
    body: string;
    latestMessageId: number;
    mentions: string[];
    roomId: string;
  }): Promise<void> {
    this.purgeExpiredActivity();
    const now = Date.now();
    const mentioned = input.authorId !== this.name && input.mentions.includes(this.name);
    if (mentioned) {
      void this.sql`INSERT INTO unread_mentions
        (room_id, message_id, author_id, author_name, body, created_at)
        VALUES (${input.roomId}, ${input.latestMessageId}, ${input.authorId},
          ${input.authorName}, ${snippet(input.body)}, ${now})
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
        mentionedBy: this.mentionedBy().get(input.roomId) ?? [],
        roomId: input.roomId,
      },
      type: "room.activity",
      v: 1,
    });
    // One's own message is read by definition.
    if (input.authorId === this.name) this.read(input.roomId, input.latestMessageId);
    if (mentioned && this.env.PARLEY_MENTIONS_SECRET) {
      await this.schedule(new Date(now + MAIL_AFTER_MS), "mailMentions", undefined, {
        idempotent: true,
      });
    }
  }

  forgetMention(input: { messageId: number; roomId: string }): void {
    void this.sql`DELETE FROM unread_mentions
      WHERE room_id = ${input.roomId} AND message_id = ${input.messageId}`;
    this.emit({
      payload: { mentionedBy: this.mentionedBy().get(input.roomId) ?? [], roomId: input.roomId },
      type: "mentions.changed",
      v: 1,
    });
  }

  async mailMentions(): Promise<void> {
    this.purgeExpiredActivity();
    const now = Date.now();
    const due = now - MAIL_AFTER_MS;
    const fresh = this.sql<{ count: number }>`SELECT COUNT(*) AS count FROM unread_mentions
      WHERE mailed_at IS NULL AND created_at <= ${due} AND created_at > ${now - MAIL_UNTIL_MS}`[0]!;
    if (fresh.count > 0) {
      const listed = this.sql<MentionRow>`SELECT * FROM unread_mentions
        WHERE created_at <= ${due} ORDER BY created_at DESC LIMIT ${MAX_LISTED}`;
      const outcome = await askToMail(this.env, {
        mentions: listed.reverse().map(
          (row): UnreadMention => ({
            at: row.created_at,
            author: row.author_id,
            authorName: row.author_name,
            body: row.body,
            message: row.message_id,
            room: row.room_id,
          }),
        ),
        userId: this.name,
      });
      if (outcome.kind !== "handled") {
        const at = outcome.kind === "later" ? outcome.at : now + RETRY_MS;
        await this.schedule(new Date(at), "mailMentions", undefined, { idempotent: false });
        return;
      }
      void this.sql`UPDATE unread_mentions SET mailed_at = ${now}
        WHERE mailed_at IS NULL AND created_at <= ${due}`;
    }
    // NOTE: the schedule running now stays listed until this returns, so the
    const next = this.sql<{ created_at: number }>`SELECT created_at FROM unread_mentions
      WHERE mailed_at IS NULL AND created_at > ${due} ORDER BY created_at LIMIT 1`[0];
    if (next !== undefined) {
      await this.schedule(new Date(next.created_at + MAIL_AFTER_MS), "mailMentions", undefined, {
        idempotent: false,
      });
    }
  }

  // Activity a year old points only at messages its room has deleted, so an
  // unread flag for one never lingers.
  private purgeExpiredActivity(): void {
    const cutoff = retentionCutoff();
    void this.sql`DELETE FROM room_activity WHERE updated_at <= ${cutoff}`;
    void this.sql`DELETE FROM unread_mentions WHERE created_at <= ${cutoff}`;
  }

  private mentionedBy(): Map<string, string[]> {
    const rows = this.sql<{ authors: string; room_id: string }>`
      SELECT room_id, json_group_array(DISTINCT author_id) AS authors
      FROM unread_mentions GROUP BY room_id`;
    return new Map(rows.map((row) => [row.room_id, JSON.parse(row.authors) as string[]]));
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
