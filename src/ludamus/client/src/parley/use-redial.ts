import { useEffect } from "react";

type Redialable = {
  addEventListener(type: "close" | "open", listener: (event: Event) => void): void;
  reconnect: () => void;
  removeEventListener(type: "close" | "open", listener: (event: Event) => void): void;
};

const FIRST_WAIT_MS = 1000;
const LONGEST_WAIT_MS = 2 * 60 * 60 * 1000;
// A socket up this long had got in and then dropped; one that closed sooner
// was turned away, and the next try waits longer.
const SETTLED_MS = 5000;

// A pass close fetches a new pass and a conversation's refusal redials by its
// own rule, so neither is redialled here.
const isFinal = (code: number) => code === 1008 || (code >= 4000 && code <= 4999);

// NOTE: partysocket's own redials never stop and come at most 10 s apart, so
// one tab that could not get in kept its rooms awake all day. These wait 1 s,
// then twice as long each time up to 2 h, and go at once when the person is
// back: the tab shows again, or the network returns.
export function useRedial(socket: Redialable): void {
  useEffect(() => {
    let failures = 0;
    let openedAt: number | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const dial = () => {
      timer = undefined;
      socket.reconnect();
    };
    const opened = () => {
      openedAt = Date.now();
    };
    const closed = (event: Event) => {
      if (isFinal((event as CloseEvent).code)) return;
      if (openedAt !== null && Date.now() - openedAt >= SETTLED_MS) failures = 0;
      openedAt = null;
      clearTimeout(timer);
      timer = setTimeout(dial, Math.min(FIRST_WAIT_MS * 2 ** failures, LONGEST_WAIT_MS));
      failures += 1;
    };
    const back = () => {
      if (timer === undefined || document.visibilityState !== "visible") return;
      clearTimeout(timer);
      dial();
    };
    socket.addEventListener("open", opened);
    socket.addEventListener("close", closed);
    document.addEventListener("visibilitychange", back);
    globalThis.addEventListener("online", back);
    return () => {
      clearTimeout(timer);
      socket.removeEventListener("open", opened);
      socket.removeEventListener("close", closed);
      document.removeEventListener("visibilitychange", back);
      globalThis.removeEventListener("online", back);
    };
  }, [socket]);
}
