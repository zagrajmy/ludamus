import {
  Agent,
  callable,
  getCurrentAgent,
  type AgentContext,
  type Connection,
  type ConnectionContext,
} from "agents";

import { canSeeRoom, inSphere, roomFromId } from "./access";
import { capabilityFromRequest } from "./auth";
import { retentionCutoff } from "./limits";
import { closeRevokedIn, passOf, sendWhere } from "./passes";
import {
  PASS_REVOKED,
  type Capability,
  type ConnectionState,
  type Revocation,
  type RoomActivity,
  type RpcResult,
  type ServerEvent,
} from "./protocol";
import { roomAgent, type Env } from "./room-agent";

type Admission = Pick<Capability, "exp" | "iat" | "sub"> & { roomId: string };

// A sphere's deny-list, and its feed of how the sphere's rooms are doing.
// It holds no messages of its own.
export class ParleySphereAgent extends Agent<Env> {
  private readonly workerEnv: Env;

  constructor(context: AgentContext, env: Env) {
    super(context, env);
    this.workerEnv = env;
  }

  async onStart(): Promise<void> {
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
    // Which rooms hold a socket for whom, so a revocation reaches
    // only those instead of every room the sphere ever had.
    void this.sql`CREATE TABLE IF NOT EXISTS admissions (
      user_id TEXT NOT NULL,
      room_id TEXT NOT NULL,
      expires_at INTEGER NOT NULL,
      PRIMARY KEY (user_id, room_id)
    )`;
    // NOTE: a sphere used to hold a room of its own; its messages go with
    // it. The daily sweep that kept them finds no callback and ends.
    void this.sql`DROP TABLE IF EXISTS reactions`;
    void this.sql`DROP TABLE IF EXISTS messages`;
    void this.sql`DROP TABLE IF EXISTS restrictions`;
    void this.sql`DROP TABLE IF EXISTS rate_events`;
  }

  async onConnect(
    connection: Connection<ConnectionState>,
    context: ConnectionContext,
  ): Promise<void> {
    const capability = await capabilityFromRequest(context.request, this.workerEnv);
    if (!inSphere(capability, this.name)) throw new Error("Forbidden feed");
    if (this.isRevoked(capability)) {
      connection.close(PASS_REVOKED, "Access revoked");
      return;
    }
    connection.setState({ admitted: true, capability });
  }

  closeRevoked(revocation: Pick<Revocation, "revokedBefore" | "sub">): void {
    closeRevokedIn(this.getConnections<ConnectionState>(), revocation);
  }

  admit(admission: Admission): boolean {
    if (!this.holds(admission.roomId) || this.isRevoked(admission)) return false;
    void this.sql`INSERT INTO admissions (user_id, room_id, expires_at)
      VALUES (${admission.sub}, ${admission.roomId}, ${admission.exp})
      ON CONFLICT(user_id, room_id) DO UPDATE SET expires_at = MAX(expires_at, excluded.expires_at)`;
    return true;
  }

  async revoke(revocation: Revocation): Promise<void> {
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
      // Only a room `admit` took is listed, so its id always names one.
      rooms.map(async ({ room_id }) =>
        (await roomAgent(this.workerEnv, roomFromId(room_id)!)).closeRevoked(revocation),
      ),
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

  private holds(roomId: string): boolean {
    const room = roomFromId(roomId);
    return room !== null && room.kind !== "conversation" && room.sphere === this.name;
  }

  private isRevoked(capability: Pick<Capability, "iat" | "sub">): boolean {
    const revokedBefore = this.sql<{ revoked_before: number | null }>`
      SELECT MAX(revoked_before) AS revoked_before FROM revocations
      WHERE user_id IN (${capability.sub}, '*') AND expires_at > ${Math.floor(Date.now() / 1_000)}`[0]
      ?.revoked_before;
    return revokedBefore != null && capability.iat < revokedBefore;
  }

  // A room's activity and anyone's read position a year old point only at
  // messages already deleted, so an unread flag for one never lingers.
  private purgeExpiredActivity(): void {
    const cutoff = retentionCutoff();
    void this.sql`DELETE FROM room_activity WHERE updated_at <= ${cutoff}`;
    void this.sql`DELETE FROM read_positions WHERE updated_at <= ${cutoff}`;
  }

  @callable()
  getActivity(): RpcResult<Record<string, RoomActivity>> {
    const capability = this.currentCapability();
    this.purgeExpiredActivity();
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

  // Not @callable: only the sphere's own rooms reach this, over Durable
  // Object RPC, so a browser cannot forge activity.
  recordActivity(input: { latestMessageId: number; roomId: string }): void {
    if (!this.holds(input.roomId)) throw new Error("Invalid room activity");
    void this.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
      VALUES (${input.roomId}, ${input.latestMessageId}, ${Date.now()})
      ON CONFLICT(room_id) DO UPDATE SET latest_message_id = MAX(latest_message_id, excluded.latest_message_id), updated_at = excluded.updated_at`;
    sendWhere(
      this.getConnections<ConnectionState>(),
      {
        type: "room.activity",
        v: 1,
        payload: { at: Date.now(), latestMessageId: input.latestMessageId, roomId: input.roomId },
      },
      (capability) => canSeeRoom(capability, input.roomId),
    );
  }

  private currentCapability(): Capability {
    return passOf(getCurrentAgent<ParleySphereAgent>().connection as Connection<ConnectionState>);
  }

  private emitTo(userId: string, event: ServerEvent): void {
    sendWhere(
      this.getConnections<ConnectionState>(),
      event,
      (capability) => capability.sub === userId,
    );
  }
}
