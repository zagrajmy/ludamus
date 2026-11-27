import { useEffect } from "react";

type Redialable = { readyState: number; reconnect: () => void };

// A socket waiting out a long backoff dials at once when the person is back:
// the tab shows again, or the network returns.
export function useRedialOnReturn(socket: Redialable): void {
  useEffect(() => {
    const back = () => {
      if (document.visibilityState === "visible" && socket.readyState === WebSocket.CLOSED) {
        socket.reconnect();
      }
    };
    document.addEventListener("visibilitychange", back);
    globalThis.addEventListener("online", back);
    return () => {
      document.removeEventListener("visibilitychange", back);
      globalThis.removeEventListener("online", back);
    };
  }, [socket]);
}
