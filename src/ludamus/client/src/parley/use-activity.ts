import { useAgent } from "agents/react";
import { useCallback, useEffect, useState } from "react";

import { agentUrl, type Bootstrap, type Event, type Result, type RoomActivity } from "./protocol";

export function useActivity(bootstrap: Bootstrap) {
  const url = agentUrl(bootstrap.agentHost);
  const [activity, setActivity] = useState<Record<string, RoomActivity>>({});
  const agent = useAgent({
    agent: "ParleySphereAgent",
    host: url.host,
    name: bootstrap.sphere.id,
    protocol: url.protocol === "https:" ? "wss" : "ws",
  });
  useEffect(() => {
    void agent.call<Result<Record<string, RoomActivity>>>("getActivity").then((result) => {
      if (result.ok) setActivity(result.value);
    });
    const listener = (raw: MessageEvent<string>) => {
      const event = JSON.parse(raw.data) as Event;
      if (event.type === "room.activity") {
        const { at, roomId } = event.payload as { at: number; roomId: string };
        setActivity((current) => ({ ...current, [roomId]: { at, unread: true } }));
      }
      if (event.type === "unread.changed") {
        const { roomId, unread } = event.payload as { roomId: string; unread: boolean };
        setActivity((current) => ({
          ...current,
          [roomId]: { at: current[roomId]?.at ?? 0, unread },
        }));
      }
    };
    agent.addEventListener("message", listener);
    return () => agent.removeEventListener("message", listener);
  }, [agent]);
  const markRead = useCallback(
    (roomId: string, messageId: number) => {
      if (document.visibilityState !== "visible") return;
      void agent.call("markRead", [{ messageId, roomId }]);
      setActivity((current) => ({
        ...current,
        [roomId]: { at: current[roomId]?.at ?? 0, unread: false },
      }));
    },
    [agent],
  );
  return { activity, markRead };
}
