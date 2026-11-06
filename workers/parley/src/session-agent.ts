import { getAgentByName, type Connection, type ConnectionContext } from "agents";

import type { Capability, ConnectionState, Message } from "./protocol";

import { lifecycleOf } from "./access";
import { RoomAgent, type Env } from "./room-agent";
import { ParleySphereAgent } from "./sphere-agent";

export class ParleySessionAgent extends RoomAgent {
  protected readonly roomPrefix = "session";

  async onStart(): Promise<void> {
    await super.onStart();
    void this.sql`CREATE TABLE IF NOT EXISTS lifecycle (
      singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
      delete_at INTEGER NOT NULL,
      read_only_at INTEGER NOT NULL,
      token_iat INTEGER NOT NULL
    )`;
  }

  async onConnect(
    connection: Connection<ConnectionState>,
    context: ConnectionContext,
  ): Promise<void> {
    await super.onConnect(connection, context);
    this.syncLifecycle(connection.state?.capability as Capability);
  }

  protected writeError(
    capability: Parameters<RoomAgent["writeError"]>[0],
  ): ReturnType<RoomAgent["writeError"]> {
    const error = super.writeError(capability);
    if (error !== null) return error;
    const lifecycle = this.storeLifecycle(capability);
    return lifecycle.read_only_at * 1_000 <= Date.now() ? { ok: false, code: "archived" } : null;
  }

  protected afterMessage(message: Message): void {
    const capability = this.currentCapability();
    this.agentContext.waitUntil(this.publishActivity({ message, sphere: capability.sphere }));
  }

  async archiveRoom(): Promise<void> {
    const lifecycle = this.sql<{
      read_only_at: number;
    }>`SELECT read_only_at FROM lifecycle WHERE singleton = 1`[0];
    if (lifecycle !== undefined && lifecycle.read_only_at * 1_000 <= Date.now()) {
      this.emit({ type: "room.archived", v: 1, payload: {} });
    }
  }

  async deleteRoom(): Promise<void> {
    const lifecycle = this.sql<{
      delete_at: number;
    }>`SELECT delete_at FROM lifecycle WHERE singleton = 1`[0];
    if (lifecycle !== undefined && lifecycle.delete_at * 1_000 <= Date.now()) await this.destroy();
  }

  async reconcileActivity(input: { latestMessageId: number; sphere: string }): Promise<void> {
    await this.publishActivity({ messageId: input.latestMessageId, sphere: input.sphere });
  }

  private async publishActivity(input: {
    message?: Message;
    messageId?: number;
    sphere: string;
  }): Promise<void> {
    const latestMessageId = input.message?.id ?? input.messageId;
    if (latestMessageId === undefined) return;
    const sphere = await getAgentByName<Env, ParleySphereAgent>(
      this.workerEnv.ParleySphereAgent,
      input.sphere,
    );
    try {
      await sphere.recordActivity({
        latestMessageId,
        roomId: this.roomId,
        secret: this.workerEnv.PARLEY_INTERNAL_SECRET,
        sphere: input.sphere,
      });
    } catch (error) {
      // The retry keeps users whole but would otherwise hide a sphere agent
      // that rejects every call, rescheduling itself every 5s forever.
      // console.error is what raises a caught failure as a Workers Issue.
      console.error("parley: recordActivity failed, scheduling retry", error);
      await this.schedule(
        5,
        "reconcileActivity",
        { latestMessageId, sphere: input.sphere },
        { idempotent: true },
      );
    }
  }

  private syncLifecycle(capability: Capability): void {
    const lifecycle = this.storeLifecycle(capability);
    void this.schedule(new Date(lifecycle.read_only_at * 1_000), "archiveRoom", undefined, {
      idempotent: true,
    });
    void this.schedule(new Date(lifecycle.delete_at * 1_000), "deleteRoom", undefined, {
      idempotent: true,
    });
  }

  // A member's grant carries the session's end, so the newest member token
  // sets the deadlines. A manager's token carries no sessions; a room only
  // managers have opened falls back to the retention window from its first
  // visit, at token_iat 0, so any member's token overrides it.
  private storeLifecycle(capability: Capability): { delete_at: number; read_only_at: number } {
    const room = this.room;
    const lifecycle = room === null ? null : lifecycleOf(capability, room);
    if (lifecycle === null) {
      const fallback = Math.floor(Date.now() / 1_000) + capability.retainFor;
      void this.sql`INSERT INTO lifecycle (singleton, delete_at, read_only_at, token_iat)
        VALUES (1, ${fallback}, ${fallback}, 0)
        ON CONFLICT(singleton) DO NOTHING`;
    } else {
      void this.sql`INSERT INTO lifecycle (singleton, delete_at, read_only_at, token_iat)
        VALUES (1, ${lifecycle.deleteAt}, ${lifecycle.readOnlyAt}, ${capability.iat})
        ON CONFLICT(singleton) DO UPDATE SET
          delete_at = excluded.delete_at, read_only_at = excluded.read_only_at, token_iat = excluded.token_iat
        WHERE excluded.token_iat > token_iat`;
    }
    return this.sql<{
      delete_at: number;
      read_only_at: number;
    }>`SELECT delete_at, read_only_at FROM lifecycle WHERE singleton = 1`[0];
  }
}
