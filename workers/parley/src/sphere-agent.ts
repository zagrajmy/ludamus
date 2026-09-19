import { callable } from "agents";

import type { Message, RpcResult } from "./protocol";

import { RoomAgent } from "./room-agent";

export class ParleySphereAgent extends RoomAgent {
  protected readonly roomPrefix = "sphere";

  async onStart(): Promise<void> {
    await super.onStart();
    void this.sql`CREATE TABLE IF NOT EXISTS room_activity (
      room_id TEXT PRIMARY KEY,
      latest_message_id INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )`;
    void this.sql`CREATE TABLE IF NOT EXISTS read_positions (
      user_id TEXT NOT NULL,
      room_id TEXT NOT NULL,
      last_read_message_id INTEGER NOT NULL,
      updated_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, room_id)
    )`;
  }

  @callable()
  listRooms(): RpcResult<string[]> {
    return { ok: true, value: this.currentCapability().rooms };
  }

  @callable()
  getUnreadCounts(): RpcResult<Record<string, boolean>> {
    const userId = this.currentCapability().sub;
    const rows = this.sql<{
      latest_message_id: number;
      last_read_message_id: number | null;
      room_id: string;
    }>`
      SELECT activity.room_id, activity.latest_message_id, positions.last_read_message_id
      FROM room_activity activity
      LEFT JOIN read_positions positions ON positions.room_id = activity.room_id AND positions.user_id = ${userId}`;
    return {
      ok: true,
      value: Object.fromEntries(
        rows.map((row) => [row.room_id, row.latest_message_id > (row.last_read_message_id ?? 0)]),
      ),
    };
  }

  @callable()
  markRead(input: { messageId?: unknown; roomId?: unknown }): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    if (
      typeof input?.roomId !== "string" ||
      !capability.rooms.includes(input.roomId) ||
      typeof input.messageId !== "number"
    ) {
      return { ok: false, code: "invalid" };
    }
    void this.sql`INSERT INTO read_positions (user_id, room_id, last_read_message_id, updated_at)
      VALUES (${capability.sub}, ${input.roomId}, ${input.messageId}, ${Date.now()})
      ON CONFLICT(user_id, room_id) DO UPDATE SET
        last_read_message_id = MAX(last_read_message_id, excluded.last_read_message_id), updated_at = excluded.updated_at`;
    this.emit({ type: "unread.changed", v: 1, payload: { roomId: input.roomId, unread: false } });
    return { ok: true, value: {} };
  }

  @callable()
  recordActivity(input: {
    latestMessageId: number;
    roomId: string;
    secret: string;
    sphere: string;
  }): void {
    if (
      input.secret !== this.workerEnv.PARLEY_INTERNAL_SECRET ||
      input.sphere !== this.name ||
      !input.roomId.startsWith("session:")
    ) {
      throw new Error("Invalid room activity");
    }
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${input.roomId}, ${input.latestMessageId}, ${Date.now()})
      ON CONFLICT(room_id) DO UPDATE SET latest_message_id = MAX(latest_message_id, excluded.latest_message_id), updated_at = excluded.updated_at`;
    this.emit({
      type: "room.activity",
      v: 1,
      payload: { latestMessageId: input.latestMessageId, roomId: input.roomId },
    });
  }

  protected afterMessage(message: Message): void {
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${this.roomId}, ${message.id}, ${Date.now()})
      ON CONFLICT(room_id) DO UPDATE SET latest_message_id = MAX(latest_message_id, excluded.latest_message_id), updated_at = excluded.updated_at`;
    this.emit({
      type: "room.activity",
      v: 1,
      payload: { latestMessageId: message.id, roomId: this.roomId },
    });
  }
}
