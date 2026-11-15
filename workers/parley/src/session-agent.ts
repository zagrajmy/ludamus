import { getAgentByName, type Connection, type ConnectionContext } from "agents";

import type { Capability, ConnectionState, Message } from "./protocol";

import { lifecycleOf } from "./access";
import { RoomAgent, type Env } from "./room-agent";
import { ParleySphereAgent } from "./sphere-agent";

abstract class SphereRoomAgent extends RoomAgent {
  protected abstract readonly roomPrefix: "event" | "organizers" | "session";

  protected async admits(capability: Capability): Promise<boolean> {
    return (await this.sphere()).admit({
      exp: capability.exp,
      iat: capability.iat,
      roomId: this.roomId,
      sub: capability.sub,
    });
  }

  private sphere() {
    return getAgentByName<Env, ParleySphereAgent>(
      this.workerEnv.ParleySphereAgent,
      this.name.split(":")[0],
    );
  }

  protected afterMessage(message: Message): void {
    this.agentContext.waitUntil(this.publishActivity(message.id));
  }

  async reconcileActivity(input: { latestMessageId: number }): Promise<void> {
    await this.publishActivity(input.latestMessageId);
  }

  private async publishActivity(latestMessageId: number): Promise<void> {
    const sphere = await this.sphere();
    try {
      await sphere.recordActivity({ latestMessageId, roomId: this.roomId });
    } catch (error) {
      // The retry keeps users whole but would otherwise hide a sphere agent
      // that rejects every call, rescheduling itself every 5s forever.
      // console.error is what raises a caught failure as a Workers Issue.
      console.error("parley: recordActivity failed, scheduling retry", error);
      await this.schedule(5, "reconcileActivity", { latestMessageId }, { idempotent: true });
    }
  }
}

export class ParleyOrganizersAgent extends SphereRoomAgent {
  protected readonly roomPrefix = "organizers";
}

abstract class ScheduledRoomAgent extends SphereRoomAgent {
  protected abstract readonly roomPrefix: "event" | "session";

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
    if (connection.state?.admitted) this.syncLifecycle(connection.state.capability);
  }

  protected writeError(
    capability: Parameters<RoomAgent["writeError"]>[0],
  ): ReturnType<RoomAgent["writeError"]> {
    const error = super.writeError(capability);
    if (error !== null) return error;
    const lifecycle = this.storeLifecycle(capability);
    return lifecycle.read_only_at * 1_000 <= Date.now() ? { ok: false, code: "archived" } : null;
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

export class ParleySessionAgent extends ScheduledRoomAgent {
  protected readonly roomPrefix = "session";
}

export class ParleyEventAgent extends ScheduledRoomAgent {
  protected readonly roomPrefix = "event";
}
