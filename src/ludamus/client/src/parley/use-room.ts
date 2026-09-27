import type { AgentConnectionError, CallOptions, StreamOptions } from "agents/client";

import { useAgent } from "agents/react";
import { type Dispatch, type SetStateAction, useCallback, useEffect, useState } from "react";

import { agentUrl, type Event, type Message, type Result, type Room } from "./protocol";

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
  addEventListener: (type: "message", listener: MessageListener) => void;
  call: <T = unknown>(
    method: string,
    args?: unknown[],
    options?: CallOptions | StreamOptions,
  ) => Promise<T>;
  connectionError: AgentConnectionError | null;
  removeEventListener: (type: "message", listener: MessageListener) => void;
};

type UseRoomResult = {
  agent: RoomAgent;
  load: () => Promise<void>;
  messages: Message[];
  presence: number;
  setMessages: Dispatch<SetStateAction<Message[]>>;
};

export function useRoom(room: Room, agentHost: string): UseRoomResult {
  const url = agentUrl(agentHost);
  const [messages, setMessages] = useState<Message[]>([]);
  const [presence, setPresence] = useState(0);
  const agent: RoomAgent = useAgent({
    agent: room.kind === "sphere" ? "ParleySphereAgent" : "ParleySessionAgent",
    host: url.host,
    name: room.id.split(":", 2)[1],
    protocol: url.protocol === "https:" ? "wss" : "ws",
  });

  const loadBefore = useCallback(
    async (beforeId?: number) => {
      const result = await agent.call<Result<Message[]>>("loadBefore", [{ beforeId, limit: 50 }]);
      if (result.ok) setMessages((current) => [...result.value, ...current]);
    },
    [agent],
  );
  const load = useCallback(() => loadBefore(messages[0]?.id), [loadBefore, messages]);

  useEffect(() => {
    const listener = (raw: MessageEvent<string>) => {
      const event = JSON.parse(raw.data) as Event;
      if (event.type === "message.created") {
        const message = event.payload as Message;
        setMessages((current) =>
          current.some(({ id }) => id === message.id) ? current : [...current, message],
        );
      }
      if (event.type === "message.deleted") {
        const { id } = event.payload as { id: number };
        setMessages((current) =>
          current.map((message) =>
            message.id === id ? { ...message, body: "", deletedAt: Date.now() } : message,
          ),
        );
      }
      if (event.type === "presence.changed")
        setPresence((event.payload as { count: number }).count);
    };
    agent.addEventListener("message", listener);
    return () => agent.removeEventListener("message", listener);
  }, [agent]);

  useEffect(() => {
    void loadBefore();
  }, [loadBefore, room.id]);

  return { agent, load, messages, presence, setMessages };
}
