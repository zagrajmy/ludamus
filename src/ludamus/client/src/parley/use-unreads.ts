import { useAgent } from "agents/react";
import { useCallback, useEffect, useState } from "react";

import { agentUrl, type Bootstrap, type Event, type Result } from "./protocol";

export function useUnreads(bootstrap: Bootstrap) {
  const url = agentUrl(bootstrap.agentHost);
  const [unreads, setUnreads] = useState<Record<string, boolean>>({});
  const agent = useAgent({
    agent: "ParleySphereAgent",
    host: url.host,
    name: bootstrap.sphere.id,
    protocol: url.protocol === "https:" ? "wss" : "ws",
  });
  useEffect(() => {
    void agent.call<Result<Record<string, boolean>>>("getUnreadCounts").then((result) => {
      if (result.ok) setUnreads(result.value);
    });
    const listener = (raw: MessageEvent<string>) => {
      const event = JSON.parse(raw.data) as Event;
      if (event.type === "room.activity") {
        const { roomId } = event.payload as { roomId: string };
        setUnreads((current) => ({ ...current, [roomId]: true }));
      }
      if (event.type === "unread.changed") {
        const { roomId, unread } = event.payload as { roomId: string; unread: boolean };
        setUnreads((current) => ({ ...current, [roomId]: unread }));
      }
    };
    agent.addEventListener("message", listener);
    return () => agent.removeEventListener("message", listener);
  }, [agent]);
  const markRead = useCallback(
    (roomId: string, messageId: number) => {
      if (document.visibilityState !== "visible") return;
      void agent.call("markRead", [{ messageId, roomId }]);
      setUnreads((current) => ({ ...current, [roomId]: false }));
    },
    [agent],
  );
  return { markRead, unreads };
}
