import { getAgentByName, type Connection, type ConnectionContext } from "agents";

import type { Capability, ConnectionState, Message } from "./protocol";

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
    const lifecycle = capability.lifecycle?.[this.roomId];
    if (lifecycle !== undefined) {
      void this.sql`INSERT INTO lifecycle (singleton, delete_at, read_only_at, token_iat)
        VALUES (1, ${lifecycle.deleteAt}, ${lifecycle.readOnlyAt}, ${capability.iat})
        ON CONFLICT(singleton) DO UPDATE SET
          delete_at = excluded.delete_at, read_only_at = excluded.read_only_at, token_iat = excluded.token_iat
        WHERE excluded.token_iat > token_iat`;
    }
    const row = this.sql<{
      read_only_at: number;
    }>`SELECT read_only_at FROM lifecycle WHERE singleton = 1`[0];
    return row !== undefined && row.read_only_at * 1_000 <= Date.now()
      ? { ok: false, code: "archived" }
      : null;
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
      this.workerEnv.PARLEY_SPHERE,
      input.sphere,
    );
    try {
      await sphere.recordActivity({
        latestMessageId,
        roomId: this.roomId,
        secret: this.workerEnv.PARLEY_INTERNAL_SECRET,
        sphere: input.sphere,
      });
    } catch {
      await this.schedule(
        5,
        "reconcileActivity",
        { latestMessageId, sphere: input.sphere },
        { idempotent: true },
      );
    }
  }

  private syncLifecycle(capability: ConnectionState["capability"]): void {
    const lifecycle = capability.lifecycle?.[this.roomId];
    if (lifecycle === undefined) return;
    void this.sql`INSERT INTO lifecycle (singleton, delete_at, read_only_at, token_iat)
      VALUES (1, ${lifecycle.deleteAt}, ${lifecycle.readOnlyAt}, ${capability.iat})
      ON CONFLICT(singleton) DO UPDATE SET delete_at = excluded.delete_at, read_only_at = excluded.read_only_at, token_iat = excluded.token_iat
      WHERE excluded.token_iat > token_iat`;
    void this.schedule(new Date(lifecycle.readOnlyAt * 1_000), "archiveRoom", undefined, {
      idempotent: true,
    });
    void this.schedule(new Date(lifecycle.deleteAt * 1_000), "deleteRoom", undefined, {
      idempotent: true,
    });
  }
}
