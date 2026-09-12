import { useAgent } from "agents/react";
import { useCallback, useEffect, useState } from "react";

import { agentUrl, type Event, type Message, type Result, type Room } from "./protocol";

export function useRoom(room: Room, agentHost: string) {
  const url = agentUrl(agentHost);
  const [messages, setMessages] = useState<Message[]>([]);
  const [presence, setPresence] = useState(0);
  const agent = useAgent({
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
