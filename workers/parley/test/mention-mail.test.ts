import { getAgentByName } from "agents";
import { runInDurableObject } from "cloudflare:test";
import { env } from "cloudflare:workers";
import { jwtVerify } from "jose";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ParleyInboxAgent } from "../src/inbox-agent";
import type { Env } from "../src/room-agent";

import { MEMBERSHIP_AUDIENCE } from "../src/auth";
import { MAIL_AFTER_MS, MENTIONS_AUDIENCE, RETRY_MS } from "../src/mention-mail";
import { now, open, pass, post, settle } from "./support";

const workerEnv = env as unknown as Env & { PARLEY_MENTIONS_SECRET: string };

type Result = { code?: string; ok: boolean; value?: { id: number } };
type Activity = { value: Record<string, { mentionedBy: string[] }> };

let next = 900;
const conversationId = () => String((next += 1));

const direct = (sub: string) => pass(sub, "3", now(), { direct: true });

async function conversationWith(users: string[]): Promise<string> {
  const id = conversationId();
  await post(
    "/conversations",
    {
      conversation: id,
      iat: now(),
      kind: "group",
      members: users.map((user) => ({ state: "active", user, writable: true })),
      needsDirect: true,
    },
    MEMBERSHIP_AUDIENCE,
  );
  return id;
}

const inbox = (userId: string) =>
  getAgentByName<Env, ParleyInboxAgent>(workerEnv.ParleyInboxAgent, userId);

function inside<R>(userId: string, callback: (agent: ParleyInboxAgent) => R | Promise<R>) {
  return inbox(userId).then((stub) =>
    runInDurableObject(stub as unknown as DurableObjectStub, (instance) =>
      callback(instance as unknown as ParleyInboxAgent),
    ),
  );
}

const age = (userId: string) =>
  inside(userId, (agent) => {
    void agent.sql`UPDATE unread_mentions SET created_at = created_at - ${MAIL_AFTER_MS}`;
  });

const mailings = (userId: string) =>
  inside(userId, async (agent) =>
    (await agent.listSchedules())
      .filter((schedule) => schedule.callback === "mailMentions")
      .map((schedule) => schedule.time * 1_000),
  );

// NOTE: a Response belongs to the Durable Object that made it, so each is
// made when the inbox asks.
function answering(response: () => Response) {
  return vi.spyOn(globalThis, "fetch").mockImplementationOnce(async () => response());
}

afterEach(() => vi.restoreAllMocks());

describe("a mention left unread", () => {
  it("asks the app, signed, to email it ten minutes on, and only once", async () => {
    const id = await conversationWith(["51", "52"]);
    const author = await open(`parley-conversation-agent/${id}`, await direct("51"));
    await author.call<Result>("sendMessage", {
      body: "<@52> your turn",
      mentions: ["52"],
      nonce: crypto.randomUUID(),
    });
    await settle(300);

    const [due] = await mailings("52");
    expect(due).toBeGreaterThan(Date.now() + MAIL_AFTER_MS - 60_000);
    const fetch = answering(() => new Response(null, { status: 204 }));
    await inside("52", (agent) => agent.mailMentions());
    expect(fetch).not.toHaveBeenCalled();

    await age("52");
    await inside("52", (agent) => agent.mailMentions());
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("http://localhost:8000/parley/mentions/");
    const { token } = JSON.parse(String(init!.body)) as { token: string };
    const { payload } = await jwtVerify(
      token,
      new TextEncoder().encode(workerEnv.PARLEY_MENTIONS_SECRET),
      { audience: MENTIONS_AUDIENCE, issuer: "parley" },
    );
    expect(payload).toMatchObject({
      mentions: [
        {
          author: "51",
          authorName: "Person 51",
          body: "<@52> your turn",
          room: `conversation:${id}`,
        },
      ],
      sub: "52",
    });

    await inside("52", (agent) => agent.mailMentions());
    expect(fetch).toHaveBeenCalledTimes(1);
    author.socket.close();
  }, 20_000);

  it("waits as long as the app asks, and retries an app that does not answer", async () => {
    const id = await conversationWith(["53", "54"]);
    const author = await open(`parley-conversation-agent/${id}`, await direct("53"));
    await author.call("sendMessage", { body: "<@54> hi", mentions: ["54"], nonce: "a" });
    await settle(300);
    await age("54");

    answering(() => Response.json({ retryAfter: 1_800 }, { status: 429 }));
    await inside("54", (agent) => agent.mailMentions());
    expect(Math.max(...(await mailings("54")))).toBeGreaterThan(Date.now() + 1_700_000);

    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("offline"));
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    await inside("54", (agent) => agent.mailMentions());
    expect(Math.min(...(await mailings("54")))).toBeLessThanOrEqual(Date.now() + RETRY_MS);

    answering(() => new Response("nope", { status: 401 }));
    await inside("54", (agent) => agent.mailMentions());
    expect(errors).toHaveBeenCalledWith("parley: mention mail refused", 401);
    author.socket.close();
  }, 20_000);

  it("gets no email once read, or once its message is deleted", async () => {
    const id = await conversationWith(["55", "56"]);
    const author = await open(`parley-conversation-agent/${id}`, await direct("55"));
    const mentioned = await open("parley-inbox-agent/56", await direct("56"));
    const first = await author.call<Result>("sendMessage", {
      body: "<@56> one",
      mentions: ["56"],
      nonce: "one",
    });
    await author.call("sendMessage", { body: "<@56> two", mentions: ["56"], nonce: "two" });
    await settle(300);

    await author.call("deleteOwnMessage", { messageId: first.value!.id });
    await expect
      .poll(() => mentioned.events.some((event) => event.type === "mentions.changed"))
      .toBe(true);
    await mentioned.call("markRead", { messageId: 2, roomId: `conversation:${id}` });
    await age("56");

    const fetch = answering(() => new Response(null, { status: 204 }));
    await inside("56", (agent) => agent.mailMentions());
    expect(fetch).not.toHaveBeenCalled();
    expect(
      (await mentioned.call<Activity>("getActivity")).value[`conversation:${id}`],
    ).toMatchObject({ mentionedBy: [] });
    for (const socket of [author, mentioned]) socket.socket.close();
  }, 20_000);

  it("clears the mark a deleted message left", async () => {
    const id = await conversationWith(["57", "58"]);
    const author = await open(`parley-conversation-agent/${id}`, await direct("57"));
    const mentioned = await open("parley-inbox-agent/58", await direct("58"));
    const sent = await author.call<Result>("sendMessage", {
      body: "<@58> oops",
      mentions: ["58"],
      nonce: "oops",
    });
    await expect
      .poll(async () => (await mentioned.call<Activity>("getActivity")).value[`conversation:${id}`])
      .toMatchObject({ mentionedBy: ["57"] });

    await author.call("deleteOwnMessage", { messageId: sent.value!.id });

    await expect
      .poll(() => mentioned.events.find((event) => event.type === "mentions.changed")?.payload)
      .toEqual({ mentionedBy: [], roomId: `conversation:${id}` });
    for (const socket of [author, mentioned]) socket.socket.close();
  }, 20_000);
});
