import { getAgentByName } from "agents";

import type { ParleyInboxAgent } from "./inbox-agent";
import type {
  Capability,
  ConnectionState,
  Member,
  Membership,
  Message,
  RpcError,
} from "./protocol";

import { NOT_A_MEMBER, RoomAgent, type Env } from "./room-agent";

type MemberRow = { state: Member["state"]; user_id: string; writable: number };

// A direct or group conversation. Django pushes who is in it; the room
// admits, and lets write, only the people on its latest list.
export class ParleyConversationAgent extends RoomAgent {
  protected readonly roomPrefix = "conversation";

  async onStart(): Promise<void> {
    await super.onStart();
    void this.sql`CREATE TABLE IF NOT EXISTS conversation (
      singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
      kind TEXT NOT NULL,
      synced_at INTEGER NOT NULL
    )`;
    void this.sql`CREATE TABLE IF NOT EXISTS members (
      user_id TEXT PRIMARY KEY,
      state TEXT NOT NULL,
      writable INTEGER NOT NULL
    )`;
  }

  protected async admits(capability: Capability): Promise<boolean> {
    return this.member(capability.sub) !== undefined;
  }

  // NOTE: refused while its list has yet to arrive, a member's socket redials
  // instead of fetching a new pass; Django sends the list right after commit.
  protected refusal(): number {
    return NOT_A_MEMBER;
  }

  sync(membership: Membership): void {
    if (membership.conversation !== this.name) throw new Error("Membership for another room");
    const synced = this.sql<{ synced_at: number }>`SELECT synced_at FROM conversation`[0];
    // Deliveries can cross; an older list never replaces a newer one.
    if (synced !== undefined && synced.synced_at > membership.iat) return;
    void this.sql`INSERT INTO conversation (singleton, kind, synced_at)
      VALUES (1, ${membership.kind}, ${membership.iat})
      ON CONFLICT(singleton) DO UPDATE SET kind = excluded.kind, synced_at = excluded.synced_at`;
    void this.sql`DELETE FROM members`;
    for (const member of membership.members) {
      void this.sql`INSERT INTO members (user_id, state, writable)
        VALUES (${member.user}, ${member.state}, ${member.writable ? 1 : 0})`;
    }
    const present = new Set(membership.members.map((member) => member.user));
    for (const connection of this.getConnections<ConnectionState>()) {
      const sub = connection.state?.capability.sub;
      if (sub !== undefined && !present.has(sub)) connection.close(NOT_A_MEMBER, "Not a member");
    }
  }

  protected writeError(capability: Capability): RpcError | null {
    const error = super.writeError(capability);
    if (error !== null) return error;
    const member = this.member(capability.sub)!;
    if (member.writable === 0) return { code: "forbidden", ok: false };
    // A direct request the other person has not accepted takes one message.
    const waiting = this.sql<{ count: number }>`
      SELECT COUNT(*) AS count FROM members WHERE state = 'request' AND user_id != ${capability.sub}`[0]!;
    if (waiting.count === 0) return null;
    const sent = this.sql<{ count: number }>`
      SELECT COUNT(*) AS count FROM messages WHERE author_id = ${capability.sub}`[0]!;
    return sent.count > 0 ? { code: "pending", ok: false } : null;
  }

  protected afterMessage(message: Message): void {
    const members = this.sql<{ user_id: string }>`SELECT user_id FROM members`;
    this.agentContext.waitUntil(
      Promise.allSettled(
        members.map(async ({ user_id }) => {
          const inbox = await getAgentByName<Env, ParleyInboxAgent>(
            this.workerEnv.ParleyInboxAgent,
            user_id,
          );
          await inbox.recordActivity({
            authorId: message.authorId,
            latestMessageId: message.id,
            roomId: this.roomId,
          });
        }),
      ),
    );
  }

  private member(userId: string): MemberRow | undefined {
    return this.sql<MemberRow>`SELECT * FROM members WHERE user_id = ${userId}`[0];
  }
}
