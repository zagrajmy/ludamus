import {
  DurableObjectSqliteSyncWrapper,
  SQLiteSyncStorage,
  TLSocketRoom,
  TLSyncErrorCloseEventCode,
  TLSyncErrorCloseEventReason,
} from "@tldraw/sync-core";
import { DurableObject } from "cloudflare:workers";

import type { Pass, PassEnv } from "./pass";

import { rollDie, type Roll } from "./dice";
import { MAX_PEOPLE, MIN_ROLL_INTERVAL_MS, ROLL_LOG_LENGTH } from "./limits";

export type Env = PassEnv & { BoardRoom: DurableObjectNamespace<BoardRoom> };

export type Refusal = "link-reset" | "full" | "too-fast";

// NOTE: the tldraw client reads close code 4099 as final and hands the
// reason to useSync as a TLRemoteSyncError, instead of retrying.
const SOCKET_REFUSAL: Record<"full" | "link-reset", string> = {
  full: TLSyncErrorCloseEventReason.ROOM_FULL,
  "link-reset": TLSyncErrorCloseEventReason.FORBIDDEN,
};

export const PASS_HEADER = "X-Board-Pass";

type Person = Pick<Pass, "link" | "name" | "owner" | "sub">;

function log(event: string, fields: Record<string, unknown>) {
  console.log(JSON.stringify({ event, ...fields }));
}

function kind(sub: string): "guest" | "member" {
  return sub.startsWith("g:") ? "guest" : "member";
}

export class BoardRoom extends DurableObject<Env> {
  private room!: TLSocketRoom<never, Person>;
  private lastRollAt = new Map<string, number>();

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.open();
  }

  // NOTE: deleteAll drops the tables and leaves the old room holding rows
  // that no longer exist, so deleting starts over from here.
  private open() {
    const sql = this.ctx.storage.sql;
    sql.exec(
      "CREATE TABLE IF NOT EXISTS board (id INTEGER PRIMARY KEY CHECK (id = 1), link INTEGER NOT NULL)",
    );
    sql.exec(
      "CREATE TABLE IF NOT EXISTS rolls (id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, sub TEXT NOT NULL, name TEXT NOT NULL, dice TEXT NOT NULL)",
    );
    this.room = new TLSocketRoom<never, Person>({
      storage: new SQLiteSyncStorage({
        sql: new DurableObjectSqliteSyncWrapper(this.ctx.storage, { tablePrefix: "tldraw_" }),
      }),
    });
    this.lastRollAt = new Map();
  }

  private link(): number {
    const [row] = this.ctx.storage.sql.exec("SELECT link FROM board").toArray();
    return row === undefined ? 0 : (row.link as number);
  }

  // A reset link carries a higher version. The first pass that shows it
  // moves the board on and puts out everyone who came in by the old link.
  private admit(pass: Pass): "link-reset" | null {
    const current = this.link();
    if (pass.link < current) return "link-reset";
    if (pass.link > current) {
      this.ctx.storage.sql.exec(
        "INSERT INTO board (id, link) VALUES (1, ?) ON CONFLICT (id) DO UPDATE SET link = excluded.link",
        pass.link,
      );
      for (const session of this.room.getSessions()) {
        if (session.meta.link < pass.link) {
          this.room.closeSession(session.sessionId, TLSyncErrorCloseEventReason.FORBIDDEN);
        }
      }
      log("board.link_reset", { board: pass.board, link: pass.link });
    }
    return null;
  }

  // NOTE: a socket cannot cross an RPC call, so the Worker forwards the
  // upgrade as a request and names the verified pass in PASS_HEADER.
  override fetch(request: Request): Response {
    const pass: Pass = JSON.parse(request.headers.get(PASS_HEADER)!);
    const sessionId = new URL(request.url).searchParams.get("sessionId")!;
    const refusal =
      this.admit(pass) ?? (this.room.getNumActiveSessions() >= MAX_PEOPLE ? "full" : null);
    if (refusal !== null) {
      log("board.refused", { board: pass.board, person: kind(pass.sub), reason: refusal });
      const { 0: client, 1: server } = new WebSocketPair();
      server.accept();
      server.close(TLSyncErrorCloseEventCode, SOCKET_REFUSAL[refusal]);
      return new Response(null, { status: 101, webSocket: client });
    }
    const { 0: client, 1: server } = new WebSocketPair();
    server.accept();
    this.room.handleSocketConnect({
      meta: { link: pass.link, name: pass.name, owner: pass.owner, sub: pass.sub },
      sessionId,
      socket: server,
    });
    log("board.connected", {
      board: pass.board,
      people: this.room.getNumActiveSessions(),
      person: kind(pass.sub),
    });
    return new Response(null, { status: 101, webSocket: client });
  }

  roll(pass: Pass, pool: number[]): Refusal | Roll {
    const refusal = this.admit(pass);
    if (refusal !== null) return refusal;
    const at = Date.now();
    if (at - (this.lastRollAt.get(pass.sub) ?? 0) < MIN_ROLL_INTERVAL_MS) return "too-fast";
    this.lastRollAt.set(pass.sub, at);
    const dice = pool.map((sides) => ({ sides, value: rollDie(sides) }));
    const [row] = this.ctx.storage.sql
      .exec(
        "INSERT INTO rolls (at, sub, name, dice) VALUES (?, ?, ?, ?) RETURNING id",
        at,
        pass.sub,
        pass.name,
        JSON.stringify(dice),
      )
      .toArray();
    const roll: Roll = { at, dice, id: row!.id as number, name: pass.name, sub: pass.sub };
    this.ctx.storage.sql.exec("DELETE FROM rolls WHERE id <= ?", roll.id - ROLL_LOG_LENGTH);
    for (const session of this.room.getSessions()) {
      this.room.sendCustomMessage(session.sessionId, { roll, type: "roll" });
    }
    log("board.rolled", { board: pass.board, dice: pool.length, person: kind(pass.sub) });
    return roll;
  }

  rolls(pass: Pass): Refusal | Roll[] {
    const refusal = this.admit(pass);
    if (refusal !== null) return refusal;
    return this.ctx.storage.sql
      .exec("SELECT id, at, sub, name, dice FROM rolls ORDER BY id")
      .toArray()
      .map((row) => ({
        at: row.at as number,
        dice: JSON.parse(row.dice as string),
        id: row.id as number,
        name: row.name as string,
        sub: row.sub as string,
      }));
  }

  async destroy(board: string) {
    for (const session of this.room.getSessions()) {
      this.room.closeSession(session.sessionId, TLSyncErrorCloseEventReason.NOT_FOUND);
    }
    this.room.close();
    await this.ctx.storage.deleteAll();
    this.open();
    log("board.deleted", { board });
  }
}
