import { getAgentByName } from "agents";
import { runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { describe, expect, it } from "vitest";

import type { ParleyConversationAgent } from "../src/conversation-agent";
import type { Env } from "../src/room-agent";

import { MEMBERSHIP_AUDIENCE, POST_AUDIENCE } from "../src/auth";
import { MESSAGE_LIFETIME_MS } from "../src/limits";
import { open, pass, post } from "./support";

// What could go wrong, and so what the tests below check:
// - anyone but Django writes into a case's thread, with a pass or a lookup token;
// - a post invents an author, or carries no text or an unknown source;
// - a redelivered post shows twice;
// - staff without direct messages open are kept out of their case's thread;
// - the thread loses its messages on chat's one-year sweep instead of the
//   moderation records' period Django sends with each post.

const workerEnv = env as unknown as Env;
const THREE_YEARS_S = 3 * 365 * 86_400;

type Result<T = unknown> = { code?: string; ok: boolean; value?: T };
type Shown = { authorId: string; authorName: string; body: string };

let next = 9_000;
const caseThread = () => String((next += 1));

const staffOnly = (conversation: string, user = "7") =>
  post(
    "/conversations",
    {
      conversation,
      kind: "staff",
      members: [{ state: "active", user, writable: true }],
      needsDirect: false,
    },
    MEMBERSHIP_AUDIENCE,
  );

const threadPost = (conversation: string, extra: Record<string, unknown> = {}) => ({
  author: "email",
  body: "Mam zrzut ekranu.",
  conversation,
  name: "Ola W. (e-mail)",
  nonce: "email-abc",
  retainFor: THREE_YEARS_S,
  source: "email_in",
  ...extra,
});

describe("a post into a case's thread", () => {
  it("shows once, under the author Django names, to staff without direct messages", async () => {
    const id = caseThread();
    await staffOnly(id);

    expect((await post("/conversations/messages", threadPost(id), POST_AUDIENCE)).status).toBe(204);
    expect((await post("/conversations/messages", threadPost(id), POST_AUDIENCE)).status).toBe(204);
    const staff = await open(`parley-conversation-agent/${id}`, await pass("7", "3"));
    const history = await staff.call<Result<Shown[]>>("loadBefore", {});

    expect(staff.socket.readyState).toBe(WebSocket.OPEN);
    expect(history.value).toEqual([
      expect.objectContaining({
        authorId: "email",
        authorName: "Ola W. (e-mail)",
        body: "Mam zrzut ekranu.",
      }),
    ]);
    staff.socket.close();
  }, 20_000);

  it("is refused unless Django signed it for this purpose", async () => {
    const id = caseThread();
    const statuses = [
      (await post("/conversations/messages", threadPost(id), "parley")).status,
      (await post("/conversations/messages", threadPost(id), "parley-message")).status,
      (await post("/conversations/messages", threadPost(id, { author: "7x" }), POST_AUDIENCE))
        .status,
      (await post("/conversations/messages", threadPost(id, { body: " " }), POST_AUDIENCE)).status,
      (await post("/conversations/messages", threadPost(id, { source: "chat" }), POST_AUDIENCE))
        .status,
    ];

    expect(statuses).toEqual([401, 401, 401, 401, 401]);
  });

  it("keeps the thread for the period it carries, past chat's year", async () => {
    const id = caseThread();
    await post("/conversations/messages", threadPost(id), POST_AUDIENCE);
    const stub = await getAgentByName<Env, ParleyConversationAgent>(
      workerEnv.ParleyConversationAgent,
      id,
    );

    const kept = await runInDurableObject(stub, (instance) => {
      const room = instance as unknown as ParleyConversationAgent;
      void room.sql`UPDATE messages SET created_at = ${Date.now() - MESSAGE_LIFETIME_MS - 60_000}`;
      (room as unknown as { purgeExpiredMessages: () => void }).purgeExpiredMessages();
      return room.sql<{ count: number }>`SELECT COUNT(*) AS count FROM messages`[0].count;
    });

    expect(kept).toBe(1);
  });
});
