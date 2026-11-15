import { getAgentByName, type Agent } from "agents";
import { runDurableObjectAlarm, runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import type { Env, RoomAgent } from "../src/room-agent";

import { LOOKUP_AUDIENCE } from "../src/auth";
import { DAY_MS, MESSAGE_LIFETIME_MS } from "../src/limits";
import { manager, now, open, pass, post, settle } from "./support";

// What could go wrong, and so what the tests below check:
// - a message past its year is still served, by history, a moderator's
//   context or Django's report lookup, because the alarm is late or never ran;
// - one just short of its year goes early (milliseconds read as seconds, or
//   the cutoff the wrong way round);
// - it is hidden but stays in storage;
// - no sweep is ever scheduled, or one that ran never comes back while
//   messages remain, or one keeps waking a room with nothing left;
// - every message pushes the pending sweep further out, so a busy room is
//   never swept, or every wake adds another;
// - the sweep displaces a session room's own archive and delete;
// - an unread flag outlives the message it stood for.

const workerEnv = env as unknown as Env;
const YEAR_AND_A_MINUTE = MESSAGE_LIFETIME_MS + 60_000;
const YEAR_LESS_A_MINUTE = MESSAGE_LIFETIME_MS - 60_000;

type Result<T = unknown> = { code?: string; ok: boolean; value?: T };
type Shown = { body: string; createdAt: number };

const organizersRoom = (name: string) =>
  getAgentByName<Env, RoomAgent>(
    workerEnv.ParleyOrganizersAgent as unknown as DurableObjectNamespace<RoomAgent>,
    name,
  );

type Stub = DurableObjectStub;

// The pool's types know a stub's object only as a DurableObject.
function inside<A extends Agent<Env> = RoomAgent, R = unknown>(
  stub: Stub,
  callback: (agent: A) => R | Promise<R>,
): Promise<R> {
  return runInDurableObject(stub, (instance) => callback(instance as unknown as A));
}

// A row a year old cannot be written through the room, so it goes in direct.
async function seed(stub: Stub, messages: { age: number; body: string }[]): Promise<number[]> {
  return inside(stub, (room) =>
    messages.map(({ age, body }) => {
      void room.sql`INSERT INTO messages (author_id, author_name, body, client_nonce, created_at)
        VALUES ('8', 'Person 8', ${body}, ${crypto.randomUUID()}, ${Date.now() - age})`;
      return room.sql<{ id: number }>`SELECT last_insert_rowid() AS id`[0].id;
    }),
  );
}

const stored = (stub: Stub) =>
  inside(stub, (room) =>
    room.sql<{ body: string }>`SELECT body FROM messages ORDER BY id`.map((row) => row.body),
  );

const sweeps = (stub: Stub) =>
  inside(stub, async (room) =>
    (await room.listSchedules())
      .filter((schedule) => schedule.callback === "sweepExpiredMessages")
      .map((schedule) => schedule.time * 1_000),
  );

const lookup = (room: string, message: number) =>
  post("/messages", { message, room }, LOOKUP_AUDIENCE);

// The tables come with a room's first visit.
async function visit(name: string): Promise<Stub> {
  (await open(`parley-organizers-agent/${name}`, await manager("7", name))).socket.close();
  return organizersRoom(name);
}

describe("a message a year old", () => {
  it("is never served again, even before the room's alarm comes round", async () => {
    const member = await open("parley-organizers-agent/61", await manager("7", "61"));
    const stub = await organizersRoom("61");
    const [old, young] = await seed(stub, [
      { age: YEAR_AND_A_MINUTE, body: "A year and a minute ago" },
      { age: YEAR_LESS_A_MINUTE, body: "A minute short of a year" },
    ]);
    await inside(stub, (room) => {
      for (const id of [old, young]) {
        void room.sql`INSERT INTO reactions (message_id, user_id, emoji, user_name, created_at)
          VALUES (${id}, '9', '👍', 'Person 9', ${Date.now()})`;
      }
    });

    const history = await member.call<Result<Shown[]>>("loadBefore");

    expect(history.value).toEqual([
      expect.objectContaining({ body: "A minute short of a year", reactions: { "👍": ["9"] } }),
    ]);
    expect((await lookup("organizers:61", old)).status).toBe(404);
    expect((await lookup("organizers:61", young)).status).toBe(200);
    expect(await stored(stub)).toEqual(["A minute short of a year"]);
    const reacted = await inside(stub, (room) =>
      room.sql<{ message_id: number }>`SELECT message_id FROM reactions`.map(
        (row) => row.message_id,
      ),
    );
    expect(reacted).toEqual([young]);
    member.socket.close();
  }, 20_000);

  it("is gone from what a moderator reads around a report", async () => {
    const moderator = await open("parley-organizers-agent/64", await manager("1", "64"));
    const [old] = await seed(await organizersRoom("64"), [
      { age: YEAR_AND_A_MINUTE, body: "Reported long ago" },
      { age: DAY_MS, body: "Said yesterday" },
    ]);

    const around = await moderator.call<Result<Shown[]>>("loadAround", { messageId: old });

    expect(around.value!.map((message) => message.body)).toEqual(["Said yesterday"]);
    moderator.socket.close();
  }, 20_000);
});

describe("a room's sweep", () => {
  it("wakes once the oldest message turns a year old, deletes it, and returns for the next", async () => {
    const stub = await visit("62");
    await seed(stub, [
      { age: YEAR_AND_A_MINUTE, body: "Due" },
      { age: MESSAGE_LIFETIME_MS - 2 * DAY_MS, body: "Due in two days" },
    ]);
    // The next wake finds the old row and sets the alarm for it.
    await inside(stub, (room) => room.onStart());

    // NOTE: an alarm already due may fire on its own first; either way it runs.
    await runDurableObjectAlarm(stub);
    await settle();

    expect(await stored(stub)).toEqual(["Due in two days"]);
    const pending = await sweeps(stub);
    expect(pending).toHaveLength(1);
    expect(pending[0]).toBeGreaterThan(Date.now() + 2 * DAY_MS - 5 * 60_000);
    expect(pending[0]).toBeLessThanOrEqual(Date.now() + 2 * DAY_MS);
  }, 20_000);

  it("comes back no sooner than a day, and not at all once nothing is left", async () => {
    const busy = await visit("65");
    const emptied = await visit("66");
    await seed(busy, [
      { age: YEAR_AND_A_MINUTE, body: "Due" },
      { age: MESSAGE_LIFETIME_MS - 3_600_000, body: "Due in an hour" },
    ]);
    await seed(emptied, [{ age: YEAR_AND_A_MINUTE, body: "Due" }]);

    for (const stub of [busy, emptied]) {
      await inside(stub, (room) => room.sweepExpiredMessages());
    }

    const [next] = await sweeps(busy);
    expect(next).toBeGreaterThanOrEqual(Date.now() + DAY_MS - 60_000);
    expect(await stored(emptied)).toEqual([]);
    expect(await sweeps(emptied)).toEqual([]);
  }, 20_000);

  it("stays where the first message set it, however much is written after", async () => {
    const member = await open("parley-organizers-agent/67", await manager("7", "67"));
    const first = await member.call<Result<Shown>>("sendMessage", {
      body: "First",
      nonce: crypto.randomUUID(),
    });
    for (const body of ["Second", "Third"]) {
      await member.call("sendMessage", { body, nonce: crypto.randomUUID() });
    }
    const stub = await organizersRoom("67");
    await inside(stub, (room) => room.onStart());

    expect(await sweeps(stub)).toEqual([
      Math.floor((first.value!.createdAt + MESSAGE_LIFETIME_MS) / 1_000) * 1_000,
    ]);
    member.socket.close();
  }, 20_000);

  it("runs beside a session room's own archive and delete", async () => {
    const member = await open("parley-session-agent/68:101", await pass("7", "68"));
    await member.call("sendMessage", { body: "See you there", nonce: crypto.randomUUID() });
    await settle();

    const stub = await getAgentByName(workerEnv.ParleySessionAgent, "68:101");
    const callbacks = await inside<Agent<Env>, string[]>(stub, async (room) =>
      (await room.listSchedules()).map((schedule) => schedule.callback).sort(),
    );

    expect(callbacks).toEqual(["archiveRoom", "deleteRoom", "sweepExpiredMessages"]);
    member.socket.close();
  }, 20_000);
});

describe("an unread flag", () => {
  it("leaves a person's inbox with the message it stood for", async () => {
    const inbox = await open(
      "parley-inbox-agent/71",
      await pass("71", "3", now(), { direct: true }),
    );
    await inside<Agent<Env>>(
      await getAgentByName(workerEnv.ParleyInboxAgent, "71"),
      (store) =>
        void store.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
          VALUES ('conversation:801', 4, ${Date.now() - YEAR_AND_A_MINUTE}),
            ('conversation:802', 9, ${Date.now() - YEAR_LESS_A_MINUTE})`,
    );

    const activity = await inbox.call<Result<Record<string, unknown>>>("getActivity");

    expect(Object.keys(activity.value!)).toEqual(["conversation:802"]);
    inbox.socket.close();
  }, 20_000);

  it("leaves a sphere's rooms, read positions and all", async () => {
    const member = await open("parley-sphere-agent/69", await pass("7", "69"));
    const stub = await getAgentByName(workerEnv.ParleySphereAgent, "69");
    await inside(stub, (room) => {
      void room.sql`INSERT INTO room_activity (room_id, latest_message_id, updated_at)
        VALUES ('session:69:101', 4, ${Date.now() - YEAR_AND_A_MINUTE})`;
      void room.sql`INSERT INTO read_positions (user_id, room_id, last_read_message_id, updated_at)
        VALUES ('7', 'session:69:101', 2, ${Date.now() - YEAR_AND_A_MINUTE})`;
    });

    const activity = await member.call<Result<Record<string, unknown>>>("getActivity");

    expect(activity.value).toEqual({});
    const positions = await inside(
      stub,
      (room) => room.sql<{ count: number }>`SELECT COUNT(*) AS count FROM read_positions`[0].count,
    );
    expect(positions).toBe(0);
    member.socket.close();
  }, 20_000);
});
