import { callable, getAgentByName } from "agents";

import type { Capability, Message, Revocation, RoomActivity, RpcResult } from "./protocol";
import type { ParleySessionAgent } from "./session-agent";

import { canSeeRoom } from "./access";
import { RoomAgent, type Env } from "./room-agent";

type Admission = Pick<Capability, "exp" | "iat" | "sub"> & { roomId: string };

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
    // The deny-list for every room of the sphere. user_id '*' is everyone.
    void this.sql`CREATE TABLE IF NOT EXISTS revocations (
      user_id TEXT PRIMARY KEY,
      revoked_before INTEGER NOT NULL,
      expires_at INTEGER NOT NULL
    )`;
    // Which session rooms hold a socket for whom, so a revocation reaches
    // only those instead of every room the sphere ever had.
    void this.sql`CREATE TABLE IF NOT EXISTS admissions (
      user_id TEXT NOT NULL,
      room_id TEXT NOT NULL,
      expires_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, room_id)
    )`;
  }

  protected async admits(capability: Capability): Promise<boolean> {
    return !this.isRevoked(capability);
  }

  admitToSession(admission: Admission): boolean {
    if (!admission.roomId.startsWith(`session:${this.name}:`) || this.isRevoked(admission)) {
      return false;
    }
    void this.sql`INSERT INTO admissions (user_id, room_id, expires_at)
      VALUES (${admission.sub}, ${admission.roomId}, ${admission.exp})
      ON CONFLICT(user_id, room_id) DO UPDATE SET expires_at = MAX(expires_at, excluded.expires_at)`;
    return true;
  }

  async revoke(revocation: Revocation): Promise<void> {
    if (revocation.sphere !== this.name) throw new Error("Revocation for another sphere");
    const now = Math.floor(Date.now() / 1_000);
    void this.sql`DELETE FROM revocations WHERE expires_at <= ${now}`;
    void this.sql`DELETE FROM admissions WHERE expires_at <= ${now}`;
    void this.sql`INSERT INTO revocations (user_id, revoked_before, expires_at)
      VALUES (${revocation.sub}, ${revocation.revokedBefore}, ${revocation.exp})
      ON CONFLICT(user_id) DO UPDATE SET
        revoked_before = MAX(revoked_before, excluded.revoked_before),
        expires_at = MAX(expires_at, excluded.expires_at)`;
    this.closeRevoked(revocation);
    const rooms =
      revocation.sub === "*"
        ? this.sql<{ room_id: string }>`SELECT DISTINCT room_id FROM admissions`
        : this.sql<{
            room_id: string;
          }>`SELECT room_id FROM admissions WHERE user_id = ${revocation.sub}`;
    const results = await Promise.allSettled(
      rooms.map(async ({ room_id }) => {
        const session = await getAgentByName<Env, ParleySessionAgent>(
          this.workerEnv.ParleySessionAgent,
          room_id.slice("session:".length),
        );
        await session.closeRevoked(revocation);
      }),
    );
    const failed = results.filter((result) => result.status === "rejected");
    // Django retries the whole revocation on an error, and every step of it
    // repeats harmlessly.
    if (failed.length > 0) {
      throw new Error(
        `Revocation reached ${rooms.length - failed.length} of ${rooms.length} rooms`,
      );
    }
  }

  private isRevoked(capability: Pick<Capability, "iat" | "sub">): boolean {
    const revokedBefore = this.sql<{ revoked_before: number | null }>`
      SELECT MAX(revoked_before) AS revoked_before FROM revocations
      WHERE user_id IN (${capability.sub}, '*') AND expires_at > ${Math.floor(Date.now() / 1_000)}`[0]
      ?.revoked_before;
    return revokedBefore != null && capability.iat < revokedBefore;
  }

  @callable()
  getActivity(): RpcResult<Record<string, RoomActivity>> {
    const capability = this.currentCapability();
    const rows = this.sql<{
      latest_message_id: number;
      last_read_message_id: number | null;
      room_id: string;
      updated_at: number;
    }>`
      SELECT activity.room_id, activity.latest_message_id, activity.updated_at,
        positions.last_read_message_id
      FROM room_activity activity
      LEFT JOIN read_positions positions ON positions.room_id = activity.room_id AND positions.user_id = ${capability.sub}`;
    return {
      ok: true,
      value: Object.fromEntries(
        rows
          .filter((row) => canSeeRoom(capability, row.room_id))
          .map((row) => [
            row.room_id,
            {
              at: row.updated_at,
              unread: row.latest_message_id > (row.last_read_message_id ?? 0),
            },
          ]),
      ),
    };
  }

  @callable()
  markRead(input: { messageId?: unknown; roomId?: unknown }): RpcResult<Record<string, never>> {
    const capability = this.currentCapability();
    if (
      typeof input?.roomId !== "string" ||
      !canSeeRoom(capability, input.roomId) ||
      typeof input.messageId !== "number"
    ) {
      return { ok: false, code: "invalid" };
    }
    void this.sql`INSERT INTO read_positions (user_id, room_id, last_read_message_id, updated_at)
      VALUES (${capability.sub}, ${input.roomId}, ${input.messageId}, ${Date.now()})
      ON CONFLICT(user_id, room_id) DO UPDATE SET
        last_read_message_id = MAX(last_read_message_id, excluded.last_read_message_id), updated_at = excluded.updated_at`;
    this.emitTo(capability.sub, {
      type: "unread.changed",
      v: 1,
      payload: { roomId: input.roomId, unread: false },
    });
    return { ok: true, value: {} };
  }

  // Not @callable: only a session room reaches this, over Durable Object
  // RPC, so a browser cannot forge activity.
  recordActivity(input: { latestMessageId: number; roomId: string }): void {
    if (!input.roomId.startsWith(`session:${this.name}:`)) {
      throw new Error("Invalid room activity");
    }
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${input.roomId}, ${input.latestMessageId}, ${Date.now()})
      ON CONFLICT(room_id) DO UPDATE SET latest_message_id = MAX(latest_message_id, excluded.latest_message_id), updated_at = excluded.updated_at`;
    this.emit({
      type: "room.activity",
      v: 1,
      payload: { at: Date.now(), latestMessageId: input.latestMessageId, roomId: input.roomId },
    });
  }

  protected afterMessage(message: Message): void {
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${this.roomId}, ${message.id}, ${Date.now()})
      ON CONFLICT(room_id) DO UPDATE SET latest_message_id = MAX(latest_message_id, excluded.latest_message_id), updated_at = excluded.updated_at`;
    this.emit({
      type: "room.activity",
      v: 1,
      payload: { at: message.createdAt, latestMessageId: message.id, roomId: this.roomId },
    });
  }
}
