import type { CallOptions, StreamOptions } from "agents/client";

import { useAgent } from "agents/react";
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  agentUrl,
  type Event,
  type Message,
  passCloseHandlers,
  type ReactionChange,
  type Result,
  type Room,
} from "./protocol";

type MessageListener = (event: MessageEvent<string>) => void;

// NOTE: useAgent() below passes no explicit AgentT, so it resolves to its
// untyped overload (call: <T>(method: string, ...) => Promise<T>), not the
// typed one — this mirrors that overload's actual return shape by hand.
// `ReturnType<typeof useAgent>` looks like a shortcut but instead reads the
// *last* overload (the typed one), which mismatches what runs and breaks
// the `agent.call<...>()` sites in conversation.tsx. The untyped overload's
// return also embeds PartySocket structurally, which `tsc --build`'s
// declaration emit can't portably name (TS2742) — so it's written out with
// only exported, single-instance types (agents/client, DOM's MessageEvent)
// instead of inferred.
type RoomAgent = {
  addEventListener: {
    (type: "message", listener: MessageListener): void;
    (type: "close" | "open", listener: () => void): void;
  };
  call: <T = unknown>(
    method: string,
    args?: unknown[],
    options?: CallOptions | StreamOptions,
  ) => Promise<T>;
  reconnect: () => void;
  removeEventListener: {
    (type: "message", listener: MessageListener): void;
    (type: "close" | "open", listener: () => void): void;
  };
};

const PAGE = 50;
// The latest page of the rooms opened most recently, so reopening one shows
// it at once while the room's own answer is on its way.
const CACHED_ROOMS = 20;
type Cached = { earlier: boolean; messages: Message[] };
const cache = new Map<string, Cached>();

const remember = (key: string, entry: Cached) => {
  cache.delete(key);
  cache.set(key, entry);
  const oldest = cache.keys().next();
  if (cache.size > CACHED_ROOMS && oldest.done !== true) cache.delete(oldest.value);
};
// NOTE: the Agents SDK takes every 4xxx close as final, so a conversation
// that shut this person out is redialled by hand, ever more slowly.
const REDIAL_FROM = 1000;
const REDIAL_MAX = 30_000;
const AGENTS = {
  conversation: "ParleyConversationAgent",
  event: "ParleyEventAgent",
  organizers: "ParleyOrganizersAgent",
  session: "ParleySessionAgent",
} as const;

export const withReactions = (messages: Message[], change: ReactionChange): Message[] =>
  messages.map((message) =>
    message.id === change.messageId
      ? { ...message, reactions: change.reactions, reactors: change.reactors }
      : message,
  );

const without = (record: Record<string, number>, key: string): Record<string, number> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

// What this person knows about their own writing access: nothing yet (null),
// or muted until a time, or with no end (until: null).
export type Muted = { until: number | null } | null;

type UseRoomResult = {
  agent: RoomAgent;
  earlier: boolean;
  // The room's latest page did not come back; retry asks again.
  failed: boolean;
  load: () => Promise<void>;
  // The messages are the room's, from this visit or the last one; until
  // then an empty list says nothing about the room.
  loaded: boolean;
  messages: Message[];
  muted: Muted;
  offline: boolean;
  presence: number;
  // The thread opened from the cache, already in place: it needs no entrance.
  remembered: boolean;
  retry: () => void;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  setMuted: Dispatch<SetStateAction<Muted>>;
  typists: string[];
};

