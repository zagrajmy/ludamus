import { useAgent } from "agents/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  agentUrl,
  type Bootstrap,
  type Event,
  passCloseHandlers,
  type Result,
  type RoomActivity,
} from "./protocol";

export type Activity = {
  activity: Record<string, RoomActivity>;
  markRead: (roomId: string, messageId: number) => void;
};

// Where news of rooms comes from: each sphere's rooms from that sphere's
// feed, one's conversations from one's inbox.
export type Source = { inbox: true } | { sphere: string };

export function useActivity(
  bootstrap: Bootstrap,
  source: Source,
  onPassClosed: () => void,
): Activity {
  const url = agentUrl(bootstrap.agentHost);
  const [activity, setActivity] = useState<Record<string, RoomActivity>>({});
  const agent = useAgent({
    agent: "inbox" in source ? "ParleyInboxAgent" : "ParleySphereAgent",
    host: url.host,
    name: "inbox" in source ? bootstrap.user.id : source.sphere,
    protocol: url.protocol === "https:" ? "wss" : "ws",
    ...passCloseHandlers(onPassClosed),
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
  return useMemo(() => ({ activity, markRead }), [activity, markRead]);
}
