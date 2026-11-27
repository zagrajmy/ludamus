import type { CallOptions, StreamOptions } from "agents/client";

import { useAgent } from "agents/react";
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import type { RoomCache } from "./room-cache";

import {
  agentUrl,
  answerOf,
  type Event,
  type Message,
  passCloseHandlers,
  type ReactionChange,
  type Result,
  type Room,
} from "./protocol";
import { useRedial } from "./use-redial";

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
    (type: "close" | "open", listener: (event: globalThis.Event) => void): void;
    (type: "message", listener: MessageListener): void;
  };
  call: <T = unknown>(
    method: string,
    args?: unknown[],
    options?: CallOptions | StreamOptions,
  ) => Promise<T>;
  reconnect: () => void;
  removeEventListener: {
    (type: "close" | "open", listener: (event: globalThis.Event) => void): void;
    (type: "message", listener: MessageListener): void;
  };
};

const PAGE = 50;
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

// A page, then whatever of the rest came after its newest message.
const appendNewer = (page: Message[], rest: Message[]): Message[] => {
  const newest = page.at(-1)?.id ?? Number.NEGATIVE_INFINITY;
  return [...page, ...rest.filter(({ id }) => id > newest)];
};

const without = (record: Record<string, number>, key: string): Record<string, number> =>
  Object.fromEntries(Object.entries(record).filter(([name]) => name !== key));

// What this person knows about their own writing access: nothing yet (null),
// or muted until a time, or with no end (until: null).
export type Muted = { until: number | null } | null;

// Whether the room has answered with its messages. Until it has, an empty
// list says nothing about the room; a page that did not come back can be
// asked for again.
export type History = { retry: () => void; state: "failed" } | { state: "loading" | "ready" };

type UseRoomResult = {
  agent: RoomAgent;
  earlier: boolean;
  history: History;
  loadEarlier: () => Promise<void>;
  messages: Message[];
  muted: Muted;
  offline: boolean;
  presence: number;
  setMessages: Dispatch<SetStateAction<Message[]>>;
  setMuted: Dispatch<SetStateAction<Muted>>;
  typists: string[];
};

type Page = "earlier" | "latest";

const historyOf = ({
  answered,
  failure,
  reload,
}: {
  answered: boolean;
  failure: Page | null;
  reload: Record<Page, () => Promise<void>>;
}): History => {
  if (failure !== null) return { retry: () => void reload[failure](), state: "failed" };
  return { state: answered ? "ready" : "loading" };
};

// The room's messages: what it answers with, kept current by the socket.
// The cache stands in until the first answer and never mixes into it, so
// nothing it remembers outlives that answer.
function useHistory({
  agent,
  cache,
  roomId,
}: {
  agent: RoomAgent;
  cache: RoomCache;
  roomId: string;
}) {
  const [standIn, setStandIn] = useState(() => cache.recall(roomId) ?? []);
  const [messages, setMessages] = useState<Message[]>([]);
  const [answered, setAnswered] = useState(false);
  const [failure, setFailure] = useState<Page | null>(null);
  const [earlier, setEarlier] = useState(false);

  const fetchPage = useCallback(
    async (kind: Page, beforeId?: number) => {
      setFailure(null);
      const result = await answerOf(
        agent.call<Result<Message[]>>("loadBefore", [{ beforeId, limit: PAGE }]),
      );
      if (result.ok) {
        setEarlier(result.value.length === PAGE);
        return result.value;
      }
      console.warn("parley: messages did not load", { code: result.code, kind, room: roomId });
      setFailure(kind);
      return null;
    },
    [agent, roomId],
  );
  // Only what the socket brought in after the room answered stays on top.
  const loadLatest = useCallback(async () => {
    const page = await fetchPage("latest");
    if (page === null) return;
    setMessages((current) => appendNewer(page, current));
    setStandIn([]);
    setAnswered(true);
  }, [fetchPage]);
  const loadEarlier = useCallback(async () => {
    const page = await fetchPage("earlier", messages[0]?.id);
    if (page !== null) setMessages((current) => [...page, ...current]);
  }, [fetchPage, messages]);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  useEffect(() => {
    if (answered) cache.remember(roomId, messages.slice(-PAGE));
  }, [answered, cache, messages, roomId]);

  return {
    earlier,
    history: historyOf({ answered, failure, reload: { earlier: loadEarlier, latest: loadLatest } }),
    loadEarlier,
    messages: appendNewer(standIn, messages),
    setMessages,
  };
}

export function useRoom({
  agentHost,
  cache,
  onPassClosed,
  onRefused,
  room,
  userId,
}: {
  agentHost: string;
  cache: RoomCache;
  onPassClosed: () => void;
  onRefused: () => Promise<boolean>;
  room: Room;
  userId: string;
}): UseRoomResult {
  const url = agentUrl(agentHost);
  const [presence, setPresence] = useState(0);
  const [typing, setTyping] = useState<Record<string, number>>({});
  const [muted, setMuted] = useState<Muted>(null);
  const [offline, setOffline] = useState(false);
  const redials = useRef(0);
  const redial = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latest = useRef<RoomAgent | null>(null);
  const refused = () =>
    void onRefused().then((member) => {
      if (!member) return;
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
  useRedial(agent);
  latest.current = agent;
  const { earlier, history, loadEarlier, messages, setMessages } = useHistory({
    agent,
    cache,
    roomId: room.id,
  });

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
  }, [agent, setMessages, userId]);

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

  return {
    agent,
    earlier,
    history,
    loadEarlier,
    messages,
    muted,
    offline,
    presence,
    setMessages,
    setMuted,
    typists: Object.keys(typing),
  };
}