export function useRoom({
  agentHost,
  onPassClosed,
  onRefused,
  room,
  userId,
}: {
  agentHost: string;
  onPassClosed: () => void;
  onRefused: () => Promise<boolean>;
  room: Room;
  userId: string;
}): UseRoomResult {
  const url = agentUrl(agentHost);
  const key = `${userId} ${room.id}`;
  const cached = useMemo(() => cache.get(key), [key]);
  const [messages, setMessages] = useState<Message[]>(cached?.messages ?? []);
  const [presence, setPresence] = useState(0);
  const [earlier, setEarlier] = useState(cached?.earlier ?? false);
  const [loaded, setLoaded] = useState(cached !== undefined);
  const [failed, setFailed] = useState(false);
  const [typing, setTyping] = useState<Record<string, number>>({});
  const [muted, setMuted] = useState<Muted>(null);
  const [offline, setOffline] = useState(false);
  const redials = useRef(0);
  const redial = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<RoomAgent | null>(null);
  const refused = () =>
    void onRefused().then((member) => {
      if (!member) {
        cache.delete(key);
        return;
      }
      const delay = Math.min(REDIAL_FROM * 2 ** redials.current, REDIAL_MAX);
      redials.current += 1;
      redial.current = setTimeout(() => latest.current?.reconnect(), delay);
    });
  useEffect(() => () => clearTimeout(redial.current ?? undefined), []);
  const agent: RoomAgent = useAgent({
    agent: AGENTS[room.kind],
    host: url.host,
    // NOTE: everything after the kind; a session room's name is "<sphere>:<session>".
    name: room.id.slice(room.id.indexOf(":") + 1),
    protocol: url.protocol === "https:" ? "wss" : "ws",
    ...passCloseHandlers(onPassClosed, refused),
  });
  latest.current = agent;

  const load = useCallback(async () => {
    const result = await agent.call<Result<Message[]>>("loadBefore", [
      { beforeId: messages[0]?.id, limit: PAGE },
    ]);
    if (!result.ok) return;
    setEarlier(result.value.length === PAGE);
    setMessages((current) => [...result.value, ...current]);
  }, [agent, messages]);

  // The latest page replaces whatever the cache showed: a message deleted,
  // edited or expired while this person was away must not linger. Only what
  // the socket brought in since the room answered stays on top of it.
  const newestCached = cached?.messages.at(-1)?.id ?? 0;
  const loadLatest = useCallback(async () => {
    setFailed(false);
    const result = await agent
      .call<Result<Message[]>>("loadBefore", [{ limit: PAGE }])
      .catch((error: unknown) => ({ code: String(error), ok: false as const }));
    if (!result.ok) {
      console.warn("parley: latest messages did not load", { code: result.code, room: room.id });
      setFailed(true);
      return;
    }
    const page = result.value;
    const floor = Math.max(page.at(-1)?.id ?? 0, newestCached);
    setEarlier(page.length === PAGE);
    setMessages((current) => [...page, ...current.filter(({ id }) => id > floor)]);
    setLoaded(true);
  }, [agent, newestCached, room.id]);

  useEffect(() => {
    const listener = (raw: MessageEvent<string>) => {
      const event = JSON.parse(raw.data) as Event;
      if (event.type === "message.created") {
        const message = event.payload as Message;
        setMessages((current) =>
          current.some(({ id }) => id === message.id) ? current : [...current, message],
        );
        setTyping((current) => without(current, message.authorId));
      }
      if (event.type === "typing.changed") {
        const { expiresAt, userId: typist } = event.payload as {
          expiresAt: number;
          userId: string;
        };
        if (typist !== userId)
          setTyping((current) =>
            expiresAt > Date.now() ? { ...current, [typist]: expiresAt } : without(current, typist),
          );
      }
      if (event.type === "restriction.changed") {
        const { mutedUntil, userId: target } = event.payload as {
          mutedUntil: number | null;
          userId: string;
        };
        // NOTE: the Worker sends 0 for restored access and null for no end.
        if (target === userId)
          setMuted(mutedUntil === null || mutedUntil > Date.now() ? { until: mutedUntil } : null);
      }
      if (event.type === "message.deleted") {
        const { id } = event.payload as { id: number };
        setMessages((current) =>
          current.map((message) =>
            message.id === id ? { ...message, body: "", deletedAt: Date.now() } : message,
          ),
        );
      }
      if (event.type === "reaction.changed")
        setMessages((current) => withReactions(current, event.payload as ReactionChange));
      if (event.type === "presence.changed")
        setPresence((event.payload as { count: number }).count);
    };
    agent.addEventListener("message", listener);
    return () => agent.removeEventListener("message", listener);
  }, [agent, userId]);

  // NOTE: useAgent's connectionError is set only by a close it will not
  // retry; a dropped socket it keeps redialling shows only through these.
  useEffect(() => {
    const lost = () => setOffline(true);
    const back = () => {
      redials.current = 0;
      setOffline(false);
    };
    agent.addEventListener("close", lost);
    agent.addEventListener("open", back);
    return () => {
      agent.removeEventListener("close", lost);
      agent.removeEventListener("open", back);
    };
  }, [agent]);

  // A typist who goes quiet without saying so drops off at their expiry.
  useEffect(() => {
    const next = Math.min(...Object.values(typing));
    if (!Number.isFinite(next)) return;
    const timer = setTimeout(
      () =>
        setTyping((current) =>
          Object.fromEntries(Object.entries(current).filter(([, expiry]) => expiry > Date.now())),
        ),
      Math.max(0, next - Date.now()) + 50,
    );
    return () => clearTimeout(timer);
  }, [typing]);

  const mutedUntil = muted?.until ?? null;
  useEffect(() => {
    if (mutedUntil === null) return;
    // NOTE: setTimeout overflows past ~24.8 days; mutes are at most 7.
    const timer = setTimeout(() => setMuted(null), Math.max(0, mutedUntil - Date.now()));
    return () => clearTimeout(timer);
  }, [mutedUntil]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    if (loaded)
      remember(key, {
        earlier: earlier || messages.length > PAGE,
        messages: messages.slice(-PAGE),
      });
  }, [earlier, key, loaded, messages]);

  return {
    agent,
    earlier,
    failed,
    load,
    loaded,
    messages,
    muted,
    offline,
    presence,
    remembered: cached !== undefined,
    retry: () => void loadLatest(),
    setMessages,
    setMuted,
    typists: Object.keys(typing),
  };
}
